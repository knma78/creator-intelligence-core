from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AbilityDefinition:
    key: str
    display_name: str
    weight: float = 1.0
    status: str = "active"
    aliases: list[str] = field(default_factory=list)
    version: int = 1
    source: str = "config"


@dataclass
class AbilityEvidence:
    key: str
    source_categories: set[str] = field(default_factory=set)
    related_videos: set[str] = field(default_factory=set)
    related_creators: set[str] = field(default_factory=set)
    related_templates: dict[str, dict[str, Any]] = field(default_factory=dict)
    capability_documents: list[dict[str, Any]] = field(default_factory=list)
    evidence_sources: set[str] = field(default_factory=set)


@dataclass
class CreatorRecord:
    name: str
    creator_type: str = ""
    category: str = ""
    ability_score: dict[str, float] = field(default_factory=dict)
    video_count: int = 0
    last_analyze_time: str = ""
    source_authors: list[str] = field(default_factory=list)


@dataclass
class VideoRecord:
    video_id: str
    title: str = ""
    author: str = ""
    publish_time: str = ""
    duration: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)
    abilities: set[str] = field(default_factory=set)


@dataclass
class KnowledgeDataset:
    ability_definitions: dict[str, AbilityDefinition]
    ability_evidence: dict[str, AbilityEvidence]
    creators: dict[str, CreatorRecord]
    videos: dict[str, VideoRecord]
    templates: list[dict[str, Any]]
    thresholds: dict[str, Any]
    ability_weights: dict[str, Any]
    creator_weights: dict[str, Any]
    source_paths: dict[str, str]
    source_summary: dict[str, Any]
