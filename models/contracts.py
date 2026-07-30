from __future__ import annotations

from pathlib import Path
from typing import Any, NotRequired, TypedDict

from .core import AnalysisResult, Transcript, Video

PIPELINE_RESULT_SCHEMA_VERSION = "1.0"
BATCH_RESULT_SCHEMA_VERSION = "1.0"


class PipelineResult(TypedDict):
    schema_version: str
    video: Video
    transcript: Transcript
    analysis: AnalysisResult
    markdown_path: Path
    enrichment: dict[str, Any] | None


class BatchPipelineResult(TypedDict):
    schema_version: str
    platform: str
    source: str
    profile_path: Path
    manifest_path: Path
    success_count: int
    failure_count: int
    knowledge_base_path: Path | None
    knowledge_base_status: str
    knowledge_base_skipped_reason: str | None
    video_outputs: list[dict[str, Any]]
    warnings: NotRequired[list[str]]
    subject_type: NotRequired[str]
    subject_id: NotRequired[str]
    subject_name: NotRequired[str]
    content_category: NotRequired[str]
    content_category_label: NotRequired[str]


def build_pipeline_result(
    *,
    video: Video,
    transcript: Transcript,
    analysis: AnalysisResult,
    markdown_path: Path,
    enrichment: dict[str, Any] | None,
) -> PipelineResult:
    return {
        "schema_version": PIPELINE_RESULT_SCHEMA_VERSION,
        "video": video,
        "transcript": transcript,
        "analysis": analysis,
        "markdown_path": markdown_path,
        "enrichment": enrichment,
    }


def validate_pipeline_result(payload: dict[str, Any]) -> PipelineResult:
    required = {
        "video": Video,
        "transcript": Transcript,
        "analysis": AnalysisResult,
        "markdown_path": Path,
    }
    for key, expected_type in required.items():
        value = payload.get(key)
        if not isinstance(value, expected_type):
            raise TypeError(
                f"Pipeline result field {key!r} must be "
                f"{expected_type.__name__}, got {type(value).__name__}"
            )
    normalized = dict(payload)
    normalized.setdefault("schema_version", PIPELINE_RESULT_SCHEMA_VERSION)
    normalized.setdefault("enrichment", None)
    return normalized  # type: ignore[return-value]
