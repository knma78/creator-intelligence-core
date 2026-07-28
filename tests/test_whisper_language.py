from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from config import Settings
from models import Video
from pipeline.process import _whisper_language_for_video
from processor.whisper import (
    WhisperExecution,
    WhisperProgressMessage,
    _transcribe_attempt,
)


class WhisperLanguageTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(tempfile.gettempdir()) / "content-research-language-test"
        self.settings = Settings(
            base_dir=root,
            output_dir=root / "output",
            cache_dir=root / "cache",
            logs_dir=root / "logs",
            whisper_language="zh",
            youtube_whisper_language=None,
            douyin_whisper_language="zh",
        )

    def test_platform_language_policy(self) -> None:
        youtube = Video("url", "youtube", "YT_test", "test")
        douyin = Video("url", "douyin", "DY_test", "test")
        bilibili = Video("url", "bilibili", "BV_test", "test")
        self.assertIsNone(_whisper_language_for_video(youtube, self.settings))
        self.assertEqual(_whisper_language_for_video(douyin, self.settings), "zh")
        self.assertEqual(_whisper_language_for_video(bilibili, self.settings), "zh")

    def test_auto_detection_omits_language_argument(self) -> None:
        transcriber = _FakeTranscriber()
        _transcribe_attempt(
            Path("audio.wav"),
            self.settings,
            _execution(),
            {"model": transcriber, "batched": transcriber},
            1,
            None,
            None,
        )
        self.assertNotIn("language", transcriber.kwargs)

    def test_explicit_language_is_forwarded(self) -> None:
        transcriber = _FakeTranscriber()
        _transcribe_attempt(
            Path("audio.wav"),
            self.settings,
            _execution(),
            {"model": transcriber, "batched": transcriber},
            1,
            None,
            "zh",
        )
        self.assertEqual(transcriber.kwargs["language"], "zh")

    def test_progress_messages_include_whisper_phase_metadata(self) -> None:
        transcriber = _ProgressTranscriber()
        events: list[tuple[str, int, str]] = []

        _transcribe_attempt(
            Path("audio.wav"),
            self.settings,
            _execution(),
            {"model": transcriber, "batched": transcriber},
            1,
            lambda stage, percent, message: events.append(
                (stage, percent, message)
            ),
            "zh",
        )

        progress_messages = [
            message
            for _stage, _percent, message in events
            if isinstance(message, WhisperProgressMessage)
            and message.progress_meta["phase_percent"]
        ]
        self.assertTrue(progress_messages)
        self.assertEqual(
            progress_messages[-1].progress_meta["phase_percent"],
            100,
        )
        self.assertEqual(
            progress_messages[-1].progress_meta["device"],
            "cpu",
        )


class _FakeTranscriber:
    def __init__(self) -> None:
        self.kwargs = {}

    def transcribe(self, _path: str, **kwargs):
        self.kwargs = kwargs
        return [], SimpleNamespace(duration=0, language="en")


class _ProgressTranscriber(_FakeTranscriber):
    def transcribe(self, _path: str, **kwargs):
        self.kwargs = kwargs
        segments = [
            SimpleNamespace(start=0, end=5, text="first"),
            SimpleNamespace(start=5, end=10, text="second"),
        ]
        return segments, SimpleNamespace(duration=10, language="zh")


def _execution() -> WhisperExecution:
    return WhisperExecution(
        requested_device="cpu",
        device="cpu",
        compute_type="int8",
        batch_size=1,
        cpu_threads=1,
        num_workers=1,
        reason="test",
    )


if __name__ == "__main__":
    unittest.main()
