from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from config import Settings
from intelligence.gap_analysis.repository import LocalKnowledgeRepository
from intelligence.gap_analysis.services import GapAnalysisService


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class GapSemanticProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.settings = Settings(
            base_dir=self.root,
            output_dir=self.root / "output",
            cache_dir=self.root / "cache",
            logs_dir=self.root / "logs",
        )
        ability_names = {
            "retention": "观看留存",
            "conflict": "冲突设计",
            "suspense": "悬念设计",
            "humor": "幽默表达",
            "cta": "行动引导",
        }
        write_json(
            self.root / "config" / "AbilityWeight.json",
            {
                "default_weight": 1,
                "abilities": {
                    key: {
                        "display_name": name,
                        "aliases": [],
                    }
                    for key, name in ability_names.items()
                },
            },
        )
        write_json(
            self.root / "config" / "Threshold.json",
            {
                "ability_defaults": {
                    "target_score": 70,
                    "target_coverage": 0.7,
                    "target_reference_count": 1,
                    "target_creator_count": 1,
                    "target_template_count": 1,
                    "min_learning_reference_count": 1,
                    "mature_score": 80,
                    "mature_coverage": 0.8,
                },
                "abilities": {
                    key: {}
                    for key in ability_names
                },
            },
        )
        write_json(
            self.root / "config" / "CreatorWeight.json",
            {},
        )
        write_json(
            self.settings.output_dir
            / "integrated"
            / "integrated_summary.json",
            {
                "videos": [
                    {
                        "video_id": "video-1",
                        "title": "fixture",
                        "author": "Creator",
                    }
                ]
            },
        )
        write_json(
            self.settings.output_dir
            / "video-1"
            / "ability_profile.json",
            {
                "video_id": "video-1",
                "creator_name": "Creator",
                "abilities": [
                    {
                        "ability_key": key,
                        "evidence_count": 1,
                        "mapping_confidence": 0.7,
                        "evidence": [
                            {
                                "source_metric": f"semantic_{key}",
                                "raw_value": {
                                    "evidence_type": (
                                        "design_proxy"
                                        if key == "retention"
                                        else "semantic_signal"
                                    )
                                },
                            }
                        ],
                    }
                    for key in ability_names
                ],
            },
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_gap_analysis_uses_semantic_video_profiles(self) -> None:
        repository = LocalKnowledgeRepository(self.settings)
        dataset = repository.load_dataset()

        for key in ("retention", "conflict", "suspense", "humor", "cta"):
            self.assertEqual(
                dataset.ability_evidence[key].related_videos,
                {"video-1"},
            )

        payload = GapAnalysisService(
            self.settings,
            repository=repository,
        ).run(save=False)
        by_key = {
            item["ability_key"]: item
            for item in payload["ability_ranking"]
        }
        self.assertTrue(
            all(
                by_key[key]["status"] != "missing"
                for key in ("retention", "conflict", "suspense", "humor", "cta")
            )
        )
        self.assertEqual(by_key["retention"]["score"], 61)
        self.assertEqual(by_key["retention"]["status"], "learning")
        self.assertEqual(
            by_key["retention"]["evidence_quality_factor"],
            0.72,
        )
        for key in ("conflict", "suspense", "humor", "cta"):
            self.assertEqual(by_key[key]["score"], 72)
            self.assertEqual(by_key[key]["status"], "usable")
        self.assertEqual(
            payload["source_summary"]["ability_profile_count"],
            1,
        )
        self.assertEqual(
            payload["source_summary"]["semantic_evidence_counts"],
            {
                "retention": 1,
                "conflict": 1,
                "suspense": 1,
                "humor": 1,
                "cta": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()
