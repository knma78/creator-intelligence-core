from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from config import Settings
from downloader.bilibili_common import apply_yt_dlp_auth_options
from downloader.platform_auth import (
    ensure_platform_authorized,
    get_platform_auth_status,
    import_platform_cookies,
    manual_cookie_path,
    resolve_authorized_cookie_file,
)
from downloader.yt_dlp_common import apply_yt_dlp_options
from webapp.server import _required_auth_platform


def _cookie_line(domain: str, name: str, value: str = "test-value") -> str:
    return f"{domain}\tTRUE\t/\tTRUE\t2147483647\t{name}\t{value}\n"


class PlatformAuthTests(unittest.TestCase):
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

    def test_bilibili_cookie_import_is_persistent_and_used_by_downloader(self) -> None:
        content = "# Netscape HTTP Cookie File\n" + _cookie_line(
            ".bilibili.com",
            "SESSDATA",
        )
        status = import_platform_cookies("bilibili", content, self.settings)

        expected = manual_cookie_path("bilibili", self.settings)
        self.assertTrue(status["ready"])
        self.assertEqual(status["source"], "manual")
        self.assertEqual(resolve_authorized_cookie_file("bilibili", self.settings), expected)

        options: dict[str, object] = {}
        apply_yt_dlp_auth_options(options, self.settings)
        self.assertEqual(options["cookiefile"], str(expected))

    def test_youtube_cookie_import_is_used_by_video_and_channel_downloaders(self) -> None:
        content = "# Netscape HTTP Cookie File\n" + _cookie_line(
            ".youtube.com",
            "LOGIN_INFO",
        )
        status = import_platform_cookies("youtube", content, self.settings)

        expected = manual_cookie_path("youtube", self.settings)
        self.assertTrue(status["ready"])
        options = apply_yt_dlp_options({}, self.settings, "youtube")
        self.assertEqual(options["cookiefile"], str(expected))

    def test_wrong_platform_cookie_is_rejected(self) -> None:
        content = "# Netscape HTTP Cookie File\n" + _cookie_line(
            ".youtube.com",
            "LOGIN_INFO",
        )
        with self.assertRaisesRegex(ValueError, "B站"):
            import_platform_cookies("bilibili", content, self.settings)
        self.assertFalse(
            get_platform_auth_status("bilibili", self.settings)["ready"]
        )

    def test_unauthorized_platform_is_blocked_before_download(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Cookie 授权"):
            ensure_platform_authorized("youtube", self.settings)

    def test_source_routing_requires_only_bilibili_and_youtube_auth(self) -> None:
        self.assertEqual(
            _required_auth_platform("https://www.bilibili.com/video/BV123"),
            "bilibili",
        )
        self.assertEqual(
            _required_auth_platform("https://www.youtube.com/@veritasium"),
            "youtube",
        )
        self.assertEqual(_required_auth_platform("某个UP名称"), "bilibili")
        self.assertIsNone(
            _required_auth_platform("https://www.douyin.com/user/example")
        )
        self.assertIsNone(_required_auth_platform(r"D:\videos\local.mp4"))


if __name__ == "__main__":
    unittest.main()
