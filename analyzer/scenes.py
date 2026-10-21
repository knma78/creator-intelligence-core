from __future__ import annotations

import logging
import math
import statistics
import subprocess
from pathlib import Path
from typing import Any, Callable

from config import SETTINGS, Settings
from infrastructure.cancellation import (
    JobCancelledError,
    raise_if_cancelled,
)
from infrastructure.resources import ResourceKind, get_resource_manager


logger = logging.getLogger(__name__)


def analyze_video_scenes(
    video_path: Path | None,
    settings: Settings = SETTINGS,
    *,
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    raise_if_cancelled(cancel_requested)
    if not settings.scene_detection_enabled:
        return {"status": "skipped", "reason": "scene detection disabled", "scenes": []}
    if not video_path or not video_path.exists():
        return {"status": "skipped", "reason": "video file unavailable", "scenes": []}

    try:
        import cv2
        from scenedetect import ContentDetector
    except ImportError as exc:
        return {"status": "unavailable", "reason": str(exc), "scenes": []}

    try:
        with get_resource_manager(settings).lease(
            ResourceKind.CPU_HEAVY,
            owner=f"scene_detection:{video_path.name}",
            cancel_requested=cancel_requested,
        ):
            capture = cv2.VideoCapture(str(video_path))
            if not capture.isOpened():
                return {"status": "failed", "reason": "OpenCV could not open video", "scenes": []}
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            if fps <= 0 or frame_count <= 0:
                capture.release()
                return {
                    "status": "failed",
                    "reason": "video duration metadata unavailable",
                    "scenes": [],
                }

            duration = frame_count / fps
            configured_step = max(
                0.25,
                float(settings.scene_sample_seconds),
            )
            maximum_samples = max(30, int(settings.scene_max_samples))
            step_seconds = max(
                configured_step,
                duration / maximum_samples,
            )
            sample_count = min(
                maximum_samples,
                max(2, int(math.ceil(duration / step_seconds)) + 1),
            )
            sample_frames = sorted(
                {
                    min(
                        frame_count - 1,
                        int(round(index * (frame_count - 1) / (sample_count - 1))),
                    )
                    for index in range(sample_count)
                }
            )
            capture.release()
            min_scene_len = max(
                1,
                int(fps * settings.scene_min_seconds),
            )
            downscale_width = max(
                160,
                int(settings.scene_downscale_width),
            )
            cuts, processed_samples, decode_mode = _detect_sampled_cuts(
                video_path=video_path,
                sample_frames=sample_frames,
                fps=fps,
                width=width,
                height=height,
                downscale_width=downscale_width,
                threshold=settings.scene_threshold,
                min_scene_len=min_scene_len,
                settings=settings,
                cv2_module=cv2,
                detector_type=ContentDetector,
                progress_callback=progress_callback,
                cancel_requested=cancel_requested,
            )
            boundaries = [
                0,
                *sorted(
                    {
                        int(value)
                        for value in cuts
                        if 0 < int(value) < frame_count
                    }
                ),
                frame_count,
            ]
    except JobCancelledError:
        raise
    except Exception as exc:  # pragma: no cover - codec/backend dependent
        logger.warning("Scene detection failed for %s: %s", video_path, exc)
        return {"status": "failed", "reason": str(exc), "scenes": []}

    scenes = []
    durations = []
    for index, (start_frame, end_frame) in enumerate(
        zip(boundaries, boundaries[1:]),
        start=1,
    ):
        start_seconds = start_frame / fps
        end_seconds = end_frame / fps
        duration = max(0.0, end_seconds - start_seconds)
        durations.append(duration)
        scenes.append(
            {
                "index": index,
                "start": round(start_seconds, 3),
                "end": round(end_seconds, 3),
                "duration": round(duration, 3),
                "start_timecode": _timecode(start_seconds),
                "end_timecode": _timecode(end_seconds),
            }
        )

    total_duration = frame_count / fps if fps > 0 else sum(durations)
    average = statistics.fmean(durations) if durations else total_duration
    median = statistics.median(durations) if durations else total_duration
    return {
        "status": "ok",
        "engine": "PySceneDetect+FFmpeg sampled",
        "analysis_mode": "uniform_sampling",
        "decode_mode": decode_mode,
        "threshold": settings.scene_threshold,
        "sampling_interval_seconds": round(step_seconds, 3),
        "sample_count": processed_samples,
        "max_samples": maximum_samples,
        "downscale_width": downscale_width,
        "fps": round(fps, 3),
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "duration": round(total_duration, 3),
        "scene_count": len(scenes),
        "cut_count": max(0, len(scenes) - 1),
        "average_scene_duration": round(average, 3),
        "median_scene_duration": round(median, 3),
        "pace": _pace_label(average),
        "scenes": scenes,
    }


def _detect_sampled_cuts(
    *,
    video_path: Path,
    sample_frames: list[int],
    fps: float,
    width: int,
    height: int,
    downscale_width: int,
    threshold: float,
    min_scene_len: int,
    settings: Settings,
    cv2_module: Any,
    detector_type: Any,
    progress_callback: Callable[[int, int], None] | None,
    cancel_requested: Callable[[], bool] | None,
) -> tuple[list[int], int, str]:
    if not sample_frames:
        return [], 0, "empty"

    stride = max(1, sample_frames[1] - sample_frames[0]) if len(sample_frames) > 1 else 1
    target_width = min(width, downscale_width) if width > 0 else downscale_width
    target_height = _scaled_even_height(width, height, target_width)
    attempts = (
        ("ffmpeg_cuda", True),
        ("ffmpeg_cpu", False),
    )
    for mode, use_cuda in attempts:
        result = _detect_with_ffmpeg(
            video_path=video_path,
            stride=stride,
            maximum_samples=len(sample_frames),
            target_width=target_width,
            target_height=target_height,
            threshold=threshold,
            min_scene_len=min_scene_len,
            ffmpeg_path=settings.ffmpeg_path,
            use_cuda=use_cuda,
            cv2_module=cv2_module,
            detector_type=detector_type,
            progress_callback=progress_callback,
            cancel_requested=cancel_requested,
        )
        if result is not None:
            return result[0], result[1], mode

    logger.warning(
        "FFmpeg sampled decode unavailable for %s; falling back to OpenCV seeks.",
        video_path,
    )
    detector = detector_type(threshold=threshold, min_scene_len=min_scene_len)
    capture = cv2_module.VideoCapture(str(video_path))
    cuts: list[int] = []
    processed = 0
    try:
        for frame_number in sample_frames:
            raise_if_cancelled(cancel_requested)
            capture.set(cv2_module.CAP_PROP_POS_FRAMES, frame_number)
            ok, frame = capture.read()
            if not ok:
                continue
            frame = _resize_frame(frame, downscale_width, cv2_module)
            cuts.extend(detector.process_frame(frame_number, frame))
            processed += 1
            if progress_callback is not None:
                progress_callback(processed, len(sample_frames))
    finally:
        capture.release()
    return cuts, processed, "opencv_seek_fallback"


def _detect_with_ffmpeg(
    *,
    video_path: Path,
    stride: int,
    maximum_samples: int,
    target_width: int,
    target_height: int,
    threshold: float,
    min_scene_len: int,
    ffmpeg_path: str,
    use_cuda: bool,
    cv2_module: Any,
    detector_type: Any,
    progress_callback: Callable[[int, int], None] | None,
    cancel_requested: Callable[[], bool] | None,
) -> tuple[list[int], int] | None:
    import numpy as np

    select_filter = f"select=not(mod(n\\,{stride}))"
    if use_cuda:
        filters = (
            f"{select_filter},scale_cuda={target_width}:{target_height},"
            "hwdownload,format=nv12,format=bgr24"
        )
        acceleration = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
    else:
        filters = f"{select_filter},scale={target_width}:{target_height}"
        acceleration = []
    command = [
        ffmpeg_path,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        *acceleration,
        "-i",
        str(video_path),
        "-vf",
        filters,
        "-fps_mode",
        "vfr",
        "-frames:v",
        str(maximum_samples),
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "pipe:1",
    ]
    frame_bytes = target_width * target_height * 3
    detector = detector_type(threshold=threshold, min_scene_len=min_scene_len)
    cuts: list[int] = []
    processed = 0
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError):
        return None
    assert process.stdout is not None
    try:
        while processed < maximum_samples:
            if cancel_requested is not None and cancel_requested():
                process.terminate()
                try:
                    process.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
                raise JobCancelledError("场景分析已由用户取消。")
            payload = process.stdout.read(frame_bytes)
            if len(payload) != frame_bytes:
                break
            frame = np.frombuffer(payload, dtype="uint8").reshape(
                (target_height, target_width, 3)
            )
            cuts.extend(detector.process_frame(processed * stride, frame))
            processed += 1
            if progress_callback is not None:
                progress_callback(processed, maximum_samples)
    finally:
        process.stdout.close()
        if process.poll() is None and (
            cancel_requested is not None and cancel_requested()
        ):
            process.kill()
            process.wait(timeout=2)
    return_code = process.wait()
    if return_code != 0 or processed == 0:
        return None
    return cuts, processed


def _scaled_even_height(width: int, height: int, target_width: int) -> int:
    if width <= 0 or height <= 0:
        return max(2, int(round(target_width * 9 / 16 / 2) * 2))
    scaled = height * target_width / width
    return max(2, int(round(scaled / 2) * 2))


def _resize_frame(frame: Any, target_width: int, cv2_module: Any) -> Any:
    if frame.shape[1] <= target_width:
        return frame
    scale = target_width / frame.shape[1]
    return cv2_module.resize(
        frame,
        (target_width, max(1, int(frame.shape[0] * scale))),
        interpolation=cv2_module.INTER_AREA,
    )


def _timecode(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return (
        f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}."
        f"{milliseconds:03d}"
    )


def _pace_label(average_scene_duration: float) -> str:
    if average_scene_duration <= 3:
        return "fast"
    if average_scene_duration <= 8:
        return "medium"
    return "slow"
