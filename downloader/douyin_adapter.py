from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from config import SETTINGS, Settings, ensure_directories
from infrastructure.atomic_io import atomic_write_json, atomic_write_text
from models import Video


logger = logging.getLogger(__name__)

DOUYIN_LINK_RE = re.compile(
    r"https?://(?:(?:www|m|v)\.)?douyin\.com/[^\s<>'\"]+|"
    r"https?://(?:www\.)?iesdouyin\.com/[^\s<>'\"]+",
    re.IGNORECASE,
)
DOUYIN_VIDEO_ID_RE = re.compile(r"/(?:video|note)/(\d{15,20})", re.IGNORECASE)
DOUYIN_PROFILE_RE = re.compile(r"/user/([0-9A-Za-z_-]+)", re.IGNORECASE)
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
REQUIRED_COOKIE_KEYS = {"ttwid", "odin_tt", "passport_csrf_token"}


class DouyinAdapterTimeout(RuntimeError):
    """The adapter timed out after it may have completed some downloads."""


def extract_douyin_url(value: str) -> str:
    match = DOUYIN_LINK_RE.search(value.strip())
    if not match:
        return value.strip()
    return match.group(0).rstrip("。，、；;！!？?)）]】")


def douyin_profile_id(value: str) -> str | None:
    match = DOUYIN_PROFILE_RE.search(extract_douyin_url(value))
    return match.group(1) if match else None


def douyin_video_id(value: str) -> str | None:
    match = DOUYIN_VIDEO_ID_RE.search(extract_douyin_url(value))
    return match.group(1) if match else None


def douyin_cookie_path(settings: Settings = SETTINGS) -> Path:
    return settings.douyin_cache_dir / "cookies.json"


def load_douyin_cookies(settings: Settings = SETTINGS) -> dict[str, str]:
    candidates: list[Path] = []
    if settings.douyin_cookie_file:
        configured = Path(settings.douyin_cookie_file).expanduser()
        candidates.append(
            configured if configured.is_absolute() else settings.base_dir / configured
        )
    candidates.append(douyin_cookie_path(settings))

    fallback: dict[str, str] = {}
    for path in candidates:
        if not path.is_file():
            continue
        try:
            cookies = _read_cookie_file(path)
        except Exception as exc:
            logger.warning("Failed to load Douyin cookies from %s: %s", path, exc)
            continue
        if REQUIRED_COOKIE_KEYS.issubset(cookies):
            return cookies
        if not fallback and cookies:
            fallback = cookies
    return fallback


def get_douyin_status(settings: Settings = SETTINGS) -> dict[str, Any]:
    cookies = load_douyin_cookies(settings)
    missing = sorted(REQUIRED_COOKIE_KEYS - cookies.keys())
    status_path = settings.douyin_cache_dir / "auth_status.json"
    runtime: dict[str, Any] = {}
    if status_path.is_file():
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            runtime = payload if isinstance(payload, dict) else {}
        except Exception:
            runtime = {}

    ready = not missing
    state = "ready" if ready else str(runtime.get("state") or "required")
    if state == "ready" and not ready:
        state = "required"
    message = (
        "抖音访问已配置，可以分析单视频和创作者主页。"
        if ready
        else str(runtime.get("message") or "首次使用抖音前，请完成一次网页登录。")
    )
    return {
        "state": state,
        "ready": ready,
        "message": message,
        "adapter_available": DouyinAdapter(settings).available,
        "cookie_file": str(douyin_cookie_path(settings)),
        "missing_cookie_count": len(missing),
        "updated_at": runtime.get("updated_at"),
    }


