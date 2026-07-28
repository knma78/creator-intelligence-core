from __future__ import annotations

import unittest
from unittest.mock import patch

from config import Settings
from processor import whisper


GPU = {
    "name": "Test GPU",
    "total_memory_mb": 8192,
    "free_memory_mb": 6500,
    "utilization": 10,
}


class WhisperRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        whisper.release_whisper_models()

    def tearDown(self) -> None:
        whisper.release_whisper_models()

    def test_auto_mode_uses_gpu_when_runtime_and_resources_are_ready(self) -> None:
        settings = Settings(
            whisper_device="auto",
            whisper_compute_type="auto",
            whisper_batch_size=8,
        )
        with (
            patch.object(whisper, "_configure_cuda_paths", return_value=[]),
            patch.object(whisper, "_query_nvidia_gpu", return_value=GPU),
            patch.object(whisper, "_find_cuda_dll", return_value=None),
            patch.object(whisper, "_CUDA_DLLS", ()),
        ):
            execution, diagnostics = whisper._resolve_execution(settings)

        self.assertEqual(execution.device, "cuda")
        self.assertEqual(execution.compute_type, "float16")
        self.assertEqual(execution.batch_size, 8)
        self.assertTrue(diagnostics["cuda_ready"])

    def test_auto_mode_protects_gpu_when_utilization_is_high(self) -> None:
        settings = Settings(
            whisper_device="auto",
            whisper_gpu_max_utilization=60,
        )
        busy_gpu = {**GPU, "utilization": 90}
        with (
            patch.object(whisper, "_configure_cuda_paths", return_value=[]),
            patch.object(whisper, "_query_nvidia_gpu", return_value=busy_gpu),
            patch.object(whisper, "_find_cuda_dll", return_value=None),
            patch.object(whisper, "_CUDA_DLLS", ()),
        ):
            execution, _ = whisper._resolve_execution(settings)

        self.assertEqual(execution.device, "cpu")
        self.assertEqual(execution.compute_type, "int8")
        self.assertEqual(execution.batch_size, 1)
        self.assertIn("GPU占用", execution.reason)

    def test_auto_mode_uses_cpu_when_cuda_component_is_missing(self) -> None:
        settings = Settings(whisper_device="auto")
        with (
            patch.object(whisper, "_configure_cuda_paths", return_value=[]),
            patch.object(whisper, "_query_nvidia_gpu", return_value=GPU),
            patch.object(whisper, "_find_cuda_dll", return_value=None),
            patch.object(whisper, "_CUDA_DLLS", ("cublas64_12.dll",)),
        ):
            execution, diagnostics = whisper._resolve_execution(settings)

        self.assertEqual(execution.device, "cpu")
        self.assertEqual(diagnostics["missing_cuda_dlls"], ["cublas64_12.dll"])

    def test_batch_candidates_reduce_to_one(self) -> None:
        self.assertEqual(whisper._batch_candidates(8), [8, 4, 2, 1])
        self.assertEqual(whisper._batch_candidates(3), [3, 1])

    def test_nested_sessions_release_only_after_outer_job(self) -> None:
        settings = Settings(whisper_release_after_job=True)
        key = ("small", "cpu", "int8", 4, 1)
        with whisper.whisper_model_session(settings):
            whisper._MODEL_CACHE[key] = {"model": object()}
            with whisper.whisper_model_session(settings):
                self.assertIn(key, whisper._MODEL_CACHE)
            self.assertIn(key, whisper._MODEL_CACHE)

        self.assertNotIn(key, whisper._MODEL_CACHE)


if __name__ == "__main__":
    unittest.main()
