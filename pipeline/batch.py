from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from analyzer.up_profile import build_up_profile
from config import SETTINGS, Settings, ensure_directories
from infrastructure.cancellation import (
    JobCancelledError,
    cancellation_scope,
    raise_if_cancelled,
)
from infrastructure.creator_progress import CreatorProgressStore
from infrastructure.progress import BatchProgressMessage
from downloader.bilibili_up import BilibiliUPCrawler, normalize_up_url, up_cache_key
from downloader.douyin_adapter import DouyinAdapter, extract_douyin_url
from downloader.social import is_douyin_profile_url
from downloader.youtube import is_youtube_channel_url, normalize_youtube_channel_url
from downloader.youtube_channel import YoutubeChannelCrawler, youtube_channel_cache_key
from exporter.up_profile import export_up_profile
from infrastructure.atomic_io import atomic_write_json
from models import BATCH_RESULT_SCHEMA_VERSION
from pipeline.run import (
    run_acquired_video_pipeline_details,
    run_video_pipeline_details,
)
from pipeline.registry import SourceHandler, SourceRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CreatorBatchContext:
    settings: Settings
    limit: int | None
    progress: Callable[[str, int, str], None]


@dataclass(frozen=True)
class CreatorBatchSource:
    platform: str
    creator_id: str
    normalized: str
    output_name: str
    videos: list[dict[str, Any]]
    known_video_ids: frozenset[str] = frozenset()
    scan_limit: int = 0
    scan_exhausted: bool = False


_CREATOR_SOURCE_REGISTRY: SourceRegistry[
    CreatorBatchContext,
    CreatorBatchSource,
] | None = None


def get_creator_source_registry() -> SourceRegistry[
    CreatorBatchContext,
    CreatorBatchSource,
]:
    global _CREATOR_SOURCE_REGISTRY
    if _CREATOR_SOURCE_REGISTRY is None:
        registry: SourceRegistry[CreatorBatchContext, CreatorBatchSource] = (
            SourceRegistry("creator")
        )
        registry.register(
            SourceHandler(
                "douyin",
                is_douyin_profile_url,
                _resolve_douyin_creator_source,
            )
        )
        registry.register(
            SourceHandler(
                "youtube",
                is_youtube_channel_url,
                _resolve_youtube_creator_source,
            )
        )
        registry.register(
            SourceHandler(
                "bilibili",
                lambda _source: True,
                _resolve_bilibili_creator_source,
            )
        )
        _CREATOR_SOURCE_REGISTRY = registry
    return _CREATOR_SOURCE_REGISTRY


def register_creator_source_handler(
    handler: SourceHandler[CreatorBatchContext, CreatorBatchSource],
    *,
    prepend: bool = True,
    replace: bool = False,
) -> None:
    get_creator_source_registry().register(
        handler,
        prepend=prepend,
        replace=replace,
    )


