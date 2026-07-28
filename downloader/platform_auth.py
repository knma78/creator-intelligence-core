from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from config import SETTINGS, Settings, ensure_directories


SUPPORTED_PLATFORMS = {"bilibili", "youtube"}
PLATFORM_LABELS = {
    "bilibili": "B站",
    "youtube": "YouTube",
}
PLATFORM_DOMAINS = {
    "bilibili": ("bilibili.com",),
    "youtube": ("youtube.com", "google.com"),
}
LOGIN_COOKIE_NAMES = {
    "bilibili": {"SESSDATA"},
    "youtube": {
        "LOGIN_INFO",
        "SAPISID",
        "__Secure-1PAPISID",
        "__Secure-3PAPISID",
    },
}


def platform_auth_dir(settings: Settings = SETTINGS) -> Path:
    return settings.cache_dir / "platform_auth"


def manual_cookie_path(platform: str, settings: Settings = SETTINGS) -> Path:
    platform = _normalize_platform(platform)
    return platform_auth_dir(settings) / f"{platform}.cookies.txt"


def platform_auth_status_path(
    platform: str,
    settings: Settings = SETTINGS,
) -> Path:
    platform = _normalize_platform(platform)
    return platform_auth_dir(settings) / f"{platform}.auth_status.json"


def get_platform_auth_status(
    platform: str,
    settings: Settings = SETTINGS,
) -> dict[str, Any]:
    platform = _normalize_platform(platform)
    label = PLATFORM_LABELS[platform]
    runtime = _read_platform_auth_status(platform, settings)

    for path, source in _cookie_file_candidates(platform, settings):
        if not path.is_file():
            continue
        cookies = parse_netscape_cookies(path.read_text(encoding="utf-8", errors="ignore"))
        valid, reason = _validate_cookie_map(platform, cookies)
        if valid:
            return {
                "platform": platform,
                "label": label,
                "state": "ready",
                "ready": True,
                "source": runtime.get("source") or source,
                "message": (
                    f"{label}网页登录已授权，可以开始分析。"
                    if runtime.get("source") == "web_login"
                    else f"{label} Cookie 已授权，可以开始分析。"
                ),
                "cookie_file": str(path),
                "cookie_count": len(cookies),
                "missing": [],
                "updated_at": runtime.get("updated_at"),
            }
        invalid_reason = reason
    browser_spec = _browser_cookie_spec(platform, settings)
    if browser_spec:
        return {
            "platform": platform,
            "label": label,
            "state": "ready",
            "ready": True,
            "source": "browser",
            "message": f"{label}已配置浏览器 Cookie 读取。",
            "cookie_file": None,
            "cookie_count": None,
            "missing": [],
            "updated_at": runtime.get("updated_at"),
        }

    runtime_state = str(runtime.get("state") or "")
    if runtime_state in {"running", "failed"}:
        return {
            "platform": platform,
            "label": label,
            "state": runtime_state,
            "ready": False,
            "source": runtime.get("source"),
            "message": str(
                runtime.get("message")
                or f"{label}网页登录尚未完成。"
            ),
            "cookie_file": str(manual_cookie_path(platform, settings)),
            "cookie_count": 0,
            "missing": sorted(LOGIN_COOKIE_NAMES[platform]),
            "updated_at": runtime.get("updated_at"),
        }

    message = f"{label}尚未授权，请点击“登录{label}”完成一次网页登录。"
    if "invalid_reason" in locals():
        message = f"{label} Cookie 无效：{invalid_reason}。请重新登录{label}。"
    return {
        "platform": platform,
        "label": label,
        "state": "required",
        "ready": False,
        "source": None,
        "message": message,
        "cookie_file": str(manual_cookie_path(platform, settings)),
        "cookie_count": 0,
        "missing": sorted(LOGIN_COOKIE_NAMES[platform]),
        "updated_at": runtime.get("updated_at"),
    }


