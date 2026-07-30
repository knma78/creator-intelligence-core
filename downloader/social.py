from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from config import SETTINGS, Settings
from downloader.douyin_adapter import (
    DouyinAdapter,
    douyin_profile_id,
    extract_douyin_url,
)
from downloader.yt_dlp_common import apply_yt_dlp_options
from infrastructure.atomic_io import atomic_write_json
from models import Video


logger = logging.getLogger(__name__)

DOUYIN_URL_RE = re.compile(
    r"(?:https?://)?(?:(?:www|m|v)\.)?douyin\.com/|"
    r"(?:https?://)?(?:www\.)?iesdouyin\.com/",
    re.IGNORECASE,
)
DOUYIN_VIDEO_URL_RE = re.compile(
    r"(?:https?://)?(?:(?:www|m)\.)?douyin\.com/video/\d+|"
    r"(?:https?://)?v\.douyin\.com/[0-9A-Za-z_-]+|"
    r"(?:https?://)?(?:www\.)?iesdouyin\.com/share/video/\d+",
    re.IGNORECASE,
)
XIAOHONGSHU_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?xiaohongshu\.com/|"
    r"(?:https?://)?xhslink\.com/",
    re.IGNORECASE,
)
XIAOHONGSHU_VIDEO_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?xiaohongshu\.com/(?:explore|discovery/item)/[\da-f]+|"
    r"(?:https?://)?xhslink\.com/[0-9A-Za-z_-]+",
    re.IGNORECASE,
)

SUBTITLE_EXTS = {".srt", ".vtt", ".ass", ".json", ".json3", ".ttml", ".xml"}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".flv", ".m4v", ".mov"}
SUBTITLE_LANG_PRIORITY = ["zh-Hans", "zh-CN", "zh", "zh-Hant", "zh-TW", "en"]
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


@dataclass(frozen=True)
class SocialPlatform:
    key: str
    display_name: str
    video_id_prefix: str


PLATFORMS = {
    "douyin": SocialPlatform("douyin", "抖音", "DY"),
    "xiaohongshu": SocialPlatform("xiaohongshu", "小红书", "XHS"),
}


def is_douyin_url(value: str) -> bool:
    return bool(DOUYIN_URL_RE.search(value.strip()))


def is_douyin_video_url(value: str) -> bool:
    return bool(DOUYIN_VIDEO_URL_RE.search(value.strip()))


def is_douyin_profile_url(value: str) -> bool:
    return is_douyin_url(value) and douyin_profile_id(value) is not None


def is_xiaohongshu_url(value: str) -> bool:
    return bool(XIAOHONGSHU_URL_RE.search(value.strip()))


def is_xiaohongshu_video_url(value: str) -> bool:
    return bool(XIAOHONGSHU_VIDEO_URL_RE.search(value.strip()))


def detect_social_platform(value: str) -> str | None:
    if is_douyin_url(value):
        return "douyin"
    if is_xiaohongshu_url(value):
        return "xiaohongshu"
    return None


def is_social_video_url(value: str) -> bool:
    return is_douyin_video_url(value) or is_xiaohongshu_video_url(value)


def is_social_profile_url(value: str) -> bool:
    return bool(detect_social_platform(value)) and not is_social_video_url(value)


