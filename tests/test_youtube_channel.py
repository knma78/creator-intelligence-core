from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import Settings
from downloader.youtube import (
    is_youtube_channel_url,
    is_youtube_url,
    normalize_youtube_channel_url,
)
from downloader.youtube_channel import YoutubeChannelCrawler
from intelligence.creator_discovery.services import CreatorDiscoveryService
from models import Video
from pipeline.batch import _run_up_pipeline
from webapp.server import _resolve_mode


CHANNEL_URL = "https://www.youtube.com/@veritasium"


class YoutubeChannelUrlTests(unittest.TestCase):
    def test_channel_homepage_is_not_single_video(self) -> None:
        self.assertTrue(is_youtube_channel_url(CHANNEL_URL))
        self.assertFalse(is_youtube_url(CHANNEL_URL))
        self.assertEqual(
            normalize_youtube_channel_url(CHANNEL_URL),
            "https://www.youtube.com/@veritasium/videos",
        )

    def test_supported_channel_variants(self) -> None:
        urls = [
            "https://www.youtube.com/@veritasium/videos",
            "https://youtube.com/channel/UCHnyfMqiRRG1u-2MsSQLbXA",
            "https://www.youtube.com/c/Veritasium/featured",
            "https://www.youtube.com/user/1veritasium",
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertTrue(is_youtube_channel_url(url))

    def test_web_auto_mode_routes_channel_to_batch(self) -> None:
        self.assertEqual(_resolve_mode(CHANNEL_URL, "auto"), "up")


class YoutubeChannelCrawlerTests(unittest.TestCase):
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

    def test_crawler_normalizes_entries_and_caches_list(self) -> None:
        info = {
            "id": "UCHnyfMqiRRG1u-2MsSQLbXA",
            "title": "Veritasium - Videos",
            "entries": [
                {"id": "video_one", "title": "One", "url": "https://www.youtube.com/watch?v=video_one"},
                {"id": "video_two", "title": "Two", "url": "https://www.youtube.com/watch?v=video_two"},
            ],
        }
        crawler = YoutubeChannelCrawler(self.settings)
        with patch.object(crawler, "_extract_channel_info", return_value=info) as extract:
            videos = crawler.fetch_video_sources(CHANNEL_URL, 2)
        self.assertEqual(len(videos), 2)
        self.assertEqual(
            videos[0]["source_url"],
            "https://www.youtube.com/watch?v=video_one",
        )
        extract.assert_called_once_with(
            "https://www.youtube.com/@veritasium/videos",
            2,
        )

        with patch.object(crawler, "_extract_channel_info") as cached_extract:
            cached = crawler.fetch_video_sources(CHANNEL_URL, 2)
        self.assertEqual(cached, videos)
        cached_extract.assert_not_called()

    def test_batch_pipeline_selects_youtube_crawler(self) -> None:
        with (
            patch("pipeline.batch.YoutubeChannelCrawler") as crawler_class,
            patch("pipeline.batch.BilibiliUPCrawler") as bilibili_class,
        ):
            crawler_class.return_value.fetch_video_sources.return_value = []
            result = _run_up_pipeline(CHANNEL_URL, self.settings, limit=2)
        self.assertEqual(result["platform"], "youtube")
        crawler_class.return_value.fetch_video_sources.assert_called_once()
        bilibili_class.assert_not_called()

    def test_all_failed_batch_skips_knowledge_base_update(self) -> None:
        progress_messages: list[str] = []
        profile_path = self.settings.output_dir / "profile.md"
        with (
            patch("pipeline.batch.YoutubeChannelCrawler") as crawler_class,
            patch(
                "pipeline.batch.run_video_pipeline_details",
                side_effect=RuntimeError("HTTP 412"),
            ),
            patch("pipeline.batch.build_up_profile", return_value={}),
            patch("pipeline.batch.export_up_profile", return_value=profile_path),
            patch("rag.knowledge_base.build_knowledge_base") as build_kb,
        ):
            crawler_class.return_value.fetch_video_sources.return_value = [
                {
                    "source_url": "https://www.youtube.com/watch?v=blocked",
                    "title": "Blocked video",
                }
            ]
            result = _run_up_pipeline(
                CHANNEL_URL,
                self.settings,
                limit=1,
                build_kb=True,
                progress_callback=lambda _stage, _percent, message: progress_messages.append(message),
            )

        self.assertEqual(result["success_count"], 0)
        self.assertEqual(result["failure_count"], 1)
        self.assertIsNone(result["knowledge_base_path"])
        self.assertEqual(result["knowledge_base_status"], "skipped_no_success")
        self.assertEqual(
            result["knowledge_base_skipped_reason"],
            "本批次没有成功分析的视频",
        )
        build_kb.assert_not_called()
        self.assertTrue(
            any("已跳过知识库写入" in message for message in progress_messages)
        )

    def test_partial_batch_updates_knowledge_base_with_successes_only(self) -> None:
        progress_messages: list[str] = []
        profile_path = self.settings.output_dir / "profile.md"
        knowledge_base_path = self.settings.knowledge_base_dir / "index.json"
        successful_record = {
            "video": Video(
                source_url="https://www.youtube.com/watch?v=ok",
                platform="youtube",
                video_id="ok",
                title="Successful video",
            ),
            "markdown_path": self.settings.output_dir / "ok" / "video.md",
        }
        with (
            patch("pipeline.batch.YoutubeChannelCrawler") as crawler_class,
            patch(
                "pipeline.batch.run_video_pipeline_details",
                side_effect=[successful_record, RuntimeError("HTTP 412")],
            ),
            patch("pipeline.batch.build_up_profile", return_value={}),
            patch("pipeline.batch.export_up_profile", return_value=profile_path),
            patch(
                "rag.knowledge_base.build_knowledge_base",
                return_value=knowledge_base_path,
            ) as build_kb,
        ):
            crawler_class.return_value.fetch_video_sources.return_value = [
                {
                    "source_url": "https://www.youtube.com/watch?v=ok",
                    "title": "Successful video",
                },
                {
                    "source_url": "https://www.youtube.com/watch?v=blocked",
                    "title": "Blocked video",
                },
            ]
            result = _run_up_pipeline(
                CHANNEL_URL,
                self.settings,
                limit=2,
                build_kb=True,
                progress_callback=lambda _stage, _percent, message: progress_messages.append(message),
            )

        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["failure_count"], 1)
        self.assertEqual(result["knowledge_base_path"], knowledge_base_path)
        self.assertEqual(result["knowledge_base_status"], "updated")
        build_kb.assert_called_once()
        self.assertTrue(
            any("1 个失败视频不会写入" in message for message in progress_messages)
        )


class YoutubeDiscoveryRoutingTests(unittest.TestCase):
    def test_channel_candidate_uses_batch_mode(self) -> None:
        request = CreatorDiscoveryService._build_analysis_request(
            {
                "platform": "youtube",
                "creator_name": "Veritasium",
                "source_url": CHANNEL_URL,
                "ability": "explanation",
            }
        )
        self.assertTrue(request["ready"])
        self.assertEqual(request["mode"], "up")


if __name__ == "__main__":
    unittest.main()
