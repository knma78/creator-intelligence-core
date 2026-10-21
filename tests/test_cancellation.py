from __future__ import annotations

import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from analyzer.llm import analyze_with_llm
from config import Settings
from infrastructure.cancellation import (
    JobCancelledError,
    cancellation_scope,
    run_cancellable_call,
    yt_dlp_cancel_hook,
)
from infrastructure.progress import (
    BatchProgressMessage,
    DownloadProgressMessage,
)
from models import AnalysisResult, Transcript, Video
from processor.ffmpeg import _run_cancellable


class CancellationTests(unittest.TestCase):
    def test_blocking_external_call_does_not_delay_cancellation(self) -> None:
        started = time.monotonic()
        released = threading.Event()
        closed = threading.Event()

        with self.assertRaises(JobCancelledError):
            run_cancellable_call(
                lambda: released.wait(30),
                lambda: time.monotonic() - started >= 0.2,
                on_cancel=lambda: (closed.set(), released.set()),
                poll_seconds=0.05,
            )

        self.assertTrue(closed.is_set())
        self.assertLess(time.monotonic() - started, 1.0)

    def test_ffmpeg_process_is_terminated_promptly(self) -> None:
        started = time.monotonic()

        with self.assertRaises(JobCancelledError):
            _run_cancellable(
                [
                    sys.executable,
                    "-c",
                    "import time; time.sleep(30)",
                ],
                cancel_requested=lambda: time.monotonic() - started >= 0.2,
                poll_seconds=0.05,
            )

        self.assertLess(time.monotonic() - started, 3.0)

    def test_yt_dlp_hook_uses_active_cancellation_scope(self) -> None:
        with cancellation_scope(lambda: True):
            with self.assertRaises(JobCancelledError):
                yt_dlp_cancel_hook({"status": "downloading"})

        yt_dlp_cancel_hook({"status": "downloading"})

    def test_yt_dlp_hook_forwards_visible_download_progress(self) -> None:
        statuses: list[dict] = []
        status = {
            "status": "downloading",
            "downloaded_bytes": 5,
            "total_bytes": 10,
        }

        with cancellation_scope(
            lambda: False,
            yt_dlp_progress=statuses.append,
        ):
            yt_dlp_cancel_hook(status)

        self.assertEqual(statuses, [status])

    def test_batch_progress_message_has_ui_metadata(self) -> None:
        message = BatchProgressMessage(
            "10/40",
            current=10,
            total=40,
        )

        self.assertEqual(message.progress_meta["type"], "batch")
        self.assertEqual(message.progress_meta["phase_percent"], 25.0)
        self.assertTrue(message.progress_meta["heartbeat"])

    def test_download_progress_message_has_speed_and_percent(self) -> None:
        message = DownloadProgressMessage(
            "download",
            downloaded_bytes=5,
            total_bytes=20,
            speed_bytes_per_second=2,
            eta_seconds=7,
            status="downloading",
        )

        self.assertEqual(message.progress_meta["type"], "download")
        self.assertEqual(message.progress_meta["phase_percent"], 25.0)
        self.assertEqual(
            message.progress_meta["speed_bytes_per_second"],
            2.0,
        )

    def test_streaming_llm_closes_response_when_cancelled(self) -> None:
        stream = _FakeStream()
        client = _FakeOpenAIClient(stream)
        fake_openai = types.SimpleNamespace(
            OpenAI=lambda **_kwargs: client,
        )
        checks = 0

        def cancel_requested() -> bool:
            nonlocal checks
            checks += 1
            return checks >= 3

        settings = Settings(
            llm_api_key="test-key",
            llm_model="test-model",
        )
        video = Video(
            source_url="local",
            platform="local",
            video_id="video-1",
            title="title",
        )
        transcript = Transcript(
            video_id="video-1",
            text="transcript",
            source="test",
            text_path=Path("transcript.txt"),
        )
        baseline = AnalysisResult(
            video_id="video-1",
            title="title",
            one_sentence_summary="summary",
            hook={},
            structure=[],
            transitions=[],
            emotion={},
            rhythm={},
            keywords=[],
            learnings=[],
        )

        with patch.dict(sys.modules, {"openai": fake_openai}):
            with self.assertRaises(JobCancelledError):
                analyze_with_llm(
                    video,
                    transcript,
                    baseline,
                    settings,
                    cancel_requested=cancel_requested,
                )

        self.assertTrue(stream.closed)
        self.assertTrue(client.create_kwargs["stream"])


class _FakeStream:
    def __init__(self) -> None:
        self.closed = False

    def __iter__(self):
        delta = types.SimpleNamespace(content='{"title":"done"}')
        yield types.SimpleNamespace(
            choices=[types.SimpleNamespace(delta=delta)]
        )

    def close(self) -> None:
        self.closed = True


class _FakeOpenAIClient:
    def __init__(self, stream: _FakeStream) -> None:
        self.stream = stream
        self.create_kwargs: dict = {}
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self.create),
        )

    def create(self, **kwargs):
        self.create_kwargs = kwargs
        return self.stream


if __name__ == "__main__":
    unittest.main()
