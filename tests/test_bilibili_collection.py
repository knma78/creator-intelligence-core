from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from config import Settings
from downloader.bilibili import BilibiliDownloader
from downloader.bilibili_collection import (
    BilibiliCollection,
    BilibiliCollectionCrawler,
    is_bilibili_collection_url,
)
from downloader.bilibili_common import (
    apply_yt_dlp_auth_options,
    humanize_bilibili_error,
)
from pipeline.content import resolve_content_sources
from webapp.server import _resolve_mode


class BilibiliCollectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.settings = Settings(
            base_dir=root,
            output_dir=root / "output",
            cache_dir=root / "cache",
            logs_dir=root / "logs",
            bilibili_download_attempts=2,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_season_and_media_urls_are_collections(self) -> None:
        self.assertTrue(
            is_bilibili_collection_url(
                "https://www.bilibili.com/bangumi/play/ss231450?theme=movie"
            )
        )
        self.assertTrue(
            is_bilibili_collection_url(
                "https://www.bilibili.com/bangumi/media/md12345"
            )
        )
        self.assertFalse(
            is_bilibili_collection_url(
                "https://www.bilibili.com/bangumi/play/ep4448895"
            )
        )

    def test_auto_mode_routes_season_page_to_content_pipeline(self) -> None:
        source = (
            "https://www.bilibili.com/bangumi/play/ss231450"
            "?theme=movie"
        )

        self.assertEqual(_resolve_mode(source, "auto"), "content")
        self.assertEqual(_resolve_mode(source, "video"), "content")

    def test_collection_crawler_expands_flat_entries_to_episode_urls(self) -> None:
        ydl = MagicMock()
        ydl.extract_info.return_value = {
            "_type": "playlist",
            "id": "231450",
            "title": "寒战1994",
            "description": "电影简介",
            "entries": [
                {
                    "id": "4448895",
                    "url": (
                        "https://www.bilibili.com/bangumi/play/"
                        "ep4448895?theme=movie"
                    ),
                },
                {
                    "id": "4918412",
                    "url": (
                        "https://www.bilibili.com/bangumi/play/"
                        "ep4918412?theme=movie"
                    ),
                },
            ],
        }
        manager = MagicMock()
        manager.__enter__.return_value = ydl
        fake_module = SimpleNamespace(YoutubeDL=MagicMock(return_value=manager))
        source = (
            "https://www.bilibili.com/bangumi/play/ss231450"
            "?theme=movie"
        )

        with patch.dict("sys.modules", {"yt_dlp": fake_module}):
            result = BilibiliCollectionCrawler(
                self.settings
            ).fetch_video_sources(source, limit=1)

        self.assertEqual(result.title, "寒战1994")
        self.assertEqual(result.category_hint, "movie")
        self.assertEqual(len(result.videos), 1)
        self.assertIn("ep4448895", result.videos[0]["source_url"])

    def test_content_resolution_uses_collection_title_and_limit(self) -> None:
        source = "https://www.bilibili.com/bangumi/play/ss231450"
        collection = BilibiliCollection(
            source_url=source,
            title="寒战1994",
            description="",
            category_hint="movie",
            videos=[
                {"source_url": "https://www.bilibili.com/bangumi/play/ep1"},
                {"source_url": "https://www.bilibili.com/bangumi/play/ep2"},
            ],
        )
        with patch(
            "pipeline.content.BilibiliCollectionCrawler.fetch_video_sources",
            return_value=collection,
        ):
            result = resolve_content_sources(
                [source],
                self.settings,
                limit=1,
            )

        self.assertEqual(result.collection_title, "寒战1994")
        self.assertEqual(result.category_hint, "movie")
        self.assertEqual(
            result.video_sources,
            ["https://www.bilibili.com/bangumi/play/ep1"],
        )


class BilibiliRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(tempfile.gettempdir()) / "content-research-bili-retry"
        self.settings = Settings(
            base_dir=root,
            output_dir=root / "output",
            cache_dir=root / "cache",
            logs_dir=root / "logs",
            bilibili_download_attempts=2,
            bilibili_download_retries=7,
            bilibili_fragment_retries=11,
            bilibili_socket_timeout=25,
            bilibili_http_chunk_size=5_000_000,
        )

    def test_common_options_enable_resume_and_fragment_retries(self) -> None:
        options: dict[str, object] = {}

        apply_yt_dlp_auth_options(options, self.settings)

        self.assertEqual(options["retries"], 7)
        self.assertEqual(options["fragment_retries"], 11)
        self.assertEqual(options["socket_timeout"], 25)
        self.assertEqual(options["http_chunk_size"], 5_000_000)
        self.assertTrue(options["continuedl"])

    def test_whole_download_retries_transient_reset(self) -> None:
        failed_ydl = MagicMock()
        failed_ydl.download.side_effect = RuntimeError(
            "Connection broken: ConnectionResetError(10054)"
        )
        successful_ydl = MagicMock()
        first_manager = MagicMock()
        first_manager.__enter__.return_value = failed_ydl
        second_manager = MagicMock()
        second_manager.__enter__.return_value = successful_ydl
        fake_module = SimpleNamespace(
            YoutubeDL=MagicMock(
                side_effect=[first_manager, second_manager]
            )
        )

        with patch("downloader.bilibili.sleep_with_cancellation"):
            BilibiliDownloader(self.settings)._run_ytdlp_download(
                fake_module,
                {},
                "https://www.bilibili.com/bangumi/play/ep4448895",
            )

        self.assertEqual(fake_module.YoutubeDL.call_count, 2)
        successful_ydl.download.assert_called_once()

    def test_connection_reset_has_actionable_message(self) -> None:
        message = humanize_bilibili_error(
            RuntimeError("Connection broken: ConnectionResetError(10054)")
        )

        self.assertIn("自动重试", message)
        self.assertIn("断点", message)

    def test_geo_restriction_is_not_misreported_as_http_412(self) -> None:
        message = humanize_bilibili_error(
            RuntimeError(
                "This video is not available from your location due to "
                "geo restriction (expected status 412)"
            )
        )

        self.assertIn("不代表你的大会员失效", message)
        self.assertIn("受保护", message)
        self.assertNotIn("HTTP 412", message)


if __name__ == "__main__":
    unittest.main()