def run_up_pipeline(
    source: str,
    settings: Settings = SETTINGS,
    limit: int | None = None,
    enrich_v3: bool = False,
    build_kb: bool = False,
    progress_callback: Callable[[str, int, str], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    from processor.whisper import whisper_model_session

    with whisper_model_session(settings):
        return _run_up_pipeline(
            source,
            settings,
            limit,
            enrich_v3,
            build_kb,
            progress_callback,
            cancel_requested,
        )


def _run_up_pipeline(
    source: str,
    settings: Settings = SETTINGS,
    limit: int | None = None,
    enrich_v3: bool = False,
    build_kb: bool = False,
    progress_callback: Callable[[str, int, str], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    ensure_directories(settings)

    def progress(stage: str, percent: int, message: str) -> None:
        raise_if_cancelled(cancel_requested)
        if progress_callback:
            progress_callback(stage, percent, message)

    with cancellation_scope(cancel_requested):
        batch_source = get_creator_source_registry().resolve(
            source,
            CreatorBatchContext(
                settings=settings,
                limit=limit,
                progress=progress,
            ),
        )
    platform = batch_source.platform
    normalized = batch_source.normalized
    candidate_videos = _deduplicate_video_seeds(batch_source.videos)
    progress_store = CreatorProgressStore(settings.creator_progress_database_path)
    target_limit = max(1, int(limit or settings.batch_limit))
    videos, skipped_existing = _select_unseen_videos(
        candidate_videos,
        batch_source.known_video_ids,
        target_limit,
    )
    scan_exhausted = batch_source.scan_exhausted
    output_name = batch_source.output_name

    up_output_dir = settings.output_dir / output_name
    up_output_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    manifest_path = up_output_dir / "batch_manifest.json"

    if not videos:
        analyzed_count = progress_store.analyzed_count(
            platform,
            batch_source.creator_id,
        )
        skipped_existing = list(
            progress_store.completed_video_ids(platform, batch_source.creator_id)
        )
        learning_status = (
            "complete"
            if scan_exhausted and analyzed_count > 0
            else "no_unseen_candidates"
        )
        completion_message = (
            _learning_complete_message(platform, analyzed_count)
            if learning_status == "complete"
            else _incomplete_list_message(platform, analyzed_count)
        )
        progress(
            "学习完毕" if learning_status == "complete" else "未发现新视频",
            100,
            completion_message,
        )
        profile_path = up_output_dir / "up_profile.md"
        if not profile_path.is_file():
            profile_path = None
        _write_manifest(
            manifest_path,
            normalized,
            videos,
            records,
            failures,
            profile_path,
            platform=platform,
            candidate_count=len(candidate_videos),
            skipped_existing=skipped_existing,
            learning_status=learning_status,
            status_message=completion_message,
        )
        return {
            "schema_version": BATCH_RESULT_SCHEMA_VERSION,
            "platform": platform,
            "source": normalized,
            "profile_path": profile_path,
            "manifest_path": manifest_path,
            "success_count": 0,
            "failure_count": 0,
            "knowledge_base_path": None,
            "knowledge_base_status": (
                "skipped_already_complete"
                if scan_exhausted
                else "skipped_no_unseen_candidates"
            ),
            "knowledge_base_skipped_reason": completion_message,
            "video_outputs": [],
            "candidate_count": analyzed_count,
            "skipped_existing_count": analyzed_count,
            "learning_status": learning_status,
            "status_message": completion_message,
        }

    if skipped_existing:
        progress(
            "创作者列表",
            25,
            (
                f"已跳过数据库中的 {len(skipped_existing)} 个视频，"
                f"自动选择后续 {len(videos)} 个未学习视频。"
            ),
        )
    else:
        progress("创作者列表", 25, f"已获取 {len(videos)} 个视频，开始批量分析。")

    for index, seed in enumerate(videos, start=1):
        source_url = seed.get("source_url")
        if not source_url:
            failures.append({"index": index, "source_url": "", "error": "missing source_url"})
            continue
        video_id = _video_seed_identity(seed)
        if video_id:
            progress_store.mark_processing(platform, batch_source.creator_id, video_id)
        logger.info("Batch analyzing %s/%s: %s", index, len(videos), source_url)
        item_title = str(seed.get("title") or source_url)
        progress("创作者批量", _batch_progress(index, len(videos), 0), f"正在分析第 {index}/{len(videos)} 个视频：{item_title}")
        try:
            def item_progress(stage: str, percent: int, message: str) -> None:
                overall = _batch_progress(index, len(videos), percent)
                progress(f"批量 {index}/{len(videos)} {stage}", overall, message)

            acquired_video = seed.get("acquired_video")
            if acquired_video is not None:
                result = run_acquired_video_pipeline_details(
                    acquired_video,
                    settings,
                    enrich_v3=enrich_v3,
                    progress_callback=item_progress,
                    cancel_requested=cancel_requested,
                )
            else:
                result = run_video_pipeline_details(
                    source_url,
                    settings,
                    enrich_v3=enrich_v3,
                    progress_callback=item_progress,
                    cancel_requested=cancel_requested,
                )
            records.append(result)
            progress_store.mark_analyzed(
                platform,
                batch_source.creator_id,
                str(result["video"].video_id),
                str(result["video"].source_url or source_url),
                str(result["video"].title or item_title),
            )
            progress("创作者批量", _batch_progress(index, len(videos), 100), f"第 {index}/{len(videos)} 个视频完成：{result['video'].title}")
        except JobCancelledError:
            raise
        except Exception as exc:  # keep completed data even when one video fails
            if video_id:
                progress_store.mark_failed(
                    platform,
                    batch_source.creator_id,
                    video_id,
                    str(exc),
                )
            logger.exception("Batch item failed: %s", source_url)
            failures.append({"index": index, "source_url": source_url, "error": str(exc)})
            progress("创作者批量", _batch_progress(index, len(videos), 100), f"第 {index}/{len(videos)} 个视频失败：{exc}")
        _write_manifest(
            manifest_path,
            normalized,
            videos,
            records,
            failures,
            platform=platform,
            candidate_count=len(candidate_videos),
            skipped_existing=skipped_existing,
            learning_status="running",
        )

    progress("创作者画像", 88, "正在汇总视频分析结果，生成创作者画像。")
    profile = build_up_profile(normalized, records, failures)
    profile["platform"] = platform
    profile_path = export_up_profile(profile, up_output_dir)

    kb_path = None
    knowledge_base_status = "not_requested"
    knowledge_base_skipped_reason = None
    if build_kb and not records:
        knowledge_base_status = "skipped_no_success"
        knowledge_base_skipped_reason = "本批次没有成功分析的视频"
        progress(
            "知识库",
            94,
            "本批次没有成功分析的视频，已跳过知识库写入；失败记录仅保存在批量清单中。",
        )
    elif build_kb:
        from rag.knowledge_base import build_knowledge_base

        knowledge_base_status = "updated"
        if failures:
            progress(
                "知识库",
                94,
                (
                    f"正在把 {len(records)} 个成功分析结果写入知识库；"
                    f"{len(failures)} 个失败视频不会写入。"
                ),
            )
        else:
            progress(
                "知识库",
                94,
                f"正在把 {len(records)} 个成功分析结果写入知识库。",
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

    remaining_pending = progress_store.pending_count(
        platform,
        batch_source.creator_id,
    )
    learning_status = (
        "complete_after_batch"
        if (
            scan_exhausted
            and remaining_pending == 0
            and videos
            and not failures
            and len(records) == len(videos)
        )
        else "updated"
    )
    status_message = _batch_status_message(
        platform,
        learning_status,
        len(skipped_existing),
        len(records),
    )
    _write_manifest(
        manifest_path,
        normalized,
        videos,
        records,
        failures,
        profile_path,
        kb_path,
        platform=platform,
        candidate_count=len(candidate_videos),
        skipped_existing=skipped_existing,
        learning_status=learning_status,
        status_message=status_message,
    )
    return {
        "schema_version": BATCH_RESULT_SCHEMA_VERSION,
        "platform": platform,
        "source": normalized,
        "profile_path": profile_path,
        "manifest_path": manifest_path,
        "success_count": len(records),
        "failure_count": len(failures),
        "knowledge_base_path": kb_path,
        "knowledge_base_status": knowledge_base_status,
        "knowledge_base_skipped_reason": knowledge_base_skipped_reason,
        "candidate_count": len(candidate_videos),
        "skipped_existing_count": len(skipped_existing),
        "learning_status": learning_status,
        "status_message": status_message,
        "video_outputs": [
            {
                "video_id": record["video"].video_id,
                "title": record["video"].title,
                "markdown_path": record["markdown_path"],
            }
            for record in records
        ],
    }


def _resolve_douyin_creator_source(
    source: str,
    context: CreatorBatchContext,
) -> CreatorBatchSource:
    context.progress("抖音主页", 18, "正在解析抖音创作者主页。")
    normalized = extract_douyin_url(source)
    context.progress("抖音主页", 22, "正在获取并缓存抖音创作者最新视频。")
    adapter = DouyinAdapter(context.settings)
    scan_limit = max(1, int(context.limit or context.settings.batch_limit))
    acquired_videos = adapter.download(
        normalized,
        scan_limit,
    )
    if adapter.last_warning:
        context.progress("抖音主页", 24, adapter.last_warning)
    return CreatorBatchSource(
        platform="douyin",
        creator_id=f"creator_douyin_{_short_key(normalized)}",
        normalized=normalized,
        output_name=f"creator_douyin_{_short_key(normalized)}",
        videos=[
            {
                "source_url": video.source_url,
                "title": video.title,
                "acquired_video": video,
            }
            for video in acquired_videos
        ],
        # The current Douyin adapter downloads while enumerating.  Keep its
        # existing behavior until it exposes a metadata-only creator listing;
        # otherwise looking for the next unseen item would redownload every
        # skipped candidate before deduplication can run.
        known_video_ids=frozenset(),
        scan_limit=scan_limit,
        scan_exhausted=False,
    )


def _resolve_youtube_creator_source(
    source: str,
    context: CreatorBatchContext,
) -> CreatorBatchSource:
    context.progress("频道列表", 18, "正在解析 YouTube 频道主页。")
    normalized = normalize_youtube_channel_url(source)
    output_name = f"channel_youtube_{youtube_channel_cache_key(normalized)}"
    return _resolve_persistent_creator_queue(
        context,
        platform="youtube",
        creator_id=output_name,
        normalized=normalized,
        output_name=output_name,
        crawler_type=YoutubeChannelCrawler,
        progress_stage="频道列表",
        progress_message="正在获取 YouTube 频道视频列表。",
    )


def _resolve_bilibili_creator_source(
    source: str,
    context: CreatorBatchContext,
) -> CreatorBatchSource:
    context.progress("UP列表", 18, "正在解析 B站 UP 主页、UID 或 UP 名。")
    normalized = normalize_up_url(source)
    output_name = f"up_{up_cache_key(normalized)}"
    return _resolve_persistent_creator_queue(
        context,
        platform="bilibili",
        creator_id=output_name,
        normalized=normalized,
        output_name=output_name,
        crawler_type=BilibiliUPCrawler,
        progress_stage="UP列表",
        progress_message="正在获取 B站 UP 视频列表。",
    )


def _resolve_persistent_creator_queue(
    context: CreatorBatchContext,
    *,
    platform: str,
    creator_id: str,
    normalized: str,
    output_name: str,
    crawler_type: type[Any],
    progress_stage: str,
    progress_message: str,
) -> CreatorBatchSource:
    store = CreatorProgressStore(context.settings.creator_progress_database_path)
    legacy_ids = _load_legacy_creator_video_ids(
        context.settings.output_dir / output_name
    )
    store.record_legacy_completed(
        platform,
        creator_id,
        legacy_ids,
        source=normalized,
    )
    target_limit = max(1, int(context.limit or context.settings.batch_limit))
    page_size = max(target_limit, context.settings.batch_limit, 10)
    state = store.state(platform, creator_id)
    pending = store.pending_videos(platform, creator_id, target_limit)

    if len(pending) < target_limit:
        completed = store.completed_video_ids(platform, creator_id)
        scan_limit = max(
            int(state["scan_limit"]) + page_size,
            len(completed) + page_size,
            page_size,
        )
        context.progress(progress_stage, 22, progress_message)
        crawler = crawler_type(context.settings)
        fetched = _deduplicate_video_seeds(
            crawler.fetch_video_sources(normalized, scan_limit)
        )
        candidates = [
            {**seed, "video_id": _video_seed_identity(seed)}
            for seed in fetched
            if _video_seed_identity(seed)
        ]
        store.record_candidates(
            platform,
            creator_id,
            normalized,
            candidates,
            scan_limit=scan_limit,
            scan_exhausted=crawler.last_list_complete is True,
        )
        state = store.state(platform, creator_id)
        pending = store.pending_videos(platform, creator_id, target_limit)

    return CreatorBatchSource(
        platform=platform,
        creator_id=creator_id,
        normalized=normalized,
        output_name=output_name,
        videos=pending,
        known_video_ids=store.completed_video_ids(platform, creator_id),
        scan_limit=int(state["scan_limit"]),
        scan_exhausted=bool(state["scan_exhausted"]),
    )


def _deduplicate_video_seeds(
    videos: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for seed in videos:
        identity = _video_seed_identity(seed)
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        unique.append(seed)
    return unique


def _select_unseen_videos(
    videos: list[dict[str, Any]],
    known_video_ids: frozenset[str],
    limit: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    selected: list[dict[str, Any]] = []
    skipped: list[str] = []
    for seed in videos:
        identity = _video_seed_identity(seed)
        if identity and identity in known_video_ids:
            skipped.append(identity)
            continue
        selected.append(seed)
        if len(selected) >= limit:
            break
    return selected, skipped


def _video_seed_identity(seed: dict[str, Any]) -> str:
    identity = str(seed.get("video_id") or "").strip()
    if identity:
        return identity
    acquired_video = seed.get("acquired_video")
    identity = str(getattr(acquired_video, "video_id", "") or "").strip()
    if identity:
        return identity
    source_url = str(seed.get("source_url") or "").strip()
    match = re.search(r"/(BV[0-9A-Za-z]+)(?:[/?#]|$)", source_url)
    if match:
        return match.group(1)
    match = re.search(r"[?&]v=([^&#]+)", source_url)
    return match.group(1) if match else source_url


def _load_legacy_creator_video_ids(creator_output_dir: Path) -> set[str]:
    """Read creator-specific legacy records for migration into durable state."""

    known: set[str] = set()
    try:
        index_path = creator_output_dir / "creator_video_index.json"
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        ids = payload.get("video_ids", []) if isinstance(payload, dict) else []
        if isinstance(ids, list):
            known.update(str(item).strip() for item in ids if str(item).strip())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass

    manifest_path = creator_output_dir / "batch_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        outputs = manifest.get("outputs", []) if isinstance(manifest, dict) else []
        if isinstance(outputs, list):
            known.update(
                str(item.get("video_id") or "").strip()
                for item in outputs
                if isinstance(item, dict) and str(item.get("video_id") or "").strip()
            )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    return known


def _learning_complete_message(platform: str, existing_count: int) -> str:
    creator = "该UP" if platform == "bilibili" else "该创作者"
    return (
        f"{creator}当前可获取的 {existing_count} 个视频均已完成分析；"
        "本次没有重复下载或分析。"
    )


def _incomplete_list_message(platform: str, existing_count: int) -> str:
    creator = "该UP" if platform == "bilibili" else "该创作者"
    return (
        f"已跳过当前列表中的 {existing_count} 个已学习视频；"
        f"平台没有返回{creator}的完整视频列表，暂时无法确认是否全部学习完毕，"
        "请稍后重试。"
    )


def _batch_status_message(
    platform: str,
    learning_status: str,
    skipped_existing_count: int,
    success_count: int,
) -> str:
    if learning_status == "complete_after_batch":
        creator = "该UP" if platform == "bilibili" else "该创作者"
        return f"已完成剩余 {success_count} 个视频，{creator}当前可获取的视频均已分析。"
    if skipped_existing_count:
        return (
            f"已跳过数据库中的 {skipped_existing_count} 个视频，"
            f"并自动分析后续 {success_count} 个未学习视频。"
        )
    return f"本次成功分析 {success_count} 个视频。"


def _batch_progress(index: int, total: int, item_percent: int) -> int:
    if total <= 0:
        return 25
    completed = max(0, index - 1)
    item_fraction = max(0, min(100, item_percent)) / 100
    return min(86, 25 + int(((completed + item_fraction) / total) * 60))


def _short_key(value: str) -> str:
    import hashlib

    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def _write_manifest(
    path: Path,
    source: str,
    seeds: list[dict[str, Any]],
    records: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    profile_path: Path | None = None,
    kb_path: Path | None = None,
    platform: str = "bilibili",
    candidate_count: int | None = None,
    skipped_existing: list[str] | None = None,
    learning_status: str | None = None,
    status_message: str | None = None,
) -> None:
    payload = {
        "schema_version": BATCH_RESULT_SCHEMA_VERSION,
        "platform": platform,
        "source": source,
        "seed_count": len(seeds),
        "success_count": len(records),
        "failure_count": len(failures),
        "candidate_count": candidate_count if candidate_count is not None else len(seeds),
        "skipped_existing_count": len(skipped_existing or []),
        "skipped_existing_video_ids": list(skipped_existing or []),
        "learning_status": learning_status,
        "status_message": status_message,
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
    }
    atomic_write_json(path, payload)
