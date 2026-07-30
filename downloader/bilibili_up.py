from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from config import SETTINGS, Settings
from downloader.bilibili import BV_RE, normalize_bilibili_url
from downloader.bilibili_common import (
    apply_yt_dlp_auth_options,
    bilibili_headers,
    create_bilibili_session,
    humanize_bilibili_error,
    sign_wbi_params,
)
from infrastructure.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)

UP_URL_RE = re.compile(r"(?:space\.bilibili\.com|bilibili\.com/space)/(?P<mid>\d+)")
MID_RE = re.compile(r"^\d{4,}$")


def is_bilibili_up_source(value: str) -> bool:
    value = value.strip()
    return bool(UP_URL_RE.search(value) or MID_RE.fullmatch(value))


def normalize_up_url(value: str) -> str:
    value = value.strip()
    if MID_RE.fullmatch(value):
        return f"https://space.bilibili.com/{value}/video"
    match = UP_URL_RE.search(value)
    if match and "/video" not in value:
        return f"https://space.bilibili.com/{match.group('mid')}/video"
    return value


def up_cache_key(source: str) -> str:
    match = UP_URL_RE.search(source)
    if match:
        return match.group("mid")
    if MID_RE.fullmatch(source.strip()):
        return source.strip()
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]


class BilibiliUPCrawler:
    def __init__(self, settings: Settings = SETTINGS):
        self.settings = settings

    def fetch_video_sources(self, source: str, limit: int | None = None) -> list[dict[str, Any]]:
        source = resolve_up_source(source, self.settings)
        limit = limit or self.settings.batch_limit
        cache_path = self._cache_path(source)
        stale_entries: list[dict[str, Any]] = []

        if cache_path.exists() and not self.settings.overwrite_cache:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            entries = cached.get("videos", [])
            stale_entries = entries if isinstance(entries, list) else []
            if stale_entries and len(stale_entries) >= limit:
                logger.info("Using cached UP video list: %s", cache_path)
                return stale_entries[:limit]

        videos = self._fetch_video_list(source, limit)
        if not videos and stale_entries:
            logger.info("Using stale cached UP video list after live fetch failed: %s", cache_path)
            return stale_entries[:limit]
        if not videos:
            raise RuntimeError(
                "Cannot fetch the UP video list. Bilibili may be rate-limiting the space API. "
                "Try again later, or use the Web UI to sign in to Bilibili again."
            )

        payload = {"source": source, "limit": limit, "videos": videos}
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(cache_path, payload)
        return videos

    def _fetch_video_list(self, source: str, limit: int) -> list[dict[str, Any]]:
        for attempt in range(3):
            api_videos = self._fetch_with_bilibili_api(source, limit)
            if api_videos:
                return api_videos
            if api_videos == []:
                break
            logger.info("Bilibili API returned no list, retrying API-first fetch: %s", attempt + 1)
            time.sleep(1 + attempt)

        ytdlp_videos = self._fetch_with_ytdlp(source, limit)
        if ytdlp_videos:
            return ytdlp_videos

        api_videos = self._fetch_with_bilibili_api(source, limit)
        return api_videos or []

    def _fetch_with_ytdlp(self, source: str, limit: int) -> list[dict[str, Any]]:
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError("Missing dependency: install yt-dlp first.") from exc

        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
            "ignoreerrors": True,
            "playlistend": limit,
        }
        apply_yt_dlp_auth_options(opts, self.settings)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(source, download=False)
        except Exception as exc:
            logger.info("yt-dlp UP list fallback failed: %s", humanize_bilibili_error(exc))
            return []

        entries = list(_iter_entries(info))
        videos = [_entry_to_video_seed(entry) for entry in entries]
        videos = [video for video in videos if video.get("source_url")][:limit]
        if not videos:
            logger.info("yt-dlp UP list fallback returned no usable videos: %s", source)
        return videos

    def _cache_path(self, source: str) -> Path:
        return self.settings.up_cache_dir / up_cache_key(source) / "videos.json"

    def _fetch_with_bilibili_api(self, source: str, limit: int) -> list[dict[str, Any]] | None:
        mid = up_cache_key(source)
        if not MID_RE.fullmatch(mid):
            return None

        videos: list[dict[str, Any]] = []
        page = 1
        page_size = min(50, max(1, limit))

        while len(videos) < limit:
            payload = self._fetch_api_page(mid, page, page_size)
            if payload is None:
                return None
            if payload.get("code") != 0:
                logger.info("Bilibili API list returned %s: %s", payload.get("code"), payload.get("message"))
                return None

            vlist = ((((payload.get("data") or {}).get("list")) or {}).get("vlist")) or []
            if not vlist:
                break

            for item in vlist:
                seed = _api_video_to_seed(item)
                if seed.get("source_url"):
                    videos.append(seed)
                if len(videos) >= limit:
                    break

            if len(vlist) < page_size:
                break
            page += 1

        return videos[:limit]

    def _fetch_api_page(self, mid: str, page: int, page_size: int) -> dict[str, Any] | None:
        referer = normalize_up_url(mid)
        for attempt in range(5):
            try:
                session = create_bilibili_session(self.settings, referer)
                params = sign_wbi_params(
                    session,
                    {
                        "mid": mid,
                        "ps": page_size,
                        "tid": 0,
                        "pn": page,
                        "order": "pubdate",
                        "platform": "web",
                        "web_location": "1550101",
                        "dm_img_list": "[]",
                        "dm_img_str": "",
                        "dm_cover_img_str": "",
                        "dm_img_inter": '{"ds":[],"wh":[0,0,0],"of":[0,0,0]}',
                    },
                    self.settings,
                )
                response = session.get(
                    "https://api.bilibili.com/x/space/wbi/arc/search",
                    params=params,
                    timeout=20,
                )
                if response.status_code == 412:
                    logger.info("Bilibili API page fetch blocked with HTTP 412 on attempt %s", attempt + 1)
                    time.sleep(1 + attempt)
                    continue

                response.raise_for_status()
                payload = response.json()
                if payload.get("code") in {-352, -412, -799}:
                    logger.info(
                        "Bilibili API page fetch blocked with code %s on attempt %s: %s",
                        payload.get("code"),
                        attempt + 1,
                        payload.get("message"),
                    )
                    time.sleep(1 + attempt)
                    continue
                return payload
            except Exception as exc:
                logger.info("Bilibili API page fetch failed on attempt %s: %s", attempt + 1, exc)
                time.sleep(1 + attempt)
        return None


