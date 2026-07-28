from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from analyzer.up_profile import build_up_profile
from config import SETTINGS, Settings, ensure_directories
from downloader.bilibili_up import BilibiliUPCrawler, normalize_up_url, up_cache_key
from downloader.douyin_adapter import DouyinAdapter, extract_douyin_url
from downloader.social import is_douyin_profile_url
from downloader.youtube import is_youtube_channel_url, normalize_youtube_channel_url
from downloader.youtube_channel import YoutubeChannelCrawler, youtube_channel_cache_key
from exporter.up_profile import export_up_profile
from pipeline.run import (
    run_acquired_video_pipeline_details,
    run_video_pipeline_details,
)

logger = logging.getLogger(__name__)


def run_up_pipeline(
    source: str,
    settings: Settings = SETTINGS,
    limit: int | None = None,
    enrich_v3: bool = False,
    build_kb: bool = False,
    progress_callback: Callable[[str, int, str], None] | None = None,
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
        )


def _run_up_pipeline(
    source: str,
    settings: Settings = SETTINGS,
    limit: int | None = None,
    enrich_v3: bool = False,
    build_kb: bool = False,
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> dict[str, Any]:
    ensure_directories(settings)

    def progress(stage: str, percent: int, message: str) -> None:
        if progress_callback:
            progress_callback(stage, percent, message)

    if is_douyin_profile_url(source):
        platform = "douyin"
        progress("抖音主页", 18, "正在解析抖音创作者主页。")
        normalized = extract_douyin_url(source)
        progress("抖音主页", 22, "正在获取并缓存抖音创作者最新视频。")
        douyin_adapter = DouyinAdapter(settings)
        acquired_videos = douyin_adapter.download(
            normalized,
            limit or settings.batch_limit,
        )
        if douyin_adapter.last_warning:
            progress("抖音主页", 24, douyin_adapter.last_warning)
        videos = [
            {
                "source_url": video.source_url,
                "title": video.title,
                "acquired_video": video,
            }
            for video in acquired_videos
        ]
        output_name = f"creator_douyin_{_short_key(normalized)}"
    elif is_youtube_channel_url(source):
        platform = "youtube"
        progress("频道列表", 18, "正在解析 YouTube 频道主页。")
        normalized = normalize_youtube_channel_url(source)
        progress("频道列表", 22, "正在获取 YouTube 频道最新视频列表。")
        videos = YoutubeChannelCrawler(settings).fetch_video_sources(normalized, limit)
        output_name = f"channel_youtube_{youtube_channel_cache_key(normalized)}"
    else:
        platform = "bilibili"
        progress("UP列表", 18, "正在解析 B站 UP 主页、UID 或 UP 名。")
        normalized = normalize_up_url(source)
        progress("UP列表", 22, "正在获取 B站 UP 最新视频列表。")
        videos = BilibiliUPCrawler(settings).fetch_video_sources(normalized, limit)
        output_name = f"up_{up_cache_key(normalized)}"

    progress("创作者列表", 25, f"已获取 {len(videos)} 个视频，开始批量分析。")
    up_output_dir = settings.output_dir / output_name
    up_output_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    manifest_path = up_output_dir / "batch_manifest.json"

    for index, seed in enumerate(videos, start=1):
        source_url = seed.get("source_url")
        if not source_url:
            failures.append({"index": index, "source_url": "", "error": "missing source_url"})
            continue
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
                )
            else:
                result = run_video_pipeline_details(
                    source_url,
                    settings,
                    enrich_v3=enrich_v3,
                    progress_callback=item_progress,
                )
            records.append(result)
            progress("创作者批量", _batch_progress(index, len(videos), 100), f"第 {index}/{len(videos)} 个视频完成：{result['video'].title}")
        except Exception as exc:  # keep completed data even when one video fails
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
        kb_path = build_knowledge_base(settings.output_dir, settings.knowledge_base_dir / "index.json", settings)

    _write_manifest(
        manifest_path,
        normalized,
        videos,
        records,
        failures,
        profile_path,
        kb_path,
        platform=platform,
    )
    return {
        "platform": platform,
        "source": normalized,
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
) -> None:
    payload = {
        "platform": platform,
        "source": source,
        "seed_count": len(seeds),
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
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
