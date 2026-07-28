from __future__ import annotations

from pathlib import Path
from typing import Any

from config import SETTINGS, Settings
from downloader.platform_auth import (
    browser_cookie_spec,
    resolve_authorized_cookie_file,
)


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def apply_yt_dlp_options(
    options: dict[str, Any],
    settings: Settings = SETTINGS,
    platform: str | None = None,
) -> dict[str, Any]:
    options.setdefault("http_headers", dict(DEFAULT_HEADERS))
    if settings.ffmpeg_path:
        options.setdefault("ffmpeg_location", str(settings.ffmpeg_path))
    if settings.yt_dlp_proxy:
        options.setdefault("proxy", settings.yt_dlp_proxy)

    if platform == "youtube":
        cookie_path = resolve_authorized_cookie_file(platform, settings)
        browser_spec = browser_cookie_spec(platform, settings)
    else:
        cookie_file = (
            _platform_setting(settings, platform, "cookie_file")
            or settings.yt_dlp_cookie_file
        )
        cookie_path = None
        if cookie_file:
            cookie_path = Path(str(cookie_file)).expanduser()
            if not cookie_path.is_absolute():
                cookie_path = settings.base_dir / cookie_path
            if not cookie_path.is_file():
                raise RuntimeError(f"Cookie file does not exist: {cookie_path}")
        browser_spec = (
            _platform_setting(settings, platform, "cookies_from_browser")
            or settings.yt_dlp_cookies_from_browser
        )
    if cookie_path:
        options["cookiefile"] = str(cookie_path)
    elif browser_spec:
        options["cookiesfrombrowser"] = _parse_browser_spec(str(browser_spec))
    return options


def _platform_setting(settings: Settings, platform: str | None, suffix: str) -> str | None:
    if not platform:
        return None
    value = getattr(settings, f"{platform}_{suffix}", None)
    return str(value).strip() if value else None


def _parse_browser_spec(value: str) -> tuple[str | None, ...]:
    parts = [item.strip() or None for item in value.split(":", 3)]
    while parts and parts[-1] is None:
        parts.pop()
    return tuple(parts) if parts else ("chrome",)
