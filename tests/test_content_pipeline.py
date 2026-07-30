from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from config import Settings
from models import AnalysisResult, Transcript, Video, build_pipeline_result
from pipeline.content import (
    classify_content_category,
    parse_content_sources,
    run_content_pipeline,
)
from rag.knowledge_base import build_knowledge_base
from rag.vector_store import _decode_learning_subjects
from webapp.server import AppState, _resolve_mode, _run_job


class ContentSourceTests(unittest.TestCase):
    def test_multiple_bilibili_sources_are_normalized_and_deduplicated(self) -> None:
        sources = parse_content_sources(
            "BV1abc123\nhttps://www.bilibili.com/video/BV2def456\nBV1abc123"
        )

        self.assertEqual(
            sources,
            [
                "https://www.bilibili.com/video/BV1abc123",
                "https://www.bilibili.com/video/BV2def456",
            ],
        )

    def test_creator_homepage_is_rejected_in_content_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "创作者批量"):
            parse_content_sources("https://space.bilibili.com/123456/video")

    def test_rule_first_category_detection_supports_anime(self) -> None:
        category = classify_content_category(
            "年度动画学习样本",
            ["国漫镜头语言拆解"],
        )

        self.assertEqual(category, "anime")

    def test_web_mode_keeps_old_modes_and_adds_content(self) -> None:
        self.assertEqual(_resolve_mode("BV1abc123", "video"), "video")
        self.assertEqual(_resolve_mode("任意输入", "up"), "up")
        self.assertEqual(_resolve_mode("BV1abc123", "content"), "content")


class ContentPipelineTests(unittest.TestCase):
    def _settings(self, root: Path) -> Settings:
        return Settings(
            base_dir=root,
            output_dir=root / "output",
            cache_dir=root / "cache",
            logs_dir=root / "logs",
        )

    def _result(self, root: Path, video_id: str, title: str) -> dict:
        output_dir = root / "output" / video_id
        output_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = output_dir / "video.md"
        markdown_path.write_text("# video", encoding="utf-8")
        video = Video(
            source_url=f"https://www.bilibili.com/video/{video_id}",
            platform="bilibili",
            video_id=video_id,
            title=title,
            author="原始UP",
            duration=120,
        )
        transcript = Transcript(
            video_id,
            "字幕",
            "official",
            output_dir / "subtitle.txt",
        )
        analysis = AnalysisResult(
            video_id,
            title,
            "摘要",
            {"开头方式": "悬念"},
            [],
            [],
            {},
            {},
            [{"word": "镜头", "count": 2}],
            ["镜头递进"],
        )
        return build_pipeline_result(
            video=video,
            transcript=transcript,
            analysis=analysis,
            markdown_path=markdown_path,
            enrichment=None,
        )

    def test_videos_are_grouped_as_one_content_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = self._settings(root)
            results = [
                self._result(root, "BV1abc123", "动画第一集"),
                self._result(root, "BV2def456", "动画第二集"),
            ]
            with (
                patch(
                    "processor.whisper.whisper_model_session",
                    return_value=nullcontext(),
                ),
                patch(
                    "pipeline.content.run_video_pipeline_details",
                    side_effect=results,
                ),
            ):
                result = run_content_pipeline(
                    "BV1abc123\nBV2def456",
                    settings,
                    subject_name="测试动画",
                    content_category="anime",
                )

            profile = json.loads(
                result["profile_path"]
                .with_name("content_profile.json")
                .read_text(encoding="utf-8")
            )
            self.assertEqual(result["subject_type"], "content_work")
            self.assertEqual(result["success_count"], 2)
            self.assertEqual(profile["subject_name"], "测试动画")
            self.assertEqual(profile["content_category"], "anime")
            self.assertEqual(
                [item["video_id"] for item in profile["videos"]],
                ["BV1abc123", "BV2def456"],
            )

    def test_all_failures_skip_knowledge_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = self._settings(root)
            with (
                patch(
                    "processor.whisper.whisper_model_session",
                    return_value=nullcontext(),
                ),
                patch(
                    "pipeline.content.run_video_pipeline_details",
                    side_effect=RuntimeError("HTTP 412"),
                ),
                patch(
                    "rag.knowledge_base.build_knowledge_base"
                ) as build_kb,
            ):
                result = run_content_pipeline(
                    "BV1abc123",
                    settings,
                    subject_name="失败样本",
                    build_kb=True,
                )

            self.assertEqual(result["success_count"], 0)
            self.assertEqual(result["failure_count"], 1)
            self.assertEqual(
                result["knowledge_base_status"],
                "skipped_no_success",
            )
            build_kb.assert_not_called()


