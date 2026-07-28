from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Iterable

from config import SETTINGS, Settings
from downloader.youtube import is_youtube_channel_url, normalize_youtube_channel_url
from downloader.yt_dlp_common import apply_yt_dlp_options


logger = logging.getLogger(__name__)
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


def youtube_channel_cache_key(source: str) -> str:
    normalized = normalize_youtube_channel_url(source)
    match = re.search(r"youtube\.com/(?P<channel>[^/]+(?:/[^/]+)?)/videos$", normalized)
    readable = (match.group("channel") if match else "").replace("/", "_").lstrip("@")
    readable = re.sub(r"[^0-9A-Za-z._-]+", "_", readable).strip("_")[:48]
    digest = hashlib.sha1(normalized.lower().encode("utf-8")).hexdigest()[:10]
    return f"{readable}_{digest}" if readable else digest


class YoutubeChannelCrawler:
    def __init__(self, settings: Settings = SETTINGS):
        self.settings = settings

    def fetch_video_sources(
        self,
        source: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if not is_youtube_channel_url(source):
            raise ValueError(f"无法识别 YouTube 频道主页: {source}")
        normalized = normalize_youtube_channel_url(source)
        limit = limit or self.settings.batch_limit
        cache_path = self._cache_path(normalized)
        stale_entries: list[dict[str, Any]] = []

        if cache_path.exists() and not self.settings.overwrite_cache:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            entries = cached.get("videos") or []
            stale_entries = entries if isinstance(entries, list) else []
            if stale_entries and len(stale_entries) >= limit:
                logger.info("Using cached YouTube channel list: %s", cache_path)
                return stale_entries[:limit]

        try:
            info = self._extract_channel_info(normalized, limit)
            videos = [
                seed
                for seed in (_entry_to_video_seed(entry) for entry in _iter_entries(info))
                if seed.get("source_url")
            ][:limit]
        except Exception as exc:
            if stale_entries:
                logger.warning(
                    "Using stale YouTube channel cache after live fetch failed: %s",
                    exc,
                )
                return stale_entries[:limit]
            raise RuntimeError(_humanize_youtube_channel_error(exc)) from exc

        if not videos:
            if stale_entries:
                return stale_entries[:limit]
            raise RuntimeError(
                "没有获取到 YouTube 频道视频列表。请确认频道公开且包含公开视频；"
                "如果 YouTube 要求登录，请回到网页主界面点击“登录YouTube”。"
            )

        payload = {
            "platform": "youtube",
            "source": source,
            "normalized_source": normalized,
            "channel_id": info.get("id"),
            "channel_title": info.get("channel") or info.get("uploader") or info.get("title"),
            "limit": limit,
            "videos": videos,
        }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return videos

    def _extract_channel_info(self, source: str, limit: int) -> dict[str, Any]:
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError("缺少 yt-dlp，请先安装 requirements.txt 中的依赖。") from exc

        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
            "ignoreerrors": True,
            "playlistend": limit,
            "lazy_playlist": True,
            "retries": 3,
            "extractor_retries": 3,
            "socket_timeout": 30,
        }
        apply_yt_dlp_options(options, self.settings, "youtube")

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(source, download=False)
                if isinstance(info, dict):
                    return info
            except Exception as exc:
                last_error = exc
                logger.info(
                    "YouTube channel list fetch attempt %s failed: %s",
                    attempt + 1,
                    exc,
                )
                if attempt == 0:
                    time.sleep(1)
        if last_error:
            raise last_error
        raise RuntimeError("YouTube 返回了无效的频道信息。")

    def _cache_path(self, source: str) -> Path:
        return (
            self.settings.up_cache_dir
            / "youtube"
            / youtube_channel_cache_key(source)
            / "videos.json"
        )


def _iter_entries(info: dict[str, Any] | None) -> Iterable[dict[str, Any]]:
    if not info:
        return
    entries = info.get("entries")
    if entries is None:
        yield info
        return
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        nested = entry.get("entries")
        if nested is not None:
            yield from _iter_entries(entry)
        else:
            yield entry


def _entry_to_video_seed(entry: dict[str, Any]) -> dict[str, Any]:
    video_id = str(entry.get("id") or entry.get("display_id") or "").strip()
    raw_url = str(entry.get("webpage_url") or entry.get("url") or "").strip()
    if video_id:
        source_url = f"https://www.youtube.com/watch?v={video_id}"
    elif "youtube.com/watch" in raw_url or "youtu.be/" in raw_url:
        source_url = raw_url
    else:
        source_url = ""
    return {
        "source_url": source_url,
        "video_id": video_id,
        "title": entry.get("title") or "",
        "author": entry.get("uploader") or entry.get("channel"),
        "duration": entry.get("duration"),
        "publish_time": entry.get("upload_date") or entry.get("timestamp"),
        "cover": entry.get("thumbnail"),
        "view_count": entry.get("view_count"),
    }


def _humanize_youtube_channel_error(exc: Exception) -> str:
    message = ANSI_ESCAPE_RE.sub("", str(exc))
    lowered = message.lower()
    if "cookie file does not exist" in lowered:
        return message
    if any(term in lowered for term in ("sign in", "not a bot", "login", "cookies")):
        return (
            "YouTube 要求登录或人机验证。请回到网页主界面"
            "点击“重新登录YouTube”刷新本地会话。"
        )
    if "unsupported url" in lowered:
        return "无法识别该 YouTube 频道主页，请使用频道的 @名称 或 /channel/ 链接。"
    return message


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fetch videos from a YouTube channel.")
    parser.add_argument("source")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    print(
        json.dumps(
            YoutubeChannelCrawler().fetch_video_sources(args.source, args.limit),
            ensure_ascii=False,
            indent=2,
        )
    )
