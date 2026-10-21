from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from analyzer.up_profile import build_up_profile
from config import SETTINGS, Settings, ensure_directories
from downloader.bilibili import is_bilibili_url, normalize_bilibili_url
from downloader.bilibili_collection import (
    BilibiliCollectionCrawler,
    is_bilibili_collection_url,
)
from downloader.bilibili_up import is_bilibili_up_source
from exporter.content_profile import export_content_profile
from infrastructure.cancellation import (
    JobCancelledError,
    cancellation_scope,
    raise_if_cancelled,
)
from infrastructure.progress import BatchProgressMessage
from infrastructure.atomic_io import atomic_write_json
from models import BATCH_RESULT_SCHEMA_VERSION
from pipeline.run import run_video_pipeline_details

logger = logging.getLogger(__name__)

CONTENT_PROFILE_SCHEMA_VERSION = "1.0"
CONTENT_TYPE_RULE_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "ContentTypeRule.json"
)
SUPPORTED_CONTENT_CATEGORIES = {
    "auto",
    "variety",
    "movie",
    "anime",
    "documentary",
    "other",
}
URL_RE = re.compile(r"https?://[^\s，,]+|BV[0-9A-Za-z]+", re.IGNORECASE)


@dataclass(frozen=True)
class ResolvedContentSources:
    input_sources: list[str]
    video_sources: list[str]
    collection_title: str
    category_hint: str