def resolve_up_source(source: str, settings: Settings = SETTINGS) -> str:
    source = source.strip()
    if is_bilibili_up_source(source):
        return normalize_up_url(source)

    resolved = resolve_up_name(source, settings)
    if not resolved:
        raise ValueError(f"Cannot resolve Bilibili UP name: {source}")
    return normalize_up_url(str(resolved["mid"]))


def resolve_up_name(name: str, settings: Settings = SETTINGS) -> dict[str, Any] | None:
    name = name.strip()
    if not name:
        return None

    cache_path = settings.up_cache_dir / "name_search" / f"{hashlib.sha1(name.encode('utf-8')).hexdigest()[:16]}.json"
    if cache_path.exists() and not settings.overwrite_cache:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return payload.get("best_match")

    url = "https://api.bilibili.com/x/web-interface/search/type"
    referer = f"https://search.bilibili.com/upuser?keyword={quote(name)}"
    session = create_bilibili_session(settings, referer)
    try:
        response = session.get(
            url,
            params={"search_type": "bili_user", "keyword": name, "page": 1},
            headers=bilibili_headers(referer),
            timeout=20,
        )
        response.raise_for_status()
    except Exception as exc:
        raise RuntimeError(humanize_bilibili_error(exc)) from exc

    data = response.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Bilibili UP search failed: {data.get('message')}")

    results = ((data.get("data") or {}).get("result")) or []
    candidates = [_normalize_user_result(item) for item in results if item]
    best_match = _pick_best_user_match(name, candidates)
    payload = {"name": name, "best_match": best_match, "candidates": candidates[:10]}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(cache_path, payload)
    return best_match


def _normalize_user_result(item: dict[str, Any]) -> dict[str, Any]:
    uname = re.sub(r"<[^>]+>", "", str(item.get("uname") or item.get("title") or "")).strip()
    return {
        "mid": item.get("mid"),
        "name": uname,
        "fans": item.get("fans"),
        "videos": item.get("videos"),
        "sign": item.get("usign") or item.get("sign"),
        "avatar": item.get("upic") or item.get("pic"),
    }


def _pick_best_user_match(name: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None

    exact = [item for item in candidates if item.get("name") == name]
    if exact:
        return sorted(exact, key=lambda item: int(item.get("fans") or 0), reverse=True)[0]
    return sorted(candidates, key=lambda item: int(item.get("fans") or 0), reverse=True)[0]


def _iter_entries(info: dict[str, Any] | None):
    if not info:
        return

    entries = info.get("entries")
    if isinstance(entries, list):
        for entry in entries:
            if not entry:
                continue
            nested = entry.get("entries") if isinstance(entry, dict) else None
            if isinstance(nested, list):
                yield from _iter_entries(entry)
            else:
                yield entry
    else:
        yield info


def _entry_to_video_seed(entry: dict[str, Any]) -> dict[str, Any]:
    video_id = str(entry.get("id") or entry.get("display_id") or "")
    url = entry.get("webpage_url") or entry.get("url") or ""

    if video_id and BV_RE.search(video_id):
        video_id = BV_RE.search(video_id).group(1)  # type: ignore[union-attr]
    elif url and BV_RE.search(str(url)):
        video_id = BV_RE.search(str(url)).group(1)  # type: ignore[union-attr]

    if video_id and BV_RE.fullmatch(video_id):
        source_url = normalize_bilibili_url(video_id)
    elif url:
        source_url = normalize_bilibili_url(str(url))
    else:
        source_url = ""

    return {
        "source_url": source_url,
        "video_id": video_id,
        "title": entry.get("title") or "",
        "author": entry.get("uploader") or entry.get("channel"),
        "duration": entry.get("duration"),
        "publish_time": entry.get("upload_date"),
        "cover": entry.get("thumbnail"),
        "view_count": entry.get("view_count"),
    }


def _api_video_to_seed(item: dict[str, Any]) -> dict[str, Any]:
    bvid = str(item.get("bvid") or "")
    created = item.get("created")
    return {
        "source_url": normalize_bilibili_url(bvid) if bvid else "",
        "video_id": bvid,
        "title": item.get("title") or "",
        "author": item.get("author"),
        "duration": _duration_to_seconds(item.get("length")),
        "publish_time": str(created) if created else None,
        "cover": item.get("pic"),
        "view_count": item.get("play"),
        "comment_count": item.get("comment"),
        "danmaku_count": item.get("video_review"),
    }


def _duration_to_seconds(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value)
    parts = text.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        return int(float(text))
    except ValueError:
        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fetch videos from a Bilibili UP homepage.")
    parser.add_argument("source", help="UP name, mid, or https://space.bilibili.com/<mid>/video")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    print(json.dumps(BilibiliUPCrawler().fetch_video_sources(args.source, args.limit), ensure_ascii=False, indent=2))
