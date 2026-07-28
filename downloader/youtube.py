from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from config import SETTINGS, Settings
from downloader.yt_dlp_common import apply_yt_dlp_options
from models import Video


logger = logging.getLogger(__name__)

YOUTUBE_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?(?:youtube\.com/(?:watch|shorts|live)|youtu\.be/)",
    re.IGNORECASE,
)
YOUTUBE_CHANNEL_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.|m\.)?youtube\.com/"
    r"(?P<channel>@[0-9A-Za-z._-]+|channel/[0-9A-Za-z_-]+|c/[0-9A-Za-z._-]+|user/[0-9A-Za-z._-]+)"
    r"(?:/(?:featured|videos|shorts|streams|playlists))?/?(?:[?#].*)?$",
    re.IGNORECASE,
)
SUBTITLE_EXTS = {".srt", ".vtt", ".ass", ".json", ".json3"}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".m4v"}
SUBTITLE_LANG_PRIORITY = ["zh-Hans", "zh-CN", "zh", "zh-Hant", "zh-TW", "en"]


def is_youtube_url(value: str) -> bool:
    return bool(YOUTUBE_URL_RE.search(value.strip()))


def is_youtube_channel_url(value: str) -> bool:
    return bool(YOUTUBE_CHANNEL_URL_RE.match(value.strip()))


def normalize_youtube_channel_url(value: str) -> str:
    match = YOUTUBE_CHANNEL_URL_RE.match(value.strip())
    if not match:
        raise ValueError(f"无法识别 YouTube 频道主页: {value}")
    return f"https://www.youtube.com/{match.group('channel')}/videos"


def _format_upload_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        return value


