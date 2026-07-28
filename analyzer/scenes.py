from __future__ import annotations

import logging
import statistics
from pathlib import Path
from typing import Any

from config import SETTINGS, Settings


logger = logging.getLogger(__name__)


def analyze_video_scenes(video_path: Path | None, settings: Settings = SETTINGS) -> dict[str, Any]:
    if not settings.scene_detection_enabled:
        return {"status": "skipped", "reason": "scene detection disabled", "scenes": []}
    if not video_path or not video_path.exists():
        return {"status": "skipped", "reason": "video file unavailable", "scenes": []}

    try:
        import cv2
        from scenedetect import ContentDetector, detect
    except ImportError as exc:
        return {"status": "unavailable", "reason": str(exc), "scenes": []}

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return {"status": "failed", "reason": "OpenCV could not open video", "scenes": []}
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    capture.release()

    min_scene_len = max(1, int(max(fps, 1.0) * settings.scene_min_seconds))
    try:
        scene_list = detect(
            str(video_path),
            ContentDetector(threshold=settings.scene_threshold, min_scene_len=min_scene_len),
            show_progress=False,
        )
    except Exception as exc:  # pragma: no cover - codec/backend dependent
        logger.warning("Scene detection failed for %s: %s", video_path, exc)
        return {"status": "failed", "reason": str(exc), "scenes": []}

    scenes = []
    durations = []
    for index, (start, end) in enumerate(scene_list, start=1):
        start_seconds = float(start.get_seconds())
        end_seconds = float(end.get_seconds())
        duration = max(0.0, end_seconds - start_seconds)
        durations.append(duration)
        scenes.append(
            {
                "index": index,
                "start": round(start_seconds, 3),
                "end": round(end_seconds, 3),
                "duration": round(duration, 3),
                "start_timecode": start.get_timecode(),
                "end_timecode": end.get_timecode(),
            }
        )

    total_duration = frame_count / fps if fps > 0 else sum(durations)
    average = statistics.fmean(durations) if durations else total_duration
    median = statistics.median(durations) if durations else total_duration
    return {
        "status": "ok",
        "engine": "PySceneDetect+OpenCV",
        "threshold": settings.scene_threshold,
        "fps": round(fps, 3),
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "duration": round(total_duration, 3),
        "scene_count": len(scenes) or (1 if total_duration > 0 else 0),
        "cut_count": max(0, len(scenes) - 1),
        "average_scene_duration": round(average, 3),
        "median_scene_duration": round(median, 3),
        "pace": _pace_label(average),
        "scenes": scenes,
    }


def _pace_label(average_scene_duration: float) -> str:
    if average_scene_duration <= 3:
        return "fast"
    if average_scene_duration <= 8:
        return "medium"
    return "slow"
