from __future__ import annotations

import json
import os
import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Any, Callable

from infrastructure.atomic_io import atomic_write_json
from infrastructure.cancellation import JobCancelledError


_BLACK_EVENT = re.compile(
    r"black_start:(?P<start>[\d.]+).*?"
    r"black_end:(?P<end>[\d.]+).*?"
    r"black_duration:(?P<duration>[\d.]+)"
)
_SILENCE_START = re.compile(r"silence_start:\s*(?P<start>[\d.]+)")
_SILENCE_END = re.compile(
    r"silence_end:\s*(?P<end>[\d.]+)\s*\|\s*"
    r"silence_duration:\s*(?P<duration>[\d.]+)"
)
_SRT_TIME_RANGE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{3})"
)


def _subtitle_timestamp_seconds(value: str) -> float:
    hours, minutes, seconds = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def subtitle_metrics(path: Path) -> dict[str, int | float]:
    text = Path(path).read_text(encoding="utf-8-sig").strip()
    if not text:
        return {
            "block_count": 0,
            "max_lines_per_block": 0,
            "max_chars_per_line": 0,
            "max_display_units_per_line": 0,
            "overlap_count": 0,
            "invalid_timing_count": 0,
            "last_end_seconds": 0.0,
        }

    blocks = re.split(r"\r?\n\s*\r?\n", text)
    max_lines = 0
    max_chars = 0
    max_display_units = 0
    valid_blocks = 0
    overlap_count = 0
    invalid_timing_count = 0
    previous_end: float | None = None
    last_end = 0.0
    for block in blocks:
        lines = [line.strip() for line in block.splitlines()]
        timestamp_index = next(
            (index for index, line in enumerate(lines) if "-->" in line),
            None,
        )
        if timestamp_index is None:
            continue
        timestamp = _SRT_TIME_RANGE.search(lines[timestamp_index])
        if timestamp is None:
            invalid_timing_count += 1
        else:
            start = _subtitle_timestamp_seconds(timestamp.group("start"))
            end = _subtitle_timestamp_seconds(timestamp.group("end"))
            if end <= start:
                invalid_timing_count += 1
            else:
                if previous_end is not None and start < previous_end - 0.001:
                    overlap_count += 1
                previous_end = max(previous_end or 0.0, end)
                last_end = max(last_end, end)
        caption_lines = [
            line for line in lines[timestamp_index + 1 :] if line
        ]
        valid_blocks += 1
        max_lines = max(max_lines, len(caption_lines))
        max_chars = max(
            max_chars,
            *(len(line) for line in caption_lines),
            0,
        )
        max_display_units = max(
            max_display_units,
            *(
                sum(
                    2
                    if unicodedata.east_asian_width(character)
                    in {"W", "F"}
                    else 1
                    for character in line
                )
                for line in caption_lines
            ),
            0,
        )
    return {
        "block_count": valid_blocks,
        "max_lines_per_block": max_lines,
        "max_chars_per_line": max_chars,
        "max_display_units_per_line": max_display_units,
        "overlap_count": overlap_count,
        "invalid_timing_count": invalid_timing_count,
        "last_end_seconds": round(last_end, 3),
    }


def probe_media(
    video_path: Path,
    ffprobe_path: str,
    *,
    timeout_seconds: float = 15,
) -> dict[str, Any]:
    command = [
        ffprobe_path,
        "-v",
        "error",
        "-show_entries",
        (
            "format=duration,size,bit_rate:"
            "stream=index,codec_name,codec_type,width,height,"
            "r_frame_rate,sample_rate,channels"
        ),
        "-of",
        "json",
        str(Path(video_path)),
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"ffprobe was not found: {ffprobe_path}") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffprobe failed: {exc.stderr[-2000:]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"ffprobe timed out after {timeout_seconds:g} seconds."
        ) from exc
    return json.loads(result.stdout)