class ContentKnowledgeBaseTests(unittest.TestCase):
    def test_vector_metadata_keeps_content_subjects(self) -> None:
        payload = _decode_learning_subjects(
            '[{"subject_id":"subject-1","subject_name":"测试综艺"}]'
        )

        self.assertEqual(payload[0]["subject_name"], "测试综艺")

    def test_content_subject_metadata_is_added_to_video_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_root = root / "output"
            video_dir = output_root / "BV1abc123"
            content_dir = output_root / "content_bilibili_test"
            video_dir.mkdir(parents=True)
            content_dir.mkdir(parents=True)
            (video_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "title": "动画第一集",
                        "one_sentence_summary": "摘要",
                        "learnings": ["镜头递进"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (content_dir / "content_profile.json").write_text(
                json.dumps(
                    {
                        "subject_type": "content_work",
                        "subject_id": "subject-1",
                        "subject_name": "测试动画",
                        "content_category": "anime",
                        "content_category_label": "动漫",
                        "videos": [{"video_id": "BV1abc123"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            settings = Settings(
                base_dir=root,
                output_dir=output_root,
                cache_dir=root / "cache",
                logs_dir=root / "logs",
            )
            index_path = build_knowledge_base(
                output_root,
                root / "cache" / "index.json",
                settings,
            )

            payload = json.loads(index_path.read_text(encoding="utf-8"))
            document = payload["documents"][0]
            self.assertEqual(
                document["learning_subjects"][0]["subject_name"],
                "测试动画",
            )
            self.assertIn("内容类型：动漫", document["text"])


class ContentWebJobTests(unittest.TestCase):
    def test_content_job_keeps_existing_api_and_returns_work_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
            )
            profile_path = root / "output" / "work" / "content_profile.md"
            manifest_path = (
                root / "output" / "work" / "content_manifest.json"
            )
            profile_path.parent.mkdir(parents=True)
            profile_path.write_text("# profile", encoding="utf-8")
            manifest_path.write_text("{}", encoding="utf-8")
            state = AppState(settings)
            job = state.jobs.create(
                {
                    "source": "BV1abc123",
                    "mode": "content",
                    "subject_name": "测试动漫",
                    "content_category": "anime",
                    "limit": 10,
                    "v3": False,
                    "build_kb": False,
                }
            )
            pipeline_result = {
                "subject_id": "subject-1",
                "subject_name": "测试动漫",
                "content_category": "anime",
                "content_category_label": "动漫",
                "profile_path": profile_path,
                "manifest_path": manifest_path,
                "success_count": 1,
                "failure_count": 0,
                "knowledge_base_path": None,
                "knowledge_base_status": "not_requested",
                "knowledge_base_skipped_reason": None,
                "video_outputs": [],
            }
            with (
                patch("webapp.server.ensure_platform_authorized"),
                patch(
                    "webapp.server.run_content_pipeline",
                    return_value=pipeline_result,
                ) as run_pipeline,
            ):
                _run_job(state, job["id"])

            updated = state.jobs.get(job["id"])
            self.assertEqual(updated["status"], "done")
            self.assertEqual(updated["result"]["type"], "content_work")
            self.assertEqual(updated["result"]["content_category"], "anime")
            run_pipeline.assert_called_once()
            self.assertEqual(
                run_pipeline.call_args.kwargs["subject_name"],
                "测试动漫",
            )


if __name__ == "__main__":
    unittest.main()
