from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import threading
import time
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from config import SETTINGS, Settings
from infrastructure.atomic_io import atomic_write_json, atomic_write_text
from infrastructure.cancellation import JobCancelledError, raise_if_cancelled
from infrastructure.resources import ResourceKind, get_resource_manager
from production.contracts import RenderProfile
from production.capability_layout import build_layout
from production.script_runtime import script_video_runtime_status
from production.script_schema import SCRIPT_VIDEO_SCHEMA_VERSION, TEMPLATE_NAME
from production.captions import (
    compact_caption_cues,
    display_units as _display_units,
    estimate_caption_cues,
    normalize_caption_cues,
    parse_vtt,
    semantic_caption_cues,
    split_script,
    write_ass,
    write_srt,
    write_vtt,
)
from production.assets import (
    _MIN_ASSET_MATCH_SCORE,
    cover_catalog as _cover_catalog,
    rank_assets as _rank_assets,
    read_json as _read_json,
    research_directories as _research_directories,
)
from production.ffmpeg_renderer import (
    _run_ffmpeg_cancellable,
    _subtitle_filter_path,
    inspect_ffmpeg_runtime,
)
from production.qa import probe_media, qa_video




def derive_rough_template(
    settings: Settings = SETTINGS,
) -> dict[str, Any]:
    directories = _research_directories(settings)
    scene_lengths: list[float] = []
    rhythm_samples = 0
    structure_samples = 0
    for directory in directories[:240]:
        analysis = _read_json(directory / "analysis.json")
        if analysis.get("structure"):
            structure_samples += 1
        enrichment = _read_json(directory / "v3.json")
        if enrichment.get("audio_rhythm_analysis"):
            rhythm_samples += 1
        scenes = (
            (enrichment.get("scene_analysis") or {}).get("scenes")
            or []
        )
        for scene in scenes[:120]:
            if not isinstance(scene, dict):
                continue
            try:
                length = float(scene.get("end")) - float(
                    scene.get("start")
                )
            except (TypeError, ValueError):
                continue
            if 0.6 <= length <= 12:
                scene_lengths.append(length)
    scene_lengths.sort()
    median_scene = (
        scene_lengths[len(scene_lengths) // 2]
        if scene_lengths
        else 4.0
    )
    return {
        "schema_version": SCRIPT_VIDEO_SCHEMA_VERSION,
        "template": TEMPLATE_NAME,
        "derived_from": {
            "research_directories": len(directories),
            "structure_samples": structure_samples,
            "scene_samples": len(scene_lengths),
            "rhythm_samples": rhythm_samples,
        },
        "defaults": {
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "shot_seconds": round(min(5.5, max(3.0, median_scene)), 2),
            "caption_display_units": 28,
            "hook_ratio": 0.10,
            "setup_ratio": 0.20,
            "development_ratio": 0.55,
            "payoff_ratio": 0.15,
            "voice": "zh-CN-XiaoxiaoNeural",
            "tts_rate": "+5%",
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def preview_script_video_plan(
    script: str,
    *,
    title: str = "",
    settings: Settings = SETTINGS,
) -> dict[str, Any]:
    clean_script = _validate_script(script)
    template = derive_rough_template(settings)
    estimated_seconds = max(8.0, _display_units(clean_script) / 4.2)
    return _build_storyboard(
        clean_script,
        duration_seconds=estimated_seconds,
        title=title,
        template=template,
        settings=settings,
        preview=True,
    )


def run_script_video_pipeline(
    script: str,
    output_dir: Path,
    *,
    title: str = "",
    voice: str = "zh-CN-XiaoxiaoNeural",
    tts_rate: str = "+5%",
    profile: RenderProfile | None = None,
    cancel_requested: Callable[[], bool] | None = None,
    progress_callback: Callable[[str, int, str], None] | None = None,
    settings: Settings = SETTINGS,
) -> dict[str, Any]:
    clean_script = _validate_script(script)
    selected_profile = profile or RenderProfile(
        width=1080,
        height=1920,
        fps=30,
        platform="douyin",
    )
    selected_profile.validate()
    output_dir = Path(output_dir).resolve()
    work_dir = output_dir / "work"
    render_dir = output_dir / "output"
    work_dir.mkdir(parents=True, exist_ok=True)
    render_dir.mkdir(parents=True, exist_ok=True)

    script_path = atomic_write_text(
        work_dir / "source_script.txt",
        clean_script,
    )
    template_path = work_dir / "template.json"
    template = derive_rough_template(settings)
    atomic_write_json(template_path, template)
    _progress(
        progress_callback,
        "制作规则",
        10,
        "已从现有蒸馏数据生成粗剪模板。",
    )
    raise_if_cancelled(cancel_requested)

    narration_path = work_dir / "narration.mp3"
    vtt_path = work_dir / "narration.vtt"
    tts_record_path = work_dir / "tts.json"
    signature = hashlib.sha256(
        f"{voice}\0{tts_rate}\0{clean_script}".encode("utf-8")
    ).hexdigest()
    cached_tts = _read_json(tts_record_path)
    if not _valid_tts_cache(
        cached_tts,
        signature=signature,
        narration_path=narration_path,
        vtt_path=vtt_path,
        ffprobe_path=settings.ffprobe_path,
    ):
        narration_path.unlink(missing_ok=True)
        vtt_path.unlink(missing_ok=True)
        _progress(
            progress_callback,
            "生成旁白",
            18,
            "正在生成旁白与原始时间轴。",
        )
        tts_engine = "edge-tts"
        try:
            _run_edge_tts(
                settings=settings,
                script_path=script_path,
                narration_path=narration_path,
                vtt_path=vtt_path,
                voice=voice,
                rate=tts_rate,
                cancel_requested=cancel_requested,
                progress_callback=progress_callback,
            )
        except JobCancelledError:
            raise
        except RuntimeError:
            _progress(
                progress_callback,
                "旁白回退",
                22,
                "Edge TTS 暂时不可用，自动切换 Windows 本地中文语音。",
            )
            tts_engine = "windows-sapi"
            _run_windows_sapi_tts(
                script_path=script_path,
                wav_path=work_dir / "narration.sapi.wav",
                output_path=narration_path,
                rate=tts_rate,
                settings=settings,
                cancel_requested=cancel_requested,
                progress_callback=progress_callback,
            )
            fallback_duration = _media_duration(
                narration_path,
                settings.ffprobe_path,
            )
            write_vtt(
                estimate_caption_cues(clean_script, fallback_duration),
                vtt_path,
            )
        atomic_write_json(
            tts_record_path,
            {
                "schema_version": SCRIPT_VIDEO_SCHEMA_VERSION,
                "signature": signature,
                "engine": tts_engine,
                "voice": voice,
                "rate": tts_rate,
                "narration_path": str(narration_path),
                "subtitle_source_path": str(vtt_path),
                "audio_bytes": narration_path.stat().st_size,
                "audio_sha256": _sha256_file(narration_path),
                "audio_duration_seconds": round(
                    _media_duration(narration_path, settings.ffprobe_path),
                    3,
                ),
                "vtt_bytes": vtt_path.stat().st_size,
                "vtt_sha256": _sha256_file(vtt_path),
                "cue_count": len(parse_vtt(vtt_path)),
            },
        )
    else:
        _progress(
            progress_callback,
            "生成旁白",
            26,
            "复用已完成的旁白与时间轴缓存。",
        )
        if not cached_tts.get("audio_sha256"):
            atomic_write_json(
                tts_record_path,
                {
                    **cached_tts,
                    "audio_bytes": narration_path.stat().st_size,
                    "audio_sha256": _sha256_file(narration_path),
                    "audio_duration_seconds": round(
                        _media_duration(
                            narration_path,
                            settings.ffprobe_path,
                        ),
                        3,
                    ),
                    "vtt_bytes": vtt_path.stat().st_size,
                    "vtt_sha256": _sha256_file(vtt_path),
                    "cue_count": len(parse_vtt(vtt_path)),
                },
            )
    raise_if_cancelled(cancel_requested)

    duration = _media_duration(narration_path, settings.ffprobe_path)
    raw_cues = parse_vtt(vtt_path)
    if not raw_cues:
        raise RuntimeError("TTS 未返回有效时间轴，无法生成可审计字幕。")
    cues = semantic_caption_cues(
        raw_cues,
        script=clean_script,
        max_display_units=34,
        min_duration=0.8,
        max_duration=6.0,
    )
    # VTT is kept for the CapCut draft (CapCut bridge parses VTT).
    capcut_subtitle_path = write_vtt(cues, work_dir / "captions_for_capcut.vtt")
    # ASS is used for FFmpeg burn-in so we can control canvas resolution and safe margins.
    ass_subtitle_path = write_ass(
        cues,
        work_dir / "captions.ass",
        width=selected_profile.width,
        height=selected_profile.height,
        font_size=22,
        margin_v=70,
        alignment=2,
    )
    # Also keep SRT for external tooling compatibility.
    srt_subtitle_path = write_srt(cues, work_dir / "captions.srt")
    _progress(
        progress_callback,
        "字幕时间轴",
        34,
        f"旁白 {duration:.1f} 秒，生成 {len(cues)} 条语义对齐字幕。",
    )

    storyboard = _build_storyboard(
        clean_script,
        duration_seconds=duration,
        title=title,
        template=template,
        settings=settings,
        preview=False,
        cues=raw_cues,
    )
    storyboard.update(
        {
            "narration_path": str(narration_path),
            "subtitle_path": str(capcut_subtitle_path),
            "ass_subtitle_path": str(ass_subtitle_path),
            "srt_subtitle_path": str(srt_subtitle_path),
            "voice": voice,
            "tts_rate": tts_rate,
            "render_profile": asdict(selected_profile),
        }
    )
    storyboard_path = work_dir / "storyboard.json"
    atomic_write_json(storyboard_path, storyboard)
    _progress(
        progress_callback,
        "素材解析",
        44,
        f"已生成 {len(storyboard['scenes'])} 个镜头，素材选择已写入分镜。",
    )
    raise_if_cancelled(cancel_requested)

    final_path = render_dir / "rough_narrated_video.mp4"
    _render_storyboard(
        storyboard,
        narration_path=narration_path,
        subtitle_path=ass_subtitle_path,
        output_path=final_path,
        profile=selected_profile,
        cancel_requested=cancel_requested,
        progress_callback=progress_callback,
        settings=settings,
    )
    raise_if_cancelled(cancel_requested)

    qa_path = final_path.with_suffix(final_path.suffix + ".qa.json")
    _progress(
        progress_callback,
        "成片质检",
        90,
        "正在检查音视频流、黑帧、静音和字幕安全宽度。",
    )
    qa_report = qa_video(
        final_path,
        ffmpeg_path=settings.video_ffmpeg_path,
        ffprobe_path=settings.ffprobe_path,
        subtitle_path=srt_subtitle_path,
        report_path=qa_path,
        cancel_requested=cancel_requested,
    )
    rendered_probe = qa_report.get("probe") or {}
    rendered_streams = rendered_probe.get("streams") or []
    video_stream = next(
        (
            item
            for item in rendered_streams
            if item.get("codec_type") == "video"
        ),
        {},
    )
    try:
        rendered_duration = float(
            (rendered_probe.get("format") or {}).get("duration") or 0
        )
    except (TypeError, ValueError):
        rendered_duration = 0
    expected_duration = min(
        duration,
        float(storyboard["output_duration_seconds"]),
    )
    if abs(rendered_duration - expected_duration) > max(
        0.25,
        2 / max(1, selected_profile.fps),
    ):
        qa_report.setdefault("blocking_errors", []).append(
            "Rendered duration does not match narration/storyboard duration."
        )
    if (
        int(video_stream.get("width") or 0) != selected_profile.width
        or int(video_stream.get("height") or 0) != selected_profile.height
    ):
        qa_report.setdefault("blocking_errors", []).append(
            "Rendered dimensions do not match the selected profile."
        )
    last_caption_end = max(
        (float(item.get("end") or 0) for item in cues),
        default=0,
    )
    if last_caption_end > rendered_duration + 0.15:
        qa_report.setdefault("blocking_errors", []).append(
            "Subtitle timeline extends beyond the rendered video."
        )
    if qa_report.get("blocking_errors"):
        qa_report["passed"] = False
    atomic_write_json(qa_path, qa_report)
    if qa_report.get("blocking_errors"):
        raise RuntimeError(
            "成片质检失败：" + "；".join(qa_report["blocking_errors"])
        )
    _progress(
        progress_callback,
        "闭环完成",
        100,
        "旁白、分镜、字幕、渲染与质量检查均已完成。",
    )
    return {
        "type": "script_video_production",
        "schema_version": SCRIPT_VIDEO_SCHEMA_VERSION,
        "title": storyboard["title"],
        "duration_seconds": duration,
        "scene_count": len(storyboard["scenes"]),
        "qa_status": (
            "review_required"
            if qa_report.get("review_required")
            else "passed"
        ),
        "warnings": qa_report.get("warnings") or [],
        "paths": {
            "script": script_path,
            "template": template_path,
            "narration": narration_path,
            "vtt": vtt_path,
            "subtitle": capcut_subtitle_path,
            "ass_subtitle": ass_subtitle_path,
            "srt_subtitle": srt_subtitle_path,
            "storyboard": storyboard_path,
            "video": final_path,
            "render_record": final_path.with_suffix(
                final_path.suffix + ".render.json"
            ),
            "qa": qa_path,
        },
    }


def _build_storyboard(
    script: str,
    *,
    duration_seconds: float,
    title: str,
    template: dict[str, Any],
    settings: Settings,
    preview: bool,
    cues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    defaults = template.get("defaults") or {}
    shot_seconds = float(defaults.get("shot_seconds") or 4.0)
    layout, capability_plan, execution = build_layout(
        script, duration=duration_seconds, shot_seconds=shot_seconds,
        title=title, settings=settings, cues=cues,
    )
    scene_count = len(layout)
    catalog = _cover_catalog(settings, load_analysis=True)
    global_ranked = _rank_assets(script, catalog)
    scenes: list[dict[str, Any]] = []
    start = 0.0
    used_paths: list[str] = []
    for index, segment in enumerate(layout):
        start, end = segment["start"], segment["end"]
        chunk = segment["script_excerpt"]
        ranked = _rank_assets(chunk, catalog)
        match_scope = "scene"
        candidates = ranked
        if not candidates and global_ranked:
            match_scope = "script"
            candidates = [
                item
                for item in global_ranked
                if item.get("confidence") in {"high", "medium"}
            ]
        chosen = next(
            (
                item
                for item in candidates
                if item["path"] not in used_paths[-3:]
            ),
            candidates[0] if candidates else None,
        )
        if chosen:
            used_paths.append(chosen["path"])
        scenes.append(
            {
                "scene_id": f"scene-{index + 1:03d}",
                "output_start_seconds": round(start, 3),
                "output_end_seconds": round(end, 3),
                "duration_seconds": round(end - start, 3),
                "script_excerpt": chunk,
                "script_start": segment["script_start"],
                "script_end": segment["script_end"],
                "capability_decisions": segment["capability_decisions"],
                "visual": (
                    {
                        "type": "distilled_cover",
                        "path": chosen["path"],
                        "source_id": chosen["source_id"],
                        "source_title": chosen["title"],
                        "match_score": chosen["score"],
                        "match_confidence": chosen["confidence"],
                        "match_scope": match_scope,
                        "matched_terms": chosen["matched_terms"],
                        "match_reasons": chosen["match_reasons"],
                        "score_breakdown": chosen["score_breakdown"],
                        "openclip_labels": chosen.get("visual_labels") or [],
                        "fit_mode": "contain_blurred_background",
                    }
                    if chosen
                    else {
                        "type": "local_gradient",
                        "path": None,
                        "source_id": None,
                        "source_title": "本地渐变兜底",
                        "match_score": 0,
                        "match_confidence": "fallback",
                        "match_scope": "none",
                        "matched_terms": [],
                        "match_reasons": ["没有达到最低相关度的本地封面"],
                        "score_breakdown": {
                            "lexical": 0,
                            "visual_style": 0,
                        },
                        "openclip_labels": [],
                        "fit_mode": "generated_gradient",
                    }
                ),
                "narrative_role": _narrative_role(
                    index,
                    scene_count,
                    defaults,
                ),
                "transition": "hard_cut",
            }
        )
        start = end
    return {
        "schema_version": SCRIPT_VIDEO_SCHEMA_VERSION,
        "strategy": "distilled_rules_narrated_storyboard",
        "visual_mode": "distilled_cover_slideshow",
        "template": template.get("template") or TEMPLATE_NAME,
        "title": title.strip() or split_script(script, target_units=36)[0][
            :36
        ],
        "preview": preview,
        "duration_source": "estimate" if preview else "tts_audio",
        "output_duration_seconds": round(duration_seconds, 3),
        "scene_count": len(scenes),
        "scenes": scenes,
        "capability_plan": capability_plan,
        "capability_execution": execution,
        "decision_inputs": {
            "distilled_research_count": (
                template.get("derived_from") or {}
            ).get("research_directories", 0),
            "distilled_scene_count": (
                template.get("derived_from") or {}
            ).get("scene_samples", 0),
            "asset_catalog_count": len(catalog),
            "openclip_asset_count": sum(
                1 for item in catalog if item.get("openclip_ready")
            ),
            "matched_scene_count": sum(
                1
                for item in scenes
                if item["visual"]["type"] == "distilled_cover"
            ),
            "unique_matched_asset_count": len(
                {
                    item["visual"]["source_id"]
                    for item in scenes
                    if item["visual"]["type"] == "distilled_cover"
                    and item["visual"].get("source_id")
                }
            ),
            "fallback_scene_count": sum(
                1
                for item in scenes
                if item["visual"]["type"] == "local_gradient"
            ),
            "selection_strategy": (
                "weighted title/keyword/summary/OCR relevance + "
                "OpenCLIP visual-style tie-break"
            ),
            "minimum_match_score": _MIN_ASSET_MATCH_SCORE,
            "agent_required": False,
        },
    }


def _narrative_role(
    index: int,
    scene_count: int,
    defaults: dict[str, Any],
) -> str:
    if index == 0:
        return "hook"
    if index == scene_count - 1:
        return "payoff"
    position = (index + 0.5) / max(1, scene_count)
    hook_end = float(defaults.get("hook_ratio") or 0.10)
    setup_end = hook_end + float(defaults.get("setup_ratio") or 0.20)
    payoff_start = 1 - float(defaults.get("payoff_ratio") or 0.15)
    if position <= hook_end:
        return "hook"
    if position <= setup_end:
        return "setup"
    if position >= payoff_start:
        return "payoff"
    return "development"


def _run_cancellable_process(
    command: list[str],
    *,
    cancel_requested: Callable[[], bool] | None,
    cancel_message: str,
    timeout_seconds: float,
    timeout_message: str,
    heartbeat_callback: Callable[[int], None] | None = None,
) -> tuple[int, str, str]:
    """Run a subprocess while continuously draining both output pipes."""

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    stdout_tail: deque[str] = deque(maxlen=240)
    stderr_tail: deque[str] = deque(maxlen=240)

    def drain(stream: Any, target: deque[str]) -> None:
        if stream is None:
            return
        for line in stream:
            # Bound both the line count and each individual line. Some CLIs emit
            # a single giant line, which would otherwise defeat deque(maxlen).
            target.append(line[-4096:])

    readers = [
        threading.Thread(
            target=drain,
            args=(process.stdout, stdout_tail),
            name="script-video-stdout-reader",
            daemon=True,
        ),
        threading.Thread(
            target=drain,
            args=(process.stderr, stderr_tail),
            name="script-video-stderr-reader",
            daemon=True,
        ),
    ]
    for reader in readers:
        reader.start()
    started = time.monotonic()
    last_heartbeat = started
    cancelled = False
    timed_out = False
    while process.poll() is None:
        now = time.monotonic()
        if cancel_requested is not None and cancel_requested():
            cancelled = True
            _terminate_process(process)
            break
        if now - started >= timeout_seconds:
            timed_out = True
            _terminate_process(process)
            break
        if heartbeat_callback is not None and now - last_heartbeat >= 10:
            heartbeat_callback(max(1, round(now - started)))
            last_heartbeat = now
        time.sleep(0.12)
    if process.poll() is None:
        _terminate_process(process)
    for reader in readers:
        reader.join(timeout=1)
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            stream.close()
    stdout = "".join(stdout_tail)
    stderr = "".join(stderr_tail)
    if cancelled:
        raise JobCancelledError(cancel_message)
    if timed_out:
        detail = (stderr or stdout)[-800:].strip()
        raise RuntimeError(
            timeout_message + (f" 末尾信息：{detail}" if detail else "")
        )
    return process.returncode or 0, stdout, stderr


def _terminate_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=1.5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _process_error_summary(text: str, fallback: str) -> str:
    cleaned = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not cleaned:
        return fallback
    hresult = re.search(r"HRESULT\s*:?\s*0x[0-9A-Fa-f]+", text)
    if hresult:
        return f"{fallback} ({hresult.group(0)})"[:320]
    message = next(
        (
            line
            for line in cleaned
            if not line.startswith(("$ErrorActionPreference", "+", "所在位置"))
            and "CategoryInfo" not in line
            and "FullyQualifiedErrorId" not in line
        ),
        fallback,
    )
    return message[:320]


def _run_edge_tts(
    *,
    settings: Settings,
    script_path: Path,
    narration_path: Path,
    vtt_path: Path,
    voice: str,
    rate: str,
    cancel_requested: Callable[[], bool] | None,
    progress_callback: Callable[[str, int, str], None] | None,
) -> None:
    executable = settings.edge_tts_path
    if not executable or not Path(executable).is_file():
        raise RuntimeError("Edge TTS 不可用；请先检查 EDGE_TTS_PATH。")
    narration_partial = narration_path.with_name(
        f".{narration_path.stem}.partial{narration_path.suffix}"
    )
    vtt_partial = vtt_path.with_name(
        f".{vtt_path.stem}.partial{vtt_path.suffix}"
    )
    narration_partial.unlink(missing_ok=True)
    vtt_partial.unlink(missing_ok=True)
    command = [
        executable,
        "--file",
        str(script_path),
        "--voice",
        voice,
        "--rate",
        rate,
        "--write-media",
        str(narration_partial),
        "--write-subtitles",
        str(vtt_partial),
    ]
    manager = get_resource_manager(settings)
    with manager.lease(
        ResourceKind.NETWORK_IO,
        owner=f"script-video-tts:{narration_path.name}",
        cancel_requested=cancel_requested,
    ):
        script_char_count = len(
            script_path.read_text(encoding="utf-8-sig", errors="replace")
        )
        try:
            return_code, stdout, stderr = _run_cancellable_process(
                command,
                cancel_requested=cancel_requested,
                cancel_message="旁白生成已由用户取消。",
                timeout_seconds=max(
                    180,
                    min(3600, 180 + script_char_count / 3),
                ),
                timeout_message="Edge TTS 超时，已停止并保留任务可重试。",
                heartbeat_callback=lambda elapsed: _progress(
                    progress_callback,
                    "生成旁白",
                    18,
                    f"旁白仍在生成，已运行 {elapsed} 秒；可随时取消。",
                ),
            )
        except (JobCancelledError, RuntimeError):
            narration_partial.unlink(missing_ok=True)
            vtt_partial.unlink(missing_ok=True)
            raise
    if return_code != 0:
        narration_partial.unlink(missing_ok=True)
        vtt_partial.unlink(missing_ok=True)
        raise RuntimeError(
            f"Edge TTS 生成失败：{(stderr or stdout)[-1600:]}"
        )
    if not _nonempty(narration_partial):
        narration_partial.unlink(missing_ok=True)
        vtt_partial.unlink(missing_ok=True)
        raise RuntimeError("Edge TTS 没有生成有效旁白文件。")
    if not _nonempty(vtt_partial):
        narration_partial.unlink(missing_ok=True)
        vtt_partial.unlink(missing_ok=True)
        raise RuntimeError("Edge TTS 没有生成有效时间轴。")
    try:
        duration = _media_duration(narration_partial, settings.ffprobe_path)
        cues = parse_vtt(vtt_partial)
        if not cues:
            raise RuntimeError("Edge TTS 时间轴没有有效字幕。")
        if float(cues[-1].get("end") or 0) > duration + 2.0:
            raise RuntimeError("Edge TTS 时间轴超过旁白时长。")
    except Exception as exc:
        narration_partial.unlink(missing_ok=True)
        vtt_partial.unlink(missing_ok=True)
        raise RuntimeError(f"Edge TTS 产物校验失败：{exc}") from exc
    narration_partial.replace(narration_path)
    vtt_partial.replace(vtt_path)


def _run_windows_sapi_tts(
    *,
    script_path: Path,
    wav_path: Path,
    output_path: Path,
    rate: str,
    settings: Settings,
    cancel_requested: Callable[[], bool] | None,
    progress_callback: Callable[[str, int, str], None] | None,
) -> None:
    wav_path.unlink(missing_ok=True)
    output_path.unlink(missing_ok=True)
    output_partial = output_path.with_name(
        f".{output_path.stem}.partial{output_path.suffix}"
    )
    output_partial.unlink(missing_ok=True)
    try:
        percent = int(rate.removesuffix("%").replace("+", "") or 0)
    except ValueError:
        percent = 0
    sapi_rate = max(-10, min(10, round(percent / 5)))
    escaped_script_path = str(script_path).replace("'", "''")
    escaped_path = str(wav_path).replace("'", "''")
    powershell = (
        "$ErrorActionPreference = 'Stop'; $s = $null; $stream = $null; "
        "try { $s = New-Object -ComObject SAPI.SpVoice; "
        "$tokens = $s.GetVoices(); $selected = $null; "
        "for ($i = 0; $i -lt $tokens.Count; $i++) { "
        "$candidate = $tokens.Item($i); "
        "$language = ''; try { $language = $candidate.GetAttribute('Language') } catch {}; "
        "if ($language -match '(^|;)804(;|$)' -or "
        "$candidate.GetDescription() -match 'Chinese|Huihui|中文') { "
        "$selected = $candidate; break } }; "
        "if (-not $selected) { throw 'No local Chinese SAPI voice.' }; "
        "$s.Voice = $selected; "
        f"$s.Rate = {sapi_rate}; "
        "$stream = New-Object -ComObject SAPI.SpFileStream; "
        f"$stream.Open('{escaped_path}', 3, $false); "
        "$s.AudioOutputStream = $stream; "
        f"$text = [IO.File]::ReadAllText('{escaped_script_path}', "
        "[Text.Encoding]::UTF8); "
        "[void]$s.Speak($text); $stream.Close(); $stream = $null; "
        f"if ((Get-Item -LiteralPath '{escaped_path}').Length -le 46) {{ "
        "throw 'SAPI produced an empty WAV.' }; exit 0 "
        "} catch { Write-Error $_; exit 1 } finally { "
        "if ($stream) { try { $stream.Close() } catch {} }; "
        "if ($stream) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($stream) }; "
        "if ($s) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($s) } }"
    )
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        powershell,
    ]
    script_char_count = len(
        script_path.read_text(encoding="utf-8-sig", errors="replace")
    )
    try:
        return_code, stdout, stderr = _run_cancellable_process(
            command,
            cancel_requested=cancel_requested,
            cancel_message="本地旁白生成已由用户取消。",
            timeout_seconds=max(180, min(3600, 180 + script_char_count / 2)),
            timeout_message="Windows 本地旁白生成超时。",
            heartbeat_callback=lambda elapsed: _progress(
                progress_callback,
                "旁白回退",
                22,
                f"本地旁白仍在生成，已运行 {elapsed} 秒；可随时取消。",
            ),
        )
    except (JobCancelledError, RuntimeError):
        wav_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        raise
    if return_code != 0 or not _nonempty(wav_path):
        wav_path.unlink(missing_ok=True)
        raise RuntimeError(
            "Windows 本地中文语音生成失败："
            + (stderr or stdout)[-1600:]
        )
    convert = [
        settings.video_ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(wav_path),
        "-codec:a",
        "libmp3lame",
        "-b:a",
        "128k",
        str(output_partial),
    ]
    try:
        convert_return_code, stdout, stderr = _run_cancellable_process(
            convert,
            cancel_requested=cancel_requested,
            cancel_message="本地旁白转换已由用户取消。",
            timeout_seconds=1800,
            timeout_message="本地旁白转 MP3 超时。",
            heartbeat_callback=lambda elapsed: _progress(
                progress_callback,
                "旁白转换",
                24,
                f"旁白格式转换仍在进行，已运行 {elapsed} 秒；可随时取消。",
            ),
        )
    except (JobCancelledError, RuntimeError):
        wav_path.unlink(missing_ok=True)
        output_partial.unlink(missing_ok=True)
        raise
    wav_path.unlink(missing_ok=True)
    if convert_return_code != 0 or not _nonempty(output_partial):
        output_partial.unlink(missing_ok=True)
        raise RuntimeError(
            f"本地旁白转换失败：{(stderr or stdout)[-1600:]}"
        )
    try:
        media = probe_media(output_partial, settings.ffprobe_path)
        audio_streams = [
            item
            for item in media.get("streams") or []
            if item.get("codec_type") == "audio"
        ]
        duration = float(
            (media.get("format") or {}).get("duration") or 0
        )
        if not audio_streams or duration <= 0.1:
            raise RuntimeError("本地旁白没有有效音频流。")
    except Exception as exc:
        output_partial.unlink(missing_ok=True)
        raise RuntimeError(f"本地旁白校验失败：{exc}") from exc
    output_partial.replace(output_path)


def _render_storyboard(
    storyboard: dict[str, Any],
    *,
    narration_path: Path,
    subtitle_path: Path,
    output_path: Path,
    profile: RenderProfile,
    cancel_requested: Callable[[], bool] | None,
    progress_callback: Callable[[str, int, str], None] | None,
    settings: Settings,
) -> Path:
    scenes = list(storyboard.get("scenes") or [])
    if not scenes:
        raise ValueError("分镜清单为空。")
    runtime = inspect_ffmpeg_runtime(
        settings.video_ffmpeg_path,
        validate_nvenc=True,
    )
    if not runtime["available"]:
        raise RuntimeError("视频生产 FFmpeg 不可用。")
    use_nvenc = bool(runtime["nvenc_validated"])
    partial = output_path.with_name(
        f".{output_path.stem}.partial{output_path.suffix}"
    )
    partial.unlink(missing_ok=True)
    command = [
        settings.video_ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-progress",
        "pipe:1",
        "-nostats",
    ]
    visual_filters: list[str] = []
    labels: list[str] = []
    for index, scene in enumerate(scenes):
        duration = max(0.2, float(scene["duration_seconds"]))
        path_value = (scene.get("visual") or {}).get("path")
        if path_value and Path(path_value).is_file():
            # 不在输入侧使用 -t 截断：图片输入按 floor(duration*fps) 产帧会逐镜头
            # 累积缩短视频流，配合 -shortest 会切掉旁白尾部。交给滤镜中的
            # trim=duration（向上含帧）控制镜头长度，保证视频流不短于旁白。
            command.extend(
                [
                    "-loop",
                    "1",
                    "-framerate",
                    str(profile.fps),
                    "-i",
                    str(Path(path_value)),
                ]
            )
            visual_filters.append(
                f"[{index}:v]split=2[bgsrc{index}][fgsrc{index}];"
                f"[bgsrc{index}]scale={profile.width}:{profile.height}:"
                "force_original_aspect_ratio=increase,"
                f"crop={profile.width}:{profile.height},"
                "boxblur=luma_radius=24:luma_power=1"
                f"[bg{index}];"
                f"[fgsrc{index}]scale={profile.width}:{profile.height}:"
                "force_original_aspect_ratio=decrease,setsar=1"
                f"[fg{index}];"
                f"[bg{index}][fg{index}]overlay=(W-w)/2:(H-h)/2:"
                f"shortest=1,fps={profile.fps},setsar=1,"
                f"trim=duration={duration:.3f},setpts=PTS-STARTPTS"
                f"[v{index}]"
            )
        else:
            command.extend(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    (
                        f"color=c=0x071419:s={profile.width}x"
                        f"{profile.height}:r={profile.fps}"
                    ),
                ]
            )
            visual_filters.append(
                f"[{index}:v]setsar=1,trim=duration={duration:.3f},"
                f"setpts=PTS-STARTPTS[v{index}]"
            )
        labels.append(f"[v{index}]")
    audio_index = len(scenes)
    command.extend(["-i", str(narration_path)])
    # concat 后用 tpad 克隆最后一帧做无限延长：逐镜头按帧取整会让视频流系统性
    # 短于旁白，-shortest 会把旁白尾部和末尾字幕切掉（QA 会拦截）。
    # 延长视频流后由 -shortest 精确裁到旁白结束，保证成片覆盖完整旁白。
    concat = "".join(labels) + (
        f"concat=n={len(labels)}:v=1:a=0,"
        "tpad=stop_mode=clone:stop=-1[base]"
    )
    # ASS file already carries canvas resolution, style and safe margins.
    subtitle_filter = (
        f"[base]subtitles=filename='{_subtitle_filter_path(subtitle_path)}'[video]"
    )
    command.extend(
        [
            "-filter_complex",
            ";".join([*visual_filters, concat, subtitle_filter]),
            "-map",
            "[video]",
            "-map",
            f"{audio_index}:a:0",
        ]
    )
    if use_nvenc:
        command.extend(
            ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "20", "-b:v", "0"]
        )
    else:
        command.extend(
            ["-c:v", "libx264", "-preset", "medium", "-crf", "19"]
        )
    command.extend(
        [
            "-pix_fmt",
            "yuv420p",
            "-af",
            f"loudnorm=I={profile.audio_loudness_lufs}:LRA=11:TP=-1.5",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(partial),
        ]
    )

    def render_progress(percent: int, message: str) -> None:
        _progress(
            progress_callback,
            "GPU 合成",
            50 + round(max(0, min(100, percent)) * 0.38),
            message,
        )

    manager = get_resource_manager(settings)
    resource = (
        ResourceKind.GPU_INFERENCE
        if use_nvenc
        else ResourceKind.CPU_HEAVY
    )
    attempts: list[dict[str, Any]] = []
    try:
        with manager.lease(
            resource,
            owner=f"script-video-render:{output_path.name}",
            family="ffmpeg-nvenc" if use_nvenc else None,
            cancel_requested=cancel_requested,
        ):
            return_code, stderr = _run_ffmpeg_cancellable(
                command,
                duration_seconds=float(
                    storyboard["output_duration_seconds"]
                ),
                cancel_requested=cancel_requested,
                progress_callback=render_progress,
            )
            attempts.append(
                {
                    "encoder": "h264_nvenc" if use_nvenc else "libx264",
                    "return_code": return_code,
                    "stderr_tail": stderr[-2500:],
                }
            )
    except JobCancelledError:
        partial.unlink(missing_ok=True)
        raise
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    final_command = command
    encoder = "h264_nvenc" if use_nvenc else "libx264"
    if return_code != 0 and use_nvenc:
        partial.unlink(missing_ok=True)
        _progress(
            progress_callback,
            "CPU 合成回退",
            52,
            "GPU 编码未完成，正在自动切换 CPU 编码重试。",
        )
        cpu_command = list(command)
        codec_index = cpu_command.index("-c:v")
        pixel_format_index = cpu_command.index("-pix_fmt", codec_index)
        cpu_command[codec_index:pixel_format_index] = [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "19",
        ]
        try:
            with manager.lease(
                ResourceKind.CPU_HEAVY,
                owner=f"script-video-render-cpu:{output_path.name}",
                cancel_requested=cancel_requested,
            ):
                return_code, stderr = _run_ffmpeg_cancellable(
                    cpu_command,
                    duration_seconds=float(
                        storyboard["output_duration_seconds"]
                    ),
                    cancel_requested=cancel_requested,
                    progress_callback=render_progress,
                )
                attempts.append(
                    {
                        "encoder": "libx264",
                        "return_code": return_code,
                        "stderr_tail": stderr[-2500:],
                    }
                )
        except JobCancelledError:
            partial.unlink(missing_ok=True)
            raise
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        final_command = cpu_command
        encoder = "libx264"
    record = {
        "schema_version": SCRIPT_VIDEO_SCHEMA_VERSION,
        "storyboard_strategy": storyboard.get("strategy"),
        "output_path": str(output_path),
        "encoder": encoder,
        "scene_count": len(scenes),
        "duration_seconds": storyboard["output_duration_seconds"],
        "command": final_command,
        "return_code": return_code,
        "attempts": attempts,
    }
    atomic_write_json(
        output_path.with_suffix(output_path.suffix + ".render.json"),
        record,
    )
    if return_code != 0:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"FFmpeg 文稿成片失败：{stderr[-2500:]}")
    partial.replace(output_path)
    return output_path


