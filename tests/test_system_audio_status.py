from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from processor.system_audio import (
    _probe_system_audio_backend_isolated,
    get_system_audio_status,
)


@unittest.skipUnless(__import__("os").name == "nt", "Windows-only audio status")
class SystemAudioStatusIsolationTests(unittest.TestCase):
    def tearDown(self) -> None:
        _probe_system_audio_backend_isolated.cache_clear()

    def test_native_probe_crash_is_reported_without_crashing_parent(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=-1073741819,
            stdout="",
            stderr="",
        )
        with patch("processor.system_audio.subprocess.run", return_value=completed):
            _probe_system_audio_backend_isolated.cache_clear()
            status = get_system_audio_status()

        self.assertFalse(status["available"])
        self.assertIn("0xC0000005", status["reason"])

    def test_successful_probe_payload_is_forwarded(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"available": true, "backend": "test", "device": {"index": 1}}\n',
            stderr="",
        )
        with patch("processor.system_audio.subprocess.run", return_value=completed):
            _probe_system_audio_backend_isolated.cache_clear()
            status = get_system_audio_status()

        self.assertTrue(status["available"])
        self.assertEqual(status["backend"], "test")
        self.assertEqual(status["device"]["index"], 1)
