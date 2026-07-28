from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from config import SETTINGS, Settings

from .models import AbilityDefinition, AbilityEvidence, KnowledgeDataset
from .repository import LocalKnowledgeRepository, display_from_key, normalize_ability_key


class GapAnalysisService:
    def __init__(self, settings: Settings = SETTINGS, repository: LocalKnowledgeRepository | None = None) -> None:
        self.settings = settings
        self.repository = repository or LocalKnowledgeRepository(settings)
        self.output_dir = settings.output_dir / "gap_analysis"
        self.history_dir = self.output_dir / "history"

    def run(self, save: bool = True) -> dict[str, Any]:
        dataset = self.repository.load_dataset()
        generated_at = datetime.now().replace(microsecond=0).isoformat()
        ability_stats = self._build_ability_stats(dataset, generated_at)
        ability_ranking = sorted(ability_stats, key=lambda item: (-item["score"], item["ability_name"]))
        gap_ranking = sorted(
            [item for item in ability_stats if item["gap"]["priority_score"] > 0],
            key=lambda item: (-item["gap"]["priority_score"], -item["gap"]["score_gap"], item["ability_name"]),
        )
        recommended_creators = self._recommend_creators_for_gaps(dataset, gap_ranking)
        recommended_videos = self._recommend_videos(dataset, gap_ranking)
        expected_improvement = self._predict_growth(dataset, ability_stats, recommended_videos)
        health = self._build_health(dataset, ability_stats)
        task_priority = self._build_task_priority(gap_ranking, recommended_creators, recommended_videos)
        previous = self._load_previous_latest()
        learning_history = self._build_learning_history(previous, ability_stats)
        dashboard = self._build_dashboard(
            health,
            ability_ranking,
            gap_ranking,
            recommended_creators,
            recommended_videos,
            expected_improvement,
            task_priority,
            learning_history,
        )

        payload = {
            "schema_version": "Knowledge Gap Analysis v1",
            "generated_at": generated_at,
            "rule_first": True,
            "ai_used": False,
            "data_sources": dataset.source_paths,
            "source_summary": dataset.source_summary,
            "knowledge_health": health,
            "ability_ranking": ability_ranking,
            "gap_ranking": gap_ranking,
            "recommended_creator": recommended_creators,
            "recommended_video_count": recommended_videos,
            "expected_improvement": expected_improvement,
            "task_priority": task_priority,
            "dashboard": dashboard,
            "learning_history": learning_history,
            "evolution": self._build_evolution_metadata(dataset),
        }
        if save:
            self._save(payload, dashboard)
        return payload

    def get_gap(self, ability_key: str | None = None) -> dict[str, Any]:
        payload = self.run(save=True)
        if not ability_key:
            return {"generated_at": payload["generated_at"], "gap_ranking": payload["gap_ranking"]}
        key = self._resolve_query_ability(ability_key, payload["ability_ranking"])
        return {
            "generated_at": payload["generated_at"],
            "ability_key": key,
            "gap": [item for item in payload["gap_ranking"] if item["ability_key"] == key],
        }

    def recommend_creator(self, ability_key: str | None = None) -> dict[str, Any]:
        payload = self.run(save=True)
        recommendations = payload["recommended_creator"]
        if not ability_key:
            return {"generated_at": payload["generated_at"], "recommended_creator": recommendations}
        key = self._resolve_query_ability(ability_key, payload["ability_ranking"])
        return {
            "generated_at": payload["generated_at"],
            "ability_key": key,
            "recommended_creator": [item for item in recommendations if item["ability_key"] == key],
        }

    def recommend_video(self, ability_key: str | None = None) -> dict[str, Any]:
        payload = self.run(save=True)
        recommendations = payload["recommended_video_count"]
        if not ability_key:
            return {"generated_at": payload["generated_at"], "recommended_video_count": recommendations}
        key = self._resolve_query_ability(ability_key, payload["ability_ranking"])
        return {
            "generated_at": payload["generated_at"],
            "ability_key": key,
            "recommended_video_count": [item for item in recommendations if item["ability_key"] == key],
        }

    def predict_growth(self, plan: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        payload = self.run(save=True)
        if not plan:
            return {"generated_at": payload["generated_at"], "expected_improvement": payload["expected_improvement"]}
        stats_by_key = {item["ability_key"]: item for item in payload["ability_ranking"]}
        simulated: list[dict[str, Any]] = []
        for item in plan:
            key = normalize_ability_key(str(item.get("ability_key") or item.get("ability") or ""))
            stats = stats_by_key.get(key)
            if not stats:
                continue
            video_count = int(item.get("video_count") or item.get("recommended_video_count") or 0)
            simulated.append(self._predict_one(stats, video_count, payload["source_summary"]))
        return {"generated_at": payload["generated_at"], "expected_improvement": simulated}

    def get_health(self) -> dict[str, Any]:
        payload = self.run(save=True)
        return {"generated_at": payload["generated_at"], "knowledge_health": payload["knowledge_health"]}

    def get_dashboard(self) -> dict[str, Any]:
        payload = self.run(save=True)
        return payload["dashboard"]

    def _build_ability_stats(self, dataset: KnowledgeDataset, generated_at: str) -> list[dict[str, Any]]:
        deleted = {
            normalize_ability_key(str(value))
            for value in ((dataset.ability_weights.get("evolution") or {}).get("deleted_abilities") or [])
        }
        stats: list[dict[str, Any]] = []
        defaults = dataset.thresholds.get("ability_defaults") or {}
        for key, definition in sorted(dataset.ability_definitions.items()):
            if definition.status == "deleted" or key in deleted:
                continue
            evidence = dataset.ability_evidence.get(key, AbilityEvidence(key=key))
            target = self._threshold_for(key, dataset, defaults)
            ref_count = len(evidence.related_videos)
            creator_count = len(evidence.related_creators)
            template_count = len(evidence.related_templates)
            coverage = self._coverage(ref_count, creator_count, template_count, target)
            score = int(round(coverage * 100))
            gap = self._gap(score, coverage, ref_count, target, definition.weight)
            state = self._state(score, coverage, ref_count, target)
            recommended_count = self._recommended_video_count(gap, ref_count, target, dataset)
            stats.append(
                {
                    "ability_key": key,
                    "ability_name": definition.display_name,
                    "score": score,
                    "coverage": round(coverage, 4),
                    "reference_count": ref_count,
                    "related_template_count": template_count,
                    "related_creator_count": creator_count,
                    "related_templates": sorted(evidence.related_templates),
                    "related_creators": sorted(evidence.related_creators),
                    "related_videos": sorted(evidence.related_videos),
                    "related_videos_preview": sorted(evidence.related_videos)[:20],
                    "source_categories": sorted(evidence.source_categories),
                    "evidence_sources": sorted(evidence.evidence_sources),
                    "target": target,
                    "gap": gap,
                    "status": state,
                    "recommended_video_count": recommended_count,
                    "last_update": generated_at,
                }
            )
        return stats

    def _threshold_for(self, key: str, dataset: KnowledgeDataset, defaults: dict[str, Any]) -> dict[str, Any]:
        configured = (dataset.thresholds.get("abilities") or {}).get(key) or {}
        target = {**defaults, **configured}
        return {
            "target_score": int(target.get("target_score", 70)),
            "target_coverage": float(target.get("target_coverage", 0.7)),
            "target_reference_count": int(target.get("target_reference_count", 20)),
            "target_creator_count": int(target.get("target_creator_count", 3)),
            "target_template_count": int(target.get("target_template_count", 2)),
            "min_learning_reference_count": int(target.get("min_learning_reference_count", 1)),
            "mature_score": int(target.get("mature_score", 80)),
            "mature_coverage": float(target.get("mature_coverage", 0.8)),
        }

    def _coverage(self, ref_count: int, creator_count: int, template_count: int, target: dict[str, Any]) -> float:
        ref_ratio = min(ref_count / max(1, int(target["target_reference_count"])), 1.0)
        creator_ratio = min(creator_count / max(1, int(target["target_creator_count"])), 1.0)
        template_ratio = min(template_count / max(1, int(target["target_template_count"])), 1.0)
        return min(1.0, ref_ratio * 0.6 + creator_ratio * 0.25 + template_ratio * 0.15)

    def _gap(
        self,
        score: int,
        coverage: float,
        ref_count: int,
        target: dict[str, Any],
        weight: float,
    ) -> dict[str, Any]:
        score_gap = max(0, int(target["target_score"]) - score)
        coverage_gap = max(0.0, float(target["target_coverage"]) - coverage)
        reference_gap = max(0, int(target["target_reference_count"]) - ref_count)
        reference_gap_ratio = reference_gap / max(1, int(target["target_reference_count"]))
        priority_score = round((score_gap + coverage_gap * 40 + reference_gap_ratio * 30) * weight, 2)
        return {
            "score_gap": score_gap,
            "coverage_gap": round(coverage_gap, 4),
            "reference_gap": reference_gap,
            "priority_score": priority_score,
        }

    def _state(self, score: int, coverage: float, ref_count: int, target: dict[str, Any]) -> str:
        if ref_count < int(target["min_learning_reference_count"]):
            return "missing"
        if (
            score >= int(target["mature_score"])
            and coverage >= float(target["mature_coverage"])
            and ref_count >= int(target["target_reference_count"])
        ):
            return "mature"
        if score >= int(target["target_score"]) and coverage >= float(target["target_coverage"]):
            return "usable"
        return "learning"

    def _recommended_video_count(
        self,
        gap: dict[str, Any],
        ref_count: int,
        target: dict[str, Any],
        dataset: KnowledgeDataset,
    ) -> int:
        if gap["priority_score"] <= 0:
            return 0
        planning = dataset.thresholds.get("planning") or {}
        min_videos = int(planning.get("min_recommended_videos", 5))
        max_videos = int(planning.get("max_recommended_videos", 30))
        target_ratio = float(planning.get("target_gap_ratio", 0.75))
        reference_gap = int(gap["reference_gap"])
        score_gap_count = math.ceil(int(target["target_reference_count"]) * (gap["score_gap"] / 100) * target_ratio)
        suggested = max(reference_gap, score_gap_count, min_videos)
        if ref_count == 0:
            suggested = max(suggested, int(planning.get("default_video_batch", min_videos)))
        return min(max_videos, suggested)

    def _build_health(self, dataset: KnowledgeDataset, ability_stats: list[dict[str, Any]]) -> dict[str, Any]:
        if not ability_stats:
            return {
                "overall_score": 0,
                "status": "empty",
                "ability_count": 0,
                "mature_count": 0,
                "learning_count": 0,
                "missing_count": 0,
                "coverage_average": 0,
            }
        weighted_total = 0.0
        weight_sum = 0.0
        for item in ability_stats:
            definition = dataset.ability_definitions[item["ability_key"]]
            weighted_total += item["score"] * definition.weight
            weight_sum += definition.weight
        overall_score = int(round(weighted_total / max(weight_sum, 1)))
        health_thresholds = dataset.thresholds.get("health") or {}
        if overall_score >= int(health_thresholds.get("excellent", 85)):
            status = "excellent"
        elif overall_score >= int(health_thresholds.get("healthy", 70)):
            status = "healthy"
        elif overall_score >= int(health_thresholds.get("watch", 55)):
            status = "watch"
        else:
            status = "weak"
        return {
            "overall_score": overall_score,
            "status": status,
            "ability_count": len(ability_stats),
            "mature_count": sum(1 for item in ability_stats if item["status"] == "mature"),
            "usable_count": sum(1 for item in ability_stats if item["status"] == "usable"),
            "learning_count": sum(1 for item in ability_stats if item["status"] == "learning"),
            "missing_count": sum(1 for item in ability_stats if item["status"] == "missing"),
            "coverage_average": round(sum(item["coverage"] for item in ability_stats) / len(ability_stats), 4),
            "reference_count_total": sum(item["reference_count"] for item in ability_stats),
            "creator_count_total": len(dataset.creators),
            "video_count_total": len(dataset.videos),
            "template_count_total": len(dataset.templates),
        }

    def _recommend_creators_for_gaps(
        self,
        dataset: KnowledgeDataset,
        gap_ranking: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        max_per_ability = int((dataset.creator_weights.get("recommendation") or {}).get("max_creator_recommendations", 5))
        recommendations: list[dict[str, Any]] = []
        for ability in gap_ranking:
            key = ability["ability_key"]
            evidence = dataset.ability_evidence.get(key, AbilityEvidence(key=key))
            candidates = self._score_creator_candidates(dataset, ability, evidence)[:max_per_ability]
            if not candidates:
                candidates = [
                    {
                        "creator": (dataset.creator_weights.get("recommendation") or {}).get(
                            "discovery_label",
                            "需要寻找合适的UP",
                        ),
                        "creator_type": f"{ability['ability_name']}专项创作者",
                        "category": ability["ability_name"],
                        "score": 0,
                        "current_video_count": 0,
                        "ability_reference_count": 0,
                        "recommendation_type": "creator_discovery_needed",
                        "reason": "本地知识库中还没有创作者为该能力提供足够证据。",
                    }
                ]
            recommendations.append(
                {
                    "ability_key": key,
                    "ability_name": ability["ability_name"],
                    "gap_priority": ability["gap"]["priority_score"],
                    "creators": candidates,
                }
            )
        return recommendations

    def _score_creator_candidates(
        self,
        dataset: KnowledgeDataset,
        ability: dict[str, Any],
        evidence: AbilityEvidence,
    ) -> list[dict[str, Any]]:
        weights = dataset.creator_weights.get("creator_scoring") or {}
        author_refs: dict[str, int] = {}
        for video_id in evidence.related_videos:
            video = dataset.videos.get(video_id)
            if not video or not video.author:
                continue
            author_refs[video.author] = author_refs.get(video.author, 0) + 1
        candidate_names = set(evidence.related_creators) | set(author_refs)
        candidates: list[dict[str, Any]] = []
        target_ref = max(1, int(ability["target"]["target_reference_count"]))
        template_score = min(1.0, ability["related_template_count"] / max(1, int(ability["target"]["target_template_count"])))
        for name in candidate_names:
            creator = dataset.creators.get(name)
            video_count = creator.video_count if creator else author_refs.get(name, 0)
            ref_count = author_refs.get(name, 0)
            reference_share = ref_count / max(1, ability["reference_count"])
            score = (
                float(weights.get("ability_match", 0.45)) * 1.0
                + float(weights.get("reference_share", 0.25)) * min(reference_share * 3, 1.0)
                + float(weights.get("video_count", 0.15)) * min(video_count / target_ref, 1.0)
                + float(weights.get("template_match", 0.1)) * template_score
                + float(weights.get("freshness", 0.05)) * 0.5
            )
            candidates.append(
                {
                    "creator": name,
                    "creator_type": creator.creator_type if creator else "",
                    "category": creator.category if creator else "",
                    "score": round(score * 100, 2),
                    "current_video_count": video_count,
                    "ability_reference_count": ref_count,
                    "recommendation_type": "existing_creator",
                    "reason": "该创作者已在本地知识库中与此能力建立关联。",
                }
            )
        return sorted(candidates, key=lambda item: (-item["score"], -item["ability_reference_count"], item["creator"]))

    def _recommend_videos(
        self,
        dataset: KnowledgeDataset,
        gap_ranking: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        recommendations = []
        for item in gap_ranking:
            count = int(item["recommended_video_count"])
            if count <= 0:
                continue
            recommendations.append(
                {
                    "ability_key": item["ability_key"],
                    "ability_name": item["ability_name"],
                    "recommended_video_count": count,
                    "current_reference_count": item["reference_count"],
                    "target_reference_count": item["target"]["target_reference_count"],
                    "video_type": self._video_type_for(item),
                    "selection_rule": "优先选择推荐创作者中能清晰体现该能力的视频，并跳过知识库中已有的重复主题。",
                }
            )
        return recommendations

    def _video_type_for(self, ability: dict[str, Any]) -> str:
        sources = set(ability.get("evidence_sources") or [])
        if ability["status"] == "missing":
            return f"新增{ability['ability_name']}参考视频"
        if "template_library" not in sources:
            return f"包含可复用模板的{ability['ability_name']}视频"
        return f"来自不同创作者的{ability['ability_name']}视频"

    def _predict_growth(
        self,
        dataset: KnowledgeDataset,
        ability_stats: list[dict[str, Any]],
        recommended_videos: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        plan_by_key = {item["ability_key"]: int(item["recommended_video_count"]) for item in recommended_videos}
        return [
            self._predict_one(item, plan_by_key[item["ability_key"]], dataset.source_summary)
            for item in ability_stats
            if item["ability_key"] in plan_by_key
        ]

    def _predict_one(
        self,
        ability: dict[str, Any],
        video_count: int,
        source_summary: dict[str, Any],
    ) -> dict[str, Any]:
        target = ability["target"]
        current_refs = int(ability["reference_count"])
        target_refs = max(1, int(target["target_reference_count"]))
        base_learning_rate = 0.72
        diminishing_factor = 0.82
        effective_new_refs = video_count * base_learning_rate * (diminishing_factor ** min(current_refs / target_refs, 3))
        predicted_ref_count = current_refs + effective_new_refs
        predicted_creator_count = int(ability["related_creator_count"]) + max(0, math.floor(video_count / 5))
        predicted_template_count = int(ability["related_template_count"]) + (1 if video_count >= 10 else 0)
        predicted_coverage = self._coverage(
            math.ceil(predicted_ref_count),
            predicted_creator_count,
            predicted_template_count,
            target,
        )
        predicted_score = int(round(predicted_coverage * 100))
        return {
            "ability_key": ability["ability_key"],
            "ability_name": ability["ability_name"],
            "current_score": ability["score"],
            "expected_score": max(ability["score"], predicted_score),
            "score_delta": max(0, predicted_score - ability["score"]),
            "current_reference_count": current_refs,
            "expected_reference_count": round(predicted_ref_count, 2),
            "added_video_count": video_count,
            "assumption": "根据参考样本数、创作者多样性和模板证据进行规则模拟。",
            "source_video_count_total": source_summary.get("integrated_video_count") or source_summary.get("manifest_video_count") or 0,
        }

    def _build_task_priority(
        self,
        gap_ranking: list[dict[str, Any]],
        recommended_creators: list[dict[str, Any]],
        recommended_videos: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        creators_by_key = {item["ability_key"]: item for item in recommended_creators}
        videos_by_key = {item["ability_key"]: item for item in recommended_videos}
        tasks: list[dict[str, Any]] = []
        for index, ability in enumerate(gap_ranking[:10], start=1):
            creator_item = creators_by_key.get(ability["ability_key"], {})
            video_item = videos_by_key.get(ability["ability_key"], {})
            first_creator = (creator_item.get("creators") or [{}])[0]
            tasks.append(
                {
                    "priority": index,
                    "ability_key": ability["ability_key"],
                    "ability_name": ability["ability_name"],
                    "status": ability["status"],
                    "priority_score": ability["gap"]["priority_score"],
                    "action": "collect_more_reference_videos" if ability["status"] != "mature" else "monitor",
                    "recommended_creator": first_creator.get("creator", ""),
                    "recommended_video_count": video_item.get("recommended_video_count", 0),
                    "reason": self._task_reason(ability),
                }
            )
        return tasks

    def _task_reason(self, ability: dict[str, Any]) -> str:
        gap = ability["gap"]
        if ability["status"] == "missing":
            return "本地知识库中还没有该能力的可用参考样本。"
        return (
            f"评分缺口 {gap['score_gap']}，覆盖率缺口 {gap['coverage_gap']}，"
            f"参考样本缺口 {gap['reference_gap']}。"
        )

    def _build_dashboard(
        self,
        health: dict[str, Any],
        ability_ranking: list[dict[str, Any]],
        gap_ranking: list[dict[str, Any]],
        recommended_creators: list[dict[str, Any]],
        recommended_videos: list[dict[str, Any]],
        expected_improvement: list[dict[str, Any]],
        task_priority: list[dict[str, Any]],
        learning_history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "knowledge_health": health,
            "ability_radar": [
                {"ability_key": item["ability_key"], "ability_name": item["ability_name"], "score": item["score"]}
                for item in ability_ranking
            ],
            "coverage_heatmap": [
                {
                    "ability_key": item["ability_key"],
                    "ability_name": item["ability_name"],
                    "coverage": item["coverage"],
                    "reference_count": item["reference_count"],
                    "status": item["status"],
                }
                for item in ability_ranking
            ],
            "gap_ranking": [
                {
                    "ability_key": item["ability_key"],
                    "ability_name": item["ability_name"],
                    "score": item["score"],
                    "coverage": item["coverage"],
                    "priority_score": item["gap"]["priority_score"],
                    "reference_gap": item["gap"]["reference_gap"],
                    "status": item["status"],
                }
                for item in gap_ranking[:20]
            ],
            "creator_recommendation": recommended_creators[:10],
            "recommended_video_count": recommended_videos[:20],
            "expected_improvement": expected_improvement[:20],
            "task_priority": task_priority,
            "update_progress": {
                "top_gap_count": len(gap_ranking),
                "planned_video_count": sum(item.get("recommended_video_count", 0) for item in recommended_videos),
                "highest_priority": task_priority[0] if task_priority else None,
            },
            "learning_history": learning_history,
        }

    def _build_learning_history(
        self,
        previous: dict[str, Any] | None,
        ability_stats: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        current_by_key = {item["ability_key"]: item for item in ability_stats}
        history: list[dict[str, Any]] = []
        if previous:
            previous_by_key = {item["ability_key"]: item for item in previous.get("ability_ranking", [])}
            for key, current in current_by_key.items():
                old = previous_by_key.get(key)
                if not old:
                    continue
                score_delta = int(current["score"]) - int(old.get("score", 0))
                reference_delta = int(current["reference_count"]) - int(old.get("reference_count", 0))
                if score_delta or reference_delta:
                    history.append(
                        {
                            "ability_key": key,
                            "ability_name": current["ability_name"],
                            "previous_score": old.get("score", 0),
                            "current_score": current["score"],
                            "score_delta": score_delta,
                            "reference_delta": reference_delta,
                        }
                    )
        snapshot_history = self._load_history_summaries(limit=8)
        return history[:20] + snapshot_history

    def _build_evolution_metadata(self, dataset: KnowledgeDataset) -> dict[str, Any]:
        ability_weights = dataset.ability_weights or {}
        evolution = ability_weights.get("evolution") or {}
        return {
            "history_enabled": bool(evolution.get("history_enabled", True)),
            "ability_count_is_dynamic": True,
            "fixed_ability_count_required": False,
            "aliases_loaded": sum(len(item.aliases) for item in dataset.ability_definitions.values()),
            "renamed_abilities": evolution.get("renamed_abilities", {}),
            "merge_rules": evolution.get("merge_rules", []),
            "split_rules": evolution.get("split_rules", []),
            "deleted_abilities": evolution.get("deleted_abilities", []),
            "database_defined_abilities": [
                key for key, item in dataset.ability_definitions.items() if item.source == "database"
            ],
        }

    def _resolve_query_ability(self, ability_key: str, ability_stats: list[dict[str, Any]]) -> str:
        raw = normalize_ability_key(ability_key)
        by_key = {item["ability_key"]: item["ability_key"] for item in ability_stats}
        by_name = {normalize_ability_key(item["ability_name"]): item["ability_key"] for item in ability_stats}
        return by_key.get(raw) or by_name.get(raw) or raw

    def _save(self, payload: dict[str, Any], dashboard: dict[str, Any]) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        timestamp = payload["generated_at"].replace(":", "").replace("-", "").replace("T", "_")
        latest_path = self.output_dir / "latest.json"
        dashboard_path = self.output_dir / "dashboard.json"
        history_path = self.history_dir / f"{timestamp}.json"
        self._write_json(latest_path, payload)
        self._write_json(dashboard_path, dashboard)
        self._write_json(history_path, payload)

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_previous_latest(self) -> dict[str, Any] | None:
        path = self.output_dir / "latest.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _load_history_summaries(self, limit: int = 8) -> list[dict[str, Any]]:
        if not self.history_dir.exists():
            return []
        summaries: list[dict[str, Any]] = []
        for path in sorted(self.history_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            health = payload.get("knowledge_health") or {}
            summaries.append(
                {
                    "generated_at": payload.get("generated_at", path.stem),
                    "overall_score": health.get("overall_score", 0),
                    "missing_count": health.get("missing_count", 0),
                    "mature_count": health.get("mature_count", 0),
                }
            )
        return summaries
