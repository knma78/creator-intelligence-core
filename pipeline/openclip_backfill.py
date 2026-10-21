from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from analyzer.visual_semantics import (
    analyze_image_semantics,
    release_openclip_models,
)
from config import SETTINGS, Settings
from infrastructure.analytics_store import (
    backfill_analytics_from_outputs,
    get_analytics_summary,
)
from infrastructure.atomic_io import atomic_write_json, atomic_write_text
from infrastructure.cancellation import raise_if_cancelled
from pipeline.enrich import _build_v3_markdown

ProgressCallback = Callable[[int, int, str, str, float], None]


def backfill_openclip_from_outputs(
    settings: Settings = SETTINGS,
    *,
    force: bool = False,
    limit: int | None = None,
    refresh_analytics: bool = True,
    cancel_requested: Callable[[], bool] | None = None,
    progress_callback: ProgressCallback | None = None,
    analyze: Callable[[Path, Settings], dict[str, Any]] = analyze_image_semantics,
) -> dict[str, Any]:
    """Add OpenCLIP cover semantics without rerunning the rest of V3.

    Successful items are written atomically as they finish. A stopped run can
    therefore resume safely: existing ``status=ok`` results are skipped unless
    ``force`` is requested.
    """

    candidates = _discover_candidates(settings)
    total = len(candidates)
    processed = 0
    updated = 0
    already_ready = 0
    unavailable_cover = 0
    failed = 0
    failures: list[dict[str, str]] = []

    try:
        for candidate_index, (v3_path, image_path) in enumerate(
            candidates,
            start=1,
        ):
            raise_if_cancelled(cancel_requested)
            if limit is not None and processed >= limit:
                break
            payload = _read_json(v3_path)
            video_id = str(payload.get("video_id") or v3_path.parent.name)
            current = (
                (payload.get("cover_analysis") or {}).get("visual_semantics")
                or {}
            )
            if not force and current.get("status") == "ok":
                already_ready += 1
                _notify(
                    progress_callback,
                    candidate_index,
                    total,
                    video_id,
                    "already_ready",
                    0.0,
                )
                continue

            if image_path is None:
                unavailable_cover += 1
                _notify(
                    progress_callback,
                    candidate_index,
                    total,
                    video_id,
                    "cover_missing",
                    0.0,
                )
                continue

            started = time.perf_counter()
            result = analyze(image_path, settings)
            elapsed = time.perf_counter() - started
            processed += 1

            cover = payload.setdefault("cover_analysis", {})
            cover["visual_semantics"] = result
            payload["rag_ready_text"] = _update_rag_visual_semantics(
                str(payload.get("rag_ready_text") or ""),
                result,
            )
            atomic_write_json(v3_path, payload)
            atomic_write_text(
                v3_path.with_name("v3.md"),
                _build_v3_markdown(payload),
            )

            status = str(result.get("status") or "unknown")
            if status == "ok":
                updated += 1
            else:
                failed += 1
                failures.append(
                    {
                        "video_id": video_id,
                        "status": status,
                        "reason": str(result.get("reason") or ""),
                    }
                )
            _notify(
                progress_callback,
                candidate_index,
                total,
                video_id,
                status,
                elapsed,
            )
    finally:
        release_openclip_models()

    analytics: dict[str, Any] | None = None
    analytics_summary: dict[str, Any] | None = None
    if refresh_analytics:
        analytics = backfill_analytics_from_outputs(
            settings,
            force=False,
            cancel_requested=cancel_requested,
        )
        analytics_summary = get_analytics_summary(settings)

    return {
        "status": "ok" if failed == 0 else "partial",
        "candidate_count": total,
        "limit": limit,
        "processed": processed,
        "updated": updated,
        "already_ready": already_ready,
        "unavailable_cover": unavailable_cover,
        "failed": failed,
        "failures": failures[:20],
        "analytics": analytics,
        "analytics_summary": analytics_summary,
    }


def _discover_candidates(
    settings: Settings,
) -> list[tuple[Path, Path | None]]:
    if not settings.output_dir.is_dir():
        return []
    candidates: list[tuple[Path, Path | None]] = []
    excluded = {"video_production", "creator_knowledge_base"}
    for v3_path in sorted(settings.output_dir.rglob("v3.json")):
        if excluded.intersection(v3_path.relative_to(settings.output_dir).parts):
            continue
        payload = _read_json(v3_path)
        video_id = str(payload.get("video_id") or v3_path.parent.name)
        candidates.append(
            (
                v3_path,
                _resolve_cover_path(payload, video_id, settings),
            )
        )
    return candidates


def _resolve_cover_path(
    payload: dict[str, Any],
    video_id: str,
    settings: Settings,
) -> Path | None:
    configured = (payload.get("cover_analysis") or {}).get("image_path")
    if configured:
        configured_path = Path(str(configured))
        if configured_path.is_file():
            return configured_path
    cover_dir = settings.covers_cache_dir / video_id
    if not cover_dir.is_dir():
        return None
    return next(
        (
            path
            for path in sorted(cover_dir.iterdir())
            if path.is_file()
            and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        ),
        None,
    )


def _update_rag_visual_semantics(
    text: str,
    result: dict[str, Any],
) -> str:
    labels = "、".join(
        str(item.get("label_zh") or item.get("label") or "")
        for item in (result.get("top_labels") or [])[:5]
        if item.get("label_zh") or item.get("label")
    )
    replacement = f"封面语义：{labels}"
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("封面语义："):
            lines[index] = replacement
            return "\n".join(lines)
    insert_at = next(
        (
            index
            for index, line in enumerate(lines)
            if line.startswith("实体：")
        ),
        len(lines),
    )
    lines.insert(insert_at, replacement)
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _notify(
    callback: ProgressCallback | None,
    current: int,
    total: int,
    video_id: str,
    status: str,
    elapsed: float,
) -> None:
    if callback is not None:
        callback(current, total, video_id, status, elapsed)
