from __future__ import annotations

import json
from pathlib import Path

from config import SETTINGS, Settings
from models import Video


def is_local_path(value: str) -> bool:
    try:
        return Path(value).expanduser().exists()
    except OSError:
        return False


class LocalDownloader:
    def __init__(self, settings: Settings = SETTINGS):
        self.settings = settings

    def download(self, path: str) -> Video:
        source = Path(path).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(source)
        video_id = source.stem
        return Video(
            source_url=str(source),
            platform="local",
            video_id=video_id,
            title=source.stem,
            video_path=source,
            metadata_path=None,
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Wrap a local video file as a Video object.")
    parser.add_argument("path")
    args = parser.parse_args()
    video = LocalDownloader().download(args.path)
    print(json.dumps(video.to_dict(), ensure_ascii=False, indent=2))
