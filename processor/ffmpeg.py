from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from config import SETTINGS, Settings

logger = logging.getLogger(__name__)


def extract_audio(
    video_path: Path,
    output_path: Path,
    settings: Settings = SETTINGS,
) -> Path:
    if output_path.exists() and not settings.overwrite_cache:
        logger.info("Using cached audio: %s", output_path)
        return output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        settings.ffmpeg_path,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        str(output_path),
    ]
    logger.info("Extracting audio with FFmpeg: %s", output_path)
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"FFmpeg was not found. Set FFMPEG_PATH in .env or install ffmpeg. Tried: {settings.ffmpeg_path}"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"FFmpeg failed: {exc.stderr[-2000:]}") from exc
    return output_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract 16k mono wav audio from a video.")
    parser.add_argument("video")
    parser.add_argument("--output", default="cache/audio.wav")
    args = parser.parse_args()
    print(extract_audio(Path(args.video), Path(args.output)))
