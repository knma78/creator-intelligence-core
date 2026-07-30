from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from config import SETTINGS, Settings, ensure_directories
from pipeline.acquire import acquire_video
from pipeline.analyze import analyze_transcript
from pipeline.export import export_results
from pipeline.process import process_video
from models import Video, build_pipeline_result


def run_video_pipeline(source: str, settings: Settings = SETTINGS, enrich_v3: bool = False) -> Path:
    return run_video_pipeline_details(source, settings, enrich_v3)["markdown_path"]


def run_video_pipeline_details(
    source: str,
    settings: Settings = SETTINGS,
    enrich_v3: bool = False,
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> dict[str, Any]:
    from processor.whisper import whisper_model_session

    with whisper_model_session(settings):
        return _run_video_pipeline_details(
            source,
            settings,
            enrich_v3,
            progress_callback,
        )


def run_acquired_video_pipeline_details(
    video: Video,
    settings: Settings = SETTINGS,
    enrich_v3: bool = False,
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> dict[str, Any]:
    from processor.whisper import whisper_model_session

    with whisper_model_session(settings):
        return _process_acquired_video(
            video,
            settings,
            enrich_v3,
            progress_callback,
        )


def _run_video_pipeline_details(
    source: str,
    settings: Settings = SETTINGS,
    enrich_v3: bool = False,
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> dict[str, Any]:
    ensure_directories(settings)

    def progress(stage: str, percent: int, message: str) -> None:
        if progress_callback:
            progress_callback(stage, percent, message)

    progress("获取视频", 20, "正在检查视频信息、官方字幕和本地缓存。")
    video = acquire_video(source, settings)
    if video.subtitle_path and video.subtitle_path.exists() and not video.video_path:
        progress("官方字幕", 35, "已获取官方字幕，跳过视频下载和 Whisper。")
    else:
        progress("视频就绪", 35, "视频文件已下载或已命中本地缓存。")

    return _process_acquired_video(
        video,
        settings,
        enrich_v3,
        progress_callback,
    )


def _process_acquired_video(
    video: Video,
    settings: Settings = SETTINGS,
    enrich_v3: bool = False,
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> dict[str, Any]:
    ensure_directories(settings)

    def progress(stage: str, percent: int, message: str) -> None:
        if progress_callback:
            progress_callback(stage, percent, message)

    progress("处理字幕", 40, "正在准备字幕；没有官方字幕时会提取音频并执行 Whisper。")
    transcript = process_video(video, settings, progress_callback=progress)

    progress("内容分析", 82, "正在生成结构、Hook、节奏和关键词分析。")
    analysis = analyze_transcript(video, transcript, settings)

    progress("导出结果", 90, "正在写入 Markdown、字幕和 JSON 文件。")
    markdown_path = export_results(video, transcript, analysis, settings)

    enrichment = None
    if enrich_v3:
        from pipeline.enrich import enrich_video

        progress("V3增强", 94, "正在补充封面、评论、标题统计和扩展分析。")
        enrichment = enrich_video(video, transcript, analysis, settings)

    return build_pipeline_result(
        video=video,
        transcript=transcript,
        analysis=analysis,
        markdown_path=markdown_path,
        enrichment=enrichment,
    )