def import_platform_cookies(
    platform: str,
    content: str,
    settings: Settings = SETTINGS,
) -> dict[str, Any]:
    platform = _normalize_platform(platform)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Cookie 文件内容为空。")
    if len(content.encode("utf-8")) > 4 * 1024 * 1024:
        raise ValueError("Cookie 文件超过 4MB，已拒绝导入。")

    cookies = parse_netscape_cookies(content)
    valid, reason = _validate_cookie_map(platform, cookies)
    if not valid:
        raise ValueError(
            f"这不是有效的 {PLATFORM_LABELS[platform]} 登录 Cookie：{reason}。"
        )

    target = manual_cookie_path(platform, settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("# Netscape HTTP Cookie File"):
        normalized = "# Netscape HTTP Cookie File\n" + normalized.lstrip()
    if not normalized.endswith("\n"):
        normalized += "\n"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(normalized, encoding="utf-8")
    os.replace(temporary, target)
    write_platform_auth_status(
        platform,
        "ready",
        f"{PLATFORM_LABELS[platform]} Cookie 导入完成。",
        settings,
        source="manual",
        cookie_count=len(cookies),
    )
    return get_platform_auth_status(platform, settings)


def start_platform_login(
    platform: str,
    settings: Settings = SETTINGS,
) -> dict[str, Any]:
    platform = _normalize_platform(platform)
    ensure_directories(settings)
    status = get_platform_auth_status(platform, settings)
    if status["state"] == "running":
        return status

    label = PLATFORM_LABELS[platform]
    write_platform_auth_status(
        platform,
        "running",
        f"登录窗口正在打开。请在窗口中登录{label}，完成后程序会自动保存本机会话。",
        settings,
        source="web_login",
    )
    log_path = settings.logs_dir / f"{platform}_auth.log"
    command = [
        sys.executable,
        "-m",
        "downloader.platform_login",
        "--platform",
        platform,
        "--timeout",
        str(max(60, settings.platform_auth_timeout)),
    ]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        with log_path.open("a", encoding="utf-8") as log_file:
            subprocess.Popen(
                command,
                cwd=settings.base_dir,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
    except Exception:
        write_platform_auth_status(
            platform,
            "failed",
            f"无法启动{label}登录窗口，请查看 logs/{platform}_auth.log。",
            settings,
            source="web_login",
        )
        raise
    return get_platform_auth_status(platform, settings)


def write_platform_auth_status(
    platform: str,
    state: str,
    message: str,
    settings: Settings = SETTINGS,
    **extra: Any,
) -> None:
    platform = _normalize_platform(platform)
    path = platform_auth_status_path(platform, settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "platform": platform,
                "state": state,
                "message": message,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                **extra,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def ensure_platform_authorized(
    platform: str,
    settings: Settings = SETTINGS,
) -> None:
    status = get_platform_auth_status(platform, settings)
    if status["ready"]:
        return
    label = status["label"]
    raise RuntimeError(
        f"{label}任务需要先完成 Cookie 授权。请在网页主界面的“平台访问授权”中"
        f"点击“登录{label}”，完成网页登录后重新提交。"
    )


def resolve_authorized_cookie_file(
    platform: str,
    settings: Settings = SETTINGS,
) -> Path | None:
    platform = _normalize_platform(platform)
    for path, _source in _cookie_file_candidates(platform, settings):
        if not path.is_file():
            continue
        cookies = parse_netscape_cookies(path.read_text(encoding="utf-8", errors="ignore"))
        if _validate_cookie_map(platform, cookies)[0]:
            return path
    return None


def browser_cookie_spec(
    platform: str,
    settings: Settings = SETTINGS,
) -> str | None:
    return _browser_cookie_spec(_normalize_platform(platform), settings)


def parse_netscape_cookies(content: str) -> dict[str, tuple[str, str]]:
    cookies: dict[str, tuple[str, str]] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        fields = line.split("\t")
        if len(fields) < 7:
            continue
        domain = fields[0].removeprefix("#HttpOnly_").lower()
        name = fields[-2].strip()
        value = fields[-1]
        if domain and name:
            cookies[name] = (domain, value)
    return cookies


def _validate_cookie_map(
    platform: str,
    cookies: dict[str, tuple[str, str]],
) -> tuple[bool, str]:
    domains = PLATFORM_DOMAINS[platform]
    platform_cookies = {
        name: value
        for name, (domain, value) in cookies.items()
        if any(expected in domain for expected in domains)
    }
    if not platform_cookies:
        return False, "文件中没有对应平台的 Cookie"
    if not (LOGIN_COOKIE_NAMES[platform] & platform_cookies.keys()):
        return False, "文件中没有登录会话标记"
    return True, ""


def _cookie_file_candidates(
    platform: str,
    settings: Settings,
) -> list[tuple[Path, str]]:
    candidates: list[tuple[Path, str]] = [
        (manual_cookie_path(platform, settings), "manual"),
    ]
    configured = getattr(settings, f"{platform}_cookie_file", None)
    if configured:
        candidates.append((_resolve_path(str(configured), settings), "configured"))
    if platform == "youtube" and settings.yt_dlp_cookie_file:
        candidates.append(
            (_resolve_path(str(settings.yt_dlp_cookie_file), settings), "configured")
        )
    unique: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for path, source in candidates:
        key = str(path).lower()
        if key not in seen:
            unique.append((path, source))
            seen.add(key)
    return unique


def _browser_cookie_spec(platform: str, settings: Settings) -> str | None:
    value = getattr(settings, f"{platform}_cookies_from_browser", None)
    if not value and platform == "youtube":
        value = settings.yt_dlp_cookies_from_browser
    return str(value).strip() if value else None


def _resolve_path(value: str, settings: Settings) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else settings.base_dir / path


def _read_platform_auth_status(
    platform: str,
    settings: Settings,
) -> dict[str, Any]:
    path = platform_auth_status_path(platform, settings)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    if payload.get("state") == "running":
        try:
            updated_at = datetime.fromisoformat(str(payload.get("updated_at") or ""))
            stale_after = max(120, settings.platform_auth_timeout + 60)
            if (datetime.now() - updated_at).total_seconds() > stale_after:
                return {
                    **payload,
                    "state": "failed",
                    "message": "上一次登录任务已结束或超时，请重新点击登录。",
                }
        except ValueError:
            pass
    return payload


def _normalize_platform(platform: str) -> str:
    normalized = str(platform or "").strip().lower()
    if normalized not in SUPPORTED_PLATFORMS:
        raise ValueError(f"不支持的平台授权类型：{platform}")
    return normalized