def scan_media(
    video_path: Path,
    ffmpeg_path: str,
    *,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    null_output = "NUL" if os.name == "nt" else "/dev/null"
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "info",
        "-i",
        str(Path(video_path)),
        "-vf",
        "blackdetect=d=0.6:pix_th=0.02",
        "-af",
        "silencedetect=n=-48dB:d=2.0",
        "-f",
        "null",
        null_output,
    ]
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"FFmpeg was not found: {ffmpeg_path}") from exc
    while True:
        try:
            _stdout, stderr = process.communicate(timeout=0.25)
            break
        except subprocess.TimeoutExpired:
            if cancel_requested is not None and cancel_requested():
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                raise JobCancelledError("视频质量检查已由用户取消。")

    black_events = [
        {key: float(value) for key, value in match.groupdict().items()}
        for match in _BLACK_EVENT.finditer(stderr)
    ]
    silence_events: list[dict[str, float | str]] = []
    for line in stderr.splitlines():
        start = _SILENCE_START.search(line)
        end = _SILENCE_END.search(line)
        if start:
            silence_events.append(
                {"type": "start", "start": float(start.group("start"))}
            )
        if end:
            silence_events.append(
                {
                    "type": "end",
                    "end": float(end.group("end")),
                    "duration": float(end.group("duration")),
                }
            )
    return {
        "return_code": process.returncode,
        "black_events": black_events,
        "silence_events": silence_events,
    }


def qa_video(
    video_path: Path,
    *,
    ffmpeg_path: str,
    ffprobe_path: str,
    subtitle_path: Path | None = None,
    report_path: Path | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    video_path = Path(video_path).resolve()
    if not video_path.is_file():
        raise FileNotFoundError(video_path)

    subtitle = (
        subtitle_metrics(Path(subtitle_path))
        if subtitle_path is not None
        else None
    )
    scan = scan_media(
        video_path,
        ffmpeg_path,
        cancel_requested=cancel_requested,
    )
    probe = probe_media(video_path, ffprobe_path)
    streams = probe.get("streams") or []
    blocking_errors: list[str] = []
    warnings: list[str] = []
    if scan["return_code"] != 0:
        blocking_errors.append(
            "FFmpeg media scan did not complete successfully."
        )
    if not any(item.get("codec_type") == "video" for item in streams):
        blocking_errors.append("Rendered output has no decodable video stream.")
    if not any(item.get("codec_type") == "audio" for item in streams):
        blocking_errors.append("Rendered output has no decodable audio stream.")
    if scan["black_events"]:
        warnings.append("Black-frame intervals require review.")
    silence_durations = [
        float(item.get("duration") or 0)
        for item in scan["silence_events"]
        if item.get("type") == "end"
    ]
    try:
        media_duration = float(
            (probe.get("format") or {}).get("duration") or 0
        )
    except (TypeError, ValueError):
        media_duration = 0
    silent_seconds = sum(silence_durations)
    if media_duration > 0 and silent_seconds >= media_duration * 0.8:
        blocking_errors.append("Rendered audio is silent for most of the video.")
    elif any(duration >= 5 for duration in silence_durations):
        warnings.append("Long silence intervals require review.")
    if subtitle and subtitle["max_lines_per_block"] > 2:
        warnings.append("Some subtitles use more than two lines.")
    if subtitle and subtitle["max_display_units_per_line"] > 44:
        warnings.append("Some subtitle lines exceed the safe display width.")
    if subtitle and subtitle["invalid_timing_count"]:
        blocking_errors.append("Subtitle timeline contains invalid time ranges.")
    if subtitle and subtitle["overlap_count"]:
        blocking_errors.append("Subtitle timeline contains overlapping cues.")
    if (
        subtitle
        and media_duration > 0
        and float(subtitle["last_end_seconds"]) > media_duration + 0.25
    ):
        blocking_errors.append("Subtitle timeline extends beyond the rendered video.")

    report: dict[str, Any] = {
        "schema_version": "1.0",
        "video_path": str(video_path),
        "probe": probe,
        "scan": scan,
        "subtitles": subtitle,
        "warnings": warnings,
        "blocking_errors": blocking_errors,
        "review_required": bool(warnings),
        "passed": not warnings and not blocking_errors,
    }
    if report_path is not None:
        atomic_write_json(Path(report_path), report)
    return report