class YoutubeDownloader:
    def __init__(self, settings: Settings = SETTINGS):
        self.settings = settings

    def download(self, url: str) -> Video:
        info = self._extract_info(url)
        source_id = str(info.get("id") or "").strip()
        if not source_id:
            raise RuntimeError("YouTube did not return a video id.")
        video_id = f"YT_{source_id}"
        video_dir = self.settings.video_cache_dir / video_id

        cached = self._load_cached_video(video_id)
        if cached and not self.settings.overwrite_cache:
            logger.info("Using cached YouTube asset: %s", video_id)
            return cached

        video_dir.mkdir(parents=True, exist_ok=True)
        subtitle = self._pick_subtitle(info)
        if subtitle:
            language, automatic = subtitle
            logger.info("YouTube subtitle found (%s), downloading subtitle only.", language)
            self._download_subtitle(url, video_dir, language, automatic)
            subtitle_path = self._find_file(video_dir, SUBTITLE_EXTS)
            if subtitle_path:
                video = self._video_from_info(url, info, video_id, None, subtitle_path)
                self._save_metadata(video)
                return video
            logger.warning("YouTube subtitle download produced no usable file; falling back to video download.")

        self._download_video(url, video_dir)
        video_path = self._find_file(video_dir, VIDEO_EXTS)
        if not video_path:
            raise FileNotFoundError(f"YouTube download finished but no video file was found in {video_dir}")
        video = self._video_from_info(url, info, video_id, video_path, None)
        self._save_metadata(video)
        return video

    def _extract_info(self, url: str) -> dict[str, Any]:
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError("Missing dependency: install yt-dlp first.") from exc

        try:
            with yt_dlp.YoutubeDL(self._base_options(quiet=True)) as ydl:
                return ydl.extract_info(url, download=False)
        except Exception as exc:
            raise RuntimeError(self._humanize_error(exc)) from exc

    def _download_subtitle(self, url: str, video_dir: Path, language: str, automatic: bool) -> None:
        import yt_dlp

        options = self._base_options(quiet=False)
        options.update(
            {
                "skip_download": True,
                "outtmpl": str(video_dir / "%(id)s.%(ext)s"),
                "writesubtitles": not automatic,
                "writeautomaticsub": automatic,
                "subtitleslangs": [language],
                "subtitlesformat": "srt/vtt/json3/best",
            }
        )
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([url])
        except Exception as exc:
            raise RuntimeError(self._humanize_error(exc)) from exc

    def _download_video(self, url: str, video_dir: Path) -> None:
        import yt_dlp

        options = self._base_options(quiet=False)
        options.update(
            {
                "format": "bv*+ba/best",
                "merge_output_format": "mp4",
                "outtmpl": str(video_dir / "%(id)s.%(ext)s"),
            }
        )
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([url])
        except Exception as exc:
            raise RuntimeError(self._humanize_error(exc)) from exc

    def _base_options(self, quiet: bool) -> dict[str, Any]:
        options: dict[str, Any] = {
            "quiet": quiet,
            "no_warnings": quiet,
            "noplaylist": True,
        }
        return apply_yt_dlp_options(options, self.settings, "youtube")

    def _pick_subtitle(self, info: dict[str, Any]) -> tuple[str, bool] | None:
        manual = self._pick_language(info.get("subtitles"))
        if manual:
            return manual, False
        automatic = self._pick_language(info.get("automatic_captions"))
        if automatic:
            return automatic, True
        return None

    @staticmethod
    def _pick_language(subtitles: Any) -> str | None:
        if not isinstance(subtitles, dict):
            return None
        available = [key for key, values in subtitles.items() if isinstance(values, list) and values]
        for preferred in SUBTITLE_LANG_PRIORITY:
            if preferred in available:
                return preferred
        zh_like = sorted(key for key in available if key.lower().startswith("zh"))
        if zh_like:
            return zh_like[0]
        return available[0] if available else None

    def _load_cached_video(self, video_id: str) -> Video | None:
        metadata_path = self.settings.video_cache_dir / video_id / "metadata.json"
        if not metadata_path.exists():
            return None
        video = Video.from_dict(json.loads(metadata_path.read_text(encoding="utf-8")))
        if video.subtitle_path and video.subtitle_path.exists():
            return video
        if video.video_path and video.video_path.exists():
            return video
        return None

    def _save_metadata(self, video: Video) -> None:
        metadata_path = self.settings.video_cache_dir / video.video_id / "metadata.json"
        video.metadata_path = metadata_path
        metadata_path.write_text(json.dumps(video.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _video_from_info(
        self,
        url: str,
        info: dict[str, Any],
        video_id: str,
        video_path: Path | None,
        subtitle_path: Path | None,
    ) -> Video:
        stats = {
            "view_count": info.get("view_count"),
            "like_count": info.get("like_count"),
            "comment_count": info.get("comment_count"),
            "duration": info.get("duration"),
        }
        return Video(
            source_url=url,
            platform="youtube",
            video_id=video_id,
            title=str(info.get("title") or video_id),
            author=info.get("uploader") or info.get("channel") or info.get("creator"),
            cover=info.get("thumbnail"),
            publish_time=_format_upload_date(info.get("upload_date")),
            duration=info.get("duration"),
            video_path=video_path,
            subtitle_path=subtitle_path,
            metadata_path=self.settings.video_cache_dir / video_id / "metadata.json",
            stats={key: value for key, value in stats.items() if value is not None},
            extra_metadata={
                "source_id": info.get("id"),
                "channel_id": info.get("channel_id"),
                "tags": info.get("tags") or [],
                "categories": info.get("categories") or [],
                "description": info.get("description"),
                "webpage_url": info.get("webpage_url") or url,
            },
        )

    @staticmethod
    def _find_file(directory: Path, extensions: set[str]) -> Path | None:
        candidates = [
            path for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in extensions
        ]
        return sorted(candidates, key=lambda path: path.stat().st_size, reverse=True)[0] if candidates else None

    @staticmethod
    def _humanize_error(exc: Exception) -> str:
        message = str(exc)
        if "Sign in to confirm" in message or "not a bot" in message:
            return "YouTube要求登录验证。请稍后重试，或为yt-dlp配置可用的Cookie。"
        if "ffmpeg" in message.lower():
            return "YouTube音视频合并失败，请检查FFMPEG_PATH配置。"
        return message
