from __future__ import annotations

import json

from config import SETTINGS, Settings, ensure_directories
from downloader.bilibili import BilibiliDownloader, is_bilibili_url
from downloader.local import LocalDownloader, is_local_path
from downloader.social import SocialVideoDownloader, detect_social_platform
from downloader.youtube import YoutubeDownloader, is_youtube_url
from models import Video
from pipeline.registry import SourceHandler, SourceRegistry, UnsupportedSourceError

_VIDEO_SOURCE_REGISTRY: SourceRegistry[Settings, Video] | None = None


def get_video_source_registry() -> SourceRegistry[Settings, Video]:
    global _VIDEO_SOURCE_REGISTRY
    if _VIDEO_SOURCE_REGISTRY is None:
        registry: SourceRegistry[Settings, Video] = SourceRegistry("video")
        registry.register(
            SourceHandler(
                "local",
                is_local_path,
                lambda source, settings: LocalDownloader(settings).download(source),
            )
        )
        registry.register(
            SourceHandler(
                "bilibili",
                is_bilibili_url,
                lambda source, settings: BilibiliDownloader(settings).download(source),
            )
        )
        registry.register(
            SourceHandler(
                "youtube",
                is_youtube_url,
                lambda source, settings: YoutubeDownloader(settings).download(source),
            )
        )
        registry.register(
            SourceHandler(
                "social",
                lambda source: bool(detect_social_platform(source)),
                lambda source, settings: SocialVideoDownloader(
                    str(detect_social_platform(source)),
                    settings,
                ).download(source),
            )
        )
        _VIDEO_SOURCE_REGISTRY = registry
    return _VIDEO_SOURCE_REGISTRY


def register_video_source_handler(
    handler: SourceHandler[Settings, Video],
    *,
    prepend: bool = True,
    replace: bool = False,
) -> None:
    get_video_source_registry().register(
        handler,
        prepend=prepend,
        replace=replace,
    )


def acquire_video(source: str, settings: Settings = SETTINGS) -> Video:
    ensure_directories(settings)
    try:
        return get_video_source_registry().resolve(source, settings)
    except UnsupportedSourceError as exc:
        raise ValueError(
            "Unsupported source. Supports Bilibili, YouTube, Douyin, "
            f"Xiaohongshu, and local video files: {source}"
        ) from exc


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Acquire a video from URL or local path.")
    parser.add_argument("source")
    args = parser.parse_args()
    video = acquire_video(args.source)
    print(json.dumps(video.to_dict(), ensure_ascii=False, indent=2))
