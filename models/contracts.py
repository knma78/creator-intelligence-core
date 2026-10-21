from __future__ import annotations

from pathlib import Path
from typing import Any, NotRequired, TypedDict

from .acquisition import AcquisitionResult
from .core import AnalysisResult, Transcript, Video

PIPELINE_RESULT_SCHEMA_VERSION = "1.1"
BATCH_RESULT_SCHEMA_VERSION = "1.0"


class PipelineResult(TypedDict):
    schema_version: str
    video: Video
    transcript: Transcript
    analysis: AnalysisResult
    markdown_path: Path
    enrichment: dict[str, Any] | None
    analytics_store: NotRequired[dict[str, Any]]
    acquisition: NotRequired[AcquisitionResult | None]


class BatchPipelineResult(TypedDict):
    schema_version: str
    platform: str
    source: str
    profile_path: Path | None
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
    input_source: NotRequired[str]
    candidate_count: NotRequired[int]
    skipped_existing_count: NotRequired[int]
    learning_status: NotRequired[str]
    status_message: NotRequired[str]


def build_pipeline_result(
    *,
    video: Video,
    transcript: Transcript,
    analysis: AnalysisResult,
    markdown_path: Path,
    enrichment: dict[str, Any] | None,
    analytics_store: dict[str, Any] | None = None,
    acquisition: AcquisitionResult | None = None,
) -> PipelineResult:
    return {
        "schema_version": PIPELINE_RESULT_SCHEMA_VERSION,
        "video": video,
        "transcript": transcript,
        "analysis": analysis,
        "markdown_path": markdown_path,
        "enrichment": enrichment,
        "analytics_store": analytics_store or {
            "status": "skipped",
            "reason": "not persisted",
        },
        "acquisition": acquisition,
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
    normalized.setdefault(
        "analytics_store",
        {"status": "skipped", "reason": "legacy result"},
    )
    normalized.setdefault("acquisition", None)
    acquisition = normalized["acquisition"]
    if acquisition is not None and not isinstance(
        acquisition,
        AcquisitionResult,
    ):
        raise TypeError(
            "Pipeline result field 'acquisition' must be "
            f"AcquisitionResult or None, got {type(acquisition).__name__}"
        )
    return normalized  # type: ignore[return-value]