class SocialVideoDownloader:
    def __init__(self, platform: str, settings: Settings = SETTINGS):
        try:
            self.platform = PLATFORMS[platform]
        except KeyError as exc:
            raise ValueError(f"Unsupported social platform: {platform}") from exc
        self.settings = settings

    def download(self, url: str) -> Video:
        if self.platform.key == "douyin":
            url = extract_douyin_url(url)
        detected = detect_social_platform(url)
        if detected != self.platform.key:
            raise ValueError(f"{self.platform.display_name}链接格式不正确: {url}")
        if not is_social_video_url(url):
            raise ValueError(
                f"{self.platform.display_name}链接不是可分析的单视频。"
            )

        if self.platform.key == "douyin":
            adapter = DouyinAdapter(self.settings)
            if adapter.ready:
                return adapter.download(url, limit=1)[0]

        info = self._extract_info(url)
        info = self._single_video_info(info)
        source_id = str(info.get("id") or "").strip()
        if not source_id:
            raise RuntimeError(f"{self.platform.display_name}没有返回视频 ID。")
        video_id = f"{self.platform.video_id_prefix}_{source_id}"

        cached = self._load_cached_video(video_id)
        if cached and not self.settings.overwrite_cache:
            logger.info("Using cached %s asset: %s", self.platform.display_name, video_id)
            return cached

        video_dir = self.settings.video_cache_dir / video_id
        video_dir.mkdir(parents=True, exist_ok=True)
        subtitle = self._pick_subtitle(info)
        if subtitle:
            language, automatic = subtitle
            logger.info(
                "%s subtitle found (%s), downloading subtitle only.",
                self.platform.display_name,
                language,
            )
            self._download_subtitle(url, video_dir, language, automatic)
            subtitle_path = self._find_file(video_dir, SUBTITLE_EXTS)
            if subtitle_path:
                video = self._video_from_info(url, info, video_id, None, subtitle_path)
                self._save_metadata(video)
                return video
            logger.warning(
                "%s subtitle download produced no usable file; falling back to video.",
                self.platform.display_name,
            )

        if not info.get("formats") and not info.get("url"):
            raise RuntimeError(
                f"{self.platform.display_name}页面没有可下载的视频流。"
                "如果这是图文笔记，请改用包含视频的公开链接。"
            )
        self._download_video(url, video_dir)
        video_path = self._find_file(video_dir, VIDEO_EXTS)
        if not video_path:
            raise FileNotFoundError(
                f"{self.platform.display_name}下载结束，但目录中没有视频文件: {video_dir}"
            )
        video = self._video_from_info(url, info, video_id, video_path, None)
        self._save_metadata(video)
        return video

    def _extract_info(self, url: str) -> dict[str, Any]:
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError("缺少 yt-dlp，请先安装 requirements.txt 中的依赖。") from exc

        try:
            with yt_dlp.YoutubeDL(self._base_options(quiet=True)) as ydl:
                info = ydl.extract_info(url, download=False)
            if not isinstance(info, dict):
                raise RuntimeError(f"{self.platform.display_name}返回了无效的视频信息。")
            return info
        except Exception as exc:
            raise RuntimeError(self._humanize_error(exc)) from exc

    def _download_subtitle(
        self,
        url: str,
        video_dir: Path,
        language: str,
        automatic: bool,
    ) -> None:
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
                "format": "bestvideo*+bestaudio/best",
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
            "retries": 3,
            "fragment_retries": 3,
            "socket_timeout": 30,
        }
        return apply_yt_dlp_options(options, self.settings, self.platform.key)

    @staticmethod
    def _single_video_info(info: dict[str, Any]) -> dict[str, Any]:
        entries = info.get("entries")
        if not entries:
            return info
        for entry in entries:
            if isinstance(entry, dict) and entry.get("id"):
                return entry
        raise RuntimeError("链接返回的是创作者列表，但列表中没有可分析的视频。")

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
        atomic_write_json(metadata_path, video.to_dict())

    def _video_from_info(
        self,
        url: str,
        info: dict[str, Any],
        video_id: str,
        video_path: Path | None,
        subtitle_path: Path | None,
    ) -> Video:
        stats = {
            key: info.get(key)
            for key in (
                "view_count",
                "like_count",
                "comment_count",
                "repost_count",
                "save_count",
                "duration",
            )
            if info.get(key) is not None
        }
        return Video(
            source_url=str(info.get("webpage_url") or url),
            platform=self.platform.key,
            video_id=video_id,
            title=str(info.get("title") or info.get("description") or video_id),
            author=(
                info.get("uploader")
                or info.get("channel")
                or info.get("creator")
                or info.get("uploader_id")
            ),
            cover=info.get("thumbnail"),
            publish_time=self._format_publish_time(info),
            duration=info.get("duration"),
            video_path=video_path,
            subtitle_path=subtitle_path,
            metadata_path=self.settings.video_cache_dir / video_id / "metadata.json",
            stats=stats,
            extra_metadata={
                "source_id": info.get("id"),
                "uploader_id": info.get("uploader_id"),
                "uploader_url": info.get("uploader_url"),
                "channel_id": info.get("channel_id"),
                "tags": info.get("tags") or [],
                "description": info.get("description"),
                "extractor": info.get("extractor_key") or info.get("extractor"),
                "webpage_url": info.get("webpage_url") or url,
            },
        )

    @staticmethod
    def _format_publish_time(info: dict[str, Any]) -> str | None:
        upload_date = str(info.get("upload_date") or "")
        if upload_date:
            try:
                return datetime.strptime(upload_date, "%Y%m%d").strftime("%Y-%m-%d")
            except ValueError:
                return upload_date
        timestamp = info.get("timestamp")
        if timestamp is not None:
            try:
                return datetime.fromtimestamp(float(timestamp)).strftime("%Y-%m-%d")
            except (TypeError, ValueError, OSError):
                pass
        return None

    @staticmethod
    def _pick_subtitle(info: dict[str, Any]) -> tuple[str, bool] | None:
        manual = SocialVideoDownloader._pick_language(info.get("subtitles"))
        if manual:
            return manual, False
        automatic = SocialVideoDownloader._pick_language(info.get("automatic_captions"))
        if automatic:
            return automatic, True
        return None

    @staticmethod
    def _pick_language(subtitles: Any) -> str | None:
        if not isinstance(subtitles, dict):
            return None
        available = [
            key
            for key, values in subtitles.items()
            if isinstance(values, list) and values
        ]
        for preferred in SUBTITLE_LANG_PRIORITY:
            if preferred in available:
                return preferred
        zh_like = sorted(key for key in available if key.lower().startswith("zh"))
        if zh_like:
            return zh_like[0]
        return available[0] if available else None

    @staticmethod
    def _find_file(directory: Path, extensions: set[str]) -> Path | None:
        candidates = [
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in extensions
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda path: path.stat().st_size)

    def _humanize_error(self, exc: Exception) -> str:
        message = ANSI_ESCAPE_RE.sub("", str(exc))
        lowered = message.lower()
        if "ffmpeg" in lowered:
            return "音视频合并失败，请检查 .env 中的 FFMPEG_PATH 配置。"
        if "cookie file does not exist" in lowered:
            return message
        if self.platform.key == "douyin" and (
            "fresh cookies" in lowered
            or "s_v_web_id" in lowered
            or "login required" in lowered
        ):
            return (
                "抖音要求有效登录会话。请回到网页主界面点击“登录抖音”，"
                "完成一次网页登录后重新提交任务；也可以在 .env 配置 "
                "DOUYIN_COOKIE_FILE。"
            )
        if (
            "requested format is not available" in lowered
            or "no video formats" in lowered
            or "does not have any formats" in lowered
        ):
            return (
                f"{self.platform.display_name}页面没有可下载的视频流。"
                "这可能是图文内容，或视频需要登录后访问。"
            )
        if any(term in lowered for term in ("403", "401", "login", "captcha", "verification")):
            env_prefix = "DOUYIN" if self.platform.key == "douyin" else "XIAOHONGSHU"
            return (
                f"{self.platform.display_name}拒绝了当前请求。请确认链接公开可访问；"
                f"必要时在 .env 配置 {env_prefix}_COOKIE_FILE 或 "
                f"{env_prefix}_COOKIES_FROM_BROWSER。"
            )
        if "unsupported url" in lowered:
            return (
                f"无法识别该{self.platform.display_name}链接。"
                "请粘贴平台分享功能生成的公开视频链接。"
            )
        return message