def _valid_tts_cache(
    record: dict[str, Any],
    *,
    signature: str,
    narration_path: Path,
    vtt_path: Path,
    ffprobe_path: str,
) -> bool:
    if record.get("signature") != signature:
        return False
    if not all(
        record.get(key) not in (None, "")
        for key in (
            "audio_sha256",
            "vtt_sha256",
            "audio_duration_seconds",
            "cue_count",
        )
    ):
        return False
    if not _nonempty(narration_path) or not _nonempty(vtt_path):
        return False
    try:
        duration = _media_duration(narration_path, ffprobe_path)
        cues = parse_vtt(vtt_path)
    except (OSError, RuntimeError, ValueError):
        return False
    if not cues or float(cues[-1].get("end") or 0) > duration + 2.0:
        return False
    if not all(
        float(current.get("end") or 0)
        <= float(following.get("start") or 0) + 0.001
        for current, following in zip(cues, cues[1:])
    ):
        return False
    expected_audio_hash = str(record["audio_sha256"])
    expected_vtt_hash = str(record["vtt_sha256"])
    if _sha256_file(narration_path) != expected_audio_hash:
        return False
    if _sha256_file(vtt_path) != expected_vtt_hash:
        return False
    if int(record["cue_count"]) != len(cues):
        return False
    if abs(float(record["audio_duration_seconds"]) - duration) > 0.05:
        return False
    return True


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_script(script: str) -> str:
    clean = script.strip()
    if len(clean) < 20:
        raise ValueError("文稿至少需要 20 个字符。")
    if len(clean) > 20_000:
        raise ValueError("粗闭环第一版单次最多处理 20000 个字符。")
    question_ratio = clean.count("?") / max(1, len(clean))
    if question_ratio > 0.5:
        raise ValueError("文稿疑似发生字符编码损坏，请使用 UTF-8 重新输入。")
    return clean


def _media_duration(path: Path, ffprobe_path: str) -> float:
    payload = probe_media(path, ffprobe_path)
    try:
        duration = float(
            (payload.get("format") or {}).get("duration") or 0
        )
    except (TypeError, ValueError):
        duration = 0
    if duration <= 0:
        raise RuntimeError("无法读取旁白时长。")
    return duration


def _nonempty(path: Path) -> bool:
    return Path(path).is_file() and Path(path).stat().st_size > 0


def _progress(
    callback: Callable[[str, int, str], None] | None,
    stage: str,
    percent: int,
    message: str,
) -> None:
    if callback is not None:
        callback(stage, percent, message)
