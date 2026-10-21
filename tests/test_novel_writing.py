from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from config import Settings
from infrastructure.cancellation import JobCancelledError
from integrations.local_skills import (
    get_novel_writing_skill_status,
    load_novel_writing_skill,
)
from pipeline.novel_writing import run_novel_writing
from webapp.server import AppState, _run_job


class NovelWritingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.root = Path(self._temporary_directory.name)
        self.skill_root = self.root / "novel-writing"
        (self.skill_root / "references").mkdir(parents=True)
        (self.skill_root / "scripts").mkdir()
        (self.skill_root / "SKILL.md").write_text(
            "---\n"
            "name: novel-writing\n"
            "description: Local novel workflow\n"
            "---\n"
            "# Workflow\nAlways create original fiction.\n",
            encoding="utf-8",
        )
        (self.skill_root / "references" / "craft-patterns.md").write_text(
            "# Craft patterns\nUse a story contract.\n",
            encoding="utf-8",
        )
        (self.skill_root / "references" / "corpus-observations.md").write_text(
            "# Corpus observations\nUse only aggregate observations.\n",
            encoding="utf-8",
        )
        (self.skill_root / "scripts" / "corpus_metrics.py").write_text(
            "print('metrics')\n",
            encoding="utf-8",
        )

    def settings(self) -> Settings:
        return Settings(
            base_dir=self.root,
            output_dir=self.root / "output",
            cache_dir=self.root / "cache",
            logs_dir=self.root / "logs",
            novel_writing_skill_path=self.skill_root,
            llm_api_key="test-key",
            llm_model="test-model",
        )

    def test_loader_keeps_skill_as_single_source_and_selects_references(self) -> None:
        skill = load_novel_writing_skill(self.skill_root)

        self.assertEqual(skill.name, "novel-writing")
        self.assertIn("Always create original fiction", skill.instructions)
        self.assertEqual(list(skill.references), ["craft-patterns.md"])
        self.assertEqual(skill.scripts[0].name, "corpus_metrics.py")
        self.assertTrue(skill.status()["available"])

        with_corpus = load_novel_writing_skill(
            self.skill_root,
            include_corpus_observations=True,
        )
        self.assertIn("corpus-observations.md", with_corpus.references)

    def test_missing_skill_has_actionable_status(self) -> None:
        status = get_novel_writing_skill_status(self.root / "missing")

        self.assertFalse(status["available"])
        self.assertIn("找不到", status["reason"])

    def test_pipeline_streams_progress_and_writes_auditable_artifacts(self) -> None:
        stream = _FakeStream(["正文" * 80, "\n结尾"])
        client = _FakeOpenAIClient(stream)
        fake_openai = types.SimpleNamespace(OpenAI=lambda **_kwargs: client)
        progress: list[tuple[str, int, str]] = []

        with patch.dict(sys.modules, {"openai": fake_openai}):
            result = run_novel_writing(
                "写一章带悬念钩子的都市小说",
                self.settings(),
                target_length=1000,
                use_corpus_observations=True,
                progress_callback=lambda stage, value, message: progress.append(
                    (stage, value, message)
                ),
            )

        self.assertTrue(result["result_path"].is_file())
        self.assertTrue(result["record_path"].is_file())
        self.assertIn("正文", result["result_path"].read_text(encoding="utf-8"))
        record = json.loads(result["record_path"].read_text(encoding="utf-8"))
        self.assertEqual(record["skill"]["path"], str(self.skill_root.resolve()))
        self.assertTrue(record["used_corpus_observations"])
        self.assertTrue(
            any(getattr(message, "progress_meta", {}).get("type") == "text_generation"
                for _, _, message in progress)
        )
        self.assertTrue(stream.closed)
        self.assertTrue(client.closed)
        self.assertTrue(client.create_kwargs["stream"])

    def test_english_mode_uses_native_prose_contract_and_word_units(self) -> None:
        stream = _FakeStream(
            ["He crossed the empty station before dawn. " * 20]
        )
        client = _FakeOpenAIClient(stream)
        fake_openai = types.SimpleNamespace(OpenAI=lambda **_kwargs: client)

        with patch.dict(sys.modules, {"openai": fake_openai}):
            result = run_novel_writing(
                "按照中国网文升级流写一个英文开篇",
                self.settings(),
                output_language="en-US",
                target_length=1200,
                native_english_review=False,
            )

        prompt = client.create_kwargs["messages"][1]["content"]
        self.assertIn("idiomatic contemporary American English", prompt)
        self.assertIn("Chinese web-serial craft mechanics", prompt)
        self.assertIn("never translate Chinese syntax literally", prompt)
        self.assertEqual(result["output_language"], "en-US")
        self.assertEqual(result["length_unit"], "words")
        record = json.loads(result["record_path"].read_text(encoding="utf-8"))
        self.assertEqual(record["output_language_label"], "English (US)")
        self.assertEqual(record["output_length"], 140)

    def test_british_mode_requires_consistent_british_english(self) -> None:
        stream = _FakeStream(["The colour of the gate changed."])
        client = _FakeOpenAIClient(stream)
        fake_openai = types.SimpleNamespace(OpenAI=lambda **_kwargs: client)

        with patch.dict(sys.modules, {"openai": fake_openai}):
            result = run_novel_writing(
                "写一个英文设定",
                self.settings(),
                output_language="en-GB",
                operation="concept",
                native_english_review=False,
            )

        prompt = client.create_kwargs["messages"][1]["content"]
        self.assertIn("idiomatic contemporary British English", prompt)
        self.assertIn("consistent British spelling", prompt)
        self.assertEqual(result["output_language_label"], "English (UK)")

    def test_pipeline_closes_stream_when_cancelled(self) -> None:
        stream = _FakeStream(["一" * 100, "二" * 100])
        client = _FakeOpenAIClient(stream)
        fake_openai = types.SimpleNamespace(OpenAI=lambda **_kwargs: client)
        checks = 0

        def cancel_requested() -> bool:
            nonlocal checks
            checks += 1
            return checks >= 4

        with patch.dict(sys.modules, {"openai": fake_openai}):
            with self.assertRaises(JobCancelledError):
                run_novel_writing(
                    "写一章小说",
                    self.settings(),
                    cancel_requested=cancel_requested,
                )

        self.assertTrue(stream.closed)
        self.assertTrue(client.closed)

    def test_web_job_reuses_queue_result_and_file_contract(self) -> None:
        settings = self.settings()
        state = AppState(settings)
        self.addCleanup(state.close)
        output_dir = settings.novel_writing_output_dir / "test"
        output_dir.mkdir(parents=True)
        result_path = output_dir / "result.md"
        record_path = output_dir / "request.json"
        result_path.write_text("成品", encoding="utf-8")
        record_path.write_text("{}", encoding="utf-8")
        job = state.jobs.create(
            {
                "source": "写一章小说",
                "mode": "novel",
                "operation": "chapter",
                "output_language": "en-US",
                "target_length": 1000,
            }
        )

        with patch(
            "features.novel.jobs.run_novel_writing",
            return_value={
                "operation": "chapter",
                "operation_label": "章节创作",
                "output_language": "en-US",
                "output_language_label": "English (US)",
                "output_chars": 900,
                "output_length": 180,
                "target_length": 1000,
                "length_unit": "words",
                "result_path": result_path,
                "record_path": record_path,
                "skill": {"name": "novel-writing", "fingerprint": "abc"},
            },
        ) as run:
            _run_job(state, job["id"])

        finished = state.jobs.get(job["id"])
        self.assertEqual(finished["status"], "done")
        self.assertEqual(finished["result"]["type"], "novel_writing")
        self.assertEqual(len(finished["result"]["files"]), 2)
        run.assert_called_once()

    def test_english_review_replaces_draft_and_writes_review_artifacts(self) -> None:
        stream = _FakeStream(["The gate open. He go inside."])
        client = _FakeOpenAIClient(stream)
        fake_openai = types.SimpleNamespace(OpenAI=lambda **_kwargs: client)
        review_result = {
            "schema_version": "1.0",
            "locale": "en-US",
            "review_model": "review-model",
            "skill": {"name": "native-english-fiction-review"},
            "revised": True,
            "original_text": "The gate open. He go inside.",
            "final_text": "The gate opened. He went inside.",
            "initial": {
                "deterministic": {},
                "review": {"score": 70, "decision": "rewrite"},
            },
            "final": {
                "deterministic": {
                    "harper": {"available": False},
                    "readability": {"engine": "builtin-readability-v2"},
                },
                "review": {
                    "score": 91,
                    "decision": "native-ready",
                    "dimensions": {},
                    "issues": [],
                    "revision_priorities": [],
                },
            },
        }

        with (
            patch.dict(sys.modules, {"openai": fake_openai}),
            patch(
                "pipeline.novel_writing.review_english_fiction",
                return_value=review_result,
            ),
            patch(
                "pipeline.novel_writing.render_review_markdown",
                return_value="# Review\nPassed.\n",
            ),
        ):
            result = run_novel_writing(
                "Write an opening chapter",
                self.settings(),
                output_language="en-US",
                target_length=500,
            )

        self.assertEqual(
            result["result_path"].read_text(encoding="utf-8").strip(),
            "The gate opened. He went inside.",
        )
        self.assertTrue(result["original_draft_path"].is_file())
        self.assertTrue(result["review_json_path"].is_file())
        self.assertTrue(result["review_markdown_path"].is_file())
        self.assertEqual(result["native_review"]["score"], 91)
        self.assertTrue(result["native_review"]["revised"])

    def test_ui_exposes_novel_skill_workflow(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        page = (project_root / "webapp" / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        script = (project_root / "webapp" / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('data-panel="novelPanel"', page)
        self.assertIn('id="novelForm"', page)
        self.assertIn('id="novelLanguageInput"', page)
        self.assertIn('value="en-US"', page)
        self.assertIn('value="en-GB"', page)
        self.assertIn('id="novelNativeReviewInput"', page)
        self.assertIn("母语化质检并自动修订", page)
        self.assertIn('mode: "novel"', script)
        self.assertIn("output_language: novelLanguageInput.value", script)
        self.assertIn("native_english_review:", script)
        self.assertIn("renderEnglishReviewStatus", script)
        self.assertIn("text_generation", script)


class _FakeStream:
    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks
        self.closed = False

    def __iter__(self):
        for content in self.chunks:
            delta = types.SimpleNamespace(content=content)
            yield types.SimpleNamespace(
                choices=[types.SimpleNamespace(delta=delta)]
            )

    def close(self) -> None:
        self.closed = True


class _FakeOpenAIClient:
    def __init__(self, stream: _FakeStream) -> None:
        self.stream = stream
        self.create_kwargs: dict = {}
        self.closed = False
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self.create),
        )

    def create(self, **kwargs):
        self.create_kwargs = kwargs
        return self.stream

    def close(self) -> None:
        self.closed = True


if __name__ == "__main__":
    unittest.main()
