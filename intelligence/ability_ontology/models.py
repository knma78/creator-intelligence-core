from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AbilityRecord:
    ability_id: str
    ability_key: str
    ability_name: str
    definition: str
    parent_ability_id: str | None = None
    status: str = "active"
    evaluation_rules: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class TermMapping:
    taxonomy_type: str
    source_key: str
    term_name: str
    ability_id: str
    relation_type: str
    weight: float
    confidence: float
    source_system: str = "ability_ontology"
    language: str = "zh"


@dataclass(frozen=True)
class MigrationPlan:
    ontology_version: str
    schema_version: int
    source_checksum: str
    source_paths: dict[str, str]
    abilities: list[AbilityRecord]
    mappings: list[TermMapping]
    creator_snapshots: list[dict[str, Any]]
    creator_evidence: list[dict[str, Any]]
    video_observations: list[dict[str, Any]]
    warnings: list[str]

    def counts(self) -> dict[str, int]:
        return {
            "abilities": len(self.abilities),
            "evaluation_rules": sum(
                len(ability.evaluation_rules) for ability in self.abilities
            ),
            "term_mappings": len(self.mappings),
            "creator_snapshots": len(self.creator_snapshots),
            "creator_evidence": len(self.creator_evidence),
            "video_observations": len(self.video_observations),
            "warnings": len(self.warnings),
        }
