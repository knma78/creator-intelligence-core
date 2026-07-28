from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from config import SETTINGS, Settings

from .repository import (
    AbilityOntologyRepository,
    normalize_term,
    stable_id,
)


ANALYSIS_METRICS: dict[str, tuple[tuple[str, ...], ...]] = {
    "hook_score": (("hook", "评分"), ("hook", "score"), ("hook_score",)),
    "hook_style": (
        ("hook", "开头方式"),
        ("hook", "style"),
        ("hook_style",),
    ),
    "rhythm_peak": (
        ("rhythm", "高潮位置"),
        ("rhythm", "peak"),
        ("rhythm_peak",),
    ),
    "rhythm_change": (
        ("rhythm", "节奏变化"),
        ("rhythm", "change"),
        ("rhythm_change",),
    ),
    "transitions": (("transitions",),),
    "emotion": (("emotion",),),
    "keyword_counts": (("keywords",), ("keyword_counts",)),
    "title_patterns": (("title_patterns",),),
    "cover_ocr": (("cover_ocr",),),
    "cover_dominant_colors": (("cover_dominant_colors",),),
    "learnings": (("learnings",),),
    "summary": (("one_sentence_summary",), ("summary",)),
    "comments_sentiment": (
        ("comments_analysis", "sentiment"),
        ("comments_sentiment",),
    ),
}


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def has_value(value: Any) -> bool:
    if value is None or value == "" or value == [] or value == {}:
        return False
    if isinstance(value, (int, float)) and value == 0:
        return False
    return True


