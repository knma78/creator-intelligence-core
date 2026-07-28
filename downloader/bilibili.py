from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from config import SETTINGS, Settings
from downloader.bilibili_common import apply_yt_dlp_auth_options, humanize_bilibili_error
from models import Video

logger = logging.getLogger(__name__)

BV_RE = re.compile(r"(BV[0-9A-Za-z]+)")
SUBTITLE_EXTS = {".srt", ".vtt", ".ass", ".json", ".json3", ".ttml", ".xml"}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".flv", ".m4v"}
SUBTITLE_LANG_PRIORITY = [
    "zh-Hans",
    "zh-CN",
    "zh",
    "zh-Hant",
    "zh-TW",
    "en",
]


def is_bilibili_url(value: str) -> bool:
    value = value.strip()
    return (
        "bilibili.com" in value
        or "b23.tv" in value
        or bool(BV_RE.search(value))
    )


def extract_bv_id(value: str) -> str | None:
    match = BV_RE.search(value)
    return match.group(1) if match else None


def normalize_bilibili_url(value: str) -> str:
    value = value.strip()
    if BV_RE.fullmatch(value):
        return f"https://www.bilibili.com/video/{value}"
    return value


def _safe_filename(value: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip()
    return sanitized[:120] or "untitled"


def _format_upload_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        return value


class BilibiliDownloader:
    def __init__(self, settings: Settings = SETTINGS):
        self.settings = settings

    def download(self, url: str) -> Video:
        url = normalize_bilibili_url(url)
        known_id = extract_bv_id(url)
        if known_id:
            cached = self._load_cached_video(known_id)
            if cached and not self.settings.overwrite_cache:
                logger.info("Using cached Bilibili asset: %s", known_id)
                return cached

        info = self._extract_info(url)
        video_id = str(info.get("id") or known_id or _safe_filename(info.get("title", "")))
        cached = self._load_cached_video(video_id)
        if cached and not self.settings.overwrite_cache:
            logger.info("Using cached Bilibili asset: %s", video_id)
            return cached

        video_dir = self.settings.video_cache_dir / video_id
        video_dir.mkdir(parents=True, exist_ok=True)

        subtitle_lang = self._pick_official_subtitle_lang(info)
        if subtitle_lang:
            logger.info("Official subtitle found (%s), downloading subtitle only: %s", subtitle_lang, url)
            self._download_official_subtitle_only(url, video_dir, subtitle_lang)
            subtitle_path = self._find_subtitle_file(video_dir)
            if not subtitle_path:
                raise FileNotFoundError(f"Official subtitle download finished but no subtitle file was found in {video_dir}")

            video = self._video_from_info(
                url=url,
                info=info,
                video_id=video_id,
                video_path=None,
                subtitle_path=subtitle_path,
            )
            self._save_metadata(video)
            return video

        logger.info("Downloading Bilibili video: %s", url)
        self._download_with_ytdlp(url, video_dir)

        video_path = self._find_video_file(video_dir)
        if not video_path:
            raise FileNotFoundError(f"Video download finished but no video file was found in {video_dir}")

        subtitle_path = self._find_subtitle_file(video_dir)
        video = self._video_from_info(
            url=url,
            info=info,
            video_id=video_id,
            video_path=video_path,
            subtitle_path=subtitle_path,
        )
        self._save_metadata(video)
        return video

    def _extract_info(self, url: str) -> dict[str, Any]:
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError("Missing dependency: install yt-dlp first.") from exc

        opts: dict[str, Any] = {"quiet": True, "no_warnings": True, "noplaylist": True}
        apply_yt_dlp_auth_options(opts, self.settings)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)
        except Exception as exc:
            raise RuntimeError(humanize_bilibili_error(exc)) from exc

    def _download_official_subtitle_only(self, url: str, video_dir: Path, subtitle_lang: str) -> None:
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError("Missing dependency: install yt-dlp first.") from exc

        opts: dict[str, Any] = {
            "skip_download": True,
            "noplaylist": True,
            "outtmpl": str(video_dir / "%(id)s.%(ext)s"),
            "quiet": False,
            "no_warnings": False,
            "writesubtitles": True,
            "writeautomaticsub": False,
            "subtitleslangs": [subtitle_lang],
            "subtitlesformat": "srt/vtt/json3/best",
        }
        apply_yt_dlp_auth_options(opts, self.settings)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as exc:
            raise RuntimeError(humanize_bilibili_error(exc)) from exc

    def _download_with_ytdlp(self, url: str, video_dir: Path) -> None:
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError("Missing dependency: install yt-dlp first.") from exc

        opts: dict[str, Any] = {
            "format": "bv*+ba/best",
            "merge_output_format": "mp4",
            "noplaylist": True,
            "outtmpl": str(video_dir / "%(id)s.%(ext)s"),
            "quiet": False,
            "no_warnings": False,
            "writesubtitles": False,
            "writeautomaticsub": False,
        }
        apply_yt_dlp_auth_options(opts, self.settings)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as exc:
            raise RuntimeError(humanize_bilibili_error(exc)) from exc

    def _load_cached_video(self, video_id: str) -> Video | None:
        metadata_path = self.settings.video_cache_dir / video_id / "metadata.json"
        if not metadata_path.exists():
            return None
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        video = Video.from_dict(data)
        if video.subtitle_path and not video.subtitle_path.exists():
            video.subtitle_path = self._find_subtitle_file(metadata_path.parent)
        if video.video_path and not video.video_path.exists():
            video.video_path = self._find_video_file(metadata_path.parent)
        if video.subtitle_path and video.subtitle_path.exists():
            return video
        if video.video_path and video.video_path.exists():
            return video
        return None

    def _save_metadata(self, video: Video) -> None:
        metadata_path = self.settings.video_cache_dir / video.video_id / "metadata.json"
        video.metadata_path = metadata_path
        metadata_path.write_text(
            json.dumps(video.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _video_from_info(
        self,
        url: str,
        info: dict[str, Any],
        video_id: str,
        video_path: Path | None,
        subtitle_path: Path | None,
    ) -> Video:
        title = info.get("title") or (video_path.stem if video_path else video_id)
        stats = {
            "view_count": info.get("view_count"),
            "like_count": info.get("like_count"),
            "comment_count": info.get("comment_count"),
            "danmaku_count": info.get("danmaku_count"),
            "duration": info.get("duration"),
        }
        extra_metadata = {
            "aid": info.get("aid") or info.get("av_id"),
            "cid": info.get("cid"),
            "bvid": video_id,
            "tags": info.get("tags") or [],
            "categories": info.get("categories") or [],
            "description": info.get("description"),
            "webpage_url": info.get("webpage_url"),
        }
        return Video(
            source_url=url,
            platform="bilibili",
            video_id=video_id,
            title=title,
            author=info.get("uploader") or info.get("channel") or info.get("creator"),
            cover=info.get("thumbnail"),
            publish_time=_format_upload_date(info.get("upload_date")),
            duration=info.get("duration"),
            video_path=video_path,
            subtitle_path=subtitle_path,
            metadata_path=self.settings.video_cache_dir / video_id / "metadata.json",
            stats={key: value for key, value in stats.items() if value is not None},
            extra_metadata={key: value for key, value in extra_metadata.items() if value not in (None, "", [])},
        )

    @staticmethod
    def _pick_official_subtitle_lang(info: dict[str, Any]) -> str | None:
        subtitles = info.get("subtitles")
        if not isinstance(subtitles, dict) or not subtitles:
            return None

        available = [
            lang for lang, entries in subtitles.items()
            if isinstance(entries, list) and entries
        ]
        if not available:
            return None

        for preferred in SUBTITLE_LANG_PRIORITY:
            if preferred in available:
                return preferred

        zh_like = sorted(lang for lang in available if lang.lower().startswith("zh"))
        if zh_like:
            return zh_like[0]

        return sorted(available)[0]

    @staticmethod
    def _find_video_file(video_dir: Path) -> Path | None:
        candidates = [
            path for path in video_dir.iterdir()
            if path.is_file() and path.suffix.lower() in VIDEO_EXTS
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.stat().st_size)

    @staticmethod
    def _find_subtitle_file(video_dir: Path) -> Path | None:
        candidates = [
            path for path in video_dir.iterdir()
            if path.is_file() and path.suffix.lower() in SUBTITLE_EXTS
        ]
        if not candidates:
            return None
        priority = {".srt": 0, ".vtt": 1, ".json3": 2, ".json": 3, ".ass": 4}
        return sorted(candidates, key=lambda item: priority.get(item.suffix.lower(), 99))[0]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Download a Bilibili video into cache.")
    parser.add_argument("url")
    args = parser.parse_args()
    video = BilibiliDownloader().download(args.url)
    print(json.dumps(video.to_dict(), ensure_ascii=False, indent=2))
