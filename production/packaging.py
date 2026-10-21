from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from config import SETTINGS, Settings
from infrastructure.atomic_io import atomic_write_json
from production.contracts import (
    ProductionAsset,
    ProductionManifest,
    RenderProfile,
    TimelineSegment,
)


_SMALL_ARTIFACTS: dict[str, tuple[str, str]] = {
    "analysis.json": ("research_analysis", "application/json"),
    "v3.json": ("visual_audio_analysis", "application/json"),
    "v3.md": ("visual_audio_report", "text/markdown"),
    "video.md": ("research_report", "text/markdown"),
    "ability_profile.json": ("ability_profile", "application/json"),
    "subtitle.srt": ("subtitles", "application/x-subrip"),
    "subtitle.txt": ("transcript", "text/plain"),
    "cover.jpg": ("cover", "image/jpeg"),
    "cover.jpeg": ("cover", "image/jpeg"),
    "cover.png": ("cover", "image/png"),
}


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z._-]+", "-", value.strip()).strip(".-")
    if not safe:
        raise ValueError("Video ID does not contain a safe filename.")
    return safe


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _timeline_from_analysis(payload: dict[str, Any]) -> tuple[TimelineSegment, ...]:
    timeline: list[TimelineSegment] = []
    for index, item in enumerate(payload.get("structure") or (), start=1):
        if not isinstance(item, dict):
            continue
        time_range = str(item.get("time_range", ""))
        match = re.fullmatch(
            r"\s*(\d+):(\d{2})(?::(\d{2}))?\s*-\s*"
            r"(\d+):(\d{2})(?::(\d{2}))?\s*",
            time_range,
        )
        if not match:
            continue
        values = [int(value or 0) for value in match.groups()]
        if match.group(3) is None:
            start = values[0] * 60 + values[1]
            end = values[3] * 60 + values[4]
        else:
            start = values[0] * 3600 + values[1] * 60 + values[2]
            end = values[3] * 3600 + values[4] * 60 + values[5]
        if end <= start:
            continue
        timeline.append(
            TimelineSegment(
                segment_id=f"research-{index:03d}",
                start_seconds=float(start),
                end_seconds=float(end),
                purpose=str(item.get("part") or "research structure"),
                text=str(item.get("summary") or ""),
            )
        )
    return tuple(timeline)


def find_source_video(
    video_id: str,
    metadata: dict[str, Any],
    settings: Settings,
) -> Path | None:
    configured = metadata.get("video_path")
    if configured:
        candidate = Path(str(configured))
        if candidate.is_file():
            return candidate.resolve()
    cache_dir = settings.video_cache_dir / video_id
    for pattern in ("*.mp4", "*.mkv", "*.webm", "*.mov"):
        candidate = next(cache_dir.glob(pattern), None)
        if candidate and candidate.is_file():
            return candidate.resolve()
    return None


def create_research_package(
    video_id: str,
    *,
    settings: Settings = SETTINGS,
    include_media: bool = False,
    engine: str = "ffmpeg",
    render_profile: RenderProfile | None = None,
) -> Path:
    """Create an auditable production hand-off from an existing research job.

    Small reports and subtitle artifacts are copied so the package remains
    stable.  Large source media is referenced by default and copied only when
    ``include_media`` is explicitly enabled.
    """

    safe_id = _safe_name(video_id)
    research_dir = settings.output_dir / video_id
    if not research_dir.is_dir():
        raise FileNotFoundError(f"Research output does not exist: {research_dir}")

    package_dir = settings.video_production_dir / safe_id
    artifacts_dir = package_dir / "research"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    analysis = _read_json(research_dir / "analysis.json")
    metadata = _read_json(settings.video_cache_dir / video_id / "metadata.json")
    title = str(
        analysis.get("title")
        or metadata.get("title")
        or video_id
    )

    assets: list[ProductionAsset] = []
    seen_roles: set[str] = set()
    for filename, (role, media_type) in _SMALL_ARTIFACTS.items():
        source = research_dir / filename
        if not source.is_file() or role in seen_roles:
            continue
        destination = artifacts_dir / filename
        shutil.copy2(source, destination)
        assets.append(
            ProductionAsset(
                role=role,
                source_path=str(source.resolve()),
                packaged_path=str(destination.relative_to(package_dir)),
                media_type=media_type,
                required=role in {"research_analysis", "transcript"},
            )
        )
        seen_roles.add(role)

    metadata_path = settings.video_cache_dir / video_id / "metadata.json"
    if metadata_path.is_file():
        destination = artifacts_dir / "source_metadata.json"
        shutil.copy2(metadata_path, destination)
        assets.append(
            ProductionAsset(
                role="source_metadata",
                source_path=str(metadata_path.resolve()),
                packaged_path=str(destination.relative_to(package_dir)),
                media_type="application/json",
            )
        )

    source_video = find_source_video(video_id, metadata, settings)
    if source_video is not None:
        packaged_path: str | None = None
        if include_media:
            media_dir = package_dir / "media"
            media_dir.mkdir(parents=True, exist_ok=True)
            destination = media_dir / f"source{source_video.suffix.lower()}"
            shutil.copy2(source_video, destination)
            packaged_path = str(destination.relative_to(package_dir))
        assets.append(
            ProductionAsset(
                role="source_video",
                source_path=str(source_video),
                packaged_path=packaged_path,
                media_type=f"video/{source_video.suffix.lower().lstrip('.')}",
            )
        )

    manifest = ProductionManifest(
        job_id=safe_id,
        source_video_id=video_id,
        title=title,
        engine=engine,
        render_profile=render_profile or RenderProfile(),
        assets=tuple(assets),
        timeline=_timeline_from_analysis(analysis),
        notes=(
            "Original research artifacts remain unchanged.",
            (
                "Source media was copied into this package."
                if include_media
                else "Source media is referenced in place unless explicitly copied."
            ),
        ),
    )
    manifest_path = package_dir / "production_manifest.json"
    atomic_write_json(manifest_path, manifest.to_dict())
    return manifest_path
