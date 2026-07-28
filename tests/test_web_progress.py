from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from config import Settings
from processor.whisper import WhisperExecution, WhisperProgressMessage
from webapp.server import AppState, _update_job_progress


class WebProgressTests(unittest.TestCase):
    def test_whisper_metadata_is_added_without_changing_job_api(self) -> None:
        root = Path(tempfile.gettempdir()) / "content-research-progress-test"
        settings = Settings(
            base_dir=root,
            output_dir=root / "output",
            cache_dir=root / "cache",
            logs_dir=root / "logs",
        )
        state = AppState(settings)
        job = state.jobs.create({"source": "test"})
        message = WhisperProgressMessage(
            "Whisper 识别中：5/10 秒",
            phase_percent=50,
            state="transcribing",
            execution=WhisperExecution(
                requested_device="auto",
                device="cuda",
                compute_type="float16",
                batch_size=8,
                cpu_threads=4,
                num_workers=1,
                reason="ready",
                gpu_name="Test GPU",
            ),
            processed_seconds=5,
            duration_seconds=10,
        )

        _update_job_progress(
            state,
            job["id"],
            "Whisper识别",
            67,
            message,
        )

        updated = state.jobs.get(job["id"])
        self.assertEqual(updated["progress"], 67)
        self.assertEqual(updated["stage"], "Whisper识别")
        self.assertEqual(updated["logs"][-1], str(message))
        self.assertEqual(
            updated["progress_detail"]["phase_percent"],
            50,
        )
        self.assertEqual(updated["progress_detail"]["device"], "cuda")


if __name__ == "__main__":
    unittest.main()
