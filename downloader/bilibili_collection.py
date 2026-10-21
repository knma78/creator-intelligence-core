from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from config import SETTINGS, Settings
from downloader.bilibili_common import (
    apply_yt_dlp_auth_options,
    humanize_bilibili_error,
    is_transient_bilibili_error,
)
from infrastructure.atomic_io import atomic_write_json
from infrastructure.cancellation import (
    JobCancelledError,
    raise_if_cancelled,
    sleep_with_cancellation,
)

logger = logging.getLogger(__name__)

BILIBILI_COLLECTION_RE = re.compile(
    r"bilibili\.com/(?:bangumi/play/ss\d+|bangumi/media/md\d+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BilibiliCollection:
    source_url: str
    title: str
    description: str
    category_hint: str
    videos: list[dict[str, Any]]


def is_bilibili_collection_url(value: str) -> bool:
    return bool(BILIBILI_COLLECTION_RE.search(str(value).strip()))


class BilibiliCollectionCrawler:
    def __init__(self, settings: Settings = SETTINGS):
        self.settings = settings

    def fetch_video_sources(
        self,
        source: str,
        limit: int | None = None,
    ) -> BilibiliCollection:
        if not is_bilibili_collection_url(source):
            raise ValueError(f"无法识别B站内容季页面：{source}")
        limit = max(1, int(limit or self.settings.batch_limit))
        cache_path = self._cache_path(source)
        stale = self._load_cache(cache_path, limit)
        if stale and len(stale.videos) >= limit and not self.settings.overwrite_cache:
            return BilibiliCollection(
                stale.source_url,
                stale.title,
                stale.description,
                stale.category_hint,
                stale.videos[:limit],
            )

        try:
            info = self._extract_collection_info(source, limit)
            videos = self._entry_sources(info, limit)
        except JobCancelledError:
            raise
        except Exception as exc:
            raise_if_cancelled(None)
            if stale:
                logger.warning(
                    "Using stale Bilibili collection cache after fetch failed: %s",
                    exc,
                )
                return BilibiliCollection(
                    stale.source_url,
                    stale.title,
                    stale.description,
                    stale.category_hint,
                    stale.videos[:limit],
                )
            raise RuntimeError(humanize_bilibili_error(exc)) from exc

        if not videos:
            raise RuntimeError(
                "B站内容季页面没有返回可分析的单集。请确认页面可播放，"
                "并在主界面点击“重新登录B站”刷新会话。"
            )
        collection = BilibiliCollection(
            source_url=source,
            title=str(info.get("title") or "B站内容作品").strip(),
            description=str(info.get("description") or "").strip(),
            category_hint=_category_hint(source),
            videos=videos,
        )
        atomic_write_json(
            cache_path,
            {
                "source_url": collection.source_url,
                "title": collection.title,
                "description": collection.description,
                "category_hint": collection.category_hint,
                "videos": collection.videos,
            },
        )
        return collection

    def _extract_collection_info(
        self,
        source: str,
        limit: int,
    ) -> dict[str, Any]:
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError("缺少 yt-dlp，请先安装 requirements.txt 中的依赖。") from exc

        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
            "ignoreerrors": False,
            "playlistend": limit,
            "lazy_playlist": False,
        }
        apply_yt_dlp_auth_options(options, self.settings)
        attempts = max(1, self.settings.bilibili_download_attempts)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(source, download=False)
                if isinstance(info, dict):
                    return info
                raise RuntimeError("B站返回了无效的内容季信息。")
            except Exception as exc:
                raise_if_cancelled(None)
                last_error = exc
                if not is_transient_bilibili_error(exc) or attempt + 1 >= attempts:
                    raise
                logger.warning(
                    "Bilibili collection fetch attempt %s/%s failed: %s",
                    attempt + 1,
                    attempts,
                    exc,
                )
                sleep_with_cancellation(min(3, attempt + 1))
        assert last_error is not None
        raise last_error

    @staticmethod
    def _entry_sources(
        info: dict[str, Any],
        limit: int,
    ) -> list[dict[str, Any]]:
        videos: list[dict[str, Any]] = []
        seen: set[str] = set()
        entries = info.get("entries") or []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_id = str(entry.get("id") or "").strip()
            source_url = str(
                entry.get("webpage_url") or entry.get("url") or ""
            ).strip()
            if not source_url and entry_id:
                source_url = (
                    "https://www.bilibili.com/bangumi/play/"
                    f"ep{entry_id}"
                )
            if not source_url.startswith(("http://", "https://")):
                continue
            if source_url in seen:
                continue
            seen.add(source_url)
            videos.append(
                {
                    "source_url": source_url,
                    "video_id": entry_id,
                    "title": str(entry.get("title") or "").strip(),
                }
            )
            if len(videos) >= limit:
                break
        return videos

    def _cache_path(self, source: str) -> Path:
        key = hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]
        return self.settings.cache_dir / "bilibili_collections" / key / "videos.json"

    @staticmethod
    def _load_cache(
        path: Path,
        limit: int,
    ) -> BilibiliCollection | None:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            videos = payload.get("videos") or []
            if not isinstance(videos, list) or not videos:
                return None
            return BilibiliCollection(
                source_url=str(payload.get("source_url") or ""),
                title=str(payload.get("title") or "B站内容作品"),
                description=str(payload.get("description") or ""),
                category_hint=str(payload.get("category_hint") or "auto"),
                videos=videos[:limit],
            )
        except (OSError, json.JSONDecodeError):
            return None


def _category_hint(source: str) -> str:
    query = parse_qs(urlparse(source).query)
    theme = str((query.get("theme") or [""])[0]).strip().lower()
    return theme if theme in {"movie", "anime"} else "auto"
