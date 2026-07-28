from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from config import SETTINGS, Settings

from .models import AbilityRecord, MigrationPlan, TermMapping


SCHEMA_VERSION = 1


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ontology_release (
    ontology_version TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    status TEXT NOT NULL,
    source_checksum TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ability (
    ability_id TEXT PRIMARY KEY,
    ability_key TEXT NOT NULL UNIQUE,
    ability_name TEXT NOT NULL,
    parent_ability_id TEXT NULL REFERENCES ability(ability_id),
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ability_revision (
    ability_id TEXT NOT NULL REFERENCES ability(ability_id),
    ontology_version TEXT NOT NULL REFERENCES ontology_release(ontology_version),
    definition TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    PRIMARY KEY (ability_id, ontology_version)
);

CREATE TABLE IF NOT EXISTS evaluation_rule (
    rule_id TEXT PRIMARY KEY,
    ability_id TEXT NOT NULL REFERENCES ability(ability_id),
    ontology_version TEXT NOT NULL REFERENCES ontology_release(ontology_version),
    rule_key TEXT NOT NULL,
    rule_text TEXT NOT NULL,
    weight REAL NOT NULL,
    evaluator_type TEXT NOT NULL DEFAULT 'rule',
    metric_key TEXT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE (ability_id, ontology_version, rule_key)
);

CREATE TABLE IF NOT EXISTS taxonomy_term (
    term_id TEXT PRIMARY KEY,
    taxonomy_type TEXT NOT NULL,
    source_key TEXT NOT NULL,
    term_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'zh',
    source_system TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (taxonomy_type, source_system, normalized_name)
);

CREATE TABLE IF NOT EXISTS ability_mapping (
    mapping_id TEXT PRIMARY KEY,
    term_id TEXT NOT NULL REFERENCES taxonomy_term(term_id),
    ability_id TEXT NOT NULL REFERENCES ability(ability_id),
    ontology_version TEXT NOT NULL REFERENCES ontology_release(ontology_version),
    relation_type TEXT NOT NULL,
    weight REAL NOT NULL,
    confidence REAL NOT NULL,
    source TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE (term_id, ability_id, ontology_version)
);

CREATE TABLE IF NOT EXISTS creator_ability_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    creator_id TEXT NOT NULL,
    creator_name TEXT NOT NULL,
    platform TEXT NOT NULL,
    ability_id TEXT NOT NULL REFERENCES ability(ability_id),
    ability_score REAL NULL,
    confidence REAL NOT NULL,
    evidence_count INTEGER NOT NULL,
    score_semantics TEXT NOT NULL,
    ontology_version TEXT NOT NULL REFERENCES ontology_release(ontology_version),
    calculated_at TEXT NOT NULL,
    UNIQUE (creator_id, platform, ability_id, ontology_version)
);

CREATE TABLE IF NOT EXISTS creator_ability_evidence (
    evidence_id TEXT PRIMARY KEY,
    snapshot_id TEXT NULL REFERENCES creator_ability_snapshot(snapshot_id),
    creator_id TEXT NOT NULL,
    creator_name TEXT NOT NULL,
    platform TEXT NOT NULL,
    ability_id TEXT NOT NULL REFERENCES ability(ability_id),
    source_type TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    raw_label TEXT NOT NULL,
    raw_score REAL NULL,
    mapping_weight REAL NOT NULL,
    evidence_reliability REAL NOT NULL,
    contribution_score REAL NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE (
        creator_id,
        platform,
        ability_id,
        source_type,
        source_ref,
        raw_label
    )
);

CREATE TABLE IF NOT EXISTS video_ability_observation (
    observation_id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    creator_name TEXT NOT NULL DEFAULT '',
    ability_id TEXT NOT NULL REFERENCES ability(ability_id),
    source_metric TEXT NOT NULL,
    raw_value_json TEXT NOT NULL,
    observed_score REAL NULL,
    confidence REAL NOT NULL,
    source_analysis_ref TEXT NOT NULL,
    ontology_version TEXT NOT NULL REFERENCES ontology_release(ontology_version),
    created_at TEXT NOT NULL,
    UNIQUE (video_id, ability_id, source_metric, ontology_version)
);

CREATE TABLE IF NOT EXISTS review_ability_gap (
    gap_id TEXT PRIMARY KEY,
    review_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    ability_id TEXT NOT NULL REFERENCES ability(ability_id),
    expected_score REAL NULL,
    observed_score REAL NULL,
    gap_score REAL NULL,
    status TEXT NOT NULL,
    reason_json TEXT NOT NULL DEFAULT '{}',
    ontology_version TEXT NOT NULL REFERENCES ontology_release(ontology_version),
    created_at TEXT NOT NULL,
    UNIQUE (review_id, ability_id)
);

CREATE TABLE IF NOT EXISTS migration_run (
    run_id TEXT PRIMARY KEY,
    ontology_version TEXT NOT NULL,
    source_checksum TEXT NOT NULL,
    status TEXT NOT NULL,
    dry_run INTEGER NOT NULL DEFAULT 0,
    counts_json TEXT NOT NULL DEFAULT '{}',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    started_at TEXT NOT NULL,
    finished_at TEXT NULL,
    UNIQUE (ontology_version, source_checksum, dry_run)
);

CREATE INDEX IF NOT EXISTS idx_mapping_term ON ability_mapping(term_id);
CREATE INDEX IF NOT EXISTS idx_mapping_ability ON ability_mapping(ability_id);
CREATE INDEX IF NOT EXISTS idx_creator_snapshot_creator
    ON creator_ability_snapshot(creator_id, platform);
CREATE INDEX IF NOT EXISTS idx_creator_evidence_creator
    ON creator_ability_evidence(creator_id, platform, ability_id);
CREATE INDEX IF NOT EXISTS idx_video_observation_video
    ON video_ability_observation(video_id);
"""


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def stable_id(*parts: object) -> str:
    raw = "|".join(str(part or "").strip().lower() for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def normalize_term(value: str) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


class AbilityOntologyRepository:
    def __init__(
        self,
        settings: Settings = SETTINGS,
        database_path: Path | None = None,
    ) -> None:
        self.settings = settings
        self.database_path = database_path or (
            settings.cache_dir / "intelligence" / "ability_ontology.sqlite3"
        )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    def initialize_schema(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA_SQL)
            connection.commit()

    def migration_exists(
        self,
        ontology_version: str,
        source_checksum: str,
    ) -> bool:
        if not self.database_path.exists():
            return False
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM migration_run
                WHERE ontology_version = ?
                  AND source_checksum = ?
                  AND dry_run = 0
                  AND status = 'completed'
                """,
                (ontology_version, source_checksum),
            ).fetchone()
        return row is not None

    def apply_migration(self, plan: MigrationPlan) -> dict[str, Any]:
        self.initialize_schema()
        if self.migration_exists(plan.ontology_version, plan.source_checksum):
            return {
                "status": "skipped",
                "reason": "identical source snapshot already migrated",
                "ontology_version": plan.ontology_version,
                "source_checksum": plan.source_checksum,
                "database_path": str(self.database_path),
                "counts": plan.counts(),
            }

        timestamp = now_iso()
        run_id = stable_id(
            "migration",
            plan.ontology_version,
            plan.source_checksum,
        )
        with self.connect() as connection:
            try:
                connection.execute("BEGIN")
                self._insert_release(connection, plan, timestamp)
                ability_ids = {item.ability_id for item in plan.abilities}
                self._insert_abilities(connection, plan, timestamp)
                mapping_ids = self._insert_mappings(connection, plan, timestamp)
                self._insert_creator_snapshots(
                    connection,
                    plan,
                    ability_ids,
                    timestamp,
                )
                self._insert_creator_evidence(
                    connection,
                    plan,
                    ability_ids,
                    timestamp,
                )
                self._insert_video_observations(
                    connection,
                    plan,
                    ability_ids,
                    timestamp,
                )
                counts = {
                    **plan.counts(),
                    "taxonomy_terms": len(mapping_ids["term_ids"]),
                    "ability_mappings": len(mapping_ids["mapping_ids"]),
                }
                connection.execute(
                    """
                    INSERT INTO migration_run (
                        run_id,
                        ontology_version,
                        source_checksum,
                        status,
                        dry_run,
                        counts_json,
                        warnings_json,
                        started_at,
                        finished_at
                    ) VALUES (?, ?, ?, 'completed', 0, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        plan.ontology_version,
                        plan.source_checksum,
                        json.dumps(counts, ensure_ascii=False),
                        json.dumps(plan.warnings, ensure_ascii=False),
                        timestamp,
                        now_iso(),
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

        return {
            "status": "completed",
            "ontology_version": plan.ontology_version,
            "source_checksum": plan.source_checksum,
            "database_path": str(self.database_path),
            "counts": counts,
            "warnings": plan.warnings,
        }

    def get_ability(self, ability_key: str) -> dict[str, Any] | None:
        if not self.database_path.exists():
            return None
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    a.*,
                    r.definition,
                    r.ontology_version
                FROM ability AS a
                JOIN ability_revision AS r ON r.ability_id = a.ability_id
                WHERE a.ability_key = ?
                ORDER BY r.ontology_version DESC
                LIMIT 1
                """,
                (ability_key,),
            ).fetchone()
            if row is None:
                return None
            rules = connection.execute(
                """
                SELECT rule_key, rule_text, weight, evaluator_type, metric_key
                FROM evaluation_rule
                WHERE ability_id = ? AND ontology_version = ? AND active = 1
                ORDER BY rule_key
                """,
                (row["ability_id"], row["ontology_version"]),
            ).fetchall()
        return {
            **dict(row),
            "evaluation_rules": [dict(item) for item in rules],
        }

    def map_term(
        self,
        taxonomy_type: str,
        term_name: str,
    ) -> list[dict[str, Any]]:
        if not self.database_path.exists():
            return []
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    t.taxonomy_type,
                    t.term_name,
                    a.ability_id,
                    a.ability_key,
                    a.ability_name,
                    m.relation_type,
                    m.weight,
                    m.confidence,
                    m.ontology_version
                FROM taxonomy_term AS t
                JOIN ability_mapping AS m ON m.term_id = t.term_id
                JOIN ability AS a ON a.ability_id = m.ability_id
                WHERE t.taxonomy_type = ?
                  AND t.normalized_name = ?
                  AND m.active = 1
                ORDER BY m.weight DESC, m.confidence DESC, a.ability_key
                """,
                (taxonomy_type, normalize_term(term_name)),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_creator_profile(
        self,
        creator_name: str,
        platform: str = "bilibili",
    ) -> dict[str, Any]:
        if not self.database_path.exists():
            return {
                "creator_name": creator_name,
                "platform": platform,
                "abilities": [],
            }
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    s.creator_id,
                    s.creator_name,
                    s.platform,
                    a.ability_id,
                    a.ability_key,
                    a.ability_name,
                    s.ability_score,
                    s.confidence,
                    s.evidence_count,
                    s.score_semantics,
                    s.ontology_version,
                    s.calculated_at
                FROM creator_ability_snapshot AS s
                JOIN ability AS a ON a.ability_id = s.ability_id
                WHERE s.creator_name = ? AND s.platform = ?
                ORDER BY s.confidence DESC, s.ability_score DESC, a.ability_key
                """,
                (creator_name, platform),
            ).fetchall()
        return {
            "creator_name": creator_name,
            "platform": platform,
            "abilities": [dict(row) for row in rows],
        }

    def latest_ontology_version(self) -> str | None:
        if not self.database_path.exists():
            return None
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT ontology_version
                FROM ontology_release
                WHERE status = 'active'
                ORDER BY created_at DESC, ontology_version DESC
                LIMIT 1
                """
            ).fetchone()
        return str(row["ontology_version"]) if row else None

    def save_video_observations(
        self,
        observations: list[dict[str, Any]],
        ontology_version: str | None = None,
    ) -> int:
        if not observations:
            return 0
        selected_version = ontology_version or self.latest_ontology_version()
        if not selected_version:
            raise RuntimeError(
                "Ability Ontology database is not initialized. Run the "
                "ontology migration first."
            )
        timestamp = now_iso()
        with self.connect() as connection:
            connection.execute("BEGIN")
            for item in observations:
                connection.execute(
                    """
                    INSERT INTO video_ability_observation (
                        observation_id,
                        video_id,
                        creator_name,
                        ability_id,
                        source_metric,
                        raw_value_json,
                        observed_score,
                        confidence,
                        source_analysis_ref,
                        ontology_version,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(
                        video_id,
                        ability_id,
                        source_metric,
                        ontology_version
                    ) DO UPDATE SET
                        creator_name = excluded.creator_name,
                        raw_value_json = excluded.raw_value_json,
                        observed_score = excluded.observed_score,
                        confidence = excluded.confidence,
                        source_analysis_ref = excluded.source_analysis_ref,
                        created_at = excluded.created_at
                    """,
                    (
                        item["observation_id"],
                        item["video_id"],
                        item.get("creator_name") or "",
                        item["ability_id"],
                        item["source_metric"],
                        json.dumps(
                            item.get("raw_value"),
                            ensure_ascii=False,
                        ),
                        item.get("observed_score"),
                        float(item["confidence"]),
                        str(item.get("source_analysis_ref") or ""),
                        selected_version,
                        timestamp,
                    ),
                )
            connection.commit()
        return len(observations)

    def get_video_observations(
        self,
        video_id: str,
        ontology_version: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.database_path.exists():
            return []
        selected_version = ontology_version or self.latest_ontology_version()
        if not selected_version:
            return []
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    o.observation_id,
                    o.video_id,
                    o.creator_name,
                    o.source_metric,
                    o.raw_value_json,
                    o.observed_score,
                    o.confidence,
                    o.source_analysis_ref,
                    o.ontology_version,
                    o.created_at,
                    a.ability_id,
                    a.ability_key,
                    a.ability_name
                FROM video_ability_observation AS o
                JOIN ability AS a ON a.ability_id = o.ability_id
                WHERE o.video_id = ? AND o.ontology_version = ?
                ORDER BY a.ability_key, o.source_metric
                """,
                (video_id, selected_version),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["raw_value"] = json.loads(
                item.pop("raw_value_json")
            )
            result.append(item)
        return result

    def table_counts(self) -> dict[str, int]:
        if not self.database_path.exists():
            return {}
        tables = [
            "ontology_release",
            "ability",
            "ability_revision",
            "evaluation_rule",
            "taxonomy_term",
            "ability_mapping",
            "creator_ability_snapshot",
            "creator_ability_evidence",
            "video_ability_observation",
            "review_ability_gap",
            "migration_run",
        ]
        with self.connect() as connection:
            return {
                table: int(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                )
                for table in tables
            }

    def _insert_release(
        self,
        connection: sqlite3.Connection,
        plan: MigrationPlan,
        timestamp: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO ontology_release (
                ontology_version,
                schema_version,
                status,
                source_checksum,
                metadata_json,
                created_at
            ) VALUES (?, ?, 'active', ?, ?, ?)
            ON CONFLICT(ontology_version) DO UPDATE SET
                schema_version = excluded.schema_version,
                status = excluded.status,
                source_checksum = excluded.source_checksum,
                metadata_json = excluded.metadata_json
            """,
            (
                plan.ontology_version,
                plan.schema_version,
                plan.source_checksum,
                json.dumps(
                    {"source_paths": plan.source_paths},
                    ensure_ascii=False,
                ),
                timestamp,
            ),
        )

    def _insert_abilities(
        self,
        connection: sqlite3.Connection,
        plan: MigrationPlan,
        timestamp: str,
    ) -> None:
        for item in plan.abilities:
            connection.execute(
                """
                INSERT INTO ability (
                    ability_id,
                    ability_key,
                    ability_name,
                    parent_ability_id,
                    status,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ability_id) DO UPDATE SET
                    ability_key = excluded.ability_key,
                    ability_name = excluded.ability_name,
                    parent_ability_id = excluded.parent_ability_id,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    item.ability_id,
                    item.ability_key,
                    item.ability_name,
                    None,
                    item.status,
                    timestamp,
                    timestamp,
                ),
            )

        for item in plan.abilities:
            connection.execute(
                """
                UPDATE ability
                SET parent_ability_id = ?, updated_at = ?
                WHERE ability_id = ?
                """,
                (item.parent_ability_id, timestamp, item.ability_id),
            )
            connection.execute(
                """
                INSERT INTO ability_revision (
                    ability_id,
                    ontology_version,
                    definition,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, '{}', ?)
                ON CONFLICT(ability_id, ontology_version) DO UPDATE SET
                    definition = excluded.definition
                """,
                (
                    item.ability_id,
                    plan.ontology_version,
                    item.definition,
                    timestamp,
                ),
            )
            for index, rule in enumerate(item.evaluation_rules):
                rule_key = str(rule.get("rule_key") or f"rule_{index + 1}")
                connection.execute(
                    """
                    INSERT INTO evaluation_rule (
                        rule_id,
                        ability_id,
                        ontology_version,
                        rule_key,
                        rule_text,
                        weight,
                        evaluator_type,
                        metric_key,
                        config_json,
                        active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(rule_id) DO UPDATE SET
                        rule_text = excluded.rule_text,
                        weight = excluded.weight,
                        evaluator_type = excluded.evaluator_type,
                        metric_key = excluded.metric_key,
                        config_json = excluded.config_json,
                        active = 1
                    """,
                    (
                        stable_id(
                            "rule",
                            item.ability_id,
                            plan.ontology_version,
                            rule_key,
                        ),
                        item.ability_id,
                        plan.ontology_version,
                        rule_key,
                        str(rule.get("rule_text") or rule.get("text") or ""),
                        float(rule.get("weight", 1.0)),
                        str(rule.get("evaluator_type") or "rule"),
                        rule.get("metric_key"),
                        json.dumps(
                            rule.get("config") or {},
                            ensure_ascii=False,
                        ),
                    ),
                )

    def _insert_mappings(
        self,
        connection: sqlite3.Connection,
        plan: MigrationPlan,
        timestamp: str,
    ) -> dict[str, set[str]]:
        term_ids: set[str] = set()
        mapping_ids: set[str] = set()
        for item in plan.mappings:
            normalized = normalize_term(item.term_name)
            term_id = stable_id(
                "term",
                item.taxonomy_type,
                item.source_system,
                normalized,
            )
            mapping_id = stable_id(
                "mapping",
                term_id,
                item.ability_id,
                plan.ontology_version,
            )
            connection.execute(
                """
                INSERT INTO taxonomy_term (
                    term_id,
                    taxonomy_type,
                    source_key,
                    term_name,
                    normalized_name,
                    language,
                    source_system,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(term_id) DO UPDATE SET
                    source_key = excluded.source_key,
                    term_name = excluded.term_name,
                    language = excluded.language
                """,
                (
                    term_id,
                    item.taxonomy_type,
                    item.source_key,
                    item.term_name,
                    normalized,
                    item.language,
                    item.source_system,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO ability_mapping (
                    mapping_id,
                    term_id,
                    ability_id,
                    ontology_version,
                    relation_type,
                    weight,
                    confidence,
                    source,
                    active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(mapping_id) DO UPDATE SET
                    relation_type = excluded.relation_type,
                    weight = excluded.weight,
                    confidence = excluded.confidence,
                    source = excluded.source,
                    active = 1
                """,
                (
                    mapping_id,
                    term_id,
                    item.ability_id,
                    plan.ontology_version,
                    item.relation_type,
                    item.weight,
                    item.confidence,
                    item.source_system,
                ),
            )
            term_ids.add(term_id)
            mapping_ids.add(mapping_id)
        return {"term_ids": term_ids, "mapping_ids": mapping_ids}

    def _insert_creator_snapshots(
        self,
        connection: sqlite3.Connection,
        plan: MigrationPlan,
        ability_ids: set[str],
        timestamp: str,
    ) -> None:
        for item in plan.creator_snapshots:
            if item["ability_id"] not in ability_ids:
                continue
            connection.execute(
                """
                INSERT INTO creator_ability_snapshot (
                    snapshot_id,
                    creator_id,
                    creator_name,
                    platform,
                    ability_id,
                    ability_score,
                    confidence,
                    evidence_count,
                    score_semantics,
                    ontology_version,
                    calculated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    creator_id,
                    platform,
                    ability_id,
                    ontology_version
                ) DO UPDATE SET
                    creator_name = excluded.creator_name,
                    ability_score = excluded.ability_score,
                    confidence = excluded.confidence,
                    evidence_count = excluded.evidence_count,
                    score_semantics = excluded.score_semantics,
                    calculated_at = excluded.calculated_at
                """,
                (
                    item["snapshot_id"],
                    item["creator_id"],
                    item["creator_name"],
                    item["platform"],
                    item["ability_id"],
                    item.get("ability_score"),
                    item["confidence"],
                    item["evidence_count"],
                    item["score_semantics"],
                    plan.ontology_version,
                    item.get("calculated_at") or timestamp,
                ),
            )

    def _insert_creator_evidence(
        self,
        connection: sqlite3.Connection,
        plan: MigrationPlan,
        ability_ids: set[str],
        timestamp: str,
    ) -> None:
        for item in plan.creator_evidence:
            if item["ability_id"] not in ability_ids:
                continue
            connection.execute(
                """
                INSERT INTO creator_ability_evidence (
                    evidence_id,
                    snapshot_id,
                    creator_id,
                    creator_name,
                    platform,
                    ability_id,
                    source_type,
                    source_ref,
                    raw_label,
                    raw_score,
                    mapping_weight,
                    evidence_reliability,
                    contribution_score,
                    payload_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(evidence_id) DO UPDATE SET
                    snapshot_id = excluded.snapshot_id,
                    raw_score = excluded.raw_score,
                    mapping_weight = excluded.mapping_weight,
                    evidence_reliability = excluded.evidence_reliability,
                    contribution_score = excluded.contribution_score,
                    payload_json = excluded.payload_json
                """,
                (
                    item["evidence_id"],
                    item.get("snapshot_id"),
                    item["creator_id"],
                    item["creator_name"],
                    item["platform"],
                    item["ability_id"],
                    item["source_type"],
                    item["source_ref"],
                    item["raw_label"],
                    item.get("raw_score"),
                    item["mapping_weight"],
                    item["evidence_reliability"],
                    item.get("contribution_score"),
                    json.dumps(
                        item.get("payload") or {},
                        ensure_ascii=False,
                    ),
                    timestamp,
                ),
            )

    def _insert_video_observations(
        self,
        connection: sqlite3.Connection,
        plan: MigrationPlan,
        ability_ids: set[str],
        timestamp: str,
    ) -> None:
        for item in plan.video_observations:
            if item["ability_id"] not in ability_ids:
                continue
            connection.execute(
                """
                INSERT INTO video_ability_observation (
                    observation_id,
                    video_id,
                    creator_name,
                    ability_id,
                    source_metric,
                    raw_value_json,
                    observed_score,
                    confidence,
                    source_analysis_ref,
                    ontology_version,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    video_id,
                    ability_id,
                    source_metric,
                    ontology_version
                ) DO UPDATE SET
                    creator_name = excluded.creator_name,
                    raw_value_json = excluded.raw_value_json,
                    observed_score = excluded.observed_score,
                    confidence = excluded.confidence,
                    source_analysis_ref = excluded.source_analysis_ref,
                    created_at = excluded.created_at
                """,
                (
                    item["observation_id"],
                    item["video_id"],
                    item.get("creator_name") or "",
                    item["ability_id"],
                    item["source_metric"],
                    json.dumps(
                        item.get("raw_value"),
                        ensure_ascii=False,
                    ),
                    item.get("observed_score"),
                    item["confidence"],
                    item["source_analysis_ref"],
                    plan.ontology_version,
                    timestamp,
                ),
            )
