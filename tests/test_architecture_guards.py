from __future__ import annotations

import ast
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
from webapp.job_registry import JobModeRegistry
from features.bootstrap import register_feature_job_modes
from features.contracts import FeatureJobServices


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
        self.assertIn("acquisition", result)
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
        self.assertIsNone(normalized["acquisition"])


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


class JobModeRegistryTests(unittest.TestCase):
    def test_domain_handler_resolves_without_dispatcher_branch(self) -> None:
        registry = JobModeRegistry()
        calls: list[str] = []

        def handler(_state, job_id, _payload, check_cancelled) -> None:
            check_cancelled()
            calls.append(job_id)

        registry.register(" Novel ", handler)
        resolved = registry.resolve("novel")

        self.assertIs(resolved, handler)
        resolved(None, "job-1", {}, lambda: None)
        self.assertEqual(calls, ["job-1"])
        self.assertEqual(registry.modes(), ("novel",))

    def test_duplicate_job_mode_is_rejected(self) -> None:
        registry = JobModeRegistry()

        def handler(_state, _job_id, _payload, _check_cancelled) -> None:
            return None

        registry.register("novel", handler)
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register("NOVEL", handler)


class FeatureBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]

    def test_web_shell_imports_only_the_feature_facade(self) -> None:
        server_path = self.root / "webapp" / "server.py"
        tree = ast.parse(server_path.read_text(encoding="utf-8"))
        forbidden = (
            "pipeline.novel_writing",
            "analyzer.english_fiction_quality",
            "integrations.local_skills",
            "production",
        )
        imports = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ]
        violations = [
            module
            for module in imports
            if any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in forbidden
            )
        ]
        self.assertEqual(violations, [])
        self.assertIn("features.api", imports)
        self.assertIn("features.bootstrap", imports)

    def test_optional_domains_register_through_one_contract(self) -> None:
        registry = JobModeRegistry()
        services = FeatureJobServices(
            update_progress=lambda *_args, **_kwargs: None,
            file_item=lambda label, path: {
                "label": label,
                "path": str(path),
                "url": "",
            },
        )
        register_feature_job_modes(registry, services)
        self.assertEqual(
            set(registry.modes()),
            {"novel", "video_production", "script_video"},
        )

    def test_feature_domains_do_not_import_each_other(self) -> None:
        novel = (self.root / "features" / "novel" / "jobs.py").read_text(
            encoding="utf-8"
        )
        video = (
            self.root / "features" / "video_production" / "jobs.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("features.video_production", novel)
        self.assertNotIn("pipeline.novel_writing", video)
        self.assertNotIn("features.novel", video)

    def test_refactored_monoliths_stay_within_line_budgets(self) -> None:
        budgets = {
            "webapp/server.py": 1900,
            "production/script_video.py": 1400,
            "exporter/rule_library.py": 1550,
        }
        for relative, budget in budgets.items():
            with self.subTest(relative=relative):
                line_count = len(
                    (self.root / relative).read_text(encoding="utf-8").splitlines()
                )
                self.assertLessEqual(line_count, budget)

    def test_douyin_vendor_is_reached_only_through_adapter_boundary(self) -> None:
        allowed = {
            self.root / "config.py",
            self.root / "downloader" / "douyin_adapter.py",
        }
        violations = []
        for path in self.root.rglob("*.py"):
            relative_parts = path.relative_to(self.root).parts
            if (
                path in allowed
                or "integrations" in relative_parts
                or relative_parts[0] in {"cache", "output", "tests", "backups", "restores", ".test-tmp"}
            ):
                continue
            if "douyin-downloader" in path.read_text(
                encoding="utf-8", errors="replace"
            ):
                violations.append(str(path.relative_to(self.root)))
        self.assertEqual(violations, [])


class RequirementsBoundaryTests(unittest.TestCase):
    def test_complete_install_composes_named_dependency_groups(self) -> None:
        root = Path(__file__).resolve().parents[1]
        entries = {
            line.strip()
            for line in (root / "requirements.txt").read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        self.assertEqual(
            entries,
            {
                "-r requirements/core.txt",
                "-r requirements/acquisition.txt",
                "-r requirements/research-ml.txt",
                "-r requirements/gpu-windows.txt",
            },
        )

    def test_heavy_and_platform_dependencies_stay_out_of_core(self) -> None:
        root = Path(__file__).resolve().parents[1]
        core = (root / "requirements" / "core.txt").read_text(
            encoding="utf-8"
        ).lower()
        acquisition = (
            root / "requirements" / "acquisition.txt"
        ).read_text(encoding="utf-8").lower()
        research = (
            root / "requirements" / "research-ml.txt"
        ).read_text(encoding="utf-8").lower()
        gpu = (root / "requirements" / "gpu-windows.txt").read_text(
            encoding="utf-8"
        ).lower()

        self.assertNotIn("open-clip-torch", core)
        self.assertNotIn("chromadb", core)
        self.assertNotIn("nvidia-cublas", core)
        self.assertIn("yt-dlp", acquisition)
        self.assertIn("open-clip-torch", research)
        self.assertIn("nvidia-cublas", gpu)


if __name__ == "__main__":
    unittest.main()
