from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from exporter.rule_library import build_rule_library


class RuleLibraryTests(unittest.TestCase):
    def test_writes_auditable_rules_and_preserves_rule_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "output"
            cache = root / "cache"
            self._write_sample(
                output,
                "v1",
                author="创作者甲",
                view_count=100,
                hook_style="反常识问题式开头",
            )
            self._write_sample(
                output,
                "v2",
                author="创作者乙",
                view_count=1000,
                hook_style="直接抛出主题",
            )
            payload = {
                "hook_templates": [
                    self._template("hook_contrast_gap", "反差信息缺口"),
                ],
                "workflow_templates": [
                    self._template("workflow_topic_to_script", "选题到脚本工作流"),
                ],
            }

            paths = build_rule_library(
                payload,
                output_root=output,
                cache_root=cache,
            )
            library = json.loads(
                paths["rule_library_json"].read_text(encoding="utf-8")
            )
            contrast_rule = next(
                rule
                for rule in library["rules"]
                if rule["template_id"] == "hook_contrast_gap"
            )
            workflow_rule = next(
                rule
                for rule in library["rules"]
                if rule["template_id"] == "workflow_topic_to_script"
            )

            self.assertEqual(contrast_rule["rule_id"], "R-001")
            self.assertEqual(
                contrast_rule["schema_version"],
                "creator-knowledge-rule/v2",
            )
            self.assertEqual(contrast_rule["status"], "candidate")
            self.assertFalse(contrast_rule["human_reviewed"])
            self.assertEqual(
                contrast_rule["Evidence"]["evidence_type"],
                "direct_pattern_observation",
            )
            self.assertEqual(contrast_rule["Evidence"]["video_ids"], ["v1"])
            self.assertTrue(contrast_rule["Counter Examples"])
            self.assertEqual(library["pattern_count"], 1)
            self.assertEqual(library["observation_count"], 1)
            self.assertEqual(
                library["observation_library"][0]["location"]["precision"],
                "unknown",
            )
            self.assertFalse(
                library["observation_library"][0]["performance_context"][
                    "causal_interpretation_allowed"
                ]
            )
            self.assertEqual(
                contrast_rule["Effect Evidence"]["causal_status"],
                "not_established",
            )
            self.assertLess(
                contrast_rule["Confidence"]["effect_confidence"]["score"],
                contrast_rule["Confidence"]["pattern_confidence"]["score"],
            )
            self.assertEqual(
                workflow_rule["Evidence"]["evidence_type"],
                "synthesized_workflow",
            )
            self.assertLessEqual(workflow_rule["Confidence"]["score"], 0.52)

            markdown = (output / "creator_knowledge_base" / "rules" / "R-001.md").read_text(
                encoding="utf-8"
            )
            for heading in (
                "# Rule ID: R-001",
                "## Trigger（触发条件）",
                "## Goal（传播目标）",
                "## Action（执行动作）",
                "## Constraints（约束）",
                "## Evidence（证据）",
                "## Effect Evidence（效果证据）",
                "## Confidence（置信度）",
                "## Counter Evidence（反证与替代机制）",
                "## Provenance（来源追踪）",
                "## Revision History（修订记录）",
            ):
                self.assertIn(heading, markdown)
            self.assertIn("knowledge_type: transferable_rule", markdown)
            self.assertIn("不是已证实的因果定律", markdown)
            self.assertTrue(
                (
                    output
                    / "creator_knowledge_base"
                    / "rules"
                    / "observations"
                    / "v1.md"
                ).exists()
            )
            self.assertTrue(
                (
                    output
                    / "creator_knowledge_base"
                    / "rules"
                    / "patterns"
                    / "P-R-001.md"
                ).exists()
            )

            review_path = output / "creator_knowledge_base" / "rules" / "rule_reviews.json"
            review_payload = json.loads(review_path.read_text(encoding="utf-8"))
            review_payload["reviews"]["R-001"] = {
                "approved": True,
                "status": "validated",
                "reviewer": "test-reviewer",
                "reviewed_at": "2026-07-28",
                "notes": "人工复核测试",
            }
            review_path.write_text(
                json.dumps(review_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            build_rule_library(payload, output_root=output, cache_root=cache)
            reviewed = json.loads(
                paths["rule_library_json"].read_text(encoding="utf-8")
            )
            reviewed_rule = next(
                rule
                for rule in reviewed["rules"]
                if rule["template_id"] == "hook_contrast_gap"
            )
            self.assertEqual(reviewed_rule["status"], "validated")
            self.assertTrue(reviewed_rule["human_reviewed"])

            payload["hook_templates"].insert(
                0,
                self._template("hook_question_task", "问题任务式开场"),
            )
            build_rule_library(payload, output_root=output, cache_root=cache)
            rebuilt = json.loads(
                paths["rule_library_json"].read_text(encoding="utf-8")
            )
            ids = {
                rule["template_id"]: rule["rule_id"]
                for rule in rebuilt["rules"]
            }
            self.assertEqual(ids["hook_contrast_gap"], "R-001")
            self.assertEqual(ids["workflow_topic_to_script"], "R-002")
            self.assertEqual(ids["hook_question_task"], "R-003")

    @staticmethod
    def _template(template_id: str, name: str) -> dict:
        return {
            "id": template_id,
            "name": name,
            "related_categories": ["Hook"],
            "capability": "建立观看任务",
            "use_when": "存在可验证的开场任务时。",
            "input_slots": ["对象", "问题", "证据"],
            "sequence": ["展示对象", "建立问题", "进入证据"],
            "quality_checks": ["后文能够兑现开场任务"],
            "evidence": {"source_video_ids": ["v1", "v2"]},
            "forbidden": ["复制原文句子"],
        }

    @staticmethod
    def _write_sample(
        output: Path,
        video_id: str,
        author: str,
        view_count: int,
        hook_style: str,
    ) -> None:
        integrated_path = output / "integrated" / "integrated_summary.json"
        if integrated_path.exists():
            integrated = json.loads(integrated_path.read_text(encoding="utf-8"))
        else:
            integrated = {"videos": []}
        integrated["videos"].append(
            {
                "video_id": video_id,
                "author": author,
                "view_count": view_count,
            }
        )
        integrated_path.parent.mkdir(parents=True, exist_ok=True)
        integrated_path.write_text(
            json.dumps(integrated, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        analysis = {
            "video_id": video_id,
            "video_info": {"作者": author, "播放量": view_count},
            "creator_positioning": "Storytelling",
            "content_structure": {
                "Hook": {
                    "style": hook_style,
                    "capability": "快速交代对象和分析任务",
                },
                "高潮": {"design": "把冲突推到最清晰的位置"},
                "结尾": {"design": "用结果完成故事闭环"},
            },
            "expression": {"转场": ["过程推进"]},
        }
        analysis_path = (
            output
            / "creator_knowledge_base"
            / "videos"
            / video_id
            / "analysis.json"
        )
        analysis_path.parent.mkdir(parents=True, exist_ok=True)
        analysis_path.write_text(
            json.dumps(analysis, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
