from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from analyzer.english_fiction_quality import (
    DIMENSION_MAX,
    _normalise_review,
    _parse_harper_json,
    get_english_review_runtime_status,
    review_english_fiction,
    run_deterministic_checks,
)
from config import Settings
from integrations.local_skills import (
    get_native_english_review_skill_status,
    load_native_english_review_skill,
)


class EnglishFictionQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.root = Path(self._temporary_directory.name)
        self.skill_root = self.root / "native-english-fiction-review"
        (self.skill_root / "references").mkdir(parents=True)
        (self.skill_root / "scripts").mkdir()
        (self.skill_root / "SKILL.md").write_text(
            "---\n"
            "name: native-english-fiction-review\n"
            "description: Independent native-English fiction review\n"
            "---\n"
            "# Workflow\nReview independently.\n",
            encoding="utf-8",
        )
        (self.skill_root / "references" / "review-rubric.md").write_text(
            "# Rubric\nScore native prose and preserve web-serial craft.\n",
            encoding="utf-8",
        )

    def settings(self) -> Settings:
        return Settings(
            base_dir=self.root,
            output_dir=self.root / "output",
            cache_dir=self.root / "cache",
            logs_dir=self.root / "logs",
            native_english_review_skill_path=self.skill_root,
            llm_api_key="test-key",
            llm_model="draft-model",
            novel_review_model="review-model",
            english_review_harper_cli_path=str(self.root / "missing-harper-cli.exe"),
        )

    def test_loader_and_status_expose_independent_review_capabilities(self) -> None:
        skill = load_native_english_review_skill(self.skill_root)
        status = get_native_english_review_skill_status(self.skill_root)

        self.assertEqual(skill.name, "native-english-fiction-review")
        self.assertIn("review-rubric.md", skill.references)
        self.assertTrue(status["available"])
        self.assertIn("英语母语自然度审查", status["capabilities"])

    def test_normalisation_caps_scores_and_derives_decision_in_code(self) -> None:
        dimensions = {
            key: {"score": maximum + 100, "rationale": "证据"}
            for key, maximum in DIMENSION_MAX.items()
        }
        result = _normalise_review(
            {
                "dimensions": dimensions,
                "issues": [],
                "blockers": [],
                "human_review_recommended": False,
            },
            "en-US",
        )

        self.assertEqual(result["score"], 100)
        self.assertEqual(result["decision"], "native-ready")
        self.assertFalse(result["human_review_recommended"])

        dimensions["native_fluency"]["score"] = 8
        failed = _normalise_review(
            {
                "dimensions": dimensions,
                "issues": [
                    {
                        "severity": "blocker",
                        "excerpt": "literal phrase",
                        "explanation": "翻译腔",
                        "suggestion": "idiomatic phrase",
                    }
                ],
            },
            "en-US",
        )
        self.assertEqual(failed["decision"], "revise")
        self.assertTrue(failed["blockers"])

    def test_builtin_checks_work_without_optional_packages(self) -> None:
        checks = run_deterministic_checks(
            "Her favourite color was blue. She traveled to the centre.",
            self.settings(),
            locale="en-US",
        )

        self.assertFalse(checks["harper"]["available"])
        self.assertGreater(checks["readability"]["word_count"], 0)
        self.assertIn("flesch_reading_ease", checks["readability"])
        self.assertIn("automated_readability_index", checks["readability"])
        self.assertIn("coleman_liau_index", checks["readability"])
        self.assertIn("gunning_fog_index", checks["readability"])
        self.assertIn("smog_index", checks["readability"])
        self.assertEqual(checks["readability"]["engine"], "builtin-readability-v2")
        self.assertEqual(checks["dialect_fallback"]["finding_count"], 2)

    def test_harper_cli_json_is_normalised(self) -> None:
        findings = _parse_harper_json(
            json.dumps(
                [
                    {
                        "file": "chapter.md",
                        "lint_count": 1,
                        "lints": [
                            {
                                "rule": "AnA",
                                "kind": "Grammar",
                                "span": {"char_start": 8, "char_end": 9},
                                "line": 3,
                                "column": 7,
                                "message": "Did you mean ‘an example’?",
                                "priority": 63,
                                "suggestions": ["Replace with: ‘an’"],
                                "matched_text": "a",
                            }
                        ],
                    }
                ]
            ),
            "This is a example.",
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["line"], 3)
        self.assertEqual(findings[0]["column"], 7)
        self.assertIn("Did you mean", findings[0]["message"])

    def test_blind_review_returns_structured_score_and_closes_stream(self) -> None:
        review_payload = {
            "dimensions": {
                key: {"score": maximum, "rationale": "符合目标"}
                for key, maximum in DIMENSION_MAX.items()
            },
            "blockers": [],
            "issues": [],
            "strengths": ["自然"],
            "revision_priorities": [],
            "human_review_recommended": True,
        }
        stream = _FakeStream([json.dumps(review_payload, ensure_ascii=False)])
        client = _FakeOpenAIClient([stream])
        fake_openai = types.SimpleNamespace(OpenAI=lambda **_kwargs: client)

        with patch.dict(sys.modules, {"openai": fake_openai}):
            result = review_english_fiction(
                "The gate opened. She stepped through without looking back.",
                self.settings(),
                locale="en-US",
                auto_revise=False,
            )

        self.assertEqual(result["final"]["review"]["score"], 100)
        self.assertEqual(result["final"]["review"]["decision"], "native-ready")
        self.assertFalse(result["revised"])
        self.assertTrue(stream.closed)
        self.assertTrue(client.closed)
        self.assertEqual(client.create_kwargs[0]["model"], "review-model")
        self.assertEqual(client.create_kwargs[0]["response_format"], {"type": "json_object"})

    def test_failed_initial_review_is_revised_once_and_rechecked(self) -> None:
        initial = {
            "dimensions": {
                key: {"score": max(0, maximum - 5), "rationale": "需要修订"}
                for key, maximum in DIMENSION_MAX.items()
            },
            "blockers": ["存在翻译腔"],
            "issues": [
                {
                    "severity": "major",
                    "excerpt": "He very angry.",
                    "explanation": "副词位置不自然",
                    "suggestion": "He was furious.",
                }
            ],
            "revision_priorities": ["修正翻译腔"],
        }
        final = {
            "dimensions": {
                key: {"score": maximum, "rationale": "已达到标准"}
                for key, maximum in DIMENSION_MAX.items()
            },
            "blockers": [],
            "issues": [],
            "revision_priorities": [],
        }
        streams = [
            _FakeStream([json.dumps(initial, ensure_ascii=False)]),
            _FakeStream(["He was furious. The door shook when he slammed it."]),
            _FakeStream([json.dumps(final, ensure_ascii=False)]),
        ]
        client = _FakeOpenAIClient(streams)
        fake_openai = types.SimpleNamespace(OpenAI=lambda **_kwargs: client)

        with patch.dict(sys.modules, {"openai": fake_openai}):
            result = review_english_fiction(
                "He very angry. He close the door hard.",
                self.settings(),
                locale="en-US",
                auto_revise=True,
            )

        self.assertTrue(result["revised"])
        self.assertEqual(
            result["final_text"],
            "He was furious. The door shook when he slammed it.",
        )
        self.assertEqual(result["final"]["review"]["decision"], "native-ready")
        self.assertEqual(len(client.create_kwargs), 3)
        self.assertTrue(all(stream.closed for stream in streams))

    def test_runtime_status_reports_missing_optional_engines(self) -> None:
        status = get_english_review_runtime_status(self.settings())

        self.assertTrue(status["available"])
        self.assertTrue(status["skill"]["available"])
        self.assertFalse(status["harper"]["available"])
        self.assertTrue(status["readability"]["available"])
        self.assertTrue(status["readability"]["dependency_free"])


class _FakeStream:
    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks
        self.closed = False

    def __iter__(self):
        for content in self.chunks:
            delta = types.SimpleNamespace(content=content)
            yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta)])

    def close(self) -> None:
        self.closed = True


class _FakeOpenAIClient:
    def __init__(self, streams: list[_FakeStream]) -> None:
        self.streams = list(streams)
        self.create_kwargs: list[dict] = []
        self.closed = False
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self.create),
        )

    def create(self, **kwargs):
        self.create_kwargs.append(kwargs)
        return self.streams.pop(0)

    def close(self) -> None:
        self.closed = True


if __name__ == "__main__":
    unittest.main()
