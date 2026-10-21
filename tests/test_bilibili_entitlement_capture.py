from __future__ import annotations

import tempfile
import unittest
from array import array
from pathlib import Path
from unittest.mock import Mock, patch

from config import Settings
from infrastructure.cancellation import JobCancelledError
from downloader.bilibili_entitlement import (
    BilibiliEntitlement,
    BilibiliEntitlementService,
)
from models import (
    AcquisitionStrategy,
    LoginState,
    MediaAvailability,
)
from pipeline.acquire import acquire_video_details
from processor.system_audio import (
    PlaybackCaptureResult,
    SystemAudioDevice,
    capture_system_audio,
)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _Session:
    def get(self, url, params=None, timeout=20):
        if url.endswith("/nav"):
            return _Response(
                {
                    "code": 0,
                    "data": {
                        "isLogin": True,
                        "vipType": 2,
                        "vipStatus": 1,
                        "vipDueDate": 1_800_000_000_000,
                    },
                }
            )
        return _Response(
            {
                "code": 0,
                "result": {
                    "season_title": "测试番剧",
                    "user_status": {"pay": 0},
                    "episodes": [
                        {
                            "id": 123,
                            "bvid": "BVTEST123",
                            "long_title": "第一集",
                            "duration": 1_200_000,
                            "badge": "会员",
                        }
                    ],
                },
            }
        )


class BilibiliEntitlementTests(unittest.TestCase):
    def test_vip_account_and_vip_content_are_independent_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
            )
            with (
                patch(
                    "downloader.bilibili_entitlement.get_platform_auth_status",
                    return_value={"ready": True, "state": "ready", "source": "test"},
                ),
                patch(
                    "downloader.bilibili_entitlement.create_bilibili_session",
                    return_value=_Session(),
                ),
            ):
                result = BilibiliEntitlementService(settings).assess(
                    "https://www.bilibili.com/bangumi/play/ss123"
                )

        self.assertEqual(result.account_tier, "年度大会员")
        self.assertEqual(result.content_requirement, "vip")
        self.assertTrue(result.viewing_eligible)
        self.assertIsNone(result.media_stream_available)
        self.assertEqual(result.duration, 1200)


class _FakeStream:
    def read(self, chunk, exception_on_overflow=False):
        return array("h", [1200] * chunk * 2).tobytes()

    def stop_stream(self):
        pass

    def close(self):
        pass


class _FakeAudio:
    def get_default_wasapi_loopback(self):
        return {
            "index": 10,
            "name": "Fake Speakers [Loopback]",
            "maxInputChannels": 2,
            "defaultSampleRate": 48_000,
        }

    def open(self, **kwargs):
        return _FakeStream()

    def terminate(self):
        pass


class _FakePyAudio:
    paInt16 = 8

    @staticmethod
    def PyAudio():
        return _FakeAudio()

    @staticmethod
    def get_sample_size(_format):
        return 2


class PlaybackCaptureTests(unittest.TestCase):
    def test_cancelled_capture_removes_partial_wave(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
                playback_capture_max_seconds=10,
            )
            output = root / "cancelled.wav"

            with self.assertRaises(JobCancelledError):
                capture_system_audio(
                    output,
                    10,
                    settings,
                    cancel_requested=lambda: True,
                    pyaudio_module=_FakePyAudio,
                )

            self.assertFalse(output.exists())
            self.assertFalse(
                output.with_suffix(".wav.part").exists()
            )

    def test_wasapi_capture_writes_standard_wave_and_levels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
                playback_capture_max_seconds=1,
            )
            output = root / "capture.wav"

            result = capture_system_audio(
                output,
                1,
                settings,
                pyaudio_module=_FakePyAudio,
            )

            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 44)
            self.assertGreater(result.peak_level, 0)
            self.assertFalse(result.likely_silent)

    def test_media_failure_uses_capture_only_after_explicit_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
                playback_capture_warmup_seconds=0,
            )
            entitlement = BilibiliEntitlement(
                source="https://www.bilibili.com/bangumi/play/ss123",
                login_state=LoginState.AUTHENTICATED,
                account_tier="年度大会员",
                account_valid_until="2030-01-01",
                content_id="ep123",
                title="第一集",
                author=None,
                duration=60,
                content_requirement="vip",
                viewing_eligible=True,
                official_subtitle_available=None,
                media_stream_available=None,
                can_direct_download=None,
                recommended_strategy=AcquisitionStrategy.PLATFORM_AUTO,
                reason="eligible",
                evidence={},
            )

            def fake_capture(path, duration, *_args, **_kwargs):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"RIFF" + b"\0" * 100)
                device = SystemAudioDevice(10, "Fake", 2, 48_000)
                return PlaybackCaptureResult(
                    path,
                    duration,
                    device,
                    0.5,
                    0.1,
                    False,
                    False,
                )

            registry = Mock()
            registry.resolve.side_effect = RuntimeError(
                "平台没有向下载器返回媒体流"
            )
            with (
                patch(
                    "pipeline.acquire.BilibiliEntitlementService"
                ) as service_class,
                patch(
                    "pipeline.acquire.get_video_source_registry",
                    return_value=registry,
                ),
                patch("pipeline.acquire.open_playback_source"),
                patch(
                    "pipeline.acquire.capture_system_audio",
                    side_effect=fake_capture,
                ),
            ):
                service_class.return_value.assess.return_value = entitlement
                with self.assertRaisesRegex(
                    RuntimeError,
                    "明确勾选",
                ):
                    acquire_video_details(
                        entitlement.source,
                        settings,
                        allow_playback_capture=False,
                    )
                result = acquire_video_details(
                    entitlement.source,
                    settings,
                    allow_playback_capture=True,
                    capture_duration_seconds=1,
                )

            self.assertEqual(
                result.selected_strategy,
                AcquisitionStrategy.BROWSER_PLAYBACK_CAPTURE,
            )
            self.assertEqual(
                result.assessment.media_availability,
                MediaAvailability.PLAYBACK_AUDIO,
            )
            self.assertTrue(
                Path(
                    result.video.extra_metadata["playback_audio_path"]
                ).exists()
            )


if __name__ == "__main__":
    unittest.main()