def run_content_pipeline(
    source: str,
    settings: Settings = SETTINGS,
    *,
    subject_name: str = "",
    content_category: str = "auto",
    limit: int | None = None,
    enrich_v3: bool = False,
    build_kb: bool = False,
    allow_playback_capture: bool = False,
    capture_duration_seconds: float | None = None,
    capture_stop_requested: Callable[[], bool] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> dict[str, Any]:
    from processor.whisper import whisper_model_session

    with whisper_model_session(settings):
        return _run_content_pipeline(
            source,
            settings,
            subject_name=subject_name,
            content_category=content_category,
            limit=limit,
            enrich_v3=enrich_v3,
            build_kb=build_kb,
            allow_playback_capture=allow_playback_capture,
            capture_duration_seconds=capture_duration_seconds,
            capture_stop_requested=capture_stop_requested,
            cancel_requested=cancel_requested,
            progress_callback=progress_callback,
        )


def _run_content_pipeline(
    source: str,
    settings: Settings = SETTINGS,
    *,
    subject_name: str = "",
    content_category: str = "auto",
    limit: int | None = None,
    enrich_v3: bool = False,
    build_kb: bool = False,
    allow_playback_capture: bool = False,
    capture_duration_seconds: float | None = None,
    capture_stop_requested: Callable[[], bool] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> dict[str, Any]:
    ensure_directories(settings)
    input_sources = parse_content_sources(source)
    requested_category = normalize_content_category(content_category)

    def progress(stage: str, percent: int, message: str) -> None:
        raise_if_cancelled(cancel_requested)
        if progress_callback:
            progress_callback(stage, percent, message)

    with cancellation_scope(cancel_requested):
        resolution = resolve_content_sources(
            input_sources,
            settings,
            limit=limit,
            progress_callback=progress,
        )
    sources = resolution.video_sources
    effective_subject_name = subject_name.strip() or resolution.collection_title
    effective_category = requested_category
    if effective_category == "auto" and resolution.category_hint != "auto":
        effective_category = resolution.category_hint

    progress(
        "内容作品",
        20,
        f"已识别 {len(sources)} 个B站视频，将按同一内容作品进行蒸馏。",
    )
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    subject_id = _content_subject_id(
        effective_subject_name,
        sources,
    )
    output_dir = settings.output_dir / f"content_bilibili_{subject_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "content_manifest.json"

    for index, source_url in enumerate(sources, start=1):
        progress(
            "内容作品批量",
            _batch_progress(index, len(sources), 0),
            f"正在分析第 {index}/{len(sources)} 个内容视频。",
        )
        try:
            def item_progress(stage: str, percent: int, message: str) -> None:
                progress(
                    f"内容 {index}/{len(sources)} {stage}",
                    _batch_progress(index, len(sources), percent),
                    message,
                )

            result = run_video_pipeline_details(
                source_url,
                settings,
                enrich_v3=enrich_v3,
                progress_callback=item_progress,
                allow_playback_capture=allow_playback_capture,
                capture_duration_seconds=capture_duration_seconds,
                capture_stop_requested=capture_stop_requested,
                cancel_requested=cancel_requested,
            )
            records.append(result)
            progress(
                "内容作品批量",
                _batch_progress(index, len(sources), 100),
                (
                    f"第 {index}/{len(sources)} 个内容视频完成："
                    f"{result['video'].title}"
                ),
            )
        except JobCancelledError:
            raise
        except Exception as exc:
            logger.exception("Content work item failed: %s", source_url)
            failures.append(
                {
                    "index": index,
                    "source_url": source_url,
                    "error": str(exc),
                }
            )
            progress(
                "内容作品批量",
                _batch_progress(index, len(sources), 100),
                f"第 {index}/{len(sources)} 个内容视频失败：{exc}",
            )
        _write_manifest(
            manifest_path,
            sources,
            records,
            failures,
            subject_id=subject_id,
            subject_name=effective_subject_name,
            content_category=effective_category,
            input_sources=resolution.input_sources,
        )

    inferred_name = _resolve_subject_name(effective_subject_name, records)
    category_rules = load_content_type_rules()
    resolved_category = classify_content_category(
        inferred_name,
        [
            record["video"].title
            for record in records
            if record.get("video")
        ],
        requested_category=effective_category,
        rules=category_rules,
    )
    category_label = content_category_label(
        resolved_category,
        category_rules,
    )
    progress("内容作品画像", 88, "正在汇总内容分析结果，生成作品画像。")
    profile = build_up_profile("\n".join(sources), records, failures)
    profile.update(
        {
            "schema_version": CONTENT_PROFILE_SCHEMA_VERSION,
            "subject_type": "content_work",
            "subject_id": subject_id,
            "subject_name": inferred_name,
            "platform": "bilibili",
            "content_category": resolved_category,
            "content_category_label": category_label,
            "source_urls": sources,
            "input_sources": resolution.input_sources,
            "video_count": len(sources),
        }
    )
    profile_path = export_content_profile(profile, output_dir)

    kb_path = None
    knowledge_base_status = "not_requested"
    knowledge_base_skipped_reason = None
    if build_kb and not records:
        knowledge_base_status = "skipped_no_success"
        knowledge_base_skipped_reason = "本批次没有成功分析的视频"
        progress(
            "知识库",
            94,
            "本批次没有成功视频，已跳过知识库写入；失败记录仍保存在作品清单中。",
        )
    elif build_kb:
        from rag.knowledge_base import build_knowledge_base

        knowledge_base_status = "updated"
        progress(
            "知识库",
            94,
            (
                f"正在把 {len(records)} 个成功结果按“{inferred_name}”"
                "内容作品写入知识库。"
            ),
        )
        kb_path = build_knowledge_base(
            settings.output_dir,
            settings.knowledge_base_dir / "index.json",
            settings,
            cancel_requested=cancel_requested,
            progress_callback=lambda current, total: progress(
                "知识库整理",
                min(97, 94 + int((current / max(total, 1)) * 3)),
                BatchProgressMessage(
                    f"正在整理知识文档：{current}/{total}",
                    current=current,
                    total=total,
                ),
            ),
        )

    _write_manifest(
        manifest_path,
        sources,
        records,
        failures,
        subject_id=subject_id,
        subject_name=inferred_name,
        content_category=resolved_category,
        input_sources=resolution.input_sources,
        profile_path=profile_path,
        kb_path=kb_path,
    )
    return {
        "schema_version": BATCH_RESULT_SCHEMA_VERSION,
        "platform": "bilibili",
        "source": "\n".join(sources),
        "input_source": source,
        "subject_type": "content_work",
        "subject_id": subject_id,
        "subject_name": inferred_name,
        "content_category": resolved_category,
        "content_category_label": category_label,
        "profile_path": profile_path,
        "manifest_path": manifest_path,
        "success_count": len(records),
        "failure_count": len(failures),
        "knowledge_base_path": kb_path,
        "knowledge_base_status": knowledge_base_status,
        "knowledge_base_skipped_reason": knowledge_base_skipped_reason,
        "video_outputs": [
            {
                "video_id": record["video"].video_id,
                "title": record["video"].title,
                "markdown_path": record["markdown_path"],
            }
            for record in records
        ],
    }


def parse_content_sources(source: str, limit: int | None = None) -> list[str]:
    candidates = URL_RE.findall(source)
    if not candidates and source.strip():
        candidates = [source.strip()]
    sources: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = normalize_bilibili_url(candidate)
        if not is_bilibili_url(normalized) or is_bilibili_up_source(normalized):
            raise ValueError(
                "内容作品模式仅支持B站视频链接或BV号；"
                "UP主页请使用“创作者批量”。"
            )
        if normalized not in seen:
            seen.add(normalized)
            sources.append(normalized)
    if not sources:
        raise ValueError("请至少输入一个B站视频链接或BV号。")
    if limit is not None:
        sources = sources[: max(1, int(limit))]
    return sources


def resolve_content_sources(
    input_sources: list[str],
    settings: Settings,
    *,
    limit: int | None,
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> ResolvedContentSources:
    maximum = max(1, int(limit or settings.batch_limit))
    video_sources: list[str] = []
    seen: set[str] = set()
    collection_title = ""
    category_hint = "auto"
    for input_source in input_sources:
        if len(video_sources) >= maximum:
            break
        if is_bilibili_collection_url(input_source):
            if progress_callback:
                progress_callback(
                    "内容列表",
                    16,
                    "正在解析B站电影、番剧或综艺季页面。",
                )
            collection = BilibiliCollectionCrawler(settings).fetch_video_sources(
                input_source,
                maximum - len(video_sources),
            )
            collection_title = collection_title or collection.title
            if category_hint == "auto":
                category_hint = collection.category_hint
            candidates = [
                str(item.get("source_url") or "").strip()
                for item in collection.videos
            ]
        else:
            candidates = [input_source]
        for candidate in candidates:
            if candidate and candidate not in seen:
                seen.add(candidate)
                video_sources.append(candidate)
            if len(video_sources) >= maximum:
                break
    if not video_sources:
        raise ValueError("没有解析到可分析的B站内容视频。")
    return ResolvedContentSources(
        input_sources=input_sources,
        video_sources=video_sources,
        collection_title=collection_title,
        category_hint=category_hint,
    )


def load_content_type_rules(path: Path | None = None) -> dict[str, Any]:
    rule_path = path or CONTENT_TYPE_RULE_PATH
    return json.loads(rule_path.read_text(encoding="utf-8"))


def normalize_content_category(value: str) -> str:
    category = str(value or "auto").strip().lower()
    if category not in SUPPORTED_CONTENT_CATEGORIES:
        raise ValueError(f"不支持的内容类型：{value}")
    return category


def classify_content_category(
    subject_name: str,
    titles: list[str],
    *,
    requested_category: str = "auto",
    rules: dict[str, Any] | None = None,
) -> str:
    requested = normalize_content_category(requested_category)
    if requested != "auto":
        return requested
    payload = rules or load_content_type_rules()
    text = " ".join([subject_name, *titles]).lower()
    scored: list[tuple[int, int, str]] = []
    for order, category in enumerate(payload.get("categories", [])):
        category_id = str(category.get("id") or "").strip()
        if not category_id or category_id == "other":
            continue
        score = sum(
            text.count(str(keyword).lower())
            for keyword in category.get("keywords", [])
            if str(keyword).strip()
        )
        scored.append((score, -order, category_id))
    if scored:
        score, _order, category_id = max(scored)
        if score > 0:
            return category_id
    return str(payload.get("default_category") or "other")


def content_category_label(
    category_id: str,
    rules: dict[str, Any] | None = None,
) -> str:
    payload = rules or load_content_type_rules()
    for category in payload.get("categories", []):
        if category.get("id") == category_id:
            return str(category.get("label") or category_id)
    return category_id


def _resolve_subject_name(
    requested_name: str,
    records: list[dict[str, Any]],
) -> str:
    if requested_name.strip():
        return requested_name.strip()
    if records:
        return str(records[0]["video"].title or "未命名内容作品").strip()
    return "未命名内容作品"


def _content_subject_id(name: str, sources: list[str]) -> str:
    material = "\n".join(
        [name.strip().casefold(), *sorted(sources)]
    )
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:12]


def _batch_progress(index: int, total: int, item_percent: int) -> int:
    if total <= 0:
        return 20
    completed = max(0, index - 1)
    item_fraction = max(0, min(100, item_percent)) / 100
    return min(86, 20 + int(((completed + item_fraction) / total) * 65))


def _write_manifest(
    path: Path,
    sources: list[str],
    records: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    *,
    subject_id: str,
    subject_name: str,
    content_category: str,
    input_sources: list[str] | None = None,
    profile_path: Path | None = None,
    kb_path: Path | None = None,
) -> None:
    atomic_write_json(
        path,
        {
            "schema_version": BATCH_RESULT_SCHEMA_VERSION,
            "subject_type": "content_work",
            "subject_id": subject_id,
            "subject_name": subject_name,
            "platform": "bilibili",
            "content_category": content_category,
            "seed_count": len(sources),
            "source_urls": sources,
            "input_sources": input_sources or sources,
            "success_count": len(records),
            "failure_count": len(failures),
            "outputs": [
                {
                    "video_id": record["video"].video_id,
                    "title": record["video"].title,
                    "markdown_path": str(record["markdown_path"]),
                }
                for record in records
            ],
            "failures": failures,
            "profile_path": str(profile_path) if profile_path else None,
            "knowledge_base_path": str(kb_path) if kb_path else None,
        },
    )
