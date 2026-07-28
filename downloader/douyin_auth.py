from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from time import monotonic, sleep
from typing import Any

from config import SETTINGS, Settings, ensure_directories
from downloader.douyin_adapter import REQUIRED_COOKIE_KEYS, douyin_cookie_path


def capture_douyin_login(
    settings: Settings = SETTINGS,
    timeout_seconds: int = 600,
) -> None:
    ensure_directories(settings)
    _write_status(
        settings,
        "running",
        "请在已打开的抖音窗口中完成登录，程序正在等待登录结果。",
    )
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        _write_status(settings, "failed", "缺少 Playwright，无法打开抖音登录窗口。")
        raise RuntimeError("Playwright is required for Douyin login") from exc

    profile_dir = settings.douyin_cache_dir / "browser_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    deadline = monotonic() + max(60, timeout_seconds)
    try:
        with sync_playwright() as playwright:
            context = _launch_context(playwright, profile_dir)
            page = context.pages[0] if context.pages else context.new_page()
            try:
                page.goto(
                    "https://www.douyin.com/",
                    wait_until="domcontentloaded",
                    timeout=45_000,
                )
            except Exception:
                pass

            while monotonic() < deadline:
                try:
                    browser_cookies = context.cookies(["https://www.douyin.com/"])
                except Exception:
                    _write_status(
                        settings,
                        "failed",
                        "抖音登录窗口已关闭，尚未取得完整登录信息。",
                    )
                    return
                cookies = {
                    str(item["name"]): str(item["value"])
                    for item in browser_cookies
                    if str(item.get("domain") or "").endswith("douyin.com")
                    and item.get("name")
                }
                if REQUIRED_COOKIE_KEYS.issubset(cookies):
                    _save_cookies(douyin_cookie_path(settings), cookies)
                    _write_status(
                        settings,
                        "ready",
                        "抖音登录成功。现在可以分析单视频和创作者主页。",
                        cookie_count=len(cookies),
                    )
                    sleep(1)
                    context.close()
                    return
                sleep(2)

            _write_status(
                settings,
                "failed",
                "等待抖音登录超时。请重新点击“登录抖音”再试。",
            )
            context.close()
    except Exception as exc:
        _write_status(
            settings,
            "failed",
            f"无法完成抖音登录：{type(exc).__name__}。",
        )
        raise


def _launch_context(playwright: Any, profile_dir: Path):
    launch_options = {
        "user_data_dir": str(profile_dir),
        "headless": False,
        "locale": "zh-CN",
        "viewport": {"width": 1440, "height": 900},
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    try:
        return playwright.chromium.launch_persistent_context(
            channel="chrome",
            **launch_options,
        )
    except Exception:
        chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        if not chrome.is_file():
            raise
        return playwright.chromium.launch_persistent_context(
            executable_path=str(chrome),
            **launch_options,
        )


def _save_cookies(path: Path, cookies: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(cookies, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_status(
    settings: Settings,
    state: str,
    message: str,
    **extra: Any,
) -> None:
    path = settings.douyin_cache_dir / "auth_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
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
    temporary.replace(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Capture a local Douyin login session.")
    parser.add_argument("--timeout", type=int, default=600)
    arguments = parser.parse_args()
    capture_douyin_login(timeout_seconds=arguments.timeout)
