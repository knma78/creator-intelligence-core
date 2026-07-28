from __future__ import annotations

import json

from config import SETTINGS, Settings, ensure_directories
from downloader.bilibili import BilibiliDownloader, is_bilibili_url
from downloader.local import LocalDownloader, is_local_path
from downloader.social import SocialVideoDownloader, detect_social_platform
from downloader.youtube import YoutubeDownloader, is_youtube_url
from models import Video


def acquire_video(source: str, settings: Settings = SETTINGS) -> Video:
    ensure_directories(settings)
    if is_local_path(source):
        return LocalDownloader(settings).download(source)
    if is_bilibili_url(source):
        return BilibiliDownloader(settings).download(source)
    if is_youtube_url(source):
        return YoutubeDownloader(settings).download(source)
    social_platform = detect_social_platform(source)
    if social_platform:
        return SocialVideoDownloader(social_platform, settings).download(source)
    raise ValueError(
        "Unsupported source. Supports Bilibili, YouTube, Douyin, Xiaohongshu, "
        f"and local video files: {source}"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Acquire a video from URL or local path.")
    parser.add_argument("source")
    args = parser.parse_args()
    video = acquire_video(args.source)
    print(json.dumps(video.to_dict(), ensure_ascii=False, indent=2))
