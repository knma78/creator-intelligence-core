from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DiscoveryCandidate:
    candidate_id: str
    creator_id: str | None
    creator_name: str
    platform: str
    category: str
    recommend_source: str
    recommend_reason: str
    confidence: float
    ability: str
    keyword: str
    status: str
    need_analyze: bool
    create_time: str
    last_update: str
    source_url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AbilityKeyword:
    ability: str
    keyword: str
    weight: float
    platform: str
    language: str
    priority: int


@dataclass
class CreatorAbilityScore:
    creator_id: str
    creator_name: str
    platform: str
    ability: str
    score: float
    confidence: float
    video_count: int
    last_analyze: str
    category: str = ""


@dataclass
class DiscoveryDataset:
    gap_analysis: dict[str, Any]
    creator_manifest: dict[str, Any]
    integrated_summary: dict[str, Any]
    ability_keywords: dict[str, Any]
    platform_weights: dict[str, Any]
    discovery_rules: dict[str, Any]
    creator_thresholds: dict[str, Any]
    candidates: list[dict[str, Any]]
    creator_matrix: list[dict[str, Any]]
    approved_creators: list[dict[str, Any]]
    source_paths: dict[str, str]
