from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from config import Settings
from intelligence.ability_ontology.backfill import backfill_video_profiles
from intelligence.ability_ontology.migration import (
    LegacyOntologyMigrator,
    legacy_creator_id,
)
from intelligence.ability_ontology.repository import (
    AbilityOntologyRepository,
)
from intelligence.ability_ontology.reviewer_adapter import (
    OntologyReviewerAdapter,
)
from intelligence.ability_ontology.video_profile import (
    VideoAbilityProfileService,
)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AbilityOntologyMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.settings = Settings(
            base_dir=self.root,
            output_dir=self.root / "output",
            cache_dir=self.root / "cache",
            logs_dir=self.root / "logs",
        )
        self.database_path = (
            self.settings.cache_dir
            / "intelligence"
            / "ability_ontology.sqlite3"
        )
        self.repository = AbilityOntologyRepository(
            self.settings,
            database_path=self.database_path,
        )
        self._write_fixture()
        self.migrator = LegacyOntologyMigrator(
            self.settings,
            repository=self.repository,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_dry_run_is_read_only_and_does_not_create_database(self) -> None:
        before = {
            path: checksum(path)
            for path in self._source_files()
        }

        result = self.migrator.migrate(dry_run=True)

        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(result["database_written"])
        self.assertFalse(self.database_path.exists())
        self.assertEqual(result["counts"]["abilities"], 6)
        self.assertGreaterEqual(result["counts"]["term_mappings"], 8)
        self.assertEqual(
            before,
            {path: checksum(path) for path in self._source_files()},
        )

    def test_migration_builds_versioned_one_to_many_mappings(self) -> None:
        result = self.migrator.migrate()

        self.assertEqual(result["status"], "completed")
        mappings = self.repository.map_term(
            "creator_style",
            "Historical Narrative",
        )
        self.assertEqual(
            {item["ability_key"] for item in mappings},
            {"conflict", "narrative", "storytelling"},
        )
        conflict = self.repository.get_ability("conflict")
        self.assertIsNotNone(conflict)
        self.assertEqual(
            conflict["definition"],
            "Create narrative drive through goals and obstacles.",
        )
        self.assertEqual(len(conflict["evaluation_rules"]), 1)

    def test_legacy_creator_score_keeps_proxy_semantics(self) -> None:
        self.migrator.migrate()

        profile = self.repository.get_creator_profile("Test Creator")

        ability = next(
            item
            for item in profile["abilities"]
            if item["ability_key"] == "storytelling"
        )
        self.assertEqual(ability["ability_key"], "storytelling")
        self.assertEqual(ability["ability_score"], 70)
        self.assertEqual(ability["score_semantics"], "legacy_coverage_proxy")
        self.assertAlmostEqual(ability["confidence"], 0.315)
        self.assertGreaterEqual(ability["evidence_count"], 2)
        conflict = next(
            item
            for item in profile["abilities"]
            if item["ability_key"] == "conflict"
        )
        self.assertIsNone(conflict["ability_score"])
        self.assertEqual(
            conflict["score_semantics"],
            "ontology_evidence_only",
        )

    def test_migration_is_idempotent_and_keeps_legacy_files_unchanged(self) -> None:
        before = {
            path: checksum(path)
            for path in self._source_files()
        }
        first = self.migrator.migrate()
        first_counts = self.repository.table_counts()
        second = self.migrator.migrate()

        self.assertEqual(first["status"], "completed")
        self.assertEqual(second["status"], "skipped")
        self.assertEqual(first_counts, self.repository.table_counts())
        self.assertEqual(first_counts["review_ability_gap"], 0)
        self.assertEqual(
            before,
            {path: checksum(path) for path in self._source_files()},
        )

    def test_video_metric_is_migrated_without_calling_reviewer(self) -> None:
        self.migrator.migrate()

        counts = self.repository.table_counts()

        self.assertEqual(counts["video_ability_observation"], 1)
        self.assertEqual(counts["review_ability_gap"], 0)

    def test_video_profile_separates_scores_from_presence_evidence(self) -> None:
        self.migrator.migrate()
        service = VideoAbilityProfileService(
            self.settings,
            self.repository,
        )

        profile = service.extract(
            {
                "video_id": "video-2",
                "hook": {"评分": 8},
                "one_sentence_summary": "A structured story summary.",
            },
            save=True,
        )

        by_key = {
            item["ability_key"]: item
            for item in profile["abilities"]
        }
        self.assertEqual(by_key["hook"]["ability_score"], 80)
        self.assertEqual(
            by_key["hook"]["score_semantics"],
            "observed_score",
        )
        self.assertIsNone(
            by_key["storytelling"]["ability_score"]
        )
        self.assertEqual(
            by_key["storytelling"]["score_semantics"],
            "ontology_evidence_only",
        )
        self.assertEqual(
            len(self.repository.get_video_observations("video-2")),
            2,
        )

    def test_reviewer_adapter_preserves_original_and_adds_gap_output(self) -> None:
        self.migrator.migrate()
        adapter = OntologyReviewerAdapter(
            self.settings,
            self.repository,
        )
        reviewer_result = {
            "score": 72,
            "dimensions": {
                "Conflict": 4,
                "Information Progression": 8,
            },
            "comment": "legacy reviewer result",
        }
        original = deepcopy(reviewer_result)

        enriched = adapter.enrich(
            reviewer_result,
            {
                "video_id": "video-3",
                "hook": {"评分": 7},
            },
            minimum_score=60,
        )

        self.assertEqual(reviewer_result, original)
        self.assertEqual(enriched["score"], 72)
        extension = enriched["ability_ontology"]
        self.assertEqual(
            {
                item["ability_key"]
                for item in extension["missing_abilities"]
            },
            {"conflict"},
        )
        self.assertEqual(
            {
                item["ability_key"]
                for item in extension["matched_abilities"]
            },
            {"information_progression"},
        )
        self.assertEqual(
            self.repository.table_counts()["review_ability_gap"],
            0,
        )

    def test_backfill_writes_only_additive_profile_file(self) -> None:
        self.migrator.migrate()
        analysis_path = (
            self.settings.output_dir / "video-1" / "analysis.json"
        )
        before = checksum(analysis_path)

        result = backfill_video_profiles(
            self.settings,
            database_path=self.database_path,
        )

        self.assertEqual(result["completed_count"], 1)
        self.assertEqual(checksum(analysis_path), before)
        self.assertTrue(
            (analysis_path.parent / "ability_profile.json").exists()
        )

    def _source_files(self) -> list[Path]:
        return sorted(
            path
            for path in self.root.rglob("*.json")
            if self.settings.cache_dir not in path.parents
        )

    def _write_fixture(self) -> None:
        abilities = {
            "storytelling": self._ability(
                "Storytelling",
                "Organize facts into a story.",
            ),
            "narrative": self._ability(
                "Narrative",
                "Present events in a deliberate order.",
            ),
            "conflict": self._ability(
                "Conflict",
                "Create narrative drive through goals and obstacles.",
            ),
            "humor": self._ability(
                "Humor",
                "Use contrast and timing to create humor.",
            ),
            "hook": self._ability(
                "Hook",
                "Create an early reason to continue watching.",
            ),
            "information_progression": self._ability(
                "Information Progression",
                "Reveal information in useful layers.",
            ),
        }
        write_json(
            self.root / "config" / "AbilityOntology.json",
            {
                "schema_version": 1,
                "ontology_version": "test-1",
                "abilities": abilities,
                "term_mappings": [
                    {
                        "taxonomy_type": "creator_style",
                        "term_name": "Historical Narrative",
                        "targets": [
                            {"ability_key": "narrative", "weight": 1},
                            {"ability_key": "storytelling", "weight": 0.9},
                            {"ability_key": "conflict", "weight": 0.5},
                        ],
                    },
                    {
                        "taxonomy_type": "creator_style",
                        "term_name": "Black Humor",
                        "targets": [
                            {"ability_key": "humor", "weight": 1},
                        ],
                    },
                    {
                        "taxonomy_type": "video_metric",
                        "term_name": "hook_score",
                        "targets": [
                            {
                                "ability_key": "hook",
                                "weight": 1,
                                "confidence": 0.9,
                            }
                        ],
                    },
                    {
                        "taxonomy_type": "video_metric",
                        "term_name": "summary",
                        "targets": [
                            {
                                "ability_key": "storytelling",
                                "weight": 0.5,
                                "confidence": 0.8,
                            }
                        ],
                    },
                    {
                        "taxonomy_type": "reviewer_dimension",
                        "term_name": "Conflict",
                        "targets": [
                            {
                                "ability_key": "conflict",
                                "weight": 1,
                                "confidence": 1,
                            }
                        ],
                    },
                    {
                        "taxonomy_type": "reviewer_dimension",
                        "term_name": "Information Progression",
                        "targets": [
                            {
                                "ability_key": "information_progression",
                                "weight": 1,
                                "confidence": 1,
                            }
                        ],
                    },
                ],
            },
        )
        write_json(
            self.root / "config" / "AbilityWeight.json",
            {
                "abilities": {
                    key: {
                        "display_name": value["ability_name"],
                        "aliases": [],
                    }
                    for key, value in abilities.items()
                },
                "evolution": {"renamed_abilities": {}},
            },
        )
        write_json(
            self.settings.output_dir
            / "integrated"
            / "integrated_summary.json",
            {
                "videos": [
                    {
                        "video_id": "video-1",
                        "author": "Test Creator",
                        "hook_score": 8,
                    }
                ]
            },
        )
        write_json(
            self.settings.output_dir
            / "video-1"
            / "analysis.json",
            {
                "video_id": "video-1",
                "hook": {"评分": 8},
                "one_sentence_summary": "A fixture summary.",
            },
        )
        write_json(
            self.settings.output_dir
            / "creator_knowledge_base"
            / "creator_knowledge_base.json",
            {
                "capability_documents": [
                    {
                        "category": "Historical Narrative",
                        "creators": ["Test Creator"],
                    }
                ]
            },
        )
        write_json(
            self.settings.output_dir
            / "creator_knowledge_base"
            / "templates"
            / "template_library.json",
            {
                "script_structure_templates": [
                    {
                        "id": "template-1",
                        "related_categories": ["Historical Narrative"],
                    }
                ]
            },
        )
        write_json(
            self.settings.output_dir
            / "creator_discovery"
            / "creator_ability_matrix.json",
            [
                {
                    "creator_id": legacy_creator_id(
                        "bilibili",
                        "Test Creator",
                    ),
                    "creator_name": "Test Creator",
                    "platform": "bilibili",
                    "ability": "storytelling",
                    "score": 70,
                    "confidence": 0.9,
                    "last_analyze": "2026-01-01T00:00:00",
                }
            ],
        )
        write_json(
            self.root / "tools" / "creator_specs.json",
            {
                "creators": [
                    {
                        "author": "Test Creator",
                        "primary_categories": [
                            "Historical Narrative",
                            "Black Humor",
                        ],
                    }
                ]
            },
        )

    def _ability(
        self,
        name: str,
        definition: str,
    ) -> dict[str, object]:
        key = name.lower().replace(" ", "_")
        return {
            "ability_id": f"ability.{key}",
            "ability_name": name,
            "definition": definition,
            "evaluation_rules": [
                {
                    "rule_key": "evidence",
                    "rule_text": f"Evidence for {name}",
                    "weight": 1,
                }
            ],
        }


if __name__ == "__main__":
    unittest.main()
