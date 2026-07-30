from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import Settings
from infrastructure.atomic_io import atomic_write_json, atomic_write_text
from models import (
    PIPELINE_RESULT_SCHEMA_VERSION,
    AnalysisResult,
    Transcript,
    Video,
    build_pipeline_result,
    validate_pipeline_result,
)
from pipeline.registry import SourceHandler, SourceRegistry


class AtomicIoTests(unittest.TestCase):
    def test_atomic_json_replaces_complete_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            atomic_write_json(path, {"version": 1, "value": "完整"})

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"version": 1, "value": "完整"},
            )
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_failed_replace_keeps_previous_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text("previous", encoding="utf-8")

            with patch(
                "infrastructure.atomic_io.os.replace",
                side_effect=OSError("replace failed"),
            ):
                with self.assertRaises(OSError):
                    atomic_write_text(path, "next")

            self.assertEqual(path.read_text(encoding="utf-8"), "previous")
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])


class PipelineContractTests(unittest.TestCase):
    def test_pipeline_contract_adds_version_without_removing_legacy_keys(self) -> None:
        root = Path(tempfile.gettempdir()) / "content-research-contract-test"
        video = Video("local.mp4", "local", "demo", "Demo")
        transcript = Transcript("demo", "text", "local", root / "subtitle.txt")
        analysis = AnalysisResult(
            video_id="demo",
            title="Demo",
            one_sentence_summary="summary",
            hook={},
            structure=[],
            transitions=[],
            emotion={},
            rhythm={},
            keywords=[],
            learnings=[],
        )

        result = build_pipeline_result(
            video=video,
            transcript=transcript,
            analysis=analysis,
            markdown_path=root / "video.md",
            enrichment=None,
        )

        self.assertEqual(result["schema_version"], PIPELINE_RESULT_SCHEMA_VERSION)
        self.assertIs(result["video"], video)
        self.assertIn("markdown_path", result)
        self.assertIs(validate_pipeline_result(dict(result))["analysis"], analysis)

    def test_legacy_pipeline_result_is_normalized(self) -> None:
        root = Path(tempfile.gettempdir()) / "content-research-contract-test"
        video = Video("local.mp4", "local", "demo", "Demo")
        transcript = Transcript("demo", "text", "local", root / "subtitle.txt")
        analysis = AnalysisResult(
            "demo", "Demo", "summary", {}, [], [], {}, {}, [], []
        )
        legacy = {
            "video": video,
            "transcript": transcript,
            "analysis": analysis,
            "markdown_path": root / "video.md",
        }

        normalized = validate_pipeline_result(legacy)

        self.assertEqual(normalized["schema_version"], PIPELINE_RESULT_SCHEMA_VERSION)
        self.assertIsNone(normalized["enrichment"])


class SourceRegistryTests(unittest.TestCase):
    def test_plugin_handler_can_precede_default_without_core_changes(self) -> None:
        registry: SourceRegistry[str, str] = SourceRegistry("test")
        registry.register(SourceHandler("fallback", lambda _source: True, lambda source, context: f"fallback:{context}:{source}"))
        registry.register(SourceHandler("plugin", lambda source: source.startswith("plugin:"), lambda source, context: f"plugin:{context}:{source}"), prepend=True)

        self.assertEqual(
            registry.resolve("plugin:item", "ctx"),
            "plugin:ctx:plugin:item",
        )
        self.assertEqual(registry.keys(), ("plugin", "fallback"))

    def test_matched_handler_error_is_not_rewritten_as_unsupported(self) -> None:
        registry: SourceRegistry[str, str] = SourceRegistry("test")

        def fail(_source: str, _context: str) -> str:
            raise ValueError("downloader validation failed")

        registry.register(SourceHandler("matched", lambda _source: True, fail))

        with self.assertRaisesRegex(ValueError, "downloader validation failed"):
            registry.resolve("item", "ctx")


class SettingsTests(unittest.TestCase):
    def test_new_settings_instance_reads_current_environment(self) -> None:
        with patch.dict(os.environ, {"WHISPER_MODEL": "dynamic-test-model"}):
            settings = Settings()

        self.assertEqual(settings.whisper_model, "dynamic-test-model")


if __name__ == "__main__":
    unittest.main()
