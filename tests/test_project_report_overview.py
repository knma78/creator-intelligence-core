from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from exporter.project_report import build_project_information_report


class CurrentKnowledgeOverviewTests(unittest.TestCase):
    def test_project_report_writes_current_overview_in_both_formats(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "output"
            creator_root = output / "creator_knowledge_base"
            template_root = creator_root / "templates"
            integrated_root = output / "integrated"
            gap_root = output / "gap_analysis"
            vector_root = root / "cache" / "knowledge_base" / "chroma"
            for path in (
                template_root,
                integrated_root,
                gap_root,
                vector_root,
            ):
                path.mkdir(parents=True, exist_ok=True)

            self._write_json(
                integrated_root / "integrated_summary.json",
                {
                    "summary": {
                        "video_count": 2,
                        "author_count": 1,
                        "up_profile_count": 1,
                        "authors": [
                            {
                                "author": "测试创作者",
                                "video_count": 2,
                                "total_views": 100,
                            }
                        ],
                    }
                },
            )
            self._write_json(
                creator_root / "manifest.json",
                {
                    "creator_count": 1,
                    "video_count": 2,
                    "creators": [
                        {
                            "author": "测试创作者",
                            "positioning": "Storytelling",
                            "video_count": 2,
                        }
                    ],
                },
            )
            self._write_json(
                creator_root / "creator_knowledge_base.json",
                {
                    "capability_documents": [
                        {
                            "category": "Storytelling",
                            "capability": "组织故事任务",
                            "transferable_methods": ["建立任务", "回收结果"],
                            "creators": ["测试创作者"],
                            "source_video_ids": ["v1", "v2"],
                        }
                    ],
                    "rag_index": {"document_count": 1},
                },
            )
            self._write_json(
                creator_root / "cross_creator_analysis.json",
                {
                    "共同结构": ["开场任务", "核心推进", "结尾收束"],
                    "共同特点": ["先建立观看理由"],
                    "共同Hook": [{"item": "问题式开头", "count": 2}],
                    "共同转场": [{"item": "因果收束", "count": 2}],
                },
            )
            self._write_json(
                template_root / "template_library.json",
                {
                    "hook_templates": [{"id": "hook"}],
                    "script_structure_templates": [{"id": "structure"}],
                },
            )
            self._write_json(
                gap_root / "dashboard.json",
                {
                    "knowledge_health": {
                        "overall_score": 50,
                        "ability_count": 2,
                        "mature_count": 1,
                        "missing_count": 1,
                    },
                    "ability_radar": [
                        {"ability_key": "hook", "ability_name": "开场钩子", "score": 100},
                        {"ability_key": "audio", "ability_name": "声音设计", "score": 0},
                    ],
                },
            )
            self._write_json(
                root / "cache" / "knowledge_base" / "index.json",
                {"document_count": 12},
            )
            self._write_json(
                vector_root / "manifest.json",
                {"document_count": 12, "embedding_model": "test-model"},
            )

            result = build_project_information_report(output)
            overview = json.loads(
                result["knowledge_overview_json"].read_text(encoding="utf-8")
            )
            markdown = result["knowledge_overview_markdown"].read_text(encoding="utf-8")

            self.assertEqual(overview["scope"]["video_count"], 2)
            self.assertEqual(overview["scope"]["lexical_rag_document_count"], 12)
            self.assertEqual(overview["scope"]["vector_rag_document_count"], 12)
            self.assertEqual(
                overview["knowledge_health"]["missing_standalone_abilities"][0]["ability_key"],
                "audio",
            )
            self.assertIn("缺失表示尚未形成独立能力模块", markdown)
            self.assertIn("Storytelling", markdown)

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
