from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from config import SETTINGS, Settings
from downloader.bilibili_common import bilibili_headers, load_bilibili_cookie_dict
from infrastructure.atomic_io import atomic_write_json
from models import Video

logger = logging.getLogger(__name__)


def fetch_bilibili_comments(
    video: Video,
    settings: Settings = SETTINGS,
    limit: int | None = None,
) -> dict[str, Any]:
    limit = limit or settings.comment_limit
    cache_dir = settings.comments_cache_dir / video.video_id
    cache_path = cache_dir / "comments.json"
    if cache_path.exists() and not settings.overwrite_cache:
        return json.loads(cache_path.read_text(encoding="utf-8"))

    payload = _fetch_comments(video, limit)
    cache_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(cache_path, payload)
    return payload


def _fetch_comments(video: Video, limit: int) -> dict[str, Any]:
    aid = video.extra_metadata.get("aid")
    if not aid:
        return _status(video, "skipped", "missing aid; cannot query Bilibili comment API")

    try:
        import requests
    except ImportError:
        return _status(video, "skipped", "missing dependency: requests")

    comments: list[dict[str, Any]] = []
    page = 1
    page_size = min(49, max(1, limit))
    try:
        while len(comments) < limit:
            response = requests.get(
                "https://api.bilibili.com/x/v2/reply",
                params={"type": 1, "oid": aid, "sort": 2, "pn": page, "ps": page_size},
                headers=bilibili_headers(video.source_url),
                cookies=load_bilibili_cookie_dict(settings),
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") != 0:
                return _status(video, "error", f"Bilibili comment API returned {data.get('code')}: {data.get('message')}")
            replies = ((data.get("data") or {}).get("replies")) or []
            if not replies:
                break
            for reply in replies:
                comments.append(_normalize_comment(reply))
                if len(comments) >= limit:
                    break
            page += 1
    except Exception as exc:  # network/API should not break the main pipeline
        logger.warning("Comment fetch failed for %s: %s", video.video_id, exc)
        return _status(video, "error", str(exc), comments)

    return {
        "video_id": video.video_id,
        "aid": aid,
        "status": "ok",
        "fetched_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "count": len(comments),
        "comments": comments,
    }


def _normalize_comment(reply: dict[str, Any]) -> dict[str, Any]:
    member = reply.get("member") or {}
    content = reply.get("content") or {}
    return {
        "rpid": reply.get("rpid"),
        "ctime": reply.get("ctime"),
        "like": reply.get("like"),
        "user": member.get("uname"),
        "message": content.get("message") or "",
    }


def _status(
    video: Video,
    status: str,
    reason: str,
    comments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "video_id": video.video_id,
        "aid": video.extra_metadata.get("aid"),
        "status": status,
        "reason": reason,
        "count": len(comments or []),
        "comments": comments or [],
    }