class VideoAbilityProfileService:
    def __init__(
        self,
        settings: Settings = SETTINGS,
        repository: AbilityOntologyRepository | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository or AbilityOntologyRepository(settings)
        self._term_mapping_cache: dict[
            tuple[str, str],
            list[dict[str, Any]],
        ] = {}

    def extract(
        self,
        analysis: dict[str, Any],
        *,
        v3: dict[str, Any] | None = None,
        creator_name: str = "",
        source_analysis_ref: str = "",
        save: bool = False,
        extra_observations: Iterable[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        video_id = str(
            analysis.get("video_id")
            or (v3 or {}).get("video_id")
            or ""
        ).strip()
        if not video_id:
            raise ValueError("video_id is required to build a video ability profile")
        ontology_version = self.repository.latest_ontology_version()
        if not ontology_version:
            raise RuntimeError(
                "Ability Ontology database is not initialized. Run the "
                "ontology migration first."
            )
        author = str(
            creator_name
            or analysis.get("author")
            or (v3 or {}).get("author")
            or ""
        )
        observations = self._extract_observations(
            video_id,
            author,
            analysis,
            v3 or {},
            source_analysis_ref,
            ontology_version,
        )
        observations.extend(list(extra_observations or []))
        observations = self._deduplicate_observations(observations)
        if save:
            self.repository.save_video_observations(
                observations,
                ontology_version,
            )
        return self.build_profile(
            video_id,
            observations,
            ontology_version=ontology_version,
            creator_name=author,
        )

    def build_profile(
        self,
        video_id: str,
        observations: list[dict[str, Any]],
        *,
        ontology_version: str | None = None,
        creator_name: str = "",
    ) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for observation in observations:
            grouped[str(observation["ability_id"])].append(observation)
        abilities: list[dict[str, Any]] = []
        for ability_id, items in grouped.items():
            first = items[0]
            scored = [
                item
                for item in items
                if item.get("observed_score") is not None
            ]
            score = None
            score_confidence = 0.0
            if scored:
                total_weight = sum(
                    max(0.01, float(item["confidence"]))
                    for item in scored
                )
                score = round(
                    sum(
                        float(item["observed_score"])
                        * max(0.01, float(item["confidence"]))
                        for item in scored
                    )
                    / total_weight,
                    2,
                )
                score_confidence = self._combined_confidence(
                    float(item["confidence"]) for item in scored
                )
            abilities.append(
                {
                    "ability_id": ability_id,
                    "ability_key": first["ability_key"],
                    "ability_name": first["ability_name"],
                    "ability_score": score,
                    "score_confidence": score_confidence,
                    "mapping_confidence": self._combined_confidence(
                        float(item["confidence"]) for item in items
                    ),
                    "evidence_count": len(items),
                    "score_semantics": (
                        "observed_score"
                        if scored
                        else "ontology_evidence_only"
                    ),
                    "evidence": [
                        {
                            "source_metric": item["source_metric"],
                            "raw_value": item.get("raw_value"),
                            "observed_score": item.get("observed_score"),
                            "confidence": item["confidence"],
                        }
                        for item in items
                    ],
                }
            )
        abilities.sort(
            key=lambda item: (
                item["ability_score"] is None,
                -float(item["ability_score"] or 0),
                item["ability_key"],
            )
        )
        return {
            "schema_version": "Video Ability Profile v1",
            "ontology_version": (
                ontology_version
                or self.repository.latest_ontology_version()
            ),
            "video_id": video_id,
            "creator_name": creator_name,
            "abilities": abilities,
            "summary": {
                "ability_count": len(abilities),
                "scored_count": sum(
                    item["ability_score"] is not None for item in abilities
                ),
                "evidence_only_count": sum(
                    item["ability_score"] is None for item in abilities
                ),
                "observation_count": len(observations),
            },
        }

    def compare(
        self,
        profile: dict[str, Any],
        required_abilities: Iterable[str | dict[str, Any]],
        *,
        default_target_score: float = 60.0,
    ) -> dict[str, Any]:
        required = self._resolve_required_abilities(
            required_abilities,
            default_target_score,
        )
        observed = {
            str(item["ability_id"]): item
            for item in profile.get("abilities") or []
        }
        matched: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        needs_evaluation: list[dict[str, Any]] = []
        for requirement in required:
            item = observed.get(requirement["ability_id"])
            base = {
                **requirement,
                "observed_score": (
                    item.get("ability_score") if item else None
                ),
                "evidence_count": (
                    int(item.get("evidence_count") or 0) if item else 0
                ),
            }
            if item is None:
                missing.append({**base, "reason": "not_observed"})
                continue
            if item.get("ability_score") is None:
                needs_evaluation.append(
                    {**base, "reason": "evidence_without_reliable_score"}
                )
                continue
            if float(item["ability_score"]) < float(
                requirement["target_score"]
            ):
                missing.append(
                    {
                        **base,
                        "reason": "below_target",
                        "score_gap": round(
                            float(requirement["target_score"])
                            - float(item["ability_score"]),
                            2,
                        ),
                    }
                )
                continue
            matched.append({**base, "reason": "target_met"})
        return {
            "video_id": profile.get("video_id"),
            "ontology_version": profile.get("ontology_version"),
            "matched_abilities": matched,
            "missing_abilities": missing,
            "needs_evaluation": needs_evaluation,
            "summary": {
                "required_count": len(required),
                "matched_count": len(matched),
                "missing_count": len(missing),
                "needs_evaluation_count": len(needs_evaluation),
            },
        }

    def load_and_extract(
        self,
        analysis_path: Path,
        *,
        v3_path: Path | None = None,
        save: bool = False,
    ) -> dict[str, Any]:
        analysis = read_json(analysis_path, {})
        v3 = read_json(v3_path, {}) if v3_path else {}
        return self.extract(
            analysis,
            v3=v3,
            creator_name=str(
                analysis.get("author")
                or v3.get("author")
                or ""
            ),
            source_analysis_ref=str(analysis_path),
            save=save,
        )

    def _extract_observations(
        self,
        video_id: str,
        creator_name: str,
        analysis: dict[str, Any],
        v3: dict[str, Any],
        source_analysis_ref: str,
        ontology_version: str,
    ) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        for metric, paths in ANALYSIS_METRICS.items():
            value = self._first_value(analysis, v3, paths)
            if not has_value(value):
                continue
            for mapping in self.resolve_term("video_metric", metric):
                confidence = round(
                    float(mapping["confidence"])
                    * float(mapping["weight"]),
                    4,
                )
                observations.append(
                    {
                        "observation_id": stable_id(
                            "video_observation",
                            video_id,
                            mapping["ability_id"],
                            metric,
                            ontology_version,
                        ),
                        "video_id": video_id,
                        "creator_name": creator_name,
                        "ability_id": mapping["ability_id"],
                        "ability_key": mapping["ability_key"],
                        "ability_name": mapping["ability_name"],
                        "source_metric": metric,
                        "raw_value": value,
                        "observed_score": self._metric_score(
                            metric,
                            value,
                        ),
                        "confidence": confidence,
                        "source_analysis_ref": source_analysis_ref,
                    }
                )
        return observations

    def _resolve_required_abilities(
        self,
        required: Iterable[str | dict[str, Any]],
        default_target_score: float,
    ) -> list[dict[str, Any]]:
        selected: dict[str, dict[str, Any]] = {}
        for raw in required:
            if isinstance(raw, str):
                value = raw
                target_score = default_target_score
            else:
                value = str(
                    raw.get("ability_key")
                    or raw.get("ability_name")
                    or raw.get("dimension")
                    or ""
                )
                target_score = float(
                    raw.get("target_score", default_target_score)
                )
            if not value:
                continue
            mappings = self.resolve_term(
                "reviewer_dimension",
                value,
            )
            if not mappings:
                mappings = self.resolve_term(
                    "legacy_ability",
                    value,
                )
            if not mappings:
                ability = self.repository.get_ability(
                    normalize_term(value).replace(" ", "_")
                )
                mappings = [ability] if ability else []
            for mapping in mappings:
                ability_id = str(mapping["ability_id"])
                selected[ability_id] = {
                    "ability_id": ability_id,
                    "ability_key": mapping["ability_key"],
                    "ability_name": mapping["ability_name"],
                    "target_score": target_score,
                }
        return sorted(
            selected.values(),
            key=lambda item: item["ability_key"],
        )

    def resolve_term(
        self,
        taxonomy_type: str,
        term_name: str,
    ) -> list[dict[str, Any]]:
        key = (taxonomy_type, normalize_term(term_name))
        if key not in self._term_mapping_cache:
            self._term_mapping_cache[key] = self.repository.map_term(
                taxonomy_type,
                term_name,
            )
        return self._term_mapping_cache[key]

    def _first_value(
        self,
        analysis: dict[str, Any],
        v3: dict[str, Any],
        paths: tuple[tuple[str, ...], ...],
    ) -> Any:
        for source in (analysis, v3):
            for path in paths:
                value: Any = source
                for key in path:
                    if not isinstance(value, dict) or key not in value:
                        value = None
                        break
                    value = value[key]
                if has_value(value):
                    return value
        return None

    def _metric_score(self, metric: str, value: Any) -> float | None:
        if metric == "hook_score" and isinstance(value, (int, float)):
            score = float(value)
            if score <= 10:
                score *= 10
            return round(max(0.0, min(100.0, score)), 2)
        return None

    def _combined_confidence(self, values: Iterable[float]) -> float:
        residual = 1.0
        for value in values:
            residual *= 1.0 - max(0.0, min(1.0, float(value)))
        return round(1.0 - residual, 4)

    def _deduplicate_observations(
        self,
        observations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        selected: dict[tuple[str, str, str], dict[str, Any]] = {}
        for item in observations:
            key = (
                str(item["video_id"]),
                str(item["ability_id"]),
                str(item["source_metric"]),
            )
            current = selected.get(key)
            if current is None or float(item["confidence"]) > float(
                current["confidence"]
            ):
                selected[key] = item
        return list(selected.values())