def start_douyin_login(settings: Settings = SETTINGS) -> dict[str, Any]:
    ensure_directories(settings)
    status = get_douyin_status(settings)
    if status["state"] == "running":
        return status

    _write_auth_status(
        settings,
        "running",
        "登录窗口正在打开。请在窗口中登录抖音，完成后程序会自动保存本机会话。",
    )
    log_path = settings.logs_dir / "douyin_auth.log"
    command = [
        sys.executable,
        "-m",
        "downloader.douyin_auth",
        "--timeout",
        str(max(60, settings.douyin_auth_timeout)),
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
        _write_auth_status(
            settings,
            "failed",
            "无法启动抖音登录窗口，请查看 logs/douyin_auth.log。",
        )
        raise
    return get_douyin_status(settings)


class DouyinAdapter:
    def __init__(self, settings: Settings = SETTINGS):
        self.settings = settings
        self.last_warning: str | None = None

    @property
    def available(self) -> bool:
        return (
            self.settings.douyin_adapter_enabled
            and (self.settings.douyin_adapter_dir / "run.py").is_file()
        )

    @property
    def ready(self) -> bool:
        cookies = load_douyin_cookies(self.settings)
        return self.available and REQUIRED_COOKIE_KEYS.issubset(cookies)

    def download(self, source: str, limit: int = 1) -> list[Video]:
        ensure_directories(self.settings)
        self.last_warning = None
        if not self.available:
            raise RuntimeError(
                "抖音下载适配器不可用。请确认 integrations/douyin-downloader 已安装。"
            )
        cookies = load_douyin_cookies(self.settings)
        missing = sorted(REQUIRED_COOKIE_KEYS - cookies.keys())
        if missing:
            raise RuntimeError(
                "抖音需要一次性网页登录。请在网页主界面点击“登录抖音”，"
                "登录成功后重新提交任务。"
            )

        normalized = extract_douyin_url(source)
        profile_id = douyin_profile_id(normalized)
        target_video_id = douyin_video_id(normalized)
        is_profile = profile_id is not None and target_video_id is None
        requested_limit = max(1, min(int(limit or 1), self.settings.batch_limit))
        job_key = hashlib.sha1(
            f"{normalized}|{requested_limit}".encode("utf-8")
        ).hexdigest()[:12]
        job_dir = self.settings.douyin_cache_dir / "jobs" / job_key
        media_dir = self.settings.douyin_cache_dir / "media"
        job_dir.mkdir(parents=True, exist_ok=True)
        media_dir.mkdir(parents=True, exist_ok=True)
        config_path = job_dir / "config.yml"
        atomic_write_text(
            config_path,
            yaml.safe_dump(
                self._adapter_config(
                    normalized,
                    media_dir,
                    requested_limit if is_profile else 1,
                ),
                allow_unicode=True,
                sort_keys=False,
            ),
        )

        timed_out = False
        try:
            self._run_adapter(config_path, cookies, job_dir)
        except DouyinAdapterTimeout:
            timed_out = True
        videos = self._collect_videos(
            media_dir,
            target_video_id=target_video_id,
            profile_id=profile_id if is_profile else None,
            limit=requested_limit,
        )
        if not videos:
            if timed_out:
                raise RuntimeError(
                    f"抖音下载超过 {self.settings.douyin_adapter_timeout} 秒，"
                    "且缓存中没有可继续分析的完整视频。请减少批量数量后重试。"
                )
            raise RuntimeError(
                "抖音适配器没有取得可分析的视频。请确认链接是公开视频；"
                "如果登录已过期，请点击“重新登录抖音”后再试。"
            )
        if timed_out:
            self.last_warning = (
                f"抖音下载达到 {self.settings.douyin_adapter_timeout} 秒上限，"
                f"已回收 {len(videos)} 个完整视频继续分析；未完成的临时文件不会使用。"
            )
            logger.warning(self.last_warning)
        return videos

    def _adapter_config(
        self,
        source: str,
        media_dir: Path,
        limit: int,
    ) -> dict[str, Any]:
        return {
            "link": [source],
            "path": str(media_dir),
            "music": False,
            "cover": False,
            "avatar": False,
            "json": True,
            "folderstyle": False,
            "filename_template": "{id}",
            "author_dir": "sec_uid",
            "group_by_mode": False,
            "download_pinned": False,
            "mode": ["post"],
            "number": {"post": limit},
            "increase": {"post": False},
            "thread": 2,
            "retry_times": 2,
            "proxy": self.settings.yt_dlp_proxy or "",
            "database": False,
            "progress": {"quiet_logs": True},
            "browser_fallback": {
                "enabled": True,
                "headless": False,
                "max_scrolls": max(8, limit * 3),
                "idle_rounds": 4,
                "wait_timeout_seconds": min(
                    max(60, self.settings.douyin_adapter_timeout),
                    300,
                ),
            },
            "comments": {"enabled": False},
            "transcript": {"enabled": False},
            "notifications": {"enabled": False},
        }

    def _run_adapter(
        self,
        config_path: Path,
        cookies: dict[str, str],
        job_dir: Path,
    ) -> None:
        cookie_header = "; ".join(
            f"{key}={value}" for key, value in cookies.items() if key and value
        )
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["DOUYIN_COOKIE"] = cookie_header
        command = [
            sys.executable,
            str(self.settings.douyin_adapter_dir / "run.py"),
            "-c",
            str(config_path),
            "--show-warnings",
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=self.settings.base_dir,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(60, self.settings.douyin_adapter_timeout),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            log_path = job_dir / "adapter.log"
            log_path.write_text(
                _timeout_output(exc.stdout) + "\n" + _timeout_output(exc.stderr),
                encoding="utf-8",
            )
            raise DouyinAdapterTimeout(
                f"抖音下载超过 {self.settings.douyin_adapter_timeout} 秒，任务已停止，"
                "已完成的文件仍保留在缓存中。"
            ) from exc
        finally:
            env.pop("DOUYIN_COOKIE", None)
            (job_dir / ".cookies.json").unlink(missing_ok=True)

        log_path = job_dir / "adapter.log"
        log_path.write_text(
            (completed.stdout or "") + "\n" + (completed.stderr or ""),
            encoding="utf-8",
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "抖音适配器执行失败。请检查网页登录状态；详细日志已保存到 "
                f"{log_path}。"
            )

    def _collect_videos(
        self,
        media_dir: Path,
        *,
        target_video_id: str | None,
        profile_id: str | None,
        limit: int,
    ) -> list[Video]:
        candidates: list[tuple[float, Video]] = []
        for metadata_path in media_dir.rglob("*_data.json"):
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            source_id = str(payload.get("aweme_id") or "")
            if not source_id:
                continue
            if target_video_id and source_id != target_video_id:
                continue
            author = payload.get("author") if isinstance(payload.get("author"), dict) else {}
            sec_uid = str(author.get("sec_uid") or "")
            if profile_id and sec_uid != profile_id:
                continue
            video_path = self._find_media(media_dir, source_id)
            if not video_path:
                continue
            video = self._video_from_adapter(payload, video_path, metadata_path)
            timestamp = _number(payload.get("create_time")) or metadata_path.stat().st_mtime
            candidates.append((timestamp, video))

        candidates.sort(key=lambda item: item[0], reverse=True)
        videos = [video for _, video in candidates[:limit]]
        for video in videos:
            self._persist_video(video)
        return videos

    @staticmethod
    def _find_media(media_dir: Path, source_id: str) -> Path | None:
        candidates = [
            path
            for path in media_dir.rglob(f"*{source_id}*")
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
        ]
        return max(candidates, key=lambda path: path.stat().st_size) if candidates else None

    def _video_from_adapter(
        self,
        payload: dict[str, Any],
        video_path: Path,
        source_metadata_path: Path,
    ) -> Video:
        source_id = str(payload.get("aweme_id"))
        author = payload.get("author") if isinstance(payload.get("author"), dict) else {}
        statistics = (
            payload.get("statistics")
            if isinstance(payload.get("statistics"), dict)
            else {}
        )
        video_info = payload.get("video") if isinstance(payload.get("video"), dict) else {}
        duration_ms = _number(video_info.get("duration") or payload.get("duration"))
        cover = _first_url(video_info.get("cover"))
        publish_time = None
        timestamp = _number(payload.get("create_time"))
        if timestamp:
            publish_time = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
        stats = {
            key: value
            for key, value in {
                "view_count": statistics.get("play_count"),
                "like_count": statistics.get("digg_count"),
                "comment_count": statistics.get("comment_count"),
                "share_count": statistics.get("share_count"),
                "collect_count": statistics.get("collect_count"),
            }.items()
            if value is not None
        }
        return Video(
            source_url=f"https://www.douyin.com/video/{source_id}",
            platform="douyin",
            video_id=f"DY_{source_id}",
            title=str(payload.get("desc") or f"抖音视频 {source_id}"),
            author=str(author.get("nickname") or author.get("unique_id") or "") or None,
            cover=cover,
            publish_time=publish_time,
            duration=(duration_ms / 1000) if duration_ms and duration_ms > 1000 else duration_ms,
            video_path=video_path,
            metadata_path=source_metadata_path,
            stats=stats,
            extra_metadata={
                "source_id": source_id,
                "uploader_id": author.get("uid"),
                "sec_uid": author.get("sec_uid"),
                "unique_id": author.get("unique_id"),
                "adapter": "jiji262/douyin-downloader",
                "source_metadata_path": str(source_metadata_path),
            },
        )

    def _persist_video(self, video: Video) -> None:
        metadata_dir = self.settings.video_cache_dir / video.video_id
        metadata_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = metadata_dir / "metadata.json"
        video.metadata_path = metadata_path
        atomic_write_json(metadata_path, video.to_dict())


def _load_netscape_cookies(path: Path) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        fields = line.split("\t")
        if len(fields) >= 7:
            cookies[fields[-2]] = fields[-1]
    return cookies


def _read_cookie_file(path: Path) -> dict[str, str]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        return {
            str(key): str(value)
            for key, value in payload.items()
            if key and value is not None
        }
    return _load_netscape_cookies(path)


def _write_auth_status(
    settings: Settings,
    state: str,
    message: str,
    **extra: Any,
) -> None:
    settings.douyin_cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": state,
        "message": message,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        **extra,
    }
    path = settings.douyin_cache_dir / "auth_status.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _first_url(value: Any) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        urls = value.get("url_list")
        if isinstance(urls, list):
            return next((str(item) for item in urls if item), None)
    return None
