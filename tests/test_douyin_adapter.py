from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import Settings
from downloader.douyin_adapter import (
    DouyinAdapter,
    DouyinAdapterTimeout,
    extract_douyin_url,
    get_douyin_status,
)
from downloader.social import SocialVideoDownloader


class DouyinAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        adapter_root = root / "adapter"
        adapter_root.mkdir()
        (adapter_root / "run.py").write_text("", encoding="utf-8")
        self.settings = Settings(
            base_dir=root,
            output_dir=root / "output",
            cache_dir=root / "cache",
            logs_dir=root / "logs",
            douyin_adapter_root=str(adapter_root),
        )
        cookie_path = self.settings.douyin_cache_dir / "cookies.json"
        cookie_path.parent.mkdir(parents=True)
        cookie_path.write_text(
            json.dumps(
                {
                    "ttwid": "test-ttwid",
                    "odin_tt": "test-odin",
                    "passport_csrf_token": "test-csrf",
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_extracts_url_from_share_text(self) -> None:
        text = "复制此链接打开抖音 https://v.douyin.com/AbC123/ 一起看"
        self.assertEqual(
            extract_douyin_url(text),
            "https://v.douyin.com/AbC123/",
        )

    def test_status_reports_adapter_and_login_ready(self) -> None:
        status = get_douyin_status(self.settings)
        self.assertTrue(status["ready"])
        self.assertTrue(status["adapter_available"])

    def test_profile_download_converts_adapter_files_to_videos(self) -> None:
        adapter = DouyinAdapter(self.settings)

        def fake_run(_config_path: Path, _cookies: dict[str, str], _job_dir: Path) -> None:
            media_dir = self.settings.douyin_cache_dir / "media" / "SEC_TEST"
            media_dir.mkdir(parents=True, exist_ok=True)
            for index, source_id in enumerate(("7600000000000000001", "7600000000000000002")):
                (media_dir / f"{source_id}.mp4").write_bytes(b"video")
                (media_dir / f"{source_id}_data.json").write_text(
                    json.dumps(
                        {
                            "aweme_id": source_id,
                            "desc": f"测试视频 {index}",
                            "create_time": 1785000000 + index,
                            "author": {
                                "nickname": "测试作者",
                                "sec_uid": "SEC_TEST",
                            },
                            "video": {"duration": 12000},
                            "statistics": {"play_count": 100 + index},
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

        with patch.object(adapter, "_run_adapter", side_effect=fake_run):
            videos = adapter.download(
                "https://www.douyin.com/user/SEC_TEST",
                limit=2,
            )

        self.assertEqual(len(videos), 2)
        self.assertEqual(videos[0].platform, "douyin")
        self.assertEqual(videos[0].duration, 12)
        self.assertTrue(videos[0].video_path and videos[0].video_path.exists())
        self.assertTrue(videos[0].metadata_path and videos[0].metadata_path.exists())

    def test_timeout_recovers_completed_videos_from_cache(self) -> None:
        adapter = DouyinAdapter(self.settings)

        def timed_out_run(
            _config_path: Path,
            _cookies: dict[str, str],
            _job_dir: Path,
        ) -> None:
            media_dir = self.settings.douyin_cache_dir / "media" / "SEC_TEST"
            media_dir.mkdir(parents=True, exist_ok=True)
            source_id = "7600000000000000001"
            (media_dir / f"{source_id}.mp4").write_bytes(b"complete-video")
            (media_dir / f"{source_id}.mp4.tmp").write_bytes(b"incomplete-video")
            (media_dir / f"{source_id}_data.json").write_text(
                json.dumps(
                    {
                        "aweme_id": source_id,
                        "desc": "已完成视频",
                        "author": {"nickname": "测试作者", "sec_uid": "SEC_TEST"},
                        "video": {"duration": 12000},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            raise DouyinAdapterTimeout("timeout")

        with patch.object(adapter, "_run_adapter", side_effect=timed_out_run):
            videos = adapter.download(
                "https://www.douyin.com/user/SEC_TEST",
                limit=2,
            )

        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0].title, "已完成视频")
        self.assertIsNotNone(adapter.last_warning)
        self.assertIn("已回收 1 个完整视频继续分析", adapter.last_warning or "")

    def test_timeout_without_complete_video_remains_an_error(self) -> None:
        adapter = DouyinAdapter(self.settings)
        with (
            patch.object(
                adapter,
                "_run_adapter",
                side_effect=DouyinAdapterTimeout("timeout"),
            ),
            self.assertRaisesRegex(RuntimeError, "没有可继续分析的完整视频"),
        ):
            adapter.download(
                "https://www.douyin.com/user/SEC_TEST",
                limit=2,
            )

    def test_social_downloader_uses_ready_adapter(self) -> None:
        video = self._sample_video()
        with patch("downloader.social.DouyinAdapter") as adapter_class:
            adapter_class.return_value.ready = True
            adapter_class.return_value.download.return_value = [video]
            result = SocialVideoDownloader("douyin", self.settings).download(
                "https://www.douyin.com/video/7600000000000000001"
            )
        self.assertIs(result, video)

    def _sample_video(self):
        from models import Video

        return Video(
            source_url="https://www.douyin.com/video/7600000000000000001",
            platform="douyin",
            video_id="DY_7600000000000000001",
            title="test",
        )


if __name__ == "__main__":
    unittest.main()
