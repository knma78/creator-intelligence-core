from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Callable

from config import SETTINGS, Settings
from infrastructure.cancellation import (
    JobCancelledError,
    raise_if_cancelled,
)
from infrastructure.resources import ResourceKind, get_resource_manager

logger = logging.getLogger(__name__)


def extract_audio(
    video_path: Path,
    output_path: Path,
    settings: Settings = SETTINGS,
    *,
    cancel_requested: Callable[[], bool] | None = None,
) -> Path:
    if output_path.exists() and not settings.overwrite_cache:
        logger.info("Using cached audio: %s", output_path)
        return output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = output_path.with_name(
        f".{output_path.stem}.partial{output_path.suffix}"
    )
    partial_path.unlink(missing_ok=True)
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
        str(partial_path),
    ]
    logger.info("Extracting audio with FFmpeg: %s", output_path)
    try:
        with get_resource_manager(settings).lease(
            ResourceKind.CPU_HEAVY,
            owner=f"ffmpeg:extract_audio:{video_path.name}",
            cancel_requested=cancel_requested,
        ):
            completed = _run_cancellable(
                cmd,
                cancel_requested=cancel_requested,
            )
        if completed.returncode != 0:
            raise RuntimeError(
                f"FFmpeg failed: {completed.stderr[-2000:]}"
            )
        raise_if_cancelled(cancel_requested)
        os.replace(partial_path, output_path)
    except JobCancelledError:
        partial_path.unlink(missing_ok=True)
        raise
    except FileNotFoundError as exc:
        partial_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"FFmpeg was not found. Set FFMPEG_PATH in .env or install ffmpeg. Tried: {settings.ffmpeg_path}"
        ) from exc
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise
    return output_path


def _run_cancellable(
    command: list[str],
    *,
    cancel_requested: Callable[[], bool] | None,
    poll_seconds: float = 0.2,
) -> subprocess.CompletedProcess[str]:
    raise_if_cancelled(cancel_requested)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    try:
        while True:
            try:
                stdout, stderr = process.communicate(
                    timeout=max(0.05, poll_seconds),
                )
                return subprocess.CompletedProcess(
                    command,
                    int(process.returncode or 0),
                    stdout,
                    stderr,
                )
            except subprocess.TimeoutExpired:
                raise_if_cancelled(cancel_requested)
    except JobCancelledError:
        process.terminate()
        try:
            process.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        raise
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract 16k mono wav audio from a video.")
    parser.add_argument("video")
    parser.add_argument("--output", default="cache/audio.wav")
    args = parser.parse_args()
    print(extract_audio(Path(args.video), Path(args.output)))
