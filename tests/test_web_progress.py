from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import Settings
from infrastructure.cancellation import JobCancelledError
from processor.whisper import WhisperExecution, WhisperProgressMessage
from webapp.server import (
    AppState,
    _knowledge_rules,
    _record_rule_review,
    _refresh_gap_after_analysis,
    _run_job,
    _update_job_progress,
    create_handler,
)


class WebProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)

    def _root(self) -> Path:
        return Path(self._temporary_directory.name)

    def test_knowledge_rule_review_is_saved_without_auto_rebuilding_library(self) -> None:
        root = self._root()
        settings = Settings(
            base_dir=root,
            output_dir=root / "output",
            cache_dir=root / "cache",
            logs_dir=root / "logs",
        )
        rules_dir = settings.output_dir / "creator_knowledge_base" / "rules"
        rules_dir.mkdir(parents=True)
        library_path = rules_dir / "rule_library.json"
        library_path.write_text(
            json.dumps(
                {
                    "generated_at": "2026-09-01T12:00:00",
                    "source": {"analyzed_video_count": 2},
                    "rules": [
                        {
                            "rule_id": "R-001",
                            "template_id": "opening-test",
                            "name": "测试开场规则",
                            "status": "candidate",
                            "definition": "通过问题引出待解答内容。",
                            "layer": "opening",
                            "Evidence": {
                                "evidence_label": "逐视频结构化标签直接匹配",
                                "video_count": 2,
                                "creator_count": 1,
                                "located_observation_count": 1,
                                "matching_basis": "结构化分析信号包含：问题",
                                "examples": [{"video_id": "BV-test", "author": "作者"}],
                            },
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        result = _record_rule_review(
            {
                "rule_id": "R-001",
                "status": "validated",
                "reviewer": "测试复核人",
                "notes": "证据符合定义，暂按候选能力使用。",
                "review_token": _knowledge_rules(settings)["rules"][0]["review_token"],
            },
            settings,
        )

        self.assertTrue(result["ok"])
        # Review records are separate from the generated library until an explicit rebuild.
        self.assertEqual(
            json.loads(library_path.read_text(encoding="utf-8"))["rules"][0]["status"],
            "candidate",
        )
        listed = _knowledge_rules(settings)
        self.assertEqual(listed["rules"][0]["status"], "validated")
        self.assertTrue(listed["rules"][0]["review_pending"])
        self.assertEqual(listed["rules"][0]["review"]["reviewer"], "测试复核人")

    def test_rule_review_rejects_unknown_rule_and_invalid_status(self) -> None:
        root = self._root()
        settings = Settings(
            base_dir=root,
            output_dir=root / "output",
            cache_dir=root / "cache",
            logs_dir=root / "logs",
        )
        rules_dir = settings.output_dir / "creator_knowledge_base" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "rule_library.json").write_text(
            json.dumps({"rules": [{"rule_id": "R-001"}]}), encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "状态无效"):
            _record_rule_review(
                {"rule_id": "R-001", "status": "candidate", "reviewer": "我"},
                settings,
            )
        with self.assertRaisesRegex(ValueError, "不存在"):
            _record_rule_review(
                {"rule_id": "R-404", "status": "validated", "reviewer": "我"},
                settings,
            )

    def test_whisper_metadata_is_added_without_changing_job_api(self) -> None:
        root = self._root()
        settings = Settings(
            base_dir=root,
            output_dir=root / "output",
            cache_dir=root / "cache",
            logs_dir=root / "logs",
        )
        state = AppState(settings)
        job = state.jobs.create({"source": "test"})
        message = WhisperProgressMessage(
            "Whisper 识别中：5/10 秒",
            phase_percent=50,
            state="transcribing",
            execution=WhisperExecution(
                requested_device="auto",
                device="cuda",
                compute_type="float16",
                batch_size=8,
                cpu_threads=4,
                num_workers=1,
                reason="ready",
                gpu_name="Test GPU",
            ),
            processed_seconds=5,
            duration_seconds=10,
        )

        _update_job_progress(
            state,
            job["id"],
            "Whisper识别",
            67,
            message,
        )

        updated = state.jobs.get(job["id"])
        self.assertEqual(updated["progress"], 67)
        self.assertEqual(updated["stage"], "Whisper识别")
        self.assertEqual(updated["logs"][-1], str(message))
        self.assertEqual(
            updated["progress_detail"]["phase_percent"],
            50,
        )
        self.assertEqual(updated["progress_detail"]["device"], "cuda")

    def test_plain_whisper_stage_gets_visible_fallback_detail(self) -> None:
        root = self._root()
        state = AppState(
            Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
            )
        )
        job = state.jobs.create({"source": "test"})

        _update_job_progress(
            state,
            job["id"],
            "Whisper识别",
            55,
            "正在启动 Whisper。",
        )

        updated = state.jobs.get(job["id"])
        self.assertEqual(updated["progress_detail"]["type"], "whisper")
        self.assertEqual(updated["progress_detail"]["state"], "preparing")
        self.assertIsNone(updated["progress_detail"]["phase_percent"])
        self.assertGreater(updated["revision"], 0)

    def test_heartbeat_updates_detail_without_repeating_log(self) -> None:
        root = self._root()
        state = AppState(
            Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
            )
        )
        job = state.jobs.create({"source": "test"})
        before = state.jobs.get(job["id"])
        message = WhisperProgressMessage(
            "Whisper 正在识别音频，已运行 3 秒。",
            phase_percent=None,
            state="transcribing",
            elapsed_seconds=3,
            heartbeat=True,
        )

        _update_job_progress(
            state,
            job["id"],
            "Whisper识别",
            57,
            message,
        )

        updated = state.jobs.get(job["id"])
        self.assertEqual(updated["logs"], before["logs"])
        self.assertEqual(updated["progress_detail"]["elapsed_seconds"], 3)

    def test_running_playback_capture_can_stop_without_cancelling_job(
        self,
    ) -> None:
        root = self._root()
        state = AppState(
            Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
            )
        )
        job = state.jobs.create({"source": "test"})
        state.jobs.update(
            job["id"],
            status="running",
            stage="本地播放采集",
            progress_detail={
                "type": "playback_capture",
                "state": "recording",
            },
        )

        self.assertTrue(state.request_capture_stop(job["id"]))
        self.assertTrue(state.capture_stop_requested(job["id"]))
        self.assertEqual(state.jobs.get(job["id"])["status"], "running")

    def test_general_cancel_interrupts_progress_and_is_not_capture_only(
        self,
    ) -> None:
        root = self._root()
        state = AppState(
            Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
            )
        )
        job = state.jobs.create({"source": "test"})
        state.jobs.update(job["id"], status="running", stage="内容分析")

        cancelling = state.request_cancel(job["id"])

        self.assertTrue(cancelling["cancel_requested"])
        self.assertTrue(state.capture_stop_requested(job["id"]))
        with self.assertRaises(JobCancelledError):
            _update_job_progress(
                state,
                job["id"],
                "内容分析",
                82,
                "不应继续写入。",
            )

    def test_gap_analysis_refreshes_after_analysis_job(self) -> None:
        root = self._root()
        state = AppState(
            Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
            )
        )
        job = state.jobs.create({"source": "test"})
        state.jobs.update(job["id"], status="running", progress=90)
        payload = {
            "generated_at": "2026-08-01T12:00:00",
            "knowledge_health": {"overall_score": 75, "missing_count": 3},
            "source_summary": {
                "analytics_video_count": 10,
                "analytics_capability_evidence_count": 20,
            },
        }

        with patch(
            "webapp.server.run_gap_analysis",
            return_value=payload,
        ) as refresh:
            result = _refresh_gap_after_analysis(state, job["id"])

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["analytics_video_count"], 10)
        self.assertEqual(state.jobs.get(job["id"])["stage"], "能力缺口")
        refresh.assert_called_once_with(state.settings, save=True)

    def test_cancel_api_immediately_cancels_queued_job(self) -> None:
        root = self._root()
        state = AppState(
            Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
            )
        )
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            create_handler(state),
        )
        thread = threading.Thread(
            target=server.serve_forever,
            daemon=True,
        )
        thread.start()
        try:
            job = state.jobs.create({"source": "queued"})
            request = Request(
                (
                    f"http://127.0.0.1:{server.server_port}"
                    f"/api/jobs/{job['id']}/cancel"
                ),
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                status = response.status
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            state.close()

        self.assertEqual(status, 202)
        self.assertEqual(payload["status"], "cancelled")
        self.assertTrue(payload["cancel_requested"])

    def test_file_api_streams_external_production_file_with_range(self) -> None:
        root = self._root()
        production = root / "external-production"
        production.mkdir()
        video = production / "sample.mp4"
        content = b"0123456789"
        video.write_bytes(content)

        with patch.dict(
            "os.environ",
            {"VIDEO_PRODUCTION_DIR": str(production)},
        ):
            state = AppState(
                Settings(
                    base_dir=root,
                    output_dir=root / "output",
                    cache_dir=root / "cache",
                    logs_dir=root / "logs",
                )
            )
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0),
                create_handler(state),
            )
            thread = threading.Thread(
                target=server.serve_forever,
                daemon=True,
            )
            thread.start()
            url = (
                f"http://127.0.0.1:{server.server_port}/api/file?"
                f"{urlencode({'path': str(video)})}"
            )
            try:
                with urlopen(url, timeout=5) as response:
                    full_status = response.status
                    full_accept_ranges = response.headers["Accept-Ranges"]
                    full_body = response.read()

                range_request = Request(
                    url,
                    headers={"Range": "bytes=2-5"},
                )
                with urlopen(range_request, timeout=5) as response:
                    range_status = response.status
                    content_range = response.headers["Content-Range"]
                    range_accept_ranges = response.headers["Accept-Ranges"]
                    range_body = response.read()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                state.close()

        self.assertEqual(full_status, 200)
        self.assertEqual(full_accept_ranges, "bytes")
        self.assertEqual(full_body, content)
        self.assertEqual(range_status, 206)
        self.assertEqual(content_range, "bytes 2-5/10")
        self.assertEqual(range_accept_ranges, "bytes")
        self.assertEqual(range_body, b"2345")

    def test_video_production_job_honours_render_cancellation(self) -> None:
        root = self._root()
        settings = Settings(
            base_dir=root,
            output_dir=root / "output",
            cache_dir=root / "cache",
            logs_dir=root / "logs",
        )
        state = AppState(settings)
        job = state.jobs.create(
            {
                "source": "video-1",
                "video_id": "video-1",
                "mode": "video_production",
                "target_seconds": 60,
                "platform": "douyin",
            }
        )
        package_dir = settings.video_production_dir / "video-1"
        manifest_path = package_dir / "production_manifest.json"
        plan_path = package_dir / "work" / "edit_plan.json"
        manifest_path.parent.mkdir(parents=True)
        plan_path.parent.mkdir(parents=True)
        manifest_path.write_text("{}", encoding="utf-8")
        plan_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "output_duration_seconds": 60,
                    "edit_subtitle_path": str(
                        package_dir / "work" / "edit_subtitles.srt"
                    ),
                }
            ),
            encoding="utf-8",
        )

        def cancel_render(*_args, **_kwargs):
            state.request_cancel(job["id"])
            raise JobCancelledError("cancelled")

        with (
            patch(
                "features.video_production.jobs.create_research_package",
                return_value=manifest_path,
            ),
            patch(
                "features.video_production.jobs.build_auto_edit_plan",
                return_value=plan_path,
            ),
            patch(
                "features.video_production.jobs.render_edit_plan",
                side_effect=cancel_render,
            ),
        ):
            _run_job(state, job["id"])

        cancelled = state.jobs.get(job["id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertIsNone(cancelled["result"])
        self.assertTrue(cancelled["cancel_requested"])

    def test_video_production_api_lists_sources_builds_plan_and_queues_render(
        self,
    ) -> None:
        root = self._root()
        settings = Settings(
            base_dir=root,
            output_dir=root / "output",
            cache_dir=root / "cache",
            logs_dir=root / "logs",
        )
        research = settings.output_dir / "video-1"
        video_cache = settings.video_cache_dir / "video-1"
        research.mkdir(parents=True)
        video_cache.mkdir(parents=True)
        source_video = video_cache / "video-1.mp4"
        source_video.write_bytes(b"source")
        (research / "analysis.json").write_text(
            json.dumps({"title": "Production API demo"}),
            encoding="utf-8",
        )
        (research / "subtitle.srt").write_text(
            "\n\n".join(
                [
                    (
                        f"{index + 1}\n"
                        f"00:00:{index * 2:02d},000 --> "
                        f"00:00:{index * 2 + 2:02d},000\n"
                        f"第{index + 1}段字幕"
                    )
                    for index in range(10)
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        (video_cache / "metadata.json").write_text(
            json.dumps(
                {
                    "video_path": str(source_video),
                    "duration": 20,
                }
            ),
            encoding="utf-8",
        )
        state = AppState(settings)
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            create_handler(state),
        )
        thread = threading.Thread(
            target=server.serve_forever,
            daemon=True,
        )
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(
                f"{base_url}/api/production/sources",
                timeout=5,
            ) as response:
                sources = json.loads(response.read().decode("utf-8"))

            plan_request = Request(
                f"{base_url}/api/production/plan",
                data=json.dumps(
                    {
                        "video_id": "video-1",
                        "target_seconds": 15,
                        "platform": "douyin",
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(plan_request, timeout=5) as response:
                plan = json.loads(response.read().decode("utf-8"))

            with (
                patch.object(state.runner, "notify"),
                patch(
                    "webapp.server.script_video_runtime_status",
                    return_value={
                        "available": True,
                        "capcut": {"available": True},
                        "ffmpeg": {"available": True},
                        "ffprobe": {"available": True},
                    },
                ),
            ):
                render_request = Request(
                    f"{base_url}/api/production/render",
                    data=json.dumps(
                        {
                            "video_id": "video-1",
                            "target_seconds": 15,
                            "platform": "douyin",
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(render_request, timeout=5) as response:
                    queued = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            state.close()

        self.assertEqual(sources["sources"][0]["video_id"], "video-1")
        self.assertTrue(sources["sources"][0]["source_video_ready"])
        self.assertEqual(
            plan["plan"]["strategy"],
            "research_guided_contiguous_window",
        )
        self.assertEqual(queued["status"], "queued")
        self.assertEqual(queued["payload"]["mode"], "video_production")

    def test_script_video_api_previews_and_queues_agentless_job(self) -> None:
        root = self._root()
        settings = Settings(
            base_dir=root,
            output_dir=root / "output",
            cache_dir=root / "cache",
            logs_dir=root / "logs",
        )
        research = settings.output_dir / "video-1"
        research.mkdir(parents=True)
        (research / "cover.jpg").write_bytes(b"image")
        (research / "analysis.json").write_text(
            json.dumps(
                {
                    "title": "火星素材",
                    "keywords": [{"word": "火星"}],
                }
            ),
            encoding="utf-8",
        )
        rule_library = (
            settings.output_dir
            / "creator_knowledge_base"
            / "rules"
            / "rule_library.json"
        )
        rule_library.parent.mkdir(parents=True, exist_ok=True)
        rule_library.write_text(
            json.dumps(
                {
                    "rules": [
                        {
                            "rule_id": "R-TEST",
                            "template_id": "hook_question_task",
                            "name": "问题任务式开场",
                            "layer": "opening",
                            "status": "candidate",
                            "Trigger": {"required_signals": ["火星", "生命"]},
                            "confidence": {
                                "functional_interpretation": {"score": 0.7}
                            },
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        state = AppState(settings)
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            create_handler(state),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        script = "火星上真的可能存在生命吗？我们从它的环境和已有研究开始解释。"
        try:
            plan_request = Request(
                f"{base_url}/api/production/script-plan",
                data=json.dumps(
                    {"title": "火星生命", "script": script}
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(plan_request, timeout=5) as response:
                plan = json.loads(response.read().decode("utf-8"))

            with (
                patch.object(state.runner, "notify"),
                patch(
                    "webapp.server.script_video_runtime_status",
                    return_value={"available": True},
                ),
            ):
                render_request = Request(
                    f"{base_url}/api/production/script-render",
                    data=json.dumps(
                        {
                            "title": "火星生命",
                            "script": script,
                            "platform": "douyin",
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(render_request, timeout=5) as response:
                    queued = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            state.close()

        self.assertEqual(
            plan["plan"]["strategy"],
            "distilled_rules_narrated_storyboard",
        )
        self.assertFalse(
            plan["plan"]["decision_inputs"]["agent_required"]
        )
        self.assertEqual(plan["capability_plan"]["candidate_count"], 1)
        self.assertEqual(plan["plan"]["capability_plan"], plan["capability_plan"])
        self.assertEqual(plan["plan"]["capability_execution"]["applied"][0]["rule_id"], "R-TEST")
        self.assertEqual(
            plan["capability_plan"]["selections"][0]["primary"]["rule_id"],
            "R-TEST",
        )
        self.assertEqual(queued["payload"]["mode"], "script_video")
        self.assertEqual(queued["payload"]["script"], script)

    def test_script_video_running_cancel_propagates_to_pipeline(self) -> None:
        root = self._root()
        settings = Settings(
            base_dir=root,
            output_dir=root / "output",
            cache_dir=root / "cache",
            logs_dir=root / "logs",
        )
        state = AppState(settings)
        job = state.jobs.create(
            {
                "source": "取消测试",
                "mode": "script_video",
                "script": "这是一段用于验证文稿自动成片任务可以在运行中安全取消的测试文稿。",
                "title": "取消测试",
                "platform": "douyin",
                "fps": 30,
            }
        )

        def cancel_pipeline(*_args, **kwargs):
            self.assertFalse(kwargs["cancel_requested"]())
            kwargs["progress_callback"]("生成旁白", 18, "正在生成旁白。")
            state.request_cancel(job["id"])
            self.assertTrue(kwargs["cancel_requested"]())
            raise JobCancelledError("cancelled")

        try:
            with patch(
                "features.video_production.jobs.run_script_video_pipeline",
                side_effect=cancel_pipeline,
            ) as pipeline:
                _run_job(state, job["id"])

            cancelled = state.jobs.get(job["id"])
        finally:
            state.close()

        pipeline.assert_called_once()
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertTrue(cancelled["cancel_requested"])
        self.assertIsNone(cancelled["result"])
        self.assertIsNone(cancelled["progress_detail"])

    def test_script_render_returns_503_when_runtime_is_unavailable(self) -> None:
        root = self._root()
        settings = Settings(
            base_dir=root,
            output_dir=root / "output",
            cache_dir=root / "cache",
            logs_dir=root / "logs",
            edge_tts_path=str(root / "missing-edge-tts.exe"),
            video_ffmpeg_path=str(root / "missing-ffmpeg.exe"),
            ffprobe_path=str(root / "missing-ffprobe.exe"),
        )
        state = AppState(settings)
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            create_handler(state),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        request = Request(
            (
                f"http://127.0.0.1:{server.server_port}"
                "/api/production/script-render"
            ),
            data=json.dumps(
                {
                    "title": "运行时检测",
                    "script": "这是一段长度足够的测试文稿，用于确认依赖不可用时不会创建注定失败的任务。",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with (
                patch.object(state.runner, "notify"),
                self.assertRaises(HTTPError) as raised,
            ):
                urlopen(request, timeout=5)
            payload = json.loads(raised.exception.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            state.close()

        self.assertEqual(raised.exception.code, 503)
        self.assertIn("error", payload)
        self.assertEqual(state.jobs.list(), [])

    def test_script_video_endpoints_reject_malformed_or_non_object_json(self) -> None:
        root = self._root()
        state = AppState(
            Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
            )
        )
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            create_handler(state),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        requests = [
            Request(
                f"{base_url}/api/production/script-plan",
                data=b"{",
                headers={"Content-Type": "application/json"},
                method="POST",
            ),
            Request(
                f"{base_url}/api/production/script-render",
                data=b"[]",
                headers={"Content-Type": "application/json"},
                method="POST",
            ),
        ]
        errors: list[dict[str, object]] = []
        try:
            for request in requests:
                with self.assertRaises(HTTPError) as raised:
                    urlopen(request, timeout=5)
                errors.append(
                    {
                        "status": raised.exception.code,
                        "payload": json.loads(
                            raised.exception.read().decode("utf-8")
                        ),
                    }
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            state.close()

        self.assertTrue(all(item["status"] == 400 for item in errors))
        self.assertTrue(
            all("error" in item["payload"] for item in errors)
        )
        self.assertEqual(state.jobs.list(), [])


if __name__ == "__main__":
    unittest.main()
