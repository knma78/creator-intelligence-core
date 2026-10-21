from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import Settings
from infrastructure.analytics_store import load_known_video_ids
from infrastructure.creator_progress import CreatorProgressStore
from models import Video
from pipeline.batch import _load_legacy_creator_video_ids, _run_up_pipeline
from webapp.server import AppState, _run_job


UP_SOURCE = "12345"
UP_URL = "https://space.bilibili.com/12345/video"


class CreatorDeduplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.settings = Settings(
            base_dir=root,
            output_dir=root / "output",
            cache_dir=root / "cache",
            logs_dir=root / "logs",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_creator_video_ids(self, video_ids: list[str]) -> None:
        index_path = (
            self.settings.output_dir
            / "up_12345"
            / "creator_video_index.json"
        )
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(
            json.dumps({"schema_version": 1, "video_ids": video_ids}),
            encoding="utf-8",
        )

    def test_existing_latest_video_is_replaced_with_next_unseen_video(self) -> None:
        progress_messages: list[str] = []
        next_url = "https://www.bilibili.com/video/BV_NEXT"
        next_record = {
            "video": Video(
                source_url=next_url,
                platform="bilibili",
                video_id="BV_NEXT",
                title="Next unseen video",
            ),
            "markdown_path": self.settings.output_dir / "BV_NEXT" / "video.md",
        }
        profile_path = self.settings.output_dir / "up_12345" / "up_profile.md"
        self._write_creator_video_ids(["BV_LATEST"])
        with (
            patch("pipeline.batch.BilibiliUPCrawler") as crawler_class,
            patch(
                "pipeline.batch.run_video_pipeline_details",
                return_value=next_record,
            ) as run_video,
            patch("pipeline.batch.build_up_profile", return_value={}),
            patch(
                "pipeline.batch.export_up_profile",
                return_value=profile_path,
            ),
        ):
            crawler_class.return_value.fetch_video_sources.return_value = [
                {
                    "video_id": "BV_LATEST",
                    "source_url": "https://www.bilibili.com/video/BV_LATEST",
                    "title": "Already learned",
                },
                {
                    "video_id": "BV_NEXT",
                    "source_url": next_url,
                    "title": "Next unseen video",
                },
            ]
            result = _run_up_pipeline(
                UP_SOURCE,
                self.settings,
                limit=1,
                progress_callback=lambda _stage, _percent, message: progress_messages.append(message),
            )

        crawler_class.return_value.fetch_video_sources.assert_called_once_with(
            UP_URL,
            21,
        )
        run_video.assert_called_once()
        self.assertEqual(run_video.call_args.args[0], next_url)
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["skipped_existing_count"], 0)
        self.assertEqual(result["video_outputs"][0]["video_id"], "BV_NEXT")
        store = CreatorProgressStore(self.settings.creator_progress_database_path)
        self.assertEqual(
            store.completed_video_ids("bilibili", "up_12345"),
            frozenset({"BV_LATEST", "BV_NEXT"}),
        )
        self.assertTrue(any("正在分析第 1/1 个视频" in item for item in progress_messages))

    def test_legacy_creator_manifest_migrates_only_its_successful_outputs(self) -> None:
        creator_dir = self.settings.output_dir / "up_12345"
        creator_dir.mkdir(parents=True)
        (creator_dir / "batch_manifest.json").write_text(
            json.dumps(
                {
                    "outputs": [{"video_id": "BV_CREATOR_OLD"}],
                    # Previous versions wrote platform-wide skips here. These
                    # are not safe to attribute to this creator.
                    "skipped_existing_video_ids": ["BV_OTHER_UP"],
                }
            ),
            encoding="utf-8",
        )

        self.assertEqual(
            _load_legacy_creator_video_ids(creator_dir),
            {"BV_CREATOR_OLD"},
        )

    def test_web_startup_migrates_legacy_creator_progress_outside_output(self) -> None:
        creator_dir = self.settings.output_dir / "up_12345"
        creator_dir.mkdir(parents=True)
        (creator_dir / "batch_manifest.json").write_text(
            json.dumps(
                {
                    "platform": "bilibili",
                    "source": UP_URL,
                    "outputs": [{"video_id": "BV_OLD_SUCCESS"}],
                    "skipped_existing_video_ids": ["BV_UNATTRIBUTED"],
                }
            ),
            encoding="utf-8",
        )
        state = AppState(self.settings)
        try:
            progress = CreatorProgressStore(
                self.settings.creator_progress_database_path
            )
            self.assertEqual(
                progress.completed_video_ids("bilibili", "up_12345"),
                frozenset({"BV_OLD_SUCCESS"}),
            )
            self.assertFalse(
                self.settings.creator_progress_database_path.is_relative_to(
                    self.settings.output_dir
                )
            )
        finally:
            state.close()

    def test_creator_queue_survives_store_recreation_and_keeps_order(self) -> None:
        store = CreatorProgressStore(self.settings.creator_progress_database_path)
        store.record_candidates(
            "bilibili",
            "up_12345",
            UP_URL,
            [
                {"video_id": "BV_ONE", "source_url": "https://bilibili.com/video/BV_ONE"},
                {"video_id": "BV_TWO", "source_url": "https://bilibili.com/video/BV_TWO"},
                {"video_id": "BV_THREE", "source_url": "https://bilibili.com/video/BV_THREE"},
            ],
            scan_limit=10,
            scan_exhausted=False,
        )
        first = store.pending_videos("bilibili", "up_12345", 1)[0]
        store.mark_processing("bilibili", "up_12345", first["video_id"])
        store.mark_analyzed(
            "bilibili",
            "up_12345",
            first["video_id"],
            first["source_url"],
            first["title"],
        )

        reopened = CreatorProgressStore(self.settings.creator_progress_database_path)
        pending = reopened.pending_videos("bilibili", "up_12345", 2)
        self.assertEqual(
            [item["video_id"] for item in pending],
            ["BV_TWO", "BV_THREE"],
        )
        self.assertEqual(
            reopened.state("bilibili", "up_12345")["scan_limit"],
            10,
        )
        self.assertEqual(
            self.settings.creator_progress_database_path.parent,
            self.settings.base_dir / "state",
        )

    def test_all_creator_videos_known_returns_learning_complete_without_analysis(self) -> None:
        up_dir = self.settings.output_dir / "up_12345"
        up_dir.mkdir(parents=True)
        self._write_creator_video_ids(["BV_ONE", "BV_TWO"])
        existing_profile = up_dir / "up_profile.md"
        existing_profile.write_text("existing profile\n", encoding="utf-8")

        with (
            patch("pipeline.batch.BilibiliUPCrawler") as crawler_class,
            patch("pipeline.batch.run_video_pipeline_details") as run_video,
            patch("pipeline.batch.build_up_profile") as build_profile,
            patch("pipeline.batch.export_up_profile") as export_profile,
        ):
            crawler_class.return_value.fetch_video_sources.return_value = [
                {
                    "video_id": "BV_ONE",
                    "source_url": "https://www.bilibili.com/video/BV_ONE",
                },
                {
                    "video_id": "BV_TWO",
                    "source_url": "https://www.bilibili.com/video/BV_TWO",
                },
            ]
            crawler_class.return_value.last_list_complete = True
            result = _run_up_pipeline(UP_SOURCE, self.settings, limit=1)

        crawler_class.return_value.fetch_video_sources.assert_called_once_with(
            UP_URL,
            22,
        )
        run_video.assert_not_called()
        build_profile.assert_not_called()
        export_profile.assert_not_called()
        self.assertEqual(result["learning_status"], "complete")
        self.assertEqual(result["success_count"], 0)
        self.assertIn("该UP当前可获取", result["status_message"])
        self.assertEqual(existing_profile.read_text(encoding="utf-8"), "existing profile\n")

        manifest = json.loads(
            Path(result["manifest_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["learning_status"], "complete")
        self.assertEqual(manifest["skipped_existing_count"], 2)

    def test_completed_analysis_artifact_is_a_deduplication_fallback(self) -> None:
        analysis_dir = self.settings.output_dir / "BV_DONE"
        analysis_dir.mkdir(parents=True)
        (analysis_dir / "analysis.json").write_text("{}", encoding="utf-8")

        known = load_known_video_ids(self.settings, platform="bilibili")

        self.assertIn("BV_DONE", known)

    def test_incomplete_cached_list_does_not_claim_creator_is_complete(self) -> None:
        up_dir = self.settings.output_dir / "up_12345"
        up_dir.mkdir(parents=True)
        self._write_creator_video_ids(["BV_ONE"])
        existing_profile = up_dir / "up_profile.md"
        existing_profile.write_text("existing profile\n", encoding="utf-8")
        with (
            patch("pipeline.batch.BilibiliUPCrawler") as crawler_class,
            patch("pipeline.batch.run_video_pipeline_details") as run_video,
            patch("pipeline.batch.export_up_profile") as export_profile,
        ):
            crawler_class.return_value.fetch_video_sources.return_value = [
                {
                    "video_id": "BV_ONE",
                    "source_url": "https://www.bilibili.com/video/BV_ONE",
                }
            ]
            crawler_class.return_value.last_list_complete = False
            result = _run_up_pipeline(UP_SOURCE, self.settings, limit=1)

        run_video.assert_not_called()
        export_profile.assert_not_called()
        self.assertEqual(result["learning_status"], "no_unseen_candidates")
        self.assertNotIn("已学习完毕", result["status_message"])
        self.assertIn("请稍后重试", result["status_message"])
        self.assertEqual(existing_profile.read_text(encoding="utf-8"), "existing profile\n")

    def test_web_job_surfaces_learning_complete_without_gap_rebuild(self) -> None:
        manifest_path = self.settings.output_dir / "up_12345" / "batch_manifest.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text("{}", encoding="utf-8")
        state = AppState(self.settings)
        job = state.jobs.create(
            {
                "source": UP_SOURCE,
                "mode": "up",
                "limit": 1,
                "v3": False,
                "build_kb": True,
            }
        )
        pipeline_result = {
            "platform": "bilibili",
            "source": UP_URL,
            "profile_path": None,
            "manifest_path": manifest_path,
            "success_count": 0,
            "failure_count": 0,
            "knowledge_base_path": None,
            "knowledge_base_status": "skipped_already_complete",
            "knowledge_base_skipped_reason": "该UP已学习完毕",
            "video_outputs": [],
            "candidate_count": 12,
            "skipped_existing_count": 12,
            "learning_status": "complete",
            "status_message": "该UP已学习完毕：没有重复下载或分析。",
        }
        with (
            patch("webapp.server.ensure_platform_authorized"),
            patch(
                "webapp.server.run_up_pipeline",
                return_value=pipeline_result,
            ),
            patch("webapp.server._refresh_gap_after_analysis") as refresh_gap,
        ):
            _run_job(state, job["id"])

        updated = state.jobs.get(job["id"])
        self.assertEqual(updated["status"], "done")
        self.assertEqual(updated["stage"], "学习完毕")
        self.assertEqual(updated["result"]["learning_status"], "complete")
        self.assertEqual(updated["result"]["skipped_existing_count"], 12)
        self.assertIn("该UP已学习完毕", updated["result"]["message"])
        self.assertEqual(len(updated["result"]["files"]), 1)
        refresh_gap.assert_not_called()


if __name__ == "__main__":
    unittest.main()
