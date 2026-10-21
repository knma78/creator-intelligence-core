from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
from collections import deque
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from config import SETTINGS, Settings
from infrastructure.atomic_io import atomic_write_json
from infrastructure.cancellation import JobCancelledError
from infrastructure.resources import ResourceKind, get_resource_manager
from production.contracts import RenderProfile


def _subtitle_filter_path(path: Path) -> str:
    value = Path(path).resolve().as_posix()
    value = value.replace("\\", "/").replace(":", r"\:")
    value = value.replace("'", r"\'")
    return value


@lru_cache(maxsize=8)
def inspect_ffmpeg_runtime(
    ffmpeg_path: str,
    *,
    validate_nvenc: bool = False,
    timeout_seconds: float = 10,
) -> dict[str, Any]:
    try:
        version = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-version"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
        encoders = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-encoders"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
        filters = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-filters"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "path": ffmpeg_path,
            "available": False,
            "nvenc_available": False,
            "nvenc_validated": False,
            "reason": str(exc),
        }

    encoder_text = encoders.stdout + encoders.stderr
    filter_text = filters.stdout + filters.stderr
    nvenc_available = "h264_nvenc" in encoder_text
    libx264_available = "libx264" in encoder_text
    aac_available = bool(re.search(r"\bAAC\b|\baac\b", encoder_text))
    required_filters = ("subtitles", "loudnorm", "overlay", "boxblur")
    missing_filters = [
        item
        for item in required_filters
        if not re.search(rf"\b{re.escape(item)}\b", filter_text)
    ]
    nvenc_validated = False
    validation_error: str | None = None
    if validate_nvenc and nvenc_available:
        null_output = "NUL" if os.name == "nt" else "/dev/null"
        try:
            validation = subprocess.run(
                [
                    ffmpeg_path,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=256x256:r=1",
                    "-frames:v",
                    "1",
                    "-c:v",
                    "h264_nvenc",
                    "-f",
                    "null",
                    null_output,
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
            )
            nvenc_validated = validation.returncode == 0
            if not nvenc_validated:
                validation_error = validation.stderr[-1000:].strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            validation_error = str(exc)

    first_line = next(
        (line for line in version.stdout.splitlines() if line.strip()),
        "",
    )
    available = bool(
        version.returncode == 0
        and encoders.returncode == 0
        and filters.returncode == 0
        and (nvenc_available or libx264_available)
        and aac_available
        and not missing_filters
    )
    return {
        "path": ffmpeg_path,
        "available": available,
        "version": first_line,
        "nvenc_available": nvenc_available,
        "nvenc_validated": nvenc_validated,
        "nvenc_validation_error": validation_error,
        "libx264_available": libx264_available,
        "aac_available": aac_available,
        "required_filters": list(required_filters),
        "missing_filters": missing_filters,
        "reason": (
            None
            if available
            else "FFmpeg lacks a required encoder or filter."
        ),
    }


def build_render_command(
    *,
    ffmpeg_path: str,
    source_video: Path,
    output_path: Path,
    profile: RenderProfile,
    narration_audio: Path | None = None,
    subtitle_path: Path | None = None,
    use_nvenc: bool = True,
    has_source_audio: bool = True,
) -> list[str]:
    profile.validate()
    command = [ffmpeg_path, "-hide_banner", "-y", "-i", str(source_video)]
    if narration_audio is not None:
        command.extend(["-i", str(narration_audio)])

    filters = [
        (
            f"scale={profile.width}:{profile.height}:"
            "force_original_aspect_ratio=decrease"
        ),
        (
            f"pad={profile.width}:{profile.height}:"
            "(ow-iw)/2:(oh-ih)/2:color=black"
        ),
        f"fps={profile.fps}",
    ]
    if subtitle_path is not None:
        filters.append(
            f"subtitles=filename='{_subtitle_filter_path(subtitle_path)}'"
        )
    command.extend(["-vf", ",".join(filters), "-map", "0:v:0"])

    has_audio = narration_audio is not None or has_source_audio
    if narration_audio is not None:
        command.extend(["-map", "1:a:0", "-shortest"])
    elif has_source_audio:
        command.extend(["-map", "0:a:0?"])

    if use_nvenc:
        command.extend(
            ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "19", "-b:v", "0"]
        )
    else:
        command.extend(
            ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]
        )
    command.extend(["-pix_fmt", "yuv420p"])
    if has_audio:
        command.extend(
            [
                "-af",
                f"loudnorm=I={profile.audio_loudness_lufs}:LRA=11:TP=-1.5",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
            ]
        )
    command.extend(["-movflags", "+faststart", str(output_path)])
    return command


