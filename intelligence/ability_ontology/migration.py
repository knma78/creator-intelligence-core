from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from config import SETTINGS, Settings

from .models import AbilityRecord, MigrationPlan, TermMapping
from .repository import (
    SCHEMA_VERSION,
    AbilityOntologyRepository,
    normalize_term,
    stable_id,
)

MIGRATION_VERSION = 2


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def legacy_creator_id(platform: str, creator_name: str) -> str:
    raw = f"{platform}|{creator_name}".strip().lower()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def has_value(value: Any) -> bool:
    if value is None or value == "" or value == [] or value == {}:
        return False
    if isinstance(value, (int, float)) and value == 0:
        return False
    return True


class LegacyOntologyMigrator:
    def __init__(
        self,
        settings: Settings = SETTINGS,
        repository: AbilityOntologyRepository | None = None,
        ontology_config_path: Path | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository or AbilityOntologyRepository(settings)
        self.ontology_config_path = ontology_config_path or (
            settings.base_dir / "config" / "AbilityOntology.json"
        )

    def migrate(self, dry_run: bool = False) -> dict[str, Any]:
        plan = self.build_plan()
        if dry_run:
            return {
                "status": "dry_run",
                "ontology_version": plan.ontology_version,
                "schema_version": plan.schema_version,
                "source_checksum": plan.source_checksum,
                "database_path": str(self.repository.database_path),
                "database_written": False,
                "source_paths": plan.source_paths,
                "counts": plan.counts(),
                "warnings": plan.warnings,
            }
        return self.repository.apply_migration(plan)

    def build_plan(self) -> MigrationPlan:
        paths = self._source_paths()
        ontology_config = read_json(self.ontology_config_path, {})
        ability_weights = read_json(paths["ability_weights"], {})
        integrated = read_json(paths["video_database"], {})
        creator_kb = read_json(paths["creator_knowledge_base"], {})
        templates = read_json(paths["template_library"], {})
        creator_matrix = read_json(paths["creator_ability_matrix"], [])
        creator_specs = read_json(paths["creator_specs"], {})

        warnings: list[str] = []
        abilities = self._build_abilities(
            ontology_config,
            ability_weights,
            warnings,
        )
        ability_by_key = {item.ability_key: item for item in abilities}
        alias_index = self._build_alias_index(
            ability_weights,
            ability_by_key,
        )
        mappings = self._build_config_mappings(
            ontology_config,
            ability_by_key,
            warnings,
        )
        mappings.extend(
            self._build_legacy_ability_mappings(
                ability_weights,
                ability_by_key,
            )
        )
        mappings = self._add_dynamic_taxonomy_mappings(
            mappings,
            creator_kb,
            templates,
            creator_specs,
            alias_index,
            ability_by_key,
            warnings,
        )
        mappings = self._deduplicate_mappings(mappings)

        creator_snapshots, matrix_evidence = self._migrate_creator_matrix(
            creator_matrix,
            alias_index,
            ability_by_key,
            paths["creator_ability_matrix"],
            ontology_config,
            warnings,
        )
        category_evidence = self._migrate_creator_categories(
            creator_kb,
            creator_specs,
            mappings,
            paths,
        )
        creator_evidence = self._deduplicate_evidence(
            matrix_evidence + category_evidence
        )
        creator_snapshots = self._complete_creator_snapshots(
            creator_snapshots,
            creator_evidence,
            str(ontology_config.get("ontology_version") or "1.0.0"),
        )
        video_observations = self._migrate_video_observations(
            integrated,
            mappings,
            paths["video_database"],
            ontology_config,
        )

        source_paths = {
            key: str(path)
            for key, path in paths.items()
            if path.exists()
        }
        return MigrationPlan(
            ontology_version=str(
                ontology_config.get("ontology_version") or "1.0.0"
            ),
            schema_version=int(
                ontology_config.get("schema_version") or SCHEMA_VERSION
            ),
            source_checksum=self._source_checksum(paths),
            source_paths=source_paths,
            abilities=abilities,
            mappings=mappings,
            creator_snapshots=creator_snapshots,
            creator_evidence=creator_evidence,
            video_observations=video_observations,
            warnings=warnings,
        )

    def _source_paths(self) -> dict[str, Path]:
        creator_kb_dir = self.settings.output_dir / "creator_knowledge_base"
        return {
            "ontology_config": self.ontology_config_path,
            "ability_weights": self.settings.base_dir
            / "config"
            / "AbilityWeight.json",
            "video_database": self.settings.output_dir
            / "integrated"
            / "integrated_summary.json",
            "creator_knowledge_base": creator_kb_dir
            / "creator_knowledge_base.json",
            "template_library": creator_kb_dir
            / "templates"
            / "template_library.json",
            "creator_ability_matrix": self.settings.output_dir
            / "creator_discovery"
            / "creator_ability_matrix.json",
            "creator_specs": self.settings.base_dir
            / "tools"
            / "creator_specs.json",
        }

    def _source_checksum(self, paths: dict[str, Path]) -> str:
        digest = hashlib.sha256()
        digest.update(f"migration_version={MIGRATION_VERSION}".encode("ascii"))
        digest.update(b"\0")
        for key, path in sorted(paths.items()):
            digest.update(key.encode("utf-8"))
            digest.update(b"\0")
            if path.exists():
                digest.update(path.read_bytes())
            else:
                digest.update(b"<missing>")
            digest.update(b"\0")
        return digest.hexdigest()

    def _build_abilities(
        self,
        ontology_config: dict[str, Any],
        ability_weights: dict[str, Any],
        warnings: list[str],
    ) -> list[AbilityRecord]:
        ontology_abilities = ontology_config.get("abilities") or {}
        legacy_abilities = ability_weights.get("abilities") or {}
        all_keys = sorted(set(legacy_abilities) | set(ontology_abilities))
        result: list[AbilityRecord] = []
        for ability_key in all_keys:
            ontology_item = ontology_abilities.get(ability_key) or {}
            legacy_item = legacy_abilities.get(ability_key) or {}
            ability_id = str(
                ontology_item.get("ability_id")
                or f"ability.{ability_key}"
            )
            definition = str(ontology_item.get("definition") or "").strip()
            rules = list(ontology_item.get("evaluation_rules") or [])
            if not definition:
                warnings.append(
                    f"Ability {ability_key} has no ontology definition."
                )
            if not rules:
                warnings.append(
                    f"Ability {ability_key} has no evaluation rules."
                )
            result.append(
                AbilityRecord(
                    ability_id=ability_id,
                    ability_key=ability_key,
                    ability_name=str(
                        ontology_item.get("ability_name")
                        or legacy_item.get("display_name")
                        or ability_key
                    ),
                    definition=definition,
                    parent_ability_id=ontology_item.get(
                        "parent_ability_id"
                    ),
                    status=str(
                        ontology_item.get("status")
                        or legacy_item.get("status")
                        or "active"
                    ),
                    evaluation_rules=rules,
                )
            )
        ability_ids = {item.ability_id for item in result}
        for item in result:
            if item.parent_ability_id and item.parent_ability_id not in ability_ids:
                raise ValueError(
                    f"Unknown parent ability: {item.parent_ability_id}"
                )
        return result

    def _build_alias_index(
        self,
        ability_weights: dict[str, Any],
        ability_by_key: dict[str, AbilityRecord],
    ) -> dict[str, str]:
        index: dict[str, str] = {}
        for key, ability in ability_by_key.items():
            index[normalize_term(key)] = key
            index[normalize_term(ability.ability_name)] = key
            legacy = (ability_weights.get("abilities") or {}).get(key) or {}
            for alias in legacy.get("aliases") or []:
                index[normalize_term(str(alias))] = key
            display_name = str(legacy.get("display_name") or "")
            if display_name:
                index[normalize_term(display_name)] = key
        renamed = (
            (ability_weights.get("evolution") or {}).get(
                "renamed_abilities"
            )
            or {}
        )
        for old_name, new_name in renamed.items():
            resolved = index.get(normalize_term(str(new_name)))
            if resolved:
                index[normalize_term(str(old_name))] = resolved
        return index

    def _build_config_mappings(
        self,
        ontology_config: dict[str, Any],
        ability_by_key: dict[str, AbilityRecord],
        warnings: list[str],
    ) -> list[TermMapping]:
        mappings: list[TermMapping] = []
        for entry in ontology_config.get("term_mappings") or []:
            taxonomy_type = str(entry.get("taxonomy_type") or "").strip()
            term_name = str(entry.get("term_name") or "").strip()
            if not taxonomy_type or not term_name:
                warnings.append("Ignored ontology mapping without taxonomy or term.")
                continue
            for target in entry.get("targets") or []:
                ability_key = str(target.get("ability_key") or "").strip()
                ability = ability_by_key.get(ability_key)
                if ability is None:
                    warnings.append(
                        f"Ignored mapping {term_name} -> unknown {ability_key}."
                    )
                    continue
                mappings.append(
                    TermMapping(
                        taxonomy_type=taxonomy_type,
                        source_key=str(
                            entry.get("source_key")
                            or normalize_term(term_name).replace(" ", "_")
                        ),
                        term_name=term_name,
                        ability_id=ability.ability_id,
                        relation_type=str(
                            target.get("relation_type") or "supports"
                        ),
                        weight=float(target.get("weight", 1.0)),
                        confidence=float(target.get("confidence", 0.85)),
                        source_system="ontology_config",
                        language=str(entry.get("language") or "und"),
                    )
                )
        return mappings

    def _build_legacy_ability_mappings(
        self,
        ability_weights: dict[str, Any],
        ability_by_key: dict[str, AbilityRecord],
    ) -> list[TermMapping]:
        mappings: list[TermMapping] = []
        legacy_abilities = ability_weights.get("abilities") or {}
        for key, ability in ability_by_key.items():
            legacy = legacy_abilities.get(key) or {}
            terms = {
                key,
                ability.ability_name,
                str(legacy.get("display_name") or ""),
                *[str(value) for value in legacy.get("aliases") or []],
            }
            for term in sorted(value for value in terms if value):
                mappings.append(
                    TermMapping(
                        taxonomy_type="legacy_ability",
                        source_key=key,
                        term_name=term,
                        ability_id=ability.ability_id,
                        relation_type="exact",
                        weight=1.0,
                        confidence=0.99,
                        source_system="AbilityWeight.json",
                        language="und",
                    )
                )
        return mappings

    def _add_dynamic_taxonomy_mappings(
        self,
        mappings: list[TermMapping],
        creator_kb: dict[str, Any],
        templates: dict[str, Any],
        creator_specs: dict[str, Any],
        alias_index: dict[str, str],
        ability_by_key: dict[str, AbilityRecord],
        warnings: list[str],
    ) -> list[TermMapping]:
        result = list(mappings)
        creator_terms = {
            str(item.get("category") or "").strip()
            for item in creator_kb.get("capability_documents") or []
        }
        for creator in creator_specs.get("creators") or []:
            creator_terms.update(
                str(value).strip()
                for value in creator.get("primary_categories") or []
            )
        creator_terms.discard("")
        template_terms: set[str] = set()
        for collection, values in templates.items():
            if not collection.endswith("_templates") or not isinstance(
                values,
                list,
            ):
                continue
            for template in values:
                template_terms.update(
                    str(value).strip()
                    for value in template.get("related_categories") or []
                )
        template_terms.discard("")

        for term in sorted(creator_terms):
            result = self._ensure_term_mapping(
                result,
                "creator_style",
                term,
                alias_index,
                ability_by_key,
                warnings,
            )
        for term in sorted(template_terms):
            source_mappings = self._mappings_for_term(
                result,
                "creator_style",
                term,
            )
            if source_mappings:
                for item in source_mappings:
                    result.append(
                        replace(
                            item,
                            taxonomy_type="template_category",
                            source_system="legacy_json",
                        )
                    )
            else:
                result = self._ensure_term_mapping(
                    result,
                    "template_category",
                    term,
                    alias_index,
                    ability_by_key,
                    warnings,
                )
        return result

    def _ensure_term_mapping(
        self,
        mappings: list[TermMapping],
        taxonomy_type: str,
        term: str,
        alias_index: dict[str, str],
        ability_by_key: dict[str, AbilityRecord],
        warnings: list[str],
    ) -> list[TermMapping]:
        if self._mappings_for_term(mappings, taxonomy_type, term):
            return mappings
        ability_key = alias_index.get(normalize_term(term))
        if not ability_key:
            warnings.append(
                f"No canonical ability mapping for {taxonomy_type}: {term}"
            )
            return mappings
        ability = ability_by_key[ability_key]
        mappings.append(
            TermMapping(
                taxonomy_type=taxonomy_type,
                source_key=normalize_term(term).replace(" ", "_"),
                term_name=term,
                ability_id=ability.ability_id,
                relation_type="legacy_exact",
                weight=1.0,
                confidence=0.9,
                source_system="legacy_json",
                language="und",
            )
        )
        return mappings

    def _mappings_for_term(
        self,
        mappings: list[TermMapping],
        taxonomy_type: str,
        term: str,
    ) -> list[TermMapping]:
        normalized = normalize_term(term)
        return [
            item
            for item in mappings
            if item.taxonomy_type == taxonomy_type
            and normalize_term(item.term_name) == normalized
        ]

    def _deduplicate_mappings(
        self,
        mappings: list[TermMapping],
    ) -> list[TermMapping]:
        selected: dict[tuple[str, str, str], TermMapping] = {}
        for item in mappings:
            key = (
                item.taxonomy_type,
                normalize_term(item.term_name),
                item.ability_id,
            )
            current = selected.get(key)
            if current is None or (
                item.weight,
                item.confidence,
            ) > (
                current.weight,
                current.confidence,
            ):
                selected[key] = item
        return sorted(
            selected.values(),
            key=lambda item: (
                item.taxonomy_type,
                normalize_term(item.term_name),
                -item.weight,
                item.ability_id,
            ),
        )

    def _migrate_creator_matrix(
        self,
        creator_matrix: list[dict[str, Any]],
        alias_index: dict[str, str],
        ability_by_key: dict[str, AbilityRecord],
        matrix_path: Path,
        ontology_config: dict[str, Any],
        warnings: list[str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        snapshots: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        ontology_version = str(
            ontology_config.get("ontology_version") or "1.0.0"
        )
        for index, row in enumerate(creator_matrix):
            raw_ability = str(row.get("ability") or "").strip()
            ability_key = alias_index.get(normalize_term(raw_ability))
            if not ability_key:
                warnings.append(
                    f"Skipped creator matrix row with unknown ability: {raw_ability}"
                )
                continue
            ability = ability_by_key[ability_key]
            creator_name = str(row.get("creator_name") or "").strip()
            if not creator_name:
                continue
            platform = str(row.get("platform") or "bilibili")
            creator_id = str(
                row.get("creator_id")
                or legacy_creator_id(platform, creator_name)
            )
            snapshot_id = stable_id(
                "creator_snapshot",
                creator_id,
                platform,
                ability.ability_id,
                ontology_version,
            )
            raw_score = float(row.get("score") or 0.0)
            legacy_confidence = float(row.get("confidence") or 0.0)
            confidence = round(
                max(0.0, min(1.0, legacy_confidence * 0.35)),
                4,
            )
            source_ref = f"{matrix_path}#row={index}"
            snapshots.append(
                {
                    "snapshot_id": snapshot_id,
                    "creator_id": creator_id,
                    "creator_name": creator_name,
                    "platform": platform,
                    "ability_id": ability.ability_id,
                    "ability_score": raw_score,
                    "confidence": confidence,
                    "evidence_count": 1,
                    "score_semantics": "legacy_coverage_proxy",
                    "calculated_at": str(row.get("last_analyze") or ""),
                }
            )
            evidence.append(
                {
                    "evidence_id": stable_id(
                        "creator_evidence",
                        creator_id,
                        platform,
                        ability.ability_id,
                        "legacy_creator_ability_matrix",
                        source_ref,
                    ),
                    "snapshot_id": snapshot_id,
                    "creator_id": creator_id,
                    "creator_name": creator_name,
                    "platform": platform,
                    "ability_id": ability.ability_id,
                    "source_type": "legacy_creator_ability_matrix",
                    "source_ref": source_ref,
                    "raw_label": raw_ability,
                    "raw_score": raw_score,
                    "mapping_weight": 1.0,
                    "evidence_reliability": 0.35,
                    "contribution_score": raw_score,
                    "payload": {
                        "legacy_confidence": legacy_confidence,
                        "legacy_category": row.get("category"),
                        "score_semantics": "knowledge_coverage_proxy",
                    },
                }
            )
        return snapshots, evidence

    def _migrate_creator_categories(
        self,
        creator_kb: dict[str, Any],
        creator_specs: dict[str, Any],
        mappings: list[TermMapping],
        paths: dict[str, Path],
    ) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        sources: list[tuple[str, str, list[str]]] = []
        for document in creator_kb.get("capability_documents") or []:
            category = str(document.get("category") or "").strip()
            creators = [
                str(name).strip()
                for name in document.get("creators") or []
                if str(name).strip()
            ]
            source_ref = (
                f"{paths['creator_knowledge_base']}#category={category}"
            )
            sources.append((category, source_ref, creators))
        for index, creator in enumerate(creator_specs.get("creators") or []):
            creator_name = str(creator.get("author") or "").strip()
            for category in creator.get("primary_categories") or []:
                sources.append(
                    (
                        str(category),
                        f"{paths['creator_specs']}#creator={index}",
                        [creator_name],
                    )
                )

        for raw_label, source_ref, creators in sources:
            targets = self._mappings_for_term(
                mappings,
                "creator_style",
                raw_label,
            )
            for creator_name in creators:
                creator_id = legacy_creator_id(
                    "bilibili",
                    creator_name,
                )
                for target in targets:
                    evidence.append(
                        {
                            "evidence_id": stable_id(
                                "creator_evidence",
                                creator_id,
                                target.ability_id,
                                source_ref,
                                raw_label,
                            ),
                            "snapshot_id": None,
                            "creator_id": creator_id,
                            "creator_name": creator_name,
                            "platform": "bilibili",
                            "ability_id": target.ability_id,
                            "source_type": "legacy_creator_style",
                            "source_ref": source_ref,
                            "raw_label": raw_label,
                            "raw_score": None,
                            "mapping_weight": target.weight,
                            "evidence_reliability": target.confidence,
                            "contribution_score": None,
                            "payload": {
                                "relation_type": target.relation_type,
                            },
                        }
                    )
        return evidence

    def _deduplicate_evidence(
        self,
        evidence: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return list(
            {
                str(item["evidence_id"]): item
                for item in evidence
            }.values()
        )

    def _complete_creator_snapshots(
        self,
        snapshots: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        ontology_version: str,
    ) -> list[dict[str, Any]]:
        grouped: dict[
            tuple[str, str, str],
            list[dict[str, Any]],
        ] = {}
        for item in evidence:
            key = (
                str(item["creator_id"]),
                str(item["platform"]),
                str(item["ability_id"]),
            )
            grouped.setdefault(key, []).append(item)
        snapshot_by_key = {
            (
                str(item["creator_id"]),
                str(item["platform"]),
                str(item["ability_id"]),
            ): item
            for item in snapshots
        }
        for key, items in grouped.items():
            snapshot = snapshot_by_key.get(key)
            if snapshot is None:
                first = items[0]
                residual = 1.0
                for item in items:
                    reliability = max(
                        0.0,
                        min(
                            1.0,
                            float(item["evidence_reliability"]) * 0.5,
                        ),
                    )
                    residual *= 1.0 - reliability
                snapshot_id = stable_id(
                    "creator_snapshot",
                    key[0],
                    key[1],
                    key[2],
                    ontology_version,
                )
                snapshot = {
                    "snapshot_id": snapshot_id,
                    "creator_id": key[0],
                    "creator_name": first["creator_name"],
                    "platform": key[1],
                    "ability_id": key[2],
                    "ability_score": None,
                    "confidence": round(1.0 - residual, 4),
                    "evidence_count": len(items),
                    "score_semantics": "ontology_evidence_only",
                    "calculated_at": "",
                }
                snapshots.append(snapshot)
                snapshot_by_key[key] = snapshot
            else:
                snapshot["evidence_count"] = max(1, len(items))
            for item in items:
                if not item.get("snapshot_id"):
                    item["snapshot_id"] = snapshot["snapshot_id"]
        return snapshots

    def _migrate_video_observations(
        self,
        integrated: dict[str, Any],
        mappings: list[TermMapping],
        source_path: Path,
        ontology_config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        metric_mappings: dict[str, list[TermMapping]] = {}
        for item in mappings:
            if item.taxonomy_type != "video_metric":
                continue
            metric_mappings.setdefault(item.term_name, []).append(item)
        ontology_version = str(
            ontology_config.get("ontology_version") or "1.0.0"
        )
        observations: list[dict[str, Any]] = []
        for video in integrated.get("videos") or []:
            video_id = str(video.get("video_id") or "").strip()
            if not video_id:
                continue
            for metric, targets in metric_mappings.items():
                value = video.get(metric)
                if not has_value(value):
                    continue
                for target in targets:
                    observed_score = self._metric_score(metric, value)
                    observations.append(
                        {
                            "observation_id": stable_id(
                                "video_observation",
                                video_id,
                                target.ability_id,
                                metric,
                                ontology_version,
                            ),
                            "video_id": video_id,
                            "creator_name": str(
                                video.get("author") or ""
                            ),
                            "ability_id": target.ability_id,
                            "source_metric": metric,
                            "raw_value": value,
                            "observed_score": observed_score,
                            "confidence": round(
                                target.confidence * target.weight,
                                4,
                            ),
                            "source_analysis_ref": str(source_path),
                        }
                    )
        return observations

    def _metric_score(
        self,
        metric: str,
        value: Any,
    ) -> float | None:
        if metric == "hook_score" and isinstance(value, (int, float)):
            score = float(value)
            if score <= 10:
                score *= 10
            return round(max(0.0, min(100.0, score)), 2)
        return None


def migrate_legacy_data(
    settings: Settings = SETTINGS,
    dry_run: bool = False,
    database_path: Path | None = None,
) -> dict[str, Any]:
    repository = AbilityOntologyRepository(
        settings,
        database_path=database_path,
    )
    return LegacyOntologyMigrator(
        settings,
        repository=repository,
    ).migrate(dry_run=dry_run)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate existing Creator Intelligence JSON data into the "
            "additive Ability Ontology database."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and count records without creating or changing a database.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        help="Optional SQLite path. Defaults to cache/intelligence/ability_ontology.sqlite3.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = migrate_legacy_data(
        dry_run=args.dry_run,
        database_path=args.database,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
