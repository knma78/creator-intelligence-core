from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import mimetypes
import os
import re
import socket
import threading
import time
import traceback
import webbrowser
from dataclasses import replace
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from config import SETTINGS, Settings, setup_logging
from downloader.bilibili import is_bilibili_url
from downloader.bilibili_entitlement import BilibiliEntitlementService
from downloader.bilibili_collection import is_bilibili_collection_url
from downloader.bilibili_up import is_bilibili_up_source
from downloader.douyin_adapter import get_douyin_status, start_douyin_login
from downloader.platform_auth import (
    ensure_platform_authorized,
    get_platform_auth_status,
    import_platform_cookies,
    start_platform_login,
)
from downloader.social import detect_social_platform, is_douyin_profile_url
from downloader.youtube import is_youtube_channel_url, is_youtube_url
from analyzer.visual_semantics import get_openclip_runtime_status
from features.api import (
    build_auto_edit_plan,
    get_english_review_runtime_status,
    get_native_english_review_skill_status,
    get_novel_writing_skill_status,
    inspect_ffmpeg_runtime,
    list_production_sources,
    preview_script_video_plan,
    production_profile,
    script_video_runtime_status,
    VideoFactoryAdapter,
)
from features.bootstrap import register_feature_job_modes
from features.contracts import FeatureJobServices
from pipeline.batch import run_up_pipeline
from pipeline.content import run_content_pipeline
from pipeline.run import run_video_pipeline_details
from processor.whisper import get_whisper_runtime_status
from processor.system_audio import get_system_audio_status
from rag.knowledge_base import build_knowledge_base, search_knowledge_base
from rag.report import generate_research_report
from rag.vector_store import vector_backend_status
from exporter.up_advisor import advise_next_up_targets, build_up_advisor_report
from intelligence.creator_discovery.api import (
    add_candidate,
    approve_candidate,
    discover_creator,
    finish_analysis,
    start_analysis,
)
from intelligence.gap_analysis.api import get_dashboard as get_gap_dashboard
from intelligence.gap_analysis.api import run_gap_analysis
from infrastructure.cancellation import (
    JobCancelledError,
    raise_if_cancelled,
)
from infrastructure.jobs import (
    JobQueueFullError,
    JobStore,
    LocalJobRunner,
)
from infrastructure.progress import BatchProgressMessage
from infrastructure.analytics_store import get_analytics_summary
from infrastructure.resources import get_resource_manager
from infrastructure.creator_progress import (
    CreatorProgressStore,
    migrate_legacy_creator_outputs,
)
from webapp.job_registry import JobModeRegistry
from webapp.data_management import guarded_job, handle_data_request, register_data_jobs
from webapp.knowledge_reviews import (
    knowledge_rules as _knowledge_rules,
    record_rule_review as _record_rule_review,
)

logger = logging.getLogger(__name__)

WEB_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = WEB_ROOT / "static"
APP_VERSION = "2026.08.20-script-video-loop.2"
JOB_SCHEMA_VERSION = "1.3"
SCRIPT_VIDEO_VOICES = {
    "zh-CN-XiaoxiaoNeural",
    "zh-CN-YunxiNeural",
    "zh-CN-YunjianNeural",
}
SCRIPT_VIDEO_RATES = {"+0%", "+5%", "+10%"}
SCRIPT_VIDEO_FPS = {24, 25, 30, 50, 60}


class AppState:
    def __init__(
        self,
        settings: Settings,
        *,
        start_workers: bool = False,
    ) -> None:
        self.settings = settings
        migrated_creator_videos = migrate_legacy_creator_outputs(
            settings.output_dir,
            CreatorProgressStore(settings.creator_progress_database_path),
        )
        if migrated_creator_videos:
            logger.info(
                "Migrated %s legacy creator-video progress records to durable state.",
                migrated_creator_videos,
            )
        self.jobs = JobStore(
            settings.job_database_path,
            schema_version=JOB_SCHEMA_VERSION,
            history_limit=settings.job_history_limit,
            log_limit=settings.job_log_limit,
            queue_capacity=settings.job_queue_capacity,
        )
        self.runner = LocalJobRunner(
            self.jobs,
            lambda job_id: _run_job(self, job_id),
            worker_count=settings.job_worker_count,
        )
        self.recovered_job_ids = (
            self.runner.start(recover=True)
            if start_workers
            else []
        )
        self._capture_stop_lock = threading.Lock()
        self._capture_stop_events: dict[str, threading.Event] = {}

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        job = self.jobs.create(payload)
        self.runner.notify()
        return job

    def close(self) -> None:
        self.runner.shutdown(wait=False)

    def capture_stop_requested(self, job_id: str) -> bool:
        with self._capture_stop_lock:
            event = self._capture_stop_events.setdefault(
                job_id,
                threading.Event(),
            )
            return event.is_set()

    def request_capture_stop(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.get("status") != "running":
            return False
        detail = job.get("progress_detail") or {}
        if detail.get("type") != "playback_capture":
            return False
        with self._capture_stop_lock:
            self._capture_stop_events.setdefault(
                job_id,
                threading.Event(),
            ).set()
        return True

    def clear_capture_stop(self, job_id: str) -> None:
        with self._capture_stop_lock:
            self._capture_stop_events.pop(job_id, None)

    def request_cancel(self, job_id: str) -> dict[str, Any] | None:
        job = self.jobs.request_cancel(job_id)
        if job and job.get("cancel_requested"):
            with self._capture_stop_lock:
                self._capture_stop_events.setdefault(
                    job_id,
                    threading.Event(),
                ).set()
        return job


def _update_job_progress(
    state: AppState,
    job_id: str,
    stage: str,
    progress: int,
    message: str,
) -> None:
    raise_if_cancelled(
        lambda: state.jobs.is_cancel_requested(job_id)
    )
    updates: dict[str, Any] = {
        "stage": stage,
        "progress": progress,
    }
    detail = getattr(message, "progress_meta", None)
    if isinstance(detail, dict):
        updates["progress_detail"] = dict(detail)
        if not detail.get("heartbeat"):
            updates["log"] = str(message)
    elif "Whisper" in stage:
        updates["progress_detail"] = {
            "type": "whisper",
            "state": "preparing",
            "phase_percent": None,
            "processed_seconds": None,
            "duration_seconds": None,
            "elapsed_seconds": None,
            "heartbeat": False,
        }
        updates["log"] = str(message)
    else:
        updates["progress_detail"] = None
        updates["log"] = str(message)
    state.jobs.update(job_id, **updates)


def _file_item(label: str, path: Path) -> dict[str, str]:
    path = path.resolve()
    return {
        "label": label,
        "path": str(path),
        "url": f"/api/file?path={quote(str(path))}",
    }


def create_handler(state: AppState):
    class Handler(SimpleHTTPRequestHandler):
        server_version = "ContentResearchWeb/1.0"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if handle_data_request(self, state, parsed, "GET"):
                return
            if parsed.path == "/":
                self._serve_static_file(STATIC_ROOT / "index.html")
                return
            if parsed.path == "/api/health":
                self._send_json(
                    {
                        "ok": True,
                        "version": APP_VERSION,
                        "api_schema_version": JOB_SCHEMA_VERSION,
                        "features": {
                            "up_advisor": True,
                            "gap_analysis": True,
                            "creator_discovery": True,
                            "advanced_knowledge": True,
                            "youtube": True,
                            "douyin": True,
                            "xiaohongshu": True,
                            "bilibili_content_works": True,
                            "bilibili_collections": True,
                            "v3_nlp": True,
                            "scene_detection": True,
                            "persistent_jobs": True,
                            "job_cancellation": True,
                            "structured_analytics": True,
                            "acquisition_contract": True,
                            "resource_scheduler": True,
                            "bilibili_entitlement": True,
                            "playback_capture": True,
                            "video_production": True,
                            "video_production_cancellation": True,
                            "automatic_edit_plan": True,
                            "script_video_production": True,
                            "novel_writing": True,
                            "native_english_review": True,
                        },
                        "job_queue": {
                            "storage": "sqlite",
                            "database_path": str(
                                state.settings.job_database_path
                            ),
                            "worker_count": state.settings.job_worker_count,
                            "capacity": state.settings.job_queue_capacity,
                            "status_counts": state.jobs.status_counts(),
                            "recovered_on_start": len(
                                state.recovered_job_ids
                            ),
                        },
                        "resources": get_resource_manager(
                            state.settings
                        ).snapshot(),
                        "platforms": {
                            "bilibili": {
                                "single_video": True,
                                "creator_batch": True,
                                "content_work_batch": True,
                                "collection_pages": True,
                                "cookie_configured": get_platform_auth_status(
                                    "bilibili",
                                    state.settings,
                                )["ready"],
                            },
                            "youtube": {
                                "single_video": True,
                                "creator_batch": True,
                                "cookie_configured": get_platform_auth_status(
                                    "youtube",
                                    state.settings,
                                )["ready"],
                            },
                            "douyin": {
                                "single_video": True,
                                "creator_batch": True,
                                "cookie_configured": get_douyin_status(
                                    state.settings
                                )["ready"],
                            },
                            "xiaohongshu": {
                                "single_video": True,
                                "creator_batch": False,
                                "cookie_configured": bool(
                                    state.settings.xiaohongshu_cookie_file
                                    or state.settings.xiaohongshu_cookies_from_browser
                                    or state.settings.yt_dlp_cookie_file
                                    or state.settings.yt_dlp_cookies_from_browser
                                ),
                            },
                        },
                        "llm": {
                            "configured": bool(state.settings.llm_api_key),
                            "model": state.settings.llm_model,
                        },
                        "whisper": get_whisper_runtime_status(state.settings),
                        "openclip": get_openclip_runtime_status(
                            state.settings
                        ),
                        "playback_capture": get_system_audio_status(
                            state.settings
                        ),
                        "local_skills": {
                            "novel-writing": get_novel_writing_skill_status(
                                state.settings.novel_writing_skill_path
                            ),
                            "native-english-fiction-review": (
                                get_native_english_review_skill_status(
                                    state.settings.native_english_review_skill_path
                                )
                            ),
                        },
                        "english_review": get_english_review_runtime_status(
                            state.settings
                        ),
                        "script_video": script_video_runtime_status(
                            state.settings
                        ),
                    }
                )
                return
            if parsed.path == "/api/skills":
                self._send_json(
                    {
                        "skills": {
                            "novel-writing": get_novel_writing_skill_status(
                                state.settings.novel_writing_skill_path
                            ),
                            "native-english-fiction-review": (
                                get_native_english_review_skill_status(
                                    state.settings.native_english_review_skill_path
                                )
                            ),
                        }
                    }
                )
                return
            if parsed.path == "/api/douyin/status":
                self._send_json(get_douyin_status(state.settings))
                return
            if parsed.path == "/api/platform-auth/status":
                params = parse_qs(parsed.query)
                platform = str(params.get("platform", [""])[0]).strip().lower()
                try:
                    if platform:
                        self._send_json(
                            get_platform_auth_status(platform, state.settings)
                        )
                    else:
                        self._send_json(
                            {
                                "platforms": {
                                    key: get_platform_auth_status(
                                        key,
                                        state.settings,
                                    )
                                    for key in ("bilibili", "youtube")
                                }
                            }
                        )
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            if parsed.path.startswith("/static/"):
                relative = parsed.path.removeprefix("/static/").lstrip("/")
                self._serve_static_file((STATIC_ROOT / relative).resolve())
                return
            if parsed.path == "/api/jobs":
                self._send_json({"jobs": state.jobs.list()})
                return
            if parsed.path == "/api/production/sources":
                self._send_json(
                    {
                        "sources": list_production_sources(
                            state.settings
                        )
                    }
                )
                return
            if parsed.path == "/api/production/runtime":
                self._send_json(
                    {
                        "ffmpeg": inspect_ffmpeg_runtime(
                            state.settings.video_ffmpeg_path,
                            validate_nvenc=True,
                        ),
                        "ffprobe_path": state.settings.ffprobe_path,
                        "production_directory": str(
                            state.settings.video_production_dir
                        ),
                        "video_factory": VideoFactoryAdapter(
                            settings=state.settings
                        ).inspect(),
                        "script_video": script_video_runtime_status(
                            state.settings
                        ),
                    }
                )
                return
            if parsed.path == "/api/knowledge/status":
                self._send_json(_knowledge_status(state.settings))
                return
            if parsed.path == "/api/knowledge/rules":
                try:
                    self._send_json(_knowledge_rules(state.settings))
                except Exception as exc:
                    logger.exception("Loading creator knowledge rules failed")
                    self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if parsed.path == "/api/analytics/summary":
                self._send_json(
                    get_analytics_summary(state.settings)
                )
                return
            if parsed.path == "/api/creator-discovery":
                params = parse_qs(parsed.query)
                ability = str(params.get("ability", [""])[0]).strip() or None
                try:
                    self._send_json(discover_creator(ability=ability, settings=state.settings, save=False))
                except Exception as exc:
                    logger.exception("Creator discovery failed")
                    self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if parsed.path == "/api/gap-analysis":
                try:
                    self._send_json(run_gap_analysis(state.settings, save=True))
                except Exception as exc:
                    logger.exception("Gap analysis failed")
                    self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if parsed.path == "/api/gap-analysis/dashboard":
                try:
                    self._send_json(get_gap_dashboard(state.settings))
                except Exception as exc:
                    logger.exception("Gap dashboard failed")
                    self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if parsed.path.startswith("/api/jobs/"):
                if parsed.path.endswith("/events"):
                    job_id = parsed.path.removesuffix("/events").rsplit("/", 1)[-1]
                    job = state.jobs.get(job_id)
                    if not job:
                        self._send_json(
                            {"error": "job not found"},
                            HTTPStatus.NOT_FOUND,
                        )
                        return
                    self._send_json(
                        {
                            "job_id": job_id,
                            "events": state.jobs.events(job_id),
                        }
                    )
                    return
                job_id = parsed.path.rsplit("/", 1)[-1]
                job = state.jobs.get(job_id)
                if not job:
                    self._send_json({"error": "job not found"}, HTTPStatus.NOT_FOUND)
                    return
                self._send_json(job)
                return
            if parsed.path == "/api/file":
                self._serve_output_file(parsed.query)
                return
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if handle_data_request(self, state, parsed, "POST"):
                return
            if parsed.path == "/api/knowledge/rules/review":
                payload = self._read_json_object()
                if payload is None:
                    return
                try:
                    result = _record_rule_review(payload, state.settings)
                    self._send_json(result, HTTPStatus.OK)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                except Exception as exc:
                    logger.exception("Saving creator knowledge rule review failed")
                    self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if (
                parsed.path.startswith("/api/jobs/")
                and parsed.path.endswith("/cancel")
            ):
                job_id = parsed.path.removesuffix(
                    "/cancel"
                ).rsplit("/", 1)[-1]
                before = state.jobs.get(job_id)
                if before is None:
                    self._send_json(
                        {"error": "job not found"},
                        HTTPStatus.NOT_FOUND,
                    )
                    return
                if before.get("status") in {
                    "done",
                    "failed",
                    "cancelled",
                }:
                    self._send_json(
                        {
                            "error": "任务已经结束，无法取消。",
                            "job": before,
                        },
                        HTTPStatus.CONFLICT,
                    )
                    return
                job = state.request_cancel(job_id)
                self._send_json(
                    job or {"error": "job not found"},
                    (
                        HTTPStatus.ACCEPTED
                        if job
                        else HTTPStatus.NOT_FOUND
                    ),
                )
                return
            if (
                parsed.path.startswith("/api/jobs/")
                and parsed.path.endswith("/stop-capture")
            ):
                job_id = parsed.path.removesuffix(
                    "/stop-capture"
                ).rsplit("/", 1)[-1]
                if not state.request_capture_stop(job_id):
                    self._send_json(
                        {"error": "当前任务不在播放采集阶段。"},
                        HTTPStatus.CONFLICT,
                    )
                    return
                state.jobs.update(
                    job_id,
                    log="已请求停止录制；现有音频将继续进入 Whisper。",
                )
                self._send_json(
                    {"ok": True, "job_id": job_id},
                    HTTPStatus.ACCEPTED,
                )
                return
            if parsed.path == "/api/bilibili/entitlement":
                try:
                    payload = self._read_json()
                    source = str(payload.get("source") or "").strip()
                    if not source or not is_bilibili_url(source):
                        raise ValueError("请输入可识别的B站视频或内容季链接。")
                    with get_resource_manager(state.settings).lease(
                        "network_io",
                        owner="web:bilibili_entitlement",
                    ):
                        entitlement = BilibiliEntitlementService(
                            state.settings
                        ).assess(source, probe_media=True)
                    self._send_json(entitlement.to_dict())
                except ValueError as exc:
                    self._send_json(
                        {"error": str(exc)},
                        HTTPStatus.BAD_REQUEST,
                    )
                except Exception as exc:
                    logger.exception("Bilibili entitlement check failed")
                    self._send_json(
                        {"error": str(exc)},
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                return
            if parsed.path == "/api/douyin/login":
                try:
                    self._send_json(
                        start_douyin_login(state.settings),
                        HTTPStatus.ACCEPTED,
                    )
                except Exception as exc:
                    logger.exception("Failed to start Douyin login")
                    self._send_json(
                        {"error": str(exc)},
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                return
            if parsed.path == "/api/platform-auth/import":
                try:
                    payload = self._read_json(max_bytes=4 * 1024 * 1024)
                    platform = str(payload.get("platform") or "").strip().lower()
                    content = payload.get("content")
                    if not isinstance(content, str):
                        raise ValueError("Cookie 文件内容无效。")
                    self._send_json(
                        import_platform_cookies(
                            platform,
                            content,
                            state.settings,
                        )
                    )
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                except Exception as exc:
                    logger.exception("Failed to import platform cookies")
                    self._send_json(
                        {"error": str(exc)},
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                return
            if parsed.path == "/api/platform-auth/login":
                try:
                    payload = self._read_json()
                    platform = str(payload.get("platform") or "").strip().lower()
                    self._send_json(
                        start_platform_login(platform, state.settings),
                        HTTPStatus.ACCEPTED,
                    )
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                except Exception as exc:
                    logger.exception("Failed to start platform login")
                    self._send_json(
                        {"error": str(exc)},
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                return
            if parsed.path == "/api/jobs":
                payload = self._read_json()
                try:
                    job = state.submit(payload)
                except JobQueueFullError as exc:
                    self._send_json(
                        {"error": str(exc)},
                        HTTPStatus.TOO_MANY_REQUESTS,
                    )
                    return
                self._send_json(job, HTTPStatus.CREATED)
                return
            if parsed.path == "/api/production/plan":
                payload = self._read_json()
                video_id = str(payload.get("video_id") or "").strip()
                if not video_id:
                    self._send_json(
                        {"error": "video_id is required"},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return
                try:
                    plan_path = build_auto_edit_plan(
                        video_id,
                        target_seconds=float(
                            payload.get("target_seconds") or 60
                        ),
                        platform=str(
                            payload.get("platform") or "douyin"
                        ),
                        settings=state.settings,
                    )
                    plan = json.loads(
                        plan_path.read_text(encoding="utf-8-sig")
                    )
                    self._send_json(
                        {
                            "plan": plan,
                            "file": _file_item(
                                "自动剪辑计划 edit_plan.json",
                                plan_path,
                            ),
                        }
                    )
                except (ValueError, FileNotFoundError) as exc:
                    self._send_json(
                        {"error": str(exc)},
                        HTTPStatus.BAD_REQUEST,
                    )
                except Exception as exc:
                    logger.exception("Automatic edit planning failed")
                    self._send_json(
                        {"error": str(exc)},
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                return
            if parsed.path == "/api/production/script-plan":
                payload = self._read_json_object(max_bytes=512 * 1024)
                if payload is None:
                    return
                script = str(payload.get("script") or "").strip()
                title = str(payload.get("title") or "").strip()
                try:
                    plan = preview_script_video_plan(script, title=title, settings=state.settings)
                    self._send_json(
                        {
                            "plan": plan,
                            "capability_plan": plan.get("capability_plan"),
                        }
                    )
                except ValueError as exc:
                    self._send_json(
                        {"error": str(exc)},
                        HTTPStatus.BAD_REQUEST,
                    )
                except Exception as exc:
                    logger.exception("Script-video planning failed")
                    self._send_json(
                        {"error": str(exc)},
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                return
            if parsed.path == "/api/production/render":
                payload = self._read_json()
                video_id = str(payload.get("video_id") or "").strip()
                if not video_id:
                    self._send_json(
                        {"error": "video_id is required"},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return
                runtime = script_video_runtime_status(state.settings)
                if not (
                    runtime.get("capcut", {}).get("available")
                    and runtime.get("ffmpeg", {}).get("available")
                    and runtime.get("ffprobe", {}).get("available")
                ):
                    self._send_json(
                        {
                            "error": "CapCut 草稿运行时或 FFmpeg 质检环境不可用；请检查运行状态，并在生成前正常关闭 CapCut。",
                            "runtime": runtime,
                        },
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                    return
                job_payload = {
                    "source": video_id,
                    "mode": "video_production",
                    "video_id": video_id,
                    "target_seconds": payload.get(
                        "target_seconds",
                        60,
                    ),
                    "platform": payload.get("platform", "douyin"),
                    "fps": payload.get("fps", 30),
                    "burn_subtitles": bool(
                        payload.get("burn_subtitles", True)
                    ),
                }
                try:
                    job = state.submit(job_payload)
                except JobQueueFullError as exc:
                    self._send_json(
                        {"error": str(exc)},
                        HTTPStatus.TOO_MANY_REQUESTS,
                    )
                    return
                self._send_json(job, HTTPStatus.CREATED)
                return
            if parsed.path == "/api/production/script-render":
                payload = self._read_json_object(max_bytes=512 * 1024)
                if payload is None:
                    return
                script = str(payload.get("script") or "").strip()
                if len(script) < 20:
                    self._send_json(
                        {"error": "文稿至少需要 20 个字符。"},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return
                if len(script) > 20_000:
                    self._send_json(
                        {"error": "粗闭环第一版单次最多处理 20000 个字符。"},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return
                runtime = script_video_runtime_status(state.settings)
                if not runtime.get("available"):
                    self._send_json(
                        {
                            "error": "文稿视频工厂运行时不可用，请检查旁白、FFmpeg、FFprobe 与 CapCut；生成草稿前需要先正常关闭 CapCut。",
                            "runtime": runtime,
                        },
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                    return
                try:
                    platform = str(
                        payload.get("platform") or "douyin"
                    ).strip().lower()
                    fps = int(payload.get("fps") or 30)
                    voice = str(
                        payload.get("voice")
                        or "zh-CN-XiaoxiaoNeural"
                    ).strip()
                    tts_rate = str(
                        payload.get("tts_rate") or "+5%"
                    ).strip()
                    production_profile(platform, fps)
                    if fps not in SCRIPT_VIDEO_FPS:
                        raise ValueError("帧率只支持 24、25、30、50 或 60 FPS。")
                    if voice not in SCRIPT_VIDEO_VOICES:
                        raise ValueError("不支持所选中文旁白。")
                    if tts_rate not in SCRIPT_VIDEO_RATES:
                        raise ValueError("不支持所选语速。")
                except (TypeError, ValueError) as exc:
                    self._send_json(
                        {"error": str(exc)},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return
                job_payload = {
                    "source": str(payload.get("title") or "文稿自动成片"),
                    "mode": "script_video",
                    "script": script,
                    "title": str(payload.get("title") or "").strip()[:200],
                    "platform": platform,
                    "fps": fps,
                    "voice": voice,
                    "tts_rate": tts_rate,
                }
                try:
                    job = state.submit(job_payload)
                except JobQueueFullError as exc:
                    self._send_json(
                        {"error": str(exc)},
                        HTTPStatus.TOO_MANY_REQUESTS,
                    )
                    return
                self._send_json(job, HTTPStatus.CREATED)
                return
            if parsed.path == "/api/search":
                payload = self._read_json()
                query = str(payload.get("query") or "").strip()
                top_k = int(payload.get("top_k") or 5)
                if not query:
                    self._send_json({"error": "query is required"}, HTTPStatus.BAD_REQUEST)
                    return
                try:
                    results = search_knowledge_base(query, top_k=top_k, settings=state.settings)
                    self._send_json({"results": results, "backend": state.settings.rag_search_backend})
                except FileNotFoundError:
                    self._send_json({"error": "知识库不存在，请先构建知识库。"}, HTTPStatus.NOT_FOUND)
                return
            if parsed.path == "/api/kb/build":
                try:
                    job = state.submit({"source": "", "mode": "build_kb"})
                except JobQueueFullError as exc:
                    self._send_json(
                        {"error": str(exc)},
                        HTTPStatus.TOO_MANY_REQUESTS,
                    )
                    return
                self._send_json(job, HTTPStatus.CREATED)
                return
            if parsed.path == "/api/kb/advanced":
                try:
                    job = state.submit(
                        {"source": "", "mode": "advanced_kb"}
                    )
                except JobQueueFullError as exc:
                    self._send_json(
                        {"error": str(exc)},
                        HTTPStatus.TOO_MANY_REQUESTS,
                    )
                    return
                self._send_json(job, HTTPStatus.CREATED)
                return
            if parsed.path == "/api/gap-analysis/rebuild":
                try:
                    self._send_json(run_gap_analysis(state.settings, save=True))
                except Exception as exc:
                    logger.exception("Gap analysis failed")
                    self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if parsed.path == "/api/creator-discovery/rebuild":
                payload = self._read_json()
                ability = str(payload.get("ability") or "").strip() or None
                try:
                    self._send_json(discover_creator(ability=ability, settings=state.settings, save=True))
                except Exception as exc:
                    logger.exception("Creator discovery failed")
                    self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if parsed.path == "/api/creator-discovery/candidates":
                try:
                    self._send_json(add_candidate(self._read_json(), settings=state.settings), HTTPStatus.CREATED)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                except Exception as exc:
                    logger.exception("Adding discovery candidate failed")
                    self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if parsed.path == "/api/creator-discovery/approve":
                payload = self._read_json()
                candidate_id = str(payload.get("candidate_id") or "").strip()
                try:
                    self._send_json(approve_candidate(candidate_id, settings=state.settings))
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                except Exception as exc:
                    logger.exception("Approving discovery candidate failed")
                    self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if parsed.path == "/api/creator-discovery/start-analysis":
                payload = self._read_json()
                candidate_id = str(payload.get("candidate_id") or "").strip()
                try:
                    request = start_analysis(candidate_id, settings=state.settings)
                    analysis_request = request["analysis_request"]
                    if not analysis_request.get("ready"):
                        self._send_json(
                            {
                                "error": analysis_request.get("note")
                                or "候选人缺少当前平台可分析的视频链接。",
                                **request,
                            },
                            HTTPStatus.BAD_REQUEST,
                        )
                        return
                    job = state.submit(
                        {
                            "source": analysis_request["source_url"],
                            "mode": analysis_request["mode"],
                            "candidate_id": candidate_id,
                            "limit": int(payload.get("limit") or 10),
                            "v3": bool(payload.get("v3", True)),
                            "build_kb": bool(payload.get("build_kb", True)),
                        }
                    )
                    self._send_json({**request, "job": job}, HTTPStatus.ACCEPTED)
                except JobQueueFullError as exc:
                    self._send_json(
                        {"error": str(exc)},
                        HTTPStatus.TOO_MANY_REQUESTS,
                    )
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                except Exception as exc:
                    logger.exception("Starting candidate analysis failed")
                    self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if parsed.path == "/api/up-advisor":
                payload = self._read_json()
                target = str(payload.get("target") or "").strip()
                min_samples = int(payload.get("min_samples") or 5)
                try:
                    advisor = advise_next_up_targets(
                        target=target,
                        output_root=state.settings.output_dir,
                        min_samples=min_samples,
                        settings=state.settings,
                    )
                    paths = build_up_advisor_report(
                        target=target,
                        output_root=state.settings.output_dir,
                        min_samples=min_samples,
                        settings=state.settings,
                        payload=advisor,
                    )
                    advisor["files"] = [
                        _file_item("UP抓取决策 up_advisor_report.md", paths["markdown"]),
                        _file_item("UP抓取决策数据 up_advisor_report.json", paths["json"]),
                    ]
                    self._send_json(advisor)
                except Exception as exc:
                    logger.exception("UP advisor failed")
                    self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: Any) -> None:
            logger.info("%s - %s", self.address_string(), format % args)

        def _read_json(self, max_bytes: int = 4 * 1024 * 1024) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            if length > max_bytes:
                raise ValueError("请求内容过大。")
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))

        def _read_json_object(
            self,
            max_bytes: int = 4 * 1024 * 1024,
        ) -> dict[str, Any] | None:
            try:
                payload = self._read_json(max_bytes=max_bytes)
            except (TypeError, UnicodeDecodeError, ValueError) as exc:
                self._send_json(
                    {"error": f"请求 JSON 无效：{exc}"},
                    HTTPStatus.BAD_REQUEST,
                )
                return None
            if not isinstance(payload, dict):
                self._send_json(
                    {"error": "请求 JSON 必须是对象。"},
                    HTTPStatus.BAD_REQUEST,
                )
                return None
            return payload

        def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                logger.debug("Client disconnected before the JSON response completed.")

        def _serve_static_file(self, path: Path) -> None:
            if not _is_relative_to(path, STATIC_ROOT):
                self._send_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
                return
            if not path.exists() or not path.is_file():
                self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(body)

        def _serve_output_file(self, query: str) -> None:
            params = parse_qs(query)
            raw_path = params.get("path", [""])[0]
            if not raw_path:
                self._send_json({"error": "path is required"}, HTTPStatus.BAD_REQUEST)
                return
            path = Path(raw_path).resolve()
            allowed_roots = [
                state.settings.output_dir.resolve(),
                state.settings.cache_dir.resolve(),
                state.settings.video_production_dir.resolve(),
            ]
            if not any(_is_relative_to(path, root) for root in allowed_roots):
                self._send_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
                return
            if not path.exists() or not path.is_file():
                self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(str(path))[0] or "text/plain"
            if path.suffix.lower() in {".md", ".txt", ".json"}:
                content_type = "text/plain; charset=utf-8"
            file_size = path.stat().st_size
            start = 0
            end = max(0, file_size - 1)
            status = HTTPStatus.OK
            range_header = self.headers.get("Range", "").strip()
            if range_header:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
                if not match or file_size <= 0:
                    self._send_range_error(file_size)
                    return
                raw_start, raw_end = match.groups()
                if not raw_start and not raw_end:
                    self._send_range_error(file_size)
                    return
                if raw_start:
                    start = int(raw_start)
                    end = int(raw_end) if raw_end else file_size - 1
                else:
                    suffix_length = int(raw_end)
                    if suffix_length <= 0:
                        self._send_range_error(file_size)
                        return
                    start = max(0, file_size - suffix_length)
                    end = file_size - 1
                end = min(end, file_size - 1)
                if start >= file_size or end < start:
                    self._send_range_error(file_size)
                    return
                status = HTTPStatus.PARTIAL_CONTENT
            content_length = 0 if file_size == 0 else end - start + 1
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(content_length))
            if status == HTTPStatus.PARTIAL_CONTENT:
                self.send_header(
                    "Content-Range",
                    f"bytes {start}-{end}/{file_size}",
                )
            self.end_headers()
            try:
                with path.open("rb") as handle:
                    handle.seek(start)
                    remaining = content_length
                    while remaining > 0:
                        chunk = handle.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                logger.debug("Client disconnected while streaming %s", path)

        def _send_range_error(self, file_size: int) -> None:
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{file_size}")
            self.send_header("Content-Length", "0")
            self.end_headers()

    return Handler


def _refresh_gap_after_analysis(
    state: AppState,
    job_id: str,
) -> dict[str, Any]:
    raise_if_cancelled(lambda: state.jobs.is_cancel_requested(job_id))
    state.jobs.update(
        job_id,
        stage="能力缺口",
        progress=98,
        log="结构化特征已写入 DuckDB，正在自动刷新能力缺口。",
    )
    try:
        payload = run_gap_analysis(state.settings, save=True)
        health = payload.get("knowledge_health") or {}
        source_summary = payload.get("source_summary") or {}
        return {
            "status": "ok",
            "generated_at": payload.get("generated_at"),
            "overall_score": health.get("overall_score"),
            "missing_count": health.get("missing_count"),
            "analytics_video_count": source_summary.get(
                "analytics_video_count",
                0,
            ),
            "analytics_capability_evidence_count": source_summary.get(
                "analytics_capability_evidence_count",
                0,
            ),
        }
    except JobCancelledError:
        raise
    except Exception as exc:
        logger.warning("Automatic gap refresh failed after job %s: %s", job_id, exc)
        return {"status": "failed", "reason": str(exc)}


_EXPLICIT_JOB_MODES = JobModeRegistry()
register_feature_job_modes(
    _EXPLICIT_JOB_MODES,
    FeatureJobServices(
        update_progress=_update_job_progress,
        file_item=_file_item,
    ),
)


register_data_jobs(_EXPLICIT_JOB_MODES, FeatureJobServices(update_progress=_update_job_progress, file_item=_file_item))


@guarded_job
def _run_job(state: AppState, job_id: str) -> None:
    job = state.jobs.get(job_id)
    if not job:
        return
    state.clear_capture_stop(job_id)
    payload = job["payload"]
    source = str(payload.get("source") or "").strip()
    mode = str(payload.get("mode") or "auto")
    enrich_v3 = bool(payload.get("v3"))
    build_kb = bool(payload.get("build_kb"))
    allow_playback_capture = bool(
        payload.get("allow_playback_capture")
    )
    raw_capture_duration = payload.get("capture_duration_seconds")
    capture_duration_seconds = (
        float(raw_capture_duration)
        if str(raw_capture_duration or "").strip()
        else None
    )
    subject_name = str(payload.get("subject_name") or "").strip()
    content_category = str(
        payload.get("content_category") or "auto"
    ).strip()
    candidate_id = str(payload.get("candidate_id") or "").strip()
    limit = payload.get("limit")
    limit = int(limit) if str(limit or "").strip() else None

    def check_cancelled() -> None:
        raise_if_cancelled(
            lambda: state.jobs.is_cancel_requested(job_id)
        )

    try:
        check_cancelled()
        state.jobs.update(job_id, status="running", stage="准备", progress=5, log="开始执行。")
        explicit_handler = _EXPLICIT_JOB_MODES.resolve(mode)
        if explicit_handler is not None:
            explicit_handler(state, job_id, payload, check_cancelled)
            return
        if mode == "build_kb":
            state.jobs.update(job_id, stage="知识库", progress=30, log="正在构建本地知识库。")
            kb_path = build_knowledge_base(
                state.settings.output_dir,
                state.settings.knowledge_base_dir / "index.json",
                state.settings,
                cancel_requested=lambda: state.jobs.is_cancel_requested(
                    job_id
                ),
                progress_callback=lambda current, total: _update_job_progress(
                    state,
                    job_id,
                    "知识库整理",
                    min(85, 30 + int((current / max(total, 1)) * 55)),
                    BatchProgressMessage(
                        f"正在整理知识文档：{current}/{total}",
                        current=current,
                        total=total,
                    ),
                ),
            )
            check_cancelled()
            state.jobs.update(
                job_id,
                status="done",
                stage="完成",
                progress=100,
                result={"type": "knowledge_base", "files": [_file_item("知识库 index.json", kb_path)]},
                log="知识库构建完成。",
            )
            return

        if mode == "advanced_kb":
            from pipeline.knowledge_graph import run_advanced_knowledge_graph

            state.jobs.update(
                job_id,
                stage="知识系统",
                progress=15,
                log="正在更新词法索引、向量索引、创作者库、模板库、能力缺口和发现候选池。",
            )
            result = run_advanced_knowledge_graph(
                state.settings,
                progress_callback=lambda stage, progress, message: _update_job_progress(
                    state,
                    job_id,
                    stage,
                    progress,
                    message,
                ),
                cancel_requested=lambda: state.jobs.is_cancel_requested(
                    job_id
                ),
            )
            files = []
            labels = {
                "lexical_index": "词法知识库 index.json",
                "vector_manifest": "向量知识库 manifest.json",
                "creator_manifest": "创作者知识库 manifest.json",
                "template_library": "模板库 template_library.json",
                "gap_analysis": "能力缺口 latest.json",
                "discovery_dashboard": "创作者发现 dashboard.json",
                "project_report": "项目整合报告.json",
            }
            for key, label in labels.items():
                value = result.get(key)
                if value and Path(value).exists():
                    files.append(_file_item(label, Path(value)))
            check_cancelled()
            state.jobs.update(
                job_id,
                status="done",
                stage="完成",
                progress=100,
                result={
                    "type": "advanced_knowledge",
                    "steps": result.get("steps", []),
                    "warnings": result.get("warnings", []),
                    "files": files,
                },
                log="完整知识系统更新完成。",
            )
            return

        if mode == "report":
            if not source:
                raise ValueError("请输入研究问题。")
            state.jobs.update(job_id, stage="V4报告", progress=25, log="正在读取知识库并生成V4报告。")
            result = generate_research_report(
                source,
                state.settings,
                top_k=limit or 8,
                rebuild_kb=build_kb,
                progress_callback=lambda stage, progress, message: _update_job_progress(
                    state,
                    job_id,
                    stage,
                    progress,
                    message,
                ),
                cancel_requested=lambda: state.jobs.is_cancel_requested(
                    job_id
                ),
            )
            check_cancelled()
            state.jobs.update(
                job_id,
                status="done",
                stage="完成",
                progress=100,
                result={
                    "type": "report",
                    "files": [
                        _file_item("V4研究报告 report.md", result["markdown_path"]),
                        _file_item("报告数据 report.json", result["json_path"]),
                    ],
                },
                log="V4研究报告生成完成。",
            )
            return

        if not source:
            raise ValueError(
                "请输入 UP 名、UP主页、B站/YouTube/抖音/小红书视频链接、"
                "BV号或本地文件路径。"
            )

        auth_platform = _required_auth_platform(source)
        if auth_platform:
            ensure_platform_authorized(auth_platform, state.settings)

        resolved_mode = _resolve_mode(source, mode)
        if resolved_mode == "content":
            state.jobs.update(
                job_id,
                stage="内容作品",
                progress=15,
                log="正在按综艺、电影、动漫或其他内容作品批量蒸馏B站视频。",
            )

            def update_content_progress(
                stage: str,
                progress: int,
                message: str,
            ) -> None:
                _update_job_progress(
                    state,
                    job_id,
                    stage,
                    progress,
                    message,
                )

            result = run_content_pipeline(
                source,
                state.settings,
                subject_name=subject_name,
                content_category=content_category,
                limit=limit,
                enrich_v3=enrich_v3,
                build_kb=build_kb,
                allow_playback_capture=allow_playback_capture,
                capture_duration_seconds=capture_duration_seconds,
                capture_stop_requested=lambda: state.capture_stop_requested(
                    job_id
                ),
                cancel_requested=lambda: state.jobs.is_cancel_requested(
                    job_id
                ),
                progress_callback=update_content_progress,
            )
            files = [
                _file_item(
                    "内容作品画像 content_profile.md",
                    result["profile_path"],
                ),
                _file_item(
                    "内容作品清单 content_manifest.json",
                    result["manifest_path"],
                ),
            ]
            for item in result.get("video_outputs", []):
                files.append(
                    _file_item(
                        f"{item['video_id']} video.md",
                        item["markdown_path"],
                    )
                )
            if result.get("knowledge_base_path"):
                files.append(
                    _file_item(
                        "知识库 index.json",
                        result["knowledge_base_path"],
                    )
                )
            gap_refresh = _refresh_gap_after_analysis(state, job_id)
            check_cancelled()
            state.jobs.update(
                job_id,
                status="done",
                stage="完成",
                progress=100,
                result={
                    "type": "content_work",
                    "platform": "bilibili",
                    "subject_id": result["subject_id"],
                    "subject_name": result["subject_name"],
                    "content_category": result["content_category"],
                    "content_category_label": result[
                        "content_category_label"
                    ],
                    "success_count": result["success_count"],
                    "failure_count": result["failure_count"],
                    "knowledge_base_status": result.get(
                        "knowledge_base_status"
                    ),
                    "knowledge_base_skipped_reason": result.get(
                        "knowledge_base_skipped_reason"
                    ),
                    "gap_refresh": gap_refresh,
                    "files": files,
                },
                log=(
                    f"内容作品“{result['subject_name']}”蒸馏完成，"
                    f"类型：{result['content_category_label']}。"
                ),
            )
            return

        if resolved_mode == "up":
            state.jobs.update(
                job_id,
                stage="创作者批量",
                progress=15,
                log="正在抓取创作者视频列表并批量分析。",
            )
            def update_up_progress(stage: str, progress: int, message: str) -> None:
                _update_job_progress(
                    state,
                    job_id,
                    stage,
                    progress,
                    message,
                )

            result = run_up_pipeline(
                source,
                state.settings,
                limit=limit,
                enrich_v3=enrich_v3,
                build_kb=build_kb,
                cancel_requested=lambda: state.jobs.is_cancel_requested(
                    job_id
                ),
                progress_callback=update_up_progress,
            )
            creator_label = {
                "youtube": "YouTube频道",
                "douyin": "抖音创作者",
            }.get(result.get("platform"), "B站UP")
            files = []
            if result.get("profile_path"):
                files.append(
                    _file_item(
                        f"{creator_label}画像 up_profile.md",
                        result["profile_path"],
                    )
                )
            files.append(
                _file_item("批量清单 batch_manifest.json", result["manifest_path"])
            )
            for item in result.get("video_outputs", []):
                files.append(_file_item(f"{item['video_id']} video.md", item["markdown_path"]))
            if result.get("knowledge_base_path"):
                files.append(_file_item("知识库 index.json", result["knowledge_base_path"]))
            if result.get("learning_status") in {
                "complete",
                "no_unseen_candidates",
            }:
                gap_refresh = {
                    "status": "skipped",
                    "reason": "no_new_videos",
                }
            else:
                gap_refresh = _refresh_gap_after_analysis(state, job_id)
            check_cancelled()
            completion_message = str(
                result.get("status_message")
                or f"{creator_label}批量分析完成。"
            )
            state.jobs.update(
                job_id,
                status="done",
                stage=(
                    "学习完毕"
                    if result.get("learning_status") == "complete"
                    else (
                        "未发现新视频"
                        if result.get("learning_status") == "no_unseen_candidates"
                        else "完成"
                    )
                ),
                progress=100,
                result={
                    "type": "up",
                    "platform": result.get("platform", "bilibili"),
                    "success_count": result["success_count"],
                    "failure_count": result["failure_count"],
                    "candidate_count": result.get("candidate_count", 0),
                    "skipped_existing_count": result.get(
                        "skipped_existing_count",
                        0,
                    ),
                    "learning_status": result.get("learning_status", "updated"),
                    "message": completion_message,
                    "knowledge_base_status": result.get("knowledge_base_status"),
                    "knowledge_base_skipped_reason": result.get(
                        "knowledge_base_skipped_reason"
                    ),
                    "gap_refresh": gap_refresh,
                    "files": files,
                },
                log=completion_message,
            )
            if candidate_id:
                try:
                    finish_analysis(
                        candidate_id,
                        True,
                        {
                            "result_type": "up",
                            "success_count": result["success_count"],
                            "failure_count": result["failure_count"],
                        },
                        state.settings,
                    )
                except Exception:
                    logger.exception("Failed to mark discovery candidate as analyzed")
            return

        state.jobs.update(job_id, stage="单视频", progress=15, log="正在分析单个视频。")
        def update_video_progress(stage: str, progress: int, message: str) -> None:
            _update_job_progress(
                state,
                job_id,
                stage,
                progress,
                message,
            )

        details = run_video_pipeline_details(
            source,
            state.settings,
            enrich_v3=enrich_v3,
            progress_callback=update_video_progress,
            allow_playback_capture=allow_playback_capture,
            capture_duration_seconds=capture_duration_seconds,
            capture_stop_requested=lambda: state.capture_stop_requested(
                job_id
            ),
            cancel_requested=lambda: state.jobs.is_cancel_requested(
                job_id
            ),
        )
        files = [_file_item("视频分析 video.md", details["markdown_path"])]
        acquisition = details.get("acquisition")
        acquisition_summary = None
        if acquisition is not None:
            manifest_path = acquisition.manifest_path
            if manifest_path and manifest_path.exists():
                files.append(
                    _file_item("采集清单 acquisition.json", manifest_path)
                )
            acquisition_summary = {
                "selected_strategy": acquisition.selected_strategy.value,
                "assessment": acquisition.assessment.to_dict(),
                "manifest_path": (
                    str(manifest_path) if manifest_path else None
                ),
            }
        output_dir = state.settings.output_dir / details["video"].video_id
        for name in ["analysis.json", "subtitle.txt", "subtitle.srt", "v3.md", "v3.json"]:
            path = output_dir / name
            if path.exists():
                files.append(_file_item(name, path))
        if build_kb:
            state.jobs.update(job_id, stage="知识库", progress=85, log="正在更新知识库。")
            kb_path = build_knowledge_base(
                state.settings.output_dir,
                state.settings.knowledge_base_dir / "index.json",
                state.settings,
                cancel_requested=lambda: state.jobs.is_cancel_requested(
                    job_id
                ),
                progress_callback=lambda current, total: _update_job_progress(
                    state,
                    job_id,
                    "知识库整理",
                    min(96, 85 + int((current / max(total, 1)) * 11)),
                    BatchProgressMessage(
                        f"正在更新知识文档：{current}/{total}",
                        current=current,
                        total=total,
                    ),
                ),
            )
            files.append(_file_item("知识库 index.json", kb_path))
        gap_refresh = _refresh_gap_after_analysis(state, job_id)
        check_cancelled()
        state.jobs.update(
            job_id,
            status="done",
            stage="完成",
            progress=100,
            result={
                "type": "video",
                "video_id": details["video"].video_id,
                "acquisition": acquisition_summary,
                "gap_refresh": gap_refresh,
                "files": files,
            },
            log="单视频分析完成。",
        )
        if candidate_id:
            try:
                finish_analysis(
                    candidate_id,
                    True,
                    {
                        "result_type": "video",
                        "video_id": details["video"].video_id,
                        "platform": details["video"].platform,
                    },
                    state.settings,
                )
            except Exception:
                logger.exception("Failed to mark discovery candidate as analyzed")
    except JobCancelledError:
        state.jobs.update(
            job_id,
            status="cancelled",
            stage="已取消",
            progress_detail=None,
            result=None,
            error=None,
            log="任务已安全取消；已完成的缓存文件会保留供下次复用。",
        )
    except Exception as exc:
        error_text = str(exc)
        if candidate_id:
            try:
                finish_analysis(
                    candidate_id,
                    False,
                    {"error": str(exc)},
                    state.settings,
                )
            except Exception:
                logger.exception("Failed to mark discovery candidate as failed")
        state.jobs.update(
            job_id,
            status="failed",
            stage="失败",
            error=error_text,
            log=(
                error_text
                if (
                    "点击“登录抖音”" in error_text
                    or "Cookie 授权" in error_text
                    or "B站媒体连接" in error_text
                )
                else traceback.format_exc(limit=8)
            ),
        )
    finally:
        state.clear_capture_stop(job_id)


def _resolve_mode(source: str, mode: str) -> str:
    if mode == "content" or is_bilibili_collection_url(source):
        return "content"
    if mode in {"video", "up"}:
        return mode
    if is_bilibili_up_source(source):
        return "up"
    if is_bilibili_url(source):
        return "video"
    if is_youtube_channel_url(source):
        return "up"
    if is_youtube_url(source):
        return "video"
    if is_douyin_profile_url(source):
        return "up"
    if detect_social_platform(source):
        return "video"
    if Path(source).expanduser().exists():
        return "video"
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return "video"
    return "up"


def _required_auth_platform(source: str) -> str | None:
    if is_youtube_channel_url(source) or is_youtube_url(source):
        return "youtube"
    if is_bilibili_up_source(source) or is_bilibili_url(source):
        return "bilibili"
    local_candidate = Path(source).expanduser()
    if local_candidate.exists() or local_candidate.is_absolute():
        return None
    if detect_social_platform(source):
        return None
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return None
    return "bilibili"


def _knowledge_status(settings: Settings) -> dict[str, Any]:
    artifacts = {
        "lexical": settings.knowledge_base_dir / "index.json",
        "vector": settings.vector_knowledge_base_dir / "manifest.json",
        "creator": settings.output_dir / "creator_knowledge_base" / "manifest.json",
        "templates": settings.output_dir / "creator_knowledge_base" / "templates" / "template_library.json",
        "gap": settings.output_dir / "gap_analysis" / "latest.json",
        "discovery": settings.output_dir / "creator_discovery" / "latest.json",
        "project": settings.output_dir / "integrated" / "project_information_integration.json",
    }
    dependencies = {
        name: importlib.util.find_spec(module) is not None
        for name, module in {
            "spacy": "spacy",
            "opencv": "cv2",
            "scenedetect": "scenedetect",
            "chromadb": "chromadb",
            "sentence_transformers": "sentence_transformers",
            "langgraph": "langgraph",
            "yt_dlp": "yt_dlp",
        }.items()
    }
    artifact_status = {
            key: {
                "ready": path.exists(),
                "path": str(path),
                "updated_at": path.stat().st_mtime if path.exists() else None,
                "size": path.stat().st_size if path.exists() else 0,
            }
            for key, path in artifacts.items()
        }
    vector_status = vector_backend_status(settings)
    artifact_status["vector"].update(
        {
            "ready": vector_status["ready"],
            "stale": vector_status["stale"],
            "reason": vector_status.get("reason"),
        }
    )
    return {
        "artifacts": artifact_status,
        "dependencies": dependencies,
        "analytics": get_analytics_summary(settings),
        "vector_status": vector_status,
        "search_backend": settings.rag_search_backend,
        "semantic_model": settings.sentence_transformer_model,
    }


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _find_free_port(host: str, start_port: int) -> int:
    for port in range(start_port, start_port + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No free port found from {start_port} to {start_port + 49}")


def run_server(host: str, port: int, settings: Settings, open_browser: bool = False) -> str:
    actual_port = _find_free_port(host, port)
    state = AppState(settings, start_workers=True)
    server = ThreadingHTTPServer((host, actual_port), create_handler(state))
    url = f"http://{host}:{actual_port}"
    _write_runtime_url(url)
    logger.info("Content Research UI running at %s", url)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping server.")
    finally:
        server.server_close()
        state.close()
    return url


def _write_runtime_url(url: str) -> None:
    url_file = os.getenv("CONTENT_RESEARCH_URL_FILE")
    if not url_file:
        return
    path = Path(url_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(url, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Content Research Web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--open", action="store_true", help="Open browser automatically.")
    parser.add_argument("--overwrite", action="store_true", help="Bypass cache for jobs started from this UI.")
    args = parser.parse_args()
    settings = replace(SETTINGS, overwrite_cache=args.overwrite)
    setup_logging(settings)
    run_server(args.host, args.port, settings, open_browser=args.open)


if __name__ == "__main__":
    main()
