from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from features.contracts import (
    FeatureHandler,
    FeatureJobServices,
    FeatureState,
)
from infrastructure.atomic_io import atomic_write_json
from infrastructure.cancellation import raise_if_cancelled
from production.contracts import RenderProfile
from production.edit_plan import build_auto_edit_plan
from production.ffmpeg_renderer import render_edit_plan
from production.packaging import create_research_package
from production.qa import qa_video
from production.script_video import (
    _run_cancellable_process,
    run_script_video_pipeline,
)


def production_profile(platform: str, fps: int) -> RenderProfile:
    normalized = platform.strip().lower()
    if normalized in {"douyin", "xiaohongshu", "shorts"}:
        return RenderProfile(
            width=1080,
            height=1920,
            fps=fps,
            platform=normalized,
        )
    if normalized == "square":
        return RenderProfile(
            width=1080,
            height=1080,
            fps=fps,
            platform=normalized,
        )
    if normalized not in {"bilibili", "youtube", "general"}:
        raise ValueError(f"不支持的视频平台配置：{platform}")
    return RenderProfile(
        width=1920,
        height=1080,
        fps=fps,
        platform=normalized,
    )


def run_video_production_job(
    state: FeatureState,
    job_id: str,
    payload: dict[str, Any],
    *,
    services: FeatureJobServices,
) -> None:
    video_id = str(payload.get("video_id") or "").strip()
    if not video_id:
        raise ValueError("视频生产任务缺少 video_id。")
    target_seconds = min(
        1800.0,
        max(15.0, float(payload.get("target_seconds") or 60)),
    )
    platform = str(payload.get("platform") or "douyin").strip().lower()
    fps = int(payload.get("fps") or 30)
    burn_subtitles = bool(payload.get("burn_subtitles", True))
    profile = production_profile(platform, fps)
    cancelled = lambda: state.jobs.is_cancel_requested(job_id)

    state.jobs.update(
        job_id,
        stage="生产打包",
        progress=10,
        log="正在整理研究报告、字幕和源素材引用。",
    )
    manifest_path = create_research_package(
        video_id,
        settings=state.settings,
        include_media=False,
        engine="ffmpeg",
        render_profile=profile,
    )
    raise_if_cancelled(cancelled)

    state.jobs.update(
        job_id,
        stage="自动剪辑计划",
        progress=22,
        log="正在按信息密度、钩子和叙事完整性选择连续片段。",
    )
    plan_path = build_auto_edit_plan(
        video_id,
        target_seconds=target_seconds,
        platform=platform,
        settings=state.settings,
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    raise_if_cancelled(cancelled)

    package_dir = manifest_path.parent
    render_dir = package_dir / "output"
    render_dir.mkdir(parents=True, exist_ok=True)
    duration_label = int(round(plan["output_duration_seconds"]))
    final_path = render_dir / f"{video_id}_{platform}_{duration_label}s.mp4"
    last_log_bucket = -1

    def update_render_progress(percent: int, message: str) -> None:
        nonlocal last_log_bucket
        raise_if_cancelled(cancelled)
        bucket = min(10, max(0, int(percent) // 10))
        updates: dict[str, Any] = {
            "stage": "GPU 成片",
            "progress": 30 + round(min(100, max(0, percent)) * 0.55),
            "progress_detail": {
                "type": "video_render",
                "phase_percent": min(100, max(0, percent)),
                "encoder": "NVENC 优先",
                "output_duration_seconds": plan["output_duration_seconds"],
            },
        }
        if bucket != last_log_bucket:
            updates["log"] = message
            last_log_bucket = bucket
        state.jobs.update(job_id, **updates)

    state.jobs.update(
        job_id,
        stage="GPU 成片",
        progress=30,
        progress_detail={
            "type": "video_render",
            "phase_percent": 0,
            "encoder": "NVENC 优先",
            "output_duration_seconds": plan["output_duration_seconds"],
        },
        log="正在调用 FFmpeg；可随时取消，未完成的临时成片不会作为结果保留。",
    )
    render_edit_plan(
        plan_path,
        final_path,
        profile=profile,
        burn_subtitles=burn_subtitles,
        prefer_gpu=True,
        cancel_requested=cancelled,
        progress_callback=update_render_progress,
        settings=state.settings,
    )
    raise_if_cancelled(cancelled)

    qa_path = final_path.with_suffix(final_path.suffix + ".qa.json")
    state.jobs.update(
        job_id,
        stage="成片质检",
        progress=90,
        progress_detail={"type": "video_qa", "state": "scanning"},
        log="正在检查黑帧、静音、媒体参数和字幕可读性。",
    )
    subtitle_path = Path(plan["edit_subtitle_path"])
    qa_report = qa_video(
        final_path,
        ffmpeg_path=state.settings.video_ffmpeg_path,
        ffprobe_path=state.settings.ffprobe_path,
        subtitle_path=subtitle_path,
        report_path=qa_path,
        cancel_requested=cancelled,
    )
    raise_if_cancelled(cancelled)
    if qa_report.get("blocking_errors"):
        raise RuntimeError(
            "成片质检未通过："
            + "；".join(str(item) for item in qa_report["blocking_errors"])
        )

    capcut_plan_path = package_dir / "work" / "capcut_timeline.json"
    capcut_plan = {
        "name": f"Codex_Video_{job_id[:20]}",
        "width": profile.width,
        "height": profile.height,
        "fps": profile.fps,
        "clips": [
            {
                "path": plan["source_video_path"],
                "start": 0,
                "duration": plan["output_duration_seconds"],
                "source_start": plan["segments"][0]["source_start_seconds"],
                "volume": 1,
            }
        ],
        "subtitle_path": str(subtitle_path.resolve()),
    }
    atomic_write_json(capcut_plan_path, capcut_plan)
    state.jobs.update(
        job_id,
        stage="CapCut 草稿生成",
        progress=99,
        progress_detail={"type": "capcut_draft", "phase_percent": 0},
        log="视频预览与质检完成，正在把原片区间和可编辑字幕写入 CapCut 工程。",
    )
    capcut_record_path = package_dir / "output" / "capcut_build.json"
    capcut_report = _build_capcut_draft(
        capcut_plan_path,
        name=capcut_plan["name"],
        record_path=capcut_record_path,
        cancel_requested=cancelled,
        heartbeat=lambda elapsed: state.jobs.update(
            job_id,
            stage="CapCut 草稿生成",
            progress=99,
            log=f"CapCut 正在写入草稿工程，已用时 {elapsed} 秒。",
        ),
    )
    raise_if_cancelled(cancelled)

    files = [
        services.file_item("生产清单 production_manifest.json", manifest_path),
        services.file_item("自动剪辑计划 edit_plan.json", plan_path),
        services.file_item("重排字幕 edit_subtitles.srt", subtitle_path),
        services.file_item("CapCut 工程位置与轨道记录", capcut_record_path),
        services.file_item("CapCut 时间线输入 capcut_timeline.json", capcut_plan_path),
        services.file_item("FFmpeg 预览与质检 MP4", final_path),
        services.file_item(
            "渲染记录 render.json",
            final_path.with_suffix(final_path.suffix + ".render.json"),
        ),
        services.file_item("预览质检 qa.json", qa_path),
    ]
    state.jobs.update(
        job_id,
        status="done",
        stage=(
            "CapCut 草稿就绪·预览需复核"
            if qa_report.get("review_required")
            else "CapCut 草稿就绪"
        ),
        progress=100,
        progress_detail={
            "type": "video_render",
            "phase_percent": 100,
            "encoder": qa_report["probe"]["streams"][0].get(
                "codec_name", "h264"
            ),
        },
        result={
            "type": "video_production",
            "video_id": video_id,
            "platform": platform,
            "target_seconds": target_seconds,
            "qa_status": (
                "review_required"
                if qa_report.get("review_required")
                else "passed"
            ),
            "qa_target": "ffmpeg_preview",
            "output_duration_seconds": plan["output_duration_seconds"],
            "qa_passed": qa_report["passed"],
            "warnings": qa_report["warnings"],
            "export_status": capcut_report["export_status"],
            "capcut_draft_name": capcut_report["draft_name"],
            "capcut_draft_path": str(Path(capcut_report["saved"]).parent),
            "files": files,
        },
        log=(
            "CapCut 可编辑工程已生成；用 CapCut 打开草稿并完成最后导出。"
            if qa_report["passed"]
            else "CapCut 工程已生成；预览质检发现需要人工复核的项目。"
        ),
    )


def run_script_video_job(
    state: FeatureState,
    job_id: str,
    payload: dict[str, Any],
    *,
    services: FeatureJobServices,
) -> None:
    profile = production_profile(
        str(payload.get("platform") or "douyin"),
        int(payload.get("fps") or 30),
    )
    output_dir = state.settings.video_production_dir / "script_jobs" / job_id
    cancelled = lambda: state.jobs.is_cancel_requested(job_id)

    def report(stage: str, progress: int, message: str) -> None:
        raise_if_cancelled(cancelled)
        state.jobs.update(
            job_id,
            stage=stage,
            progress=max(1, min(99, int(progress))),
            progress_detail={
                "type": "script_video",
                "phase_percent": max(0, min(100, int(progress))),
                "agent_required": False,
            },
            log=message,
        )

    result = run_script_video_pipeline(
        str(payload.get("script") or ""),
        output_dir,
        title=str(payload.get("title") or ""),
        voice=str(payload.get("voice") or "zh-CN-XiaoxiaoNeural"),
        tts_rate=str(payload.get("tts_rate") or "+5%"),
        profile=profile,
        cancel_requested=cancelled,
        progress_callback=report,
        settings=state.settings,
    )
    paths = result["paths"]
    capcut_name = f"Codex_Script_{job_id[:20]}"
    state.jobs.update(
        job_id,
        stage="CapCut 草稿生成",
        progress=99,
        progress_detail={"type": "capcut_draft", "phase_percent": 0},
        log="分镜、旁白、字幕、预览和质检已完成，正在创建 CapCut 可编辑工程。",
    )
    capcut_record_path = output_dir / "output" / "capcut_build.json"
    capcut_report = _build_capcut_draft(
        paths["storyboard"],
        name=capcut_name,
        record_path=capcut_record_path,
        cancel_requested=cancelled,
        heartbeat=lambda elapsed: state.jobs.update(
            job_id,
            stage="CapCut 草稿生成",
            progress=99,
            log=f"CapCut 正在写入草稿工程，已用时 {elapsed} 秒。",
        ),
    )
    raise_if_cancelled(cancelled)
    files = [
        services.file_item("CapCut 工程位置与轨道记录", capcut_record_path),
        services.file_item("FFmpeg 预览与质检 MP4", paths["video"]),
        services.file_item("原始文稿 source_script.txt", paths["script"]),
        services.file_item("旁白 narration.mp3", paths["narration"]),
        services.file_item("成片字幕 captions.srt", paths["subtitle"]),
        services.file_item("可审计分镜 storyboard.json", paths["storyboard"]),
        services.file_item("蒸馏模板 template.json", paths["template"]),
        services.file_item("渲染记录 render.json", paths["render_record"]),
        services.file_item("预览质检 qa.json", paths["qa"]),
    ]
    for index, asset in enumerate(capcut_report.get("generated_assets") or [], start=1):
        files.append(
            services.file_item(
                f"CapCut 兜底画面 fallback_{index}.png",
                Path(asset),
            )
        )
    state.jobs.update(
        job_id,
        status="done",
        stage=("CapCut 草稿就绪·预览需复核"
               if result["qa_status"] == "review_required"
               else "CapCut 草稿就绪"),
        progress=100,
        progress_detail={
            "type": "script_video",
            "phase_percent": 100,
            "agent_required": False,
        },
        result={
            **{key: value for key, value in result.items() if key != "paths"},
            "export_status": capcut_report["export_status"],
            "qa_target": "ffmpeg_preview",
            "capcut_draft_name": capcut_report["draft_name"],
            "capcut_draft_path": str(Path(capcut_report["saved"]).parent),
            "files": files,
        },
        log="CapCut 可编辑工程已生成；用 CapCut 打开草稿并完成最后导出。",
    )


def _build_capcut_draft(
    source_plan: Path,
    *,
    name: str,
    record_path: Path,
    cancel_requested: Callable[[], bool],
    heartbeat: Callable[[int], None],
) -> dict[str, Any]:
    repository_root = Path(__file__).resolve().parents[2]
    python = repository_root / ".venv-capcut" / "Scripts" / "python.exe"
    adapter = repository_root / "tools" / "capcut_mcp.py"
    if not python.is_file() or not adapter.is_file():
        raise RuntimeError("CapCut 草稿生成环境不可用；请检查 .venv-capcut 和 tools/capcut_mcp.py。")
    command = [
        str(python),
        str(adapter),
        "build",
        str(Path(source_plan).resolve()),
        "--name",
        name,
    ]
    return_code, stdout, stderr = _run_cancellable_process(
        command,
        cancel_requested=cancel_requested,
        cancel_message="CapCut 草稿生成已取消。",
        timeout_seconds=180,
        timeout_message="CapCut 草稿生成超时。",
        heartbeat_callback=heartbeat,
    )
    if return_code != 0:
        detail = (stderr or stdout).strip()[-1800:]
        raise RuntimeError("CapCut 草稿生成失败：" + (detail or "CLI returned an error."))
    try:
        report = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("CapCut 草稿生成返回了无效结果。") from exc
    saved = Path(str(report.get("saved") or ""))
    if not saved.is_file():
        raise RuntimeError("CapCut 未写出 draft_content.json。")
    report["draft_path"] = str(saved.parent)
    report["draft_content_path"] = str(saved)
    report["draft_name"] = name
    report["export_status"] = "awaiting_capcut_export"
    atomic_write_json(record_path, report)
    return report


def build_video_production_job_handler(
    services: FeatureJobServices,
) -> FeatureHandler:
    def handler(
        state: FeatureState,
        job_id: str,
        payload: dict[str, Any],
        _check_cancelled: Callable[[], None],
    ) -> None:
        run_video_production_job(
            state,
            job_id,
            payload,
            services=services,
        )

    return handler


def build_script_video_job_handler(
    services: FeatureJobServices,
) -> FeatureHandler:
    def handler(
        state: FeatureState,
        job_id: str,
        payload: dict[str, Any],
        _check_cancelled: Callable[[], None],
    ) -> None:
        run_script_video_job(
            state,
            job_id,
            payload,
            services=services,
        )

    return handler
