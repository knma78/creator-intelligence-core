from __future__ import annotations

import json
from typing import Any, Iterable

from config import SETTINGS, Settings

from .repository import AbilityOntologyRepository, normalize_term, stable_id
from .video_profile import VideoAbilityProfileService


class OntologyReviewerAdapter:
    """Adds ontology output without changing the reviewer's score payload."""

    def __init__(
        self,
        settings: Settings = SETTINGS,
        repository: AbilityOntologyRepository | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository or AbilityOntologyRepository(settings)
        self.profile_service = VideoAbilityProfileService(
            settings,
            self.repository,
        )

    def enrich(
        self,
        reviewer_result: dict[str, Any],
        video_analysis: dict[str, Any],
        *,
        v3: dict[str, Any] | None = None,
        required_abilities: Iterable[str | dict[str, Any]] | None = None,
        minimum_score: float = 60.0,
        source_analysis_ref: str = "",
        save_observations: bool = False,
    ) -> dict[str, Any]:
        enriched = json.loads(
            json.dumps(reviewer_result, ensure_ascii=False, default=str)
        )
        video_id = str(video_analysis.get("video_id") or "").strip()
        if not video_id:
            raise ValueError("video_analysis.video_id is required")
        ontology_version = self.repository.latest_ontology_version()
        if not ontology_version:
            raise RuntimeError(
                "Ability Ontology database is not initialized. Run the "
                "ontology migration first."
            )
        reviewer_observations, reviewer_requirements = (
            self._reviewer_observations(
                video_id,
                reviewer_result,
                ontology_version,
            )
        )
        profile = self.profile_service.extract(
            video_analysis,
            v3=v3,
            source_analysis_ref=source_analysis_ref,
            save=save_observations,
            extra_observations=reviewer_observations,
        )
        requirements = list(
            required_abilities
            if required_abilities is not None
            else reviewer_requirements
        )
        comparison = self.profile_service.compare(
            profile,
            requirements,
            default_target_score=minimum_score,
        )
        extension_key = (
            "ability_ontology"
            if "ability_ontology" not in enriched
            else "ability_ontology_v1"
        )
        enriched[extension_key] = {
            "schema_version": "Reviewer Ontology Extension v1",
            "ontology_version": ontology_version,
            "video_ability_profile": profile,
            **comparison,
        }
        return enriched

    def _reviewer_observations(
        self,
        video_id: str,
        reviewer_result: dict[str, Any],
        ontology_version: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        dimensions = self._extract_dimensions(reviewer_result)
        observations: list[dict[str, Any]] = []
        requirements: list[dict[str, Any]] = []
        for dimension, score in dimensions:
            mappings = self.profile_service.resolve_term(
                "reviewer_dimension",
                dimension,
            )
            if not mappings:
                mappings = self.profile_service.resolve_term(
                    "legacy_ability",
                    dimension,
                )
            for mapping in mappings:
                metric = (
                    "reviewer:"
                    + normalize_term(dimension).replace(" ", "_")
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
                        "creator_name": "",
                        "ability_id": mapping["ability_id"],
                        "ability_key": mapping["ability_key"],
                        "ability_name": mapping["ability_name"],
                        "source_metric": metric,
                        "raw_value": {
                            "dimension": dimension,
                            "score": score,
                        },
                        "observed_score": score,
                        "confidence": float(mapping["confidence"]),
                        "source_analysis_ref": "reviewer_result",
                    }
                )
                requirements.append(
                    {
                        "ability_key": mapping["ability_key"],
                    }
                )
        return observations, requirements

    def _extract_dimensions(
        self,
        reviewer_result: dict[str, Any],
    ) -> list[tuple[str, float]]:
        candidates: list[Any] = [
            reviewer_result.get("dimensions"),
            reviewer_result.get("scores"),
            reviewer_result.get("ability_scores"),
        ]
        nested = reviewer_result.get("result")
        if isinstance(nested, dict):
            candidates.extend(
                [
                    nested.get("dimensions"),
                    nested.get("scores"),
                    nested.get("ability_scores"),
                ]
            )
        result: list[tuple[str, float]] = []
        for candidate in candidates:
            if isinstance(candidate, dict):
                for name, value in candidate.items():
                    score = self._score_value(value)
                    if score is not None:
                        result.append((str(name), score))
            elif isinstance(candidate, list):
                for item in candidate:
                    if not isinstance(item, dict):
                        continue
                    name = str(
                        item.get("dimension")
                        or item.get("ability")
                        or item.get("name")
                        or ""
                    )
                    score = self._score_value(item)
                    if name and score is not None:
                        result.append((name, score))
            if result:
                break
        return result

    def _score_value(self, value: Any) -> float | None:
        if isinstance(value, dict):
            value = value.get("score")
        if not isinstance(value, (int, float)):
            return None
        score = float(value)
        if score <= 10:
            score *= 10
        return round(max(0.0, min(100.0, score)), 2)
