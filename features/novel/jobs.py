from __future__ import annotations

from collections.abc import Callable
from typing import Any

from features.contracts import (
    FeatureHandler,
    FeatureJobServices,
    FeatureState,
)
from pipeline.novel_writing import run_novel_writing


def run_novel_job(
    state: FeatureState,
    job_id: str,
    payload: dict[str, Any],
    *,
    services: FeatureJobServices,
    check_cancelled: Callable[[], None],
    run_pipeline: Callable[..., dict[str, Any]] | None = None,
) -> None:
    """Execute the novel domain through ports owned by the app shell."""

    if run_pipeline is None:
        run_pipeline = run_novel_writing

    source = str(payload.get("source") or "").strip()
    result = run_pipeline(
        source,
        state.settings,
        operation=str(payload.get("operation") or "chapter"),
        output_language=str(payload.get("output_language") or "zh-CN"),
        source_text=str(payload.get("source_text") or ""),
        target_length=int(
            payload.get("target_length")
            or payload.get("target_chars")
            or 3000
        ),
        use_corpus_observations=bool(payload.get("use_corpus_observations")),
        native_english_review=bool(
            payload.get("native_english_review", True)
        ),
        auto_native_revision=bool(
            payload.get("auto_native_revision", True)
        ),
        progress_callback=lambda stage, progress, message: (
            services.update_progress(
                state,
                job_id,
                stage,
                progress,
                message,
            )
        ),
        cancel_requested=lambda: state.jobs.is_cancel_requested(job_id),
    )
    check_cancelled()
    files = [
        services.file_item("小说成品 result.md", result["result_path"]),
        services.file_item("创作记录 request.json", result["record_path"]),
    ]
    optional_files = (
        ("original_draft_path", "英文初稿 original_draft.md"),
        ("review_markdown_path", "英语母语化质检 native_review.md"),
        ("review_json_path", "质检数据 native_review.json"),
    )
    for key, label in optional_files:
        if result.get(key):
            files.append(services.file_item(label, result[key]))

    warnings = []
    if result.get("native_review_error"):
        warnings.append(
            f"英语母语化质检未完成：{result['native_review_error']}"
        )
    state.jobs.update(
        job_id,
        status="done",
        stage="完成",
        progress=100,
        progress_detail=None,
        result={
            "type": "novel_writing",
            "operation": result["operation"],
            "operation_label": result["operation_label"],
            "output_language": result["output_language"],
            "output_language_label": result["output_language_label"],
            "output_chars": result["output_chars"],
            "output_length": result["output_length"],
            "target_length": result["target_length"],
            "length_unit": result["length_unit"],
            "native_review": result.get("native_review"),
            "warnings": warnings,
            "skill": result["skill"],
            "files": files,
        },
        log=(
            f"{result['operation_label']}完成，共生成 "
            f"{result['output_length']} {result['length_unit']}。"
            + (
                f" 母语化终审 {result['native_review']['score']}/100。"
                if result.get("native_review")
                else ""
            )
        ),
    )


def build_novel_job_handler(
    services: FeatureJobServices,
) -> FeatureHandler:
    def handler(
        state: FeatureState,
        job_id: str,
        payload: dict[str, Any],
        check_cancelled: Callable[[], None],
    ) -> None:
        run_novel_job(
            state,
            job_id,
            payload,
            services=services,
            check_cancelled=check_cancelled,
        )

    return handler
