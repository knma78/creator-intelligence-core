from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from config import SETTINGS, Settings

from .models import AbilityDefinition, AbilityEvidence, CreatorRecord, KnowledgeDataset, VideoRecord


ABILITY_FILE_SIGNALS: dict[str, tuple[str, ...]] = {
    "hook": ("hook_score", "hook_style"),
    "rhythm": ("rhythm_peak", "rhythm_change"),
    "transition": ("transitions",),
    "emotion": ("emotion",),
    "title": ("title", "title_length", "title_patterns"),
    "thumbnail": ("cover_ocr", "cover_path", "cover_brightness", "cover_contrast", "cover_dominant_colors"),
    "visual": ("cover_path", "cover_brightness", "cover_contrast", "cover_dominant_colors"),
    "knowledge_density": ("top_keywords", "keyword_counts", "rhythm_change"),
    "audience_psychology": ("view_count", "like_rate", "comment_rate", "comments_sentiment"),
    "value_delivery": ("learnings", "summary"),
    "information_gap": ("hook_style", "title_patterns"),
    "question_design": ("title_patterns",),
}


def normalize_ability_key(value: str) -> str:
    normalized = value.strip().lower()
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized


def display_from_key(key: str) -> str:
    return " ".join(part.capitalize() for part in key.split("_"))


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        # Backward compatibility for occasional unescaped control characters in older exports.
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        text = "".join(ch for ch in text if ch in "\r\n\t" or ord(ch) >= 32)
        return json.loads(text)