def render_master(
    source_video: Path,
    output_path: Path,
    *,
    profile: RenderProfile | None = None,
    narration_audio: Path | None = None,
    subtitle_path: Path | None = None,
    prefer_gpu: bool = True,
    has_source_audio: bool = True,
    cancel_requested: Callable[[], bool] | None = None,
    settings: Settings = SETTINGS,
) -> Path:
    source_video = Path(source_video).resolve()
    output_path = Path(output_path).resolve()
    if not source_video.is_file():
        raise FileNotFoundError(source_video)
    if narration_audio is not None and not Path(narration_audio).is_file():
        raise FileNotFoundError(narration_audio)
    if subtitle_path is not None and not Path(subtitle_path).is_file():
        raise FileNotFoundError(subtitle_path)

    runtime = inspect_ffmpeg_runtime(
        settings.video_ffmpeg_path,
        validate_nvenc=prefer_gpu,
    )
    if not runtime["available"]:
        raise RuntimeError(
            f"Video-production FFmpeg is unavailable: "
            f"{settings.video_ffmpeg_path}"
        )
    use_nvenc = bool(prefer_gpu and runtime["nvenc_validated"])
    selected_profile = profile or RenderProfile()
    command = build_render_command(
        ffmpeg_path=settings.video_ffmpeg_path,
        source_video=source_video,
        output_path=output_path,
        profile=selected_profile,
        narration_audio=narration_audio,
        subtitle_path=subtitle_path,
        use_nvenc=use_nvenc,
        has_source_audio=has_source_audio,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    resource = (
        ResourceKind.GPU_INFERENCE if use_nvenc else ResourceKind.CPU_HEAVY
    )
    try:
        with get_resource_manager(settings).lease(
            resource,
            owner=f"video-render:{output_path.name}",
            family="ffmpeg-nvenc" if use_nvenc else None,
            cancel_requested=cancel_requested,
        ):
            return_code, stderr = _run_ffmpeg_cancellable(
                command,
                duration_seconds=0,
                cancel_requested=cancel_requested,
                progress_callback=None,
            )
    except JobCancelledError:
        output_path.unlink(missing_ok=True)
        raise
    render_record = {
        "schema_version": "1.0",
        "source_video": str(source_video),
        "output_path": str(output_path),
        "profile": asdict(selected_profile),
        "encoder": "h264_nvenc" if use_nvenc else "libx264",
        "command": command,
        "return_code": return_code,
    }
    atomic_write_json(
        output_path.with_suffix(output_path.suffix + ".render.json"),
        render_record,
    )
    if return_code != 0:
        raise RuntimeError(f"FFmpeg render failed: {stderr[-3000:]}")
    return output_path


def _build_timeline_filter(
    *,
    segments: list[dict[str, Any]],
    profile: RenderProfile,
    subtitle_path: Path | None,
) -> tuple[str, str, str]:
    if not segments:
        raise ValueError("Edit plan does not contain any timeline segments.")
    chains: list[str] = []
    video_labels: list[str] = []
    audio_labels: list[str] = []
    for index, segment in enumerate(segments):
        start = float(segment["source_start_seconds"])
        end = float(segment["source_end_seconds"])
        if start < 0 or end <= start:
            raise ValueError(
                f"Invalid edit segment {index + 1}: {start}-{end}"
            )
        video_label = f"v{index}"
        audio_label = f"a{index}"
        chains.append(
            f"[0:v:0]trim=start={start:.3f}:end={end:.3f},"
            "setpts=PTS-STARTPTS,"
            f"scale={profile.width}:{profile.height}:"
            "force_original_aspect_ratio=decrease,"
            f"pad={profile.width}:{profile.height}:"
            "(ow-iw)/2:(oh-ih)/2:color=black,"
            f"fps={profile.fps}[{video_label}]"
        )
        chains.append(
            f"[0:a:0]atrim=start={start:.3f}:end={end:.3f},"
            f"asetpts=PTS-STARTPTS[{audio_label}]"
        )
        video_labels.append(f"[{video_label}]")
        audio_labels.append(f"[{audio_label}]")

    concat_inputs = "".join(
        value
        for pair in zip(video_labels, audio_labels)
        for value in pair
    )
    chains.append(
        f"{concat_inputs}concat=n={len(segments)}:v=1:a=1[vcat][acat]"
    )
    chains.append(
        f"[acat]loudnorm=I={profile.audio_loudness_lufs}:"
        "LRA=11:TP=-1.5[aout]"
    )
    video_output = "vcat"
    if subtitle_path is not None:
        chains.append(
            f"[vcat]subtitles=filename="
            f"'{_subtitle_filter_path(subtitle_path)}'[vout]"
        )
        video_output = "vout"
    return ";".join(chains), video_output, "aout"


def build_timeline_render_command(
    *,
    ffmpeg_path: str,
    source_video: Path,
    output_path: Path,
    segments: list[dict[str, Any]],
    profile: RenderProfile,
    subtitle_path: Path | None,
    use_nvenc: bool,
) -> list[str]:
    profile.validate()
    filter_complex, video_label, audio_label = _build_timeline_filter(
        segments=segments,
        profile=profile,
        subtitle_path=subtitle_path,
    )
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-progress",
        "pipe:1",
        "-nostats",
        "-i",
        str(source_video),
        "-filter_complex",
        filter_complex,
        "-map",
        f"[{video_label}]",
        "-map",
        f"[{audio_label}]",
    ]
    if use_nvenc:
        command.extend(
            ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "19", "-b:v", "0"]
        )
    else:
        command.extend(
            ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]
        )
    command.extend(
        [
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    return command


def _run_ffmpeg_cancellable(
    command: list[str],
    *,
    duration_seconds: float,
    cancel_requested: Callable[[], bool] | None,
    progress_callback: Callable[[int, str], None] | None,
) -> tuple[int, str]:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    progress_output: list[str] = []

    output_queue: queue.Queue[str | None] = queue.Queue()
    stderr_tail: deque[str] = deque(maxlen=240)

    def read_progress() -> None:
        assert process.stdout is not None
        try:
            for output_line in process.stdout:
                output_queue.put(output_line)
        finally:
            output_queue.put(None)

    reader = threading.Thread(
        target=read_progress,
        name="ffmpeg-progress-reader",
        daemon=True,
    )
    def read_stderr() -> None:
        assert process.stderr is not None
        for error_line in process.stderr:
            stderr_tail.append(error_line)

    error_reader = threading.Thread(
        target=read_stderr,
        name="ffmpeg-stderr-reader",
        daemon=True,
    )
    reader.start()
    error_reader.start()
    try:
        stream_finished = False
        while True:
            if cancel_requested is not None and cancel_requested():
                process.terminate()
                try:
                    process.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
                raise JobCancelledError("视频渲染已由用户取消。")

            try:
                line = output_queue.get(timeout=0.2)
            except queue.Empty:
                line = ""
            if line is None:
                stream_finished = True
            elif line:
                progress_output.append(line)
                key, _, value = line.strip().partition("=")
                if key in {"out_time_us", "out_time_ms"}:
                    try:
                        seconds = float(value) / 1_000_000
                    except ValueError:
                        seconds = 0.0
                    percent = int(
                        max(
                            0,
                            min(
                                99,
                                seconds
                                / max(duration_seconds, 0.001)
                                * 100,
                            ),
                        )
                    )
                    if progress_callback is not None:
                        progress_callback(
                            percent,
                            f"FFmpeg 已渲染 {seconds:.1f}/{duration_seconds:.1f} 秒",
                        )
            if process.poll() is not None and stream_finished:
                break
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        reader.join(timeout=1)
        error_reader.join(timeout=1)
    stderr = "".join(stderr_tail)
    return process.returncode or 0, stderr


def render_edit_plan(
    plan_path: Path,
    output_path: Path,
    *,
    profile: RenderProfile | None = None,
    burn_subtitles: bool = True,
    prefer_gpu: bool = True,
    cancel_requested: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
    settings: Settings = SETTINGS,
) -> Path:
    plan_path = Path(plan_path).resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    if plan.get("schema_version") != "1.0":
        raise ValueError(
            f"Unsupported edit plan schema: {plan.get('schema_version')}"
        )
    source_video = Path(plan["source_video_path"]).resolve()
    if not source_video.is_file():
        raise FileNotFoundError(source_video)
    segments = list(plan.get("segments") or [])
    duration_seconds = sum(
        float(item["source_end_seconds"])
        - float(item["source_start_seconds"])
        for item in segments
    )
    subtitle_path: Path | None = None
    if burn_subtitles and plan.get("edit_subtitle_path"):
        candidate = Path(plan["edit_subtitle_path"]).resolve()
        if candidate.is_file():
            subtitle_path = candidate

    runtime = inspect_ffmpeg_runtime(
        settings.video_ffmpeg_path,
        validate_nvenc=prefer_gpu,
    )
    if not runtime["available"]:
        raise RuntimeError(
            f"Video-production FFmpeg is unavailable: "
            f"{settings.video_ffmpeg_path}"
        )
    use_nvenc = bool(prefer_gpu and runtime["nvenc_validated"])
    selected_profile = profile or RenderProfile()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = output_path.with_name(
        f".{output_path.stem}.partial{output_path.suffix}"
    )
    command = build_timeline_render_command(
        ffmpeg_path=settings.video_ffmpeg_path,
        source_video=source_video,
        output_path=partial_path,
        segments=segments,
        profile=selected_profile,
        subtitle_path=subtitle_path,
        use_nvenc=use_nvenc,
    )
    resource = (
        ResourceKind.GPU_INFERENCE if use_nvenc else ResourceKind.CPU_HEAVY
    )
    try:
        with get_resource_manager(settings).lease(
            resource,
            owner=f"video-timeline-render:{output_path.name}",
            family="ffmpeg-nvenc" if use_nvenc else None,
            cancel_requested=cancel_requested,
        ):
            return_code, stderr = _run_ffmpeg_cancellable(
                command,
                duration_seconds=duration_seconds,
                cancel_requested=cancel_requested,
                progress_callback=progress_callback,
            )
        record = {
            "schema_version": "1.0",
            "edit_plan_path": str(plan_path),
            "source_video": str(source_video),
            "output_path": str(output_path),
            "profile": asdict(selected_profile),
            "encoder": "h264_nvenc" if use_nvenc else "libx264",
            "segment_count": len(segments),
            "duration_seconds": duration_seconds,
            "command": command,
            "return_code": return_code,
        }
        atomic_write_json(
            output_path.with_suffix(output_path.suffix + ".render.json"),
            record,
        )
        if return_code != 0:
            raise RuntimeError(f"FFmpeg timeline render failed: {stderr[-3000:]}")
        os.replace(partial_path, output_path)
        if progress_callback is not None:
            progress_callback(100, "FFmpeg 成片渲染完成。")
        return output_path
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise
