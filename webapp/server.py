from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import mimetypes
import os
import socket
import threading
import time
import traceback
import uuid
import webbrowser
from dataclasses import replace
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from config import SETTINGS, Settings, setup_logging
from downloader.bilibili import is_bilibili_url
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
from pipeline.batch import run_up_pipeline
from pipeline.content import run_content_pipeline
from pipeline.run import run_video_pipeline_details
from processor.whisper import get_whisper_runtime_status
from rag.knowledge_base import build_knowledge_base, search_knowledge_base
from rag.report import generate_research_report
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

logger = logging.getLogger(__name__)

WEB_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = WEB_ROOT / "static"
APP_VERSION = "2026.07.30-content-works.1"
JOB_SCHEMA_VERSION = "1.0"


class JobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:12]
        job = {
            "schema_version": JOB_SCHEMA_VERSION,
            "id": job_id,
            "status": "queued",
            "progress": 0,
            "stage": "queued",
            "progress_detail": None,
            "logs": ["任务已创建。"],
            "payload": payload,
            "result": None,
            "error": None,
            "revision": 0,
            "updated_at": time.time(),
        }
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return json.loads(json.dumps(job, ensure_ascii=False, default=str)) if job else None

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = list(self._jobs.values())
            return json.loads(json.dumps(jobs[-20:], ensure_ascii=False, default=str))

    def update(self, job_id: str, **updates: Any) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in updates.items():
                if key == "log":
                    job["logs"].append(value)
                else:
                    job[key] = value
            job["revision"] = int(job.get("revision", 0)) + 1
            job["updated_at"] = time.time()


class AppState:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.jobs = JobStore()


def _update_job_progress(
    state: AppState,
    job_id: str,
    stage: str,
    progress: int,
    message: str,
) -> None:
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


def create_handler(state: AppState):
    class Handler(SimpleHTTPRequestHandler):
        server_version = "ContentResearchWeb/1.0"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
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
                            "v3_nlp": True,
                            "scene_detection": True,
                        },
                        "platforms": {
                            "bilibili": {
                                "single_video": True,
                                "creator_batch": True,
                                "content_work_batch": True,
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
            if parsed.path == "/api/knowledge/status":
                self._send_json(_knowledge_status(state.settings))
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
                job = state.jobs.create(payload)
                thread = threading.Thread(target=_run_job, args=(state, job["id"]), daemon=True)
                thread.start()
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
                job = state.jobs.create({"source": "", "mode": "build_kb"})
                thread = threading.Thread(target=_run_job, args=(state, job["id"]), daemon=True)
                thread.start()
                self._send_json(job, HTTPStatus.CREATED)
                return
            if parsed.path == "/api/kb/advanced":
                job = state.jobs.create({"source": "", "mode": "advanced_kb"})
                thread = threading.Thread(target=_run_job, args=(state, job["id"]), daemon=True)
                thread.start()
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
                    job = state.jobs.create(
                        {
                            "source": analysis_request["source_url"],
                            "mode": analysis_request["mode"],
                            "candidate_id": candidate_id,
                            "limit": int(payload.get("limit") or 10),
                            "v3": bool(payload.get("v3", True)),
                            "build_kb": bool(payload.get("build_kb", True)),
                        }
                    )
                    thread = threading.Thread(target=_run_job, args=(state, job["id"]), daemon=True)
                    thread.start()
                    self._send_json({**request, "job": job}, HTTPStatus.ACCEPTED)
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

        def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

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
            allowed_roots = [state.settings.output_dir.resolve(), state.settings.cache_dir.resolve()]
            if not any(_is_relative_to(path, root) for root in allowed_roots):
                self._send_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
                return
            if not path.exists() or not path.is_file():
                self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(str(path))[0] or "text/plain"
            if path.suffix.lower() in {".md", ".txt", ".json"}:
                content_type = "text/plain; charset=utf-8"
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def _run_job(state: AppState, job_id: str) -> None:
    job = state.jobs.get(job_id)
    if not job:
        return
    payload = job["payload"]
    source = str(payload.get("source") or "").strip()
    mode = str(payload.get("mode") or "auto")
    enrich_v3 = bool(payload.get("v3"))
    build_kb = bool(payload.get("build_kb"))
    subject_name = str(payload.get("subject_name") or "").strip()
    content_category = str(
        payload.get("content_category") or "auto"
    ).strip()
    candidate_id = str(payload.get("candidate_id") or "").strip()
    limit = payload.get("limit")
    limit = int(limit) if str(limit or "").strip() else None

    try:
        state.jobs.update(job_id, status="running", stage="准备", progress=5, log="开始执行。")
        if mode == "build_kb":
            state.jobs.update(job_id, stage="知识库", progress=30, log="正在构建本地知识库。")
            kb_path = build_knowledge_base(state.settings.output_dir, state.settings.knowledge_base_dir / "index.json", state.settings)
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
                progress_callback=lambda stage, progress, message: state.jobs.update(
                    job_id,
                    stage=stage,
                    progress=progress,
                    log=message,
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
            )
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
                progress_callback=update_up_progress,
            )
            creator_label = {
                "youtube": "YouTube频道",
                "douyin": "抖音创作者",
            }.get(result.get("platform"), "B站UP")
            files = [
                _file_item(f"{creator_label}画像 up_profile.md", result["profile_path"]),
                _file_item("批量清单 batch_manifest.json", result["manifest_path"]),
            ]
            for item in result.get("video_outputs", []):
                files.append(_file_item(f"{item['video_id']} video.md", item["markdown_path"]))
            if result.get("knowledge_base_path"):
                files.append(_file_item("知识库 index.json", result["knowledge_base_path"]))
            state.jobs.update(
                job_id,
                status="done",
                stage="完成",
                progress=100,
                result={
                    "type": "up",
                    "platform": result.get("platform", "bilibili"),
                    "success_count": result["success_count"],
                    "failure_count": result["failure_count"],
                    "knowledge_base_status": result.get("knowledge_base_status"),
                    "knowledge_base_skipped_reason": result.get(
                        "knowledge_base_skipped_reason"
                    ),
                    "files": files,
                },
                log=f"{creator_label}批量分析完成。",
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
        )
        files = [_file_item("视频分析 video.md", details["markdown_path"])]
        output_dir = state.settings.output_dir / details["video"].video_id
        for name in ["analysis.json", "subtitle.txt", "subtitle.srt", "v3.md", "v3.json"]:
            path = output_dir / name
            if path.exists():
                files.append(_file_item(name, path))
        if build_kb:
            state.jobs.update(job_id, stage="知识库", progress=85, log="正在更新知识库。")
            kb_path = build_knowledge_base(state.settings.output_dir, state.settings.knowledge_base_dir / "index.json", state.settings)
            files.append(_file_item("知识库 index.json", kb_path))
        state.jobs.update(
            job_id,
            status="done",
            stage="完成",
            progress=100,
            result={"type": "video", "video_id": details["video"].video_id, "files": files},
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
                )
                else traceback.format_exc(limit=8)
            ),
        )


def _resolve_mode(source: str, mode: str) -> str:
    if mode in {"video", "up", "content"}:
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
    return {
        "artifacts": {
            key: {
                "ready": path.exists(),
                "path": str(path),
                "updated_at": path.stat().st_mtime if path.exists() else None,
                "size": path.stat().st_size if path.exists() else 0,
            }
            for key, path in artifacts.items()
        },
        "dependencies": dependencies,
        "search_backend": settings.rag_search_backend,
        "semantic_model": settings.sentence_transformer_model,
    }


def _file_item(label: str, path: Path) -> dict[str, str]:
    path = path.resolve()
    return {
        "label": label,
        "path": str(path),
        "url": f"/api/file?path={quote(str(path))}",
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
    server = ThreadingHTTPServer((host, actual_port), create_handler(AppState(settings)))
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