class LocalKnowledgeRepository:
    """File-backed repository for current local JSON databases.

    The service layer depends only on KnowledgeDataset, so this repository can be
    replaced by a SQLite implementation without changing callers.
    """

    def __init__(self, settings: Settings = SETTINGS) -> None:
        self.settings = settings
        self.config_dir = settings.base_dir / "config"
        self.creator_kb_dir = settings.output_dir / "creator_knowledge_base"

    def load_dataset(self) -> KnowledgeDataset:
        thresholds = read_json(self.config_dir / "Threshold.json", {})
        ability_weights = read_json(self.config_dir / "AbilityWeight.json", {})
        creator_weights = read_json(self.config_dir / "CreatorWeight.json", {})

        definitions = self._load_ability_definitions(thresholds, ability_weights)
        alias_map = self._build_alias_map(definitions, ability_weights)
        evidence: dict[str, AbilityEvidence] = {}
        creators: dict[str, CreatorRecord] = {}
        videos: dict[str, VideoRecord] = {}
        templates: list[dict[str, Any]] = []
        source_paths: dict[str, str] = {}
        source_summary: dict[str, Any] = {"mode": "json_backcompat"}

        manifest_path = self.creator_kb_dir / "manifest.json"
        manifest = read_json(manifest_path, {})
        if manifest:
            source_paths["creator_manifest"] = str(manifest_path)
            source_summary["manifest_video_count"] = manifest.get("video_count", 0)
            source_summary["manifest_creator_count"] = manifest.get("creator_count", 0)
            self._load_manifest_creators(manifest, creators)

        creator_kb_path = self.creator_kb_dir / "creator_knowledge_base.json"
        creator_kb = read_json(creator_kb_path, {})
        if creator_kb:
            source_paths["creator_knowledge_base"] = str(creator_kb_path)
            source_summary["capability_document_count"] = len(creator_kb.get("capability_documents") or [])
            self._load_capability_documents(creator_kb, definitions, alias_map, evidence)

        template_path = self.creator_kb_dir / "templates" / "template_library.json"
        template_library = read_json(template_path, {})
        if template_library:
            source_paths["template_library"] = str(template_path)
            self._load_template_library(template_library, definitions, alias_map, evidence, templates)

        integrated_path = self.settings.output_dir / "integrated" / "integrated_summary.json"
        integrated = read_json(integrated_path, {})
        if integrated:
            source_paths["video_database"] = str(integrated_path)
            source_summary["integrated_video_count"] = len(integrated.get("videos") or [])
            self._load_integrated_videos(integrated, definitions, alias_map, evidence, creators, videos)

        for key in list(definitions):
            evidence.setdefault(key, AbilityEvidence(key=key))

        return KnowledgeDataset(
            ability_definitions=definitions,
            ability_evidence=evidence,
            creators=creators,
            videos=videos,
            templates=templates,
            thresholds=thresholds,
            ability_weights=ability_weights,
            creator_weights=creator_weights,
            source_paths=source_paths,
            source_summary=source_summary,
        )

    def resolve_ability_key(
        self,
        raw_value: str,
        definitions: dict[str, AbilityDefinition],
        alias_map: dict[str, str],
    ) -> str:
        raw_value = str(raw_value or "").strip()
        normalized = normalize_ability_key(raw_value)
        mapped = alias_map.get(normalized)
        if mapped:
            return mapped
        if normalized not in definitions:
            definitions[normalized] = AbilityDefinition(
                key=normalized,
                display_name=raw_value or display_from_key(normalized),
                source="database",
            )
        return normalized

    def _load_ability_definitions(
        self,
        thresholds: dict[str, Any],
        ability_weights: dict[str, Any],
    ) -> dict[str, AbilityDefinition]:
        definitions: dict[str, AbilityDefinition] = {}
        configured_keys = set((thresholds.get("abilities") or {}).keys())
        configured_keys.update((ability_weights.get("abilities") or {}).keys())
        default_weight = float(ability_weights.get("default_weight", 1.0))
        default_status = str(ability_weights.get("default_status", "active"))

        for key in sorted(configured_keys):
            item = (ability_weights.get("abilities") or {}).get(key) or {}
            definitions[key] = AbilityDefinition(
                key=key,
                display_name=str(item.get("display_name") or display_from_key(key)),
                weight=float(item.get("weight", default_weight)),
                status=str(item.get("status", default_status)),
                aliases=[str(alias) for alias in item.get("aliases", [])],
                version=int(item.get("version", ability_weights.get("version", 1))),
                source="config",
            )
        return definitions

    def _build_alias_map(
        self,
        definitions: dict[str, AbilityDefinition],
        ability_weights: dict[str, Any],
    ) -> dict[str, str]:
        alias_map: dict[str, str] = {}
        for key, definition in definitions.items():
            alias_map[normalize_ability_key(key)] = key
            alias_map[normalize_ability_key(definition.display_name)] = key
            for alias in definition.aliases:
                alias_map[normalize_ability_key(alias)] = key
        renamed = ((ability_weights.get("evolution") or {}).get("renamed_abilities") or {})
        for old_name, new_name in renamed.items():
            alias_map[normalize_ability_key(str(old_name))] = normalize_ability_key(str(new_name))
        return alias_map

    def _evidence_for(self, key: str, evidence: dict[str, AbilityEvidence]) -> AbilityEvidence:
        if key not in evidence:
            evidence[key] = AbilityEvidence(key=key)
        return evidence[key]

    def _load_manifest_creators(self, manifest: dict[str, Any], creators: dict[str, CreatorRecord]) -> None:
        for item in manifest.get("creators") or []:
            name = str(item.get("author") or "").strip()
            if not name:
                continue
            creators[name] = CreatorRecord(
                name=name,
                creator_type=str(item.get("positioning") or ""),
                category=str(item.get("positioning") or ""),
                video_count=int(item.get("video_count") or 0),
                source_authors=[str(author) for author in item.get("source_authors") or []],
            )

    def _load_capability_documents(
        self,
        creator_kb: dict[str, Any],
        definitions: dict[str, AbilityDefinition],
        alias_map: dict[str, str],
        evidence: dict[str, AbilityEvidence],
    ) -> None:
        for doc in creator_kb.get("capability_documents") or []:
            category = str(doc.get("category") or "").strip()
            if not category:
                continue
            key = self.resolve_ability_key(category, definitions, alias_map)
            item = self._evidence_for(key, evidence)
            item.source_categories.add(category)
            item.related_videos.update(str(video_id) for video_id in doc.get("source_video_ids") or [] if video_id)
            item.related_creators.update(str(name) for name in doc.get("creators") or [] if name)
            item.capability_documents.append(
                {
                    "category": category,
                    "title": doc.get("title", ""),
                    "reference_count": len(doc.get("source_video_ids") or []),
                    "creator_count": len(doc.get("creators") or []),
                }
            )
            item.evidence_sources.add("creator_knowledge_base")

    def _load_template_library(
        self,
        template_library: dict[str, Any],
        definitions: dict[str, AbilityDefinition],
        alias_map: dict[str, str],
        evidence: dict[str, AbilityEvidence],
        templates: list[dict[str, Any]],
    ) -> None:
        for collection, values in template_library.items():
            if not collection.endswith("_templates") or not isinstance(values, list):
                continue
            for template in values:
                template_id = str(template.get("id") or template.get("name") or "")
                if not template_id:
                    continue
                related_categories = [str(value) for value in template.get("related_categories") or [] if value]
                template_record = {
                    "id": template_id,
                    "name": str(template.get("name") or template_id),
                    "collection": collection,
                    "related_categories": related_categories,
                    "source_video_ids": list(template.get("source_video_ids") or (template.get("evidence") or {}).get("source_video_ids") or []),
                    "usage_count": int(template.get("usage_count") or len(template.get("source_video_ids") or [])),
                }
                templates.append(template_record)
                for category in related_categories:
                    key = self.resolve_ability_key(category, definitions, alias_map)
                    item = self._evidence_for(key, evidence)
                    item.source_categories.add(category)
                    item.related_templates[template_id] = template_record
                    item.related_videos.update(str(video_id) for video_id in template_record["source_video_ids"] if video_id)
                    item.evidence_sources.add("template_library")

    def _load_integrated_videos(
        self,
        integrated: dict[str, Any],
        definitions: dict[str, AbilityDefinition],
        alias_map: dict[str, str],
        evidence: dict[str, AbilityEvidence],
        creators: dict[str, CreatorRecord],
        videos: dict[str, VideoRecord],
    ) -> None:
        for item in integrated.get("videos") or []:
            video_id = str(item.get("video_id") or "").strip()
            if not video_id:
                continue
            author = str(item.get("author") or "").strip()
            video = VideoRecord(
                video_id=video_id,
                title=str(item.get("title") or ""),
                author=author,
                publish_time=str(item.get("publish_time") or ""),
                duration=float(item.get("duration") or 0.0),
                metrics={
                    "view_count": item.get("view_count", 0),
                    "like_count": item.get("like_count", 0),
                    "comment_count": item.get("comment_count", 0),
                    "like_rate": item.get("like_rate", 0),
                    "comment_rate": item.get("comment_rate", 0),
                },
            )
            videos[video_id] = video
            if author and author not in creators:
                creators[author] = CreatorRecord(name=author, video_count=0)
            if author:
                creators[author].video_count = max(creators[author].video_count, 1)

            for ability_key, field_names in ABILITY_FILE_SIGNALS.items():
                if not self._video_has_signal(item, field_names):
                    continue
                key = self.resolve_ability_key(ability_key, definitions, alias_map)
                video.abilities.add(key)
                target = self._evidence_for(key, evidence)
                target.related_videos.add(video_id)
                if author:
                    target.related_creators.add(author)
                target.evidence_sources.add("video_database")

            for pattern in item.get("title_patterns") or []:
                if int(pattern.get("count") or 0) <= 0:
                    continue
                pattern_name = str(pattern.get("pattern") or "").lower()
                if "question" in pattern_name:
                    key = self.resolve_ability_key("question_design", definitions, alias_map)
                    self._evidence_for(key, evidence).related_videos.add(video_id)

    def _video_has_signal(self, item: dict[str, Any], fields: tuple[str, ...]) -> bool:
        for field in fields:
            value = item.get(field)
            if value is None or value == "" or value == [] or value == {}:
                continue
            if isinstance(value, (int, float)) and value == 0:
                continue
            return True
        return False
