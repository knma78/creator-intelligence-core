from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import Settings
from downloader.social import (
    SocialVideoDownloader,
    detect_social_platform,
    is_douyin_profile_url,
    is_douyin_video_url,
    is_social_profile_url,
    is_social_video_url,
    is_xiaohongshu_video_url,
)
from downloader.yt_dlp_common import apply_yt_dlp_options
from intelligence.creator_discovery.services import CreatorDiscoveryService
from models import Video
from pipeline.acquire import acquire_video
from webapp.server import _resolve_mode


class SocialUrlTests(unittest.TestCase):
    def test_douyin_video_urls(self) -> None:
        urls = [
            "https://www.douyin.com/video/7123456789012345678",
            "https://v.douyin.com/AbC_123/",
            "https://www.iesdouyin.com/share/video/7123456789012345678/",
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertTrue(is_douyin_video_url(url))
                self.assertEqual(detect_social_platform(url), "douyin")
                self.assertTrue(is_social_video_url(url))

    def test_xiaohongshu_video_urls(self) -> None:
        urls = [
            "https://www.xiaohongshu.com/explore/6411cf99000000001300b6d9",
            "https://www.xiaohongshu.com/discovery/item/674051740000000007027a15",
            "https://xhslink.com/a/AbC123",
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertTrue(is_xiaohongshu_video_url(url))
                self.assertEqual(detect_social_platform(url), "xiaohongshu")

    def test_profile_urls_are_not_treated_as_video(self) -> None:
        self.assertTrue(
            is_social_profile_url(
                "https://www.douyin.com/user/MS4wLjABAAAAExample"
            )
        )
        self.assertTrue(
            is_social_profile_url(
                "https://www.xiaohongshu.com/user/profile/123456789"
            )
        )

    def test_douyin_profile_routes_to_creator_batch(self) -> None:
        source = "https://www.douyin.com/user/MS4wLjABAAAAExample"
        self.assertTrue(is_douyin_profile_url(source))
        self.assertEqual(_resolve_mode(source, "auto"), "up")


class SocialDownloaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.settings = Settings(
            base_dir=root,
            output_dir=root / "output",
            cache_dir=root / "cache",
            logs_dir=root / "logs",
            ffmpeg_path="ffmpeg",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_download_builds_video_and_metadata_without_network(self) -> None:
        url = "https://www.douyin.com/video/7123456789012345678"
        info = {
            "id": "7123456789012345678",
            "title": "测试视频",
            "uploader": "测试作者",
            "duration": 18.5,
            "upload_date": "20260724",
            "formats": [{"url": "https://example.invalid/video.mp4"}],
            "view_count": 100,
        }
        downloader = SocialVideoDownloader("douyin", self.settings)

        def fake_download(_url: str, video_dir: Path) -> None:
            (video_dir / "7123456789012345678.mp4").write_bytes(b"video")

        with (
            patch.object(downloader, "_extract_info", return_value=info),
            patch.object(downloader, "_download_video", side_effect=fake_download),
        ):
            video = downloader.download(url)

        self.assertEqual(video.platform, "douyin")
        self.assertEqual(video.video_id, "DY_7123456789012345678")
        self.assertEqual(video.author, "测试作者")
        self.assertTrue(video.video_path and video.video_path.exists())
        self.assertTrue(video.metadata_path and video.metadata_path.exists())

    def test_pipeline_dispatches_social_url(self) -> None:
        expected = Video(
            source_url="https://xhslink.com/a/AbC123",
            platform="xiaohongshu",
            video_id="XHS_test",
            title="test",
        )
        with patch("pipeline.acquire.SocialVideoDownloader") as downloader_class:
            downloader_class.return_value.download.return_value = expected
            result = acquire_video(expected.source_url, self.settings)

        self.assertIs(result, expected)
        downloader_class.assert_called_once_with("xiaohongshu", self.settings)

    def test_platform_cookie_overrides_generic_cookie(self) -> None:
        platform_cookie = Path(self.temp_dir.name) / "douyin-cookies.txt"
        generic_cookie = Path(self.temp_dir.name) / "generic-cookies.txt"
        platform_cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
        generic_cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
        settings = Settings(
            base_dir=Path(self.temp_dir.name),
            output_dir=Path(self.temp_dir.name) / "output",
            cache_dir=Path(self.temp_dir.name) / "cache",
            logs_dir=Path(self.temp_dir.name) / "logs",
            douyin_cookie_file=str(platform_cookie),
            yt_dlp_cookie_file=str(generic_cookie),
        )
        options = apply_yt_dlp_options({}, settings, "douyin")
        self.assertEqual(options["cookiefile"], str(platform_cookie))


class DiscoveryRoutingTests(unittest.TestCase):
    def test_douyin_candidate_accepts_creator_profile(self) -> None:
        request = CreatorDiscoveryService._build_analysis_request(
            {
                "platform": "douyin",
                "creator_name": "示例作者",
                "source_url": "https://www.douyin.com/user/example",
                "ability": "hook",
            }
        )
        self.assertTrue(request["ready"])
        self.assertEqual(request["mode"], "up")

    def test_social_candidate_uses_video_mode(self) -> None:
        request = CreatorDiscoveryService._build_analysis_request(
            {
                "platform": "xiaohongshu",
                "creator_name": "示例作者",
                "source_url": "https://xhslink.com/a/AbC123",
                "ability": "visual",
            }
        )
        self.assertTrue(request["ready"])
        self.assertEqual(request["mode"], "video")


if __name__ == "__main__":
    unittest.main()
