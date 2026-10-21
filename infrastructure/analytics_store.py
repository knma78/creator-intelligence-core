from __future__ import annotations

import json
import logging
import statistics
import threading
from pathlib import Path
from typing import Any, Callable

from config import SETTINGS, Settings
from infrastructure.artifacts import files_fingerprint
from infrastructure.cancellation import raise_if_cancelled
from models import AnalysisResult, Transcript, Video

logger = logging.getLogger(__name__)
_WRITE_LOCK = threading.RLock()


def load_known_video_ids(
    settings: Settings = SETTINGS,
    *,
    platform: str | None = None,
) -> set[str]:
    """Return videos that have already produced durable research data.

    DuckDB is the primary source.  Completed ``analysis.json`` artifacts are
    also included so deduplication remains safe when DuckDB was disabled or a
    previous persistence attempt failed after the research files were written.
    """

    known: set[str] = set()
    database_path = settings.analytics_database_path
    if database_path.is_file():
        try:
            import duckdb

            with _WRITE_LOCK:
                connection = duckdb.connect(str(database_path), read_only=True)
                try:
                    if platform:
                        rows = connection.execute(
                            "SELECT video_id FROM videos WHERE lower(platform) = ?",
                            [platform.strip().lower()],
                        ).fetchall()
                    else:
                        rows = connection.execute(
                            "SELECT video_id FROM videos"
                        ).fetchall()
                finally:
                    connection.close()
            known.update(
                str(row[0]).strip()
                for row in rows
                if row and str(row[0] or "").strip()
            )
        except Exception as exc:
            logger.warning("DuckDB known-video lookup failed: %s", exc)

    if settings.output_dir.is_dir():
        for analysis_path in settings.output_dir.rglob("analysis.json"):
            if {
                "video_production",
                "creator_knowledge_base",
            }.intersection(analysis_path.parts):
                continue
            video_id = analysis_path.parent.name.strip()
            if not video_id:
                continue
            if platform and not _artifact_matches_platform(
                video_id,
                platform,
                settings,
            ):
                continue
            known.add(video_id)
    return known


def persist_video_analysis(
    video: Video,
    transcript: Transcript,
    analysis: AnalysisResult,
    enrichment: dict[str, Any] | None,
    settings: Settings = SETTINGS,
) -> dict[str, Any]:
    if not settings.analytics_store_enabled:
        return {"status": "skipped", "reason": "analytics store disabled"}

    try:
        import duckdb
    except ImportError:
        return {"status": "unavailable", "reason": "missing dependency: duckdb"}

    database_path = settings.analytics_database_path
    database_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _WRITE_LOCK:
            connection = duckdb.connect(str(database_path))
            try:
                _ensure_schema(connection)
                connection.execute("BEGIN TRANSACTION")
                _replace_video(connection, video)
                _replace_analysis(connection, transcript, analysis)
                _replace_enrichment(connection, video.video_id, enrichment)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        return {
            "status": "ok",
            "engine": "DuckDB",
            "database_path": str(database_path),
            "video_id": video.video_id,
        }
    except Exception as exc:  # pragma: no cover - database/backend dependent
        logger.warning("DuckDB persistence failed for %s: %s", video.video_id, exc)
        return {
            "status": "failed",
            "reason": str(exc),
            "database_path": str(database_path),
        }


def backfill_analytics_from_outputs(
    settings: Settings = SETTINGS,
    *,
    force: bool = False,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Synchronize existing JSON research outputs into DuckDB.

    The fingerprint ledger makes this safe to call before every knowledge-base
    build: unchanged videos are skipped without rerunning analysis.
    """

    if not settings.analytics_store_enabled:
        return {"status": "skipped", "reason": "analytics store disabled"}
    try:
        import duckdb
    except ImportError:
        return {"status": "unavailable", "reason": "missing dependency: duckdb"}
    if not settings.output_dir.is_dir():
        return {"status": "empty", "scanned": 0, "updated": 0, "skipped": 0}

    candidates = [
        path
        for path in settings.output_dir.rglob("analysis.json")
        if not {
            "video_production",
            "creator_knowledge_base",
        }.intersection(path.parts)
    ]
    canonical_by_video: dict[str, Path] = {}
    for path in candidates:
        video_id = path.parent.name
        current = canonical_by_video.get(video_id)
        if current is None:
            canonical_by_video[video_id] = path
            continue
        current_depth = len(current.relative_to(settings.output_dir).parts)
        candidate_depth = len(path.relative_to(settings.output_dir).parts)
        if candidate_depth < current_depth:
            canonical_by_video[video_id] = path
    analysis_paths = list(canonical_by_video.values())
    updated = 0
    skipped = 0
    failures: list[dict[str, str]] = []
    settings.analytics_database_path.parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK:
        connection = duckdb.connect(str(settings.analytics_database_path))
        try:
            _ensure_schema(connection)
            known = {
                str(row[0]): str(row[1] or "")
                for row in connection.execute(
                    "SELECT video_id, source_fingerprint FROM artifact_ingest"
                ).fetchall()
            }
            connection.execute("BEGIN TRANSACTION")
            for analysis_path in sorted(analysis_paths):
                raise_if_cancelled(cancel_requested)
                research_dir = analysis_path.parent
                video_id = research_dir.name
                metadata_path = (
                    settings.video_cache_dir / video_id / "metadata.json"
                )
                v3_path = research_dir / "v3.json"
                transcript_path = research_dir / "subtitle.txt"
                if not transcript_path.is_file():
                    transcript_path = (
                        settings.transcript_cache_dir
                        / video_id
                        / "subtitle.txt"
                    )
                input_paths = [
                    analysis_path,
                    metadata_path,
                    v3_path,
                    transcript_path,
                ]
                fingerprint = files_fingerprint(input_paths)
                if not force and known.get(video_id) == fingerprint:
                    skipped += 1
                    continue
                try:
                    analysis_payload = _read_json_file(analysis_path)
                    if not analysis_payload:
                        raise ValueError("analysis.json is empty or invalid")
                    analysis_payload.setdefault("video_id", video_id)
                    metadata = _read_json_file(metadata_path)
                    video_payload = {
                        **metadata,
                        "video_id": video_id,
                        "source_url": str(
                            metadata.get("source_url")
                            or metadata.get("webpage_url")
                            or video_id
                        ),
                        "platform": str(metadata.get("platform") or "unknown"),
                        "title": str(
                            analysis_payload.get("title")
                            or metadata.get("title")
                            or video_id
                        ),
                    }
                    video = Video.from_dict(video_payload)
                    text = (
                        transcript_path.read_text(
                            encoding="utf-8-sig",
                            errors="replace",
                        )
                        if transcript_path.is_file()
                        else ""
                    )
                    transcript = Transcript(
                        video_id=video_id,
                        text=text,
                        source="backfill",
                        text_path=transcript_path,
                        srt_path=(
                            research_dir / "subtitle.srt"
                            if (research_dir / "subtitle.srt").is_file()
                            else None
                        ),
                    )
                    analysis = AnalysisResult.from_dict(analysis_payload)
                    enrichment = _read_json_file(v3_path) or None
                    _replace_video(connection, video)
                    _replace_analysis(connection, transcript, analysis)
                    _replace_enrichment(
                        connection,
                        video_id,
                        enrichment,
                    )
                    connection.execute(
                        """
                        INSERT INTO artifact_ingest
                            (video_id, source_fingerprint, updated_at)
                        VALUES (?, ?, now())
                        ON CONFLICT(video_id) DO UPDATE SET
                            source_fingerprint = excluded.source_fingerprint,
                            updated_at = now()
                        """,
                        [video_id, fingerprint],
                    )
                    updated += 1
                except Exception as exc:
                    failures.append(
                        {"video_id": video_id, "reason": str(exc)}
                    )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
    return {
        "status": "ok" if not failures else "partial",
        "scanned": len(analysis_paths),
        "updated": updated,
        "skipped": skipped,
        "failure_count": len(failures),
        "failures": failures[:20],
        "database_path": str(settings.analytics_database_path),
    }


def load_analytics_evidence(
    settings: Settings = SETTINGS,
) -> dict[str, Any]:
    database_path = settings.analytics_database_path
    empty = {
        "status": "empty",
        "database_path": str(database_path),
        "summary": _empty_summary(),
        "records": [],
    }
    if not settings.analytics_store_enabled or not database_path.exists():
        return empty
    try:
        import duckdb
    except ImportError:
        return {
            **empty,
            "status": "unavailable",
            "reason": "missing dependency: duckdb",
        }

    try:
        connection = duckdb.connect(str(database_path), read_only=True)
        try:
            rows = connection.execute(
                """
                SELECT
                    v.video_id,
                    v.title,
                    v.author,
                    v.duration,
                    e.cover_analysis_json,
                    e.scene_analysis_json,
                    e.audio_rhythm_json
                FROM videos v
                LEFT JOIN enrichments e USING (video_id)
                ORDER BY v.updated_at DESC
                """
            ).fetchall()
        finally:
            connection.close()
    except Exception as exc:
        logger.warning("DuckDB evidence read failed: %s", exc)
        return {
            **empty,
            "status": "failed",
            "reason": str(exc),
        }

    records = [
        _analytics_record(
            video_id=str(row[0]),
            title=str(row[1] or ""),
            author=str(row[2] or ""),
            duration=float(row[3] or 0),
            cover=_decode_json(row[4]),
            scenes=_decode_json(row[5]),
            audio=_decode_json(row[6]),
        )
        for row in rows
    ]
    return {
        "status": "ok",
        "database_path": str(database_path),
        "summary": _analytics_summary(records),
        "records": records,
    }


def get_analytics_summary(
    settings: Settings = SETTINGS,
) -> dict[str, Any]:
    payload = load_analytics_evidence(settings)
    return {
        "status": payload["status"],
        "database_path": payload["database_path"],
        "reason": payload.get("reason"),
        **payload["summary"],
    }


def _analytics_record(
    *,
    video_id: str,
    title: str,
    author: str,
    duration: float,
    cover: dict[str, Any],
    scenes: dict[str, Any],
    audio: dict[str, Any],
) -> dict[str, Any]:
    capabilities: list[dict[str, Any]] = []
    if audio.get("status") == "ok":
        metrics = {
            key: audio.get(key)
            for key in (
                "tempo_bpm",
                "onsets_per_minute",
                "silence_ratio",
                "dynamic_range_db",
                "analyzed_duration",
            )
        }
        capabilities.append(
            {
                "ability_keys": ["audio"],
                "category": "structured_audio_rhythm",
                "source": "duckdb:audio_rhythm",
                "metrics": metrics,
            }
        )
    if scenes.get("status") == "ok":
        metrics = {
            key: scenes.get(key)
            for key in (
                "scene_count",
                "cut_count",
                "average_scene_duration",
                "median_scene_duration",
                "pace",
                "sample_count",
            )
        }
        capabilities.append(
            {
                "ability_keys": ["editing", "camera"],
                "category": "structured_scene_rhythm",
                "source": "duckdb:scene_analysis",
                "metrics": metrics,
            }
        )
    visual = cover.get("visual_semantics") or {}
    if visual.get("status") == "ok":
        capabilities.append(
            {
                "ability_keys": ["visual", "thumbnail"],
                "category": "structured_visual_semantics",
                "source": "duckdb:openclip",
                "metrics": {
                    "top_labels": visual.get("top_labels") or [],
                    "device": visual.get("device"),
                },
            }
        )
    return {
        "video_id": video_id,
        "title": title,
        "author": author,
        "duration": duration,
        "capabilities": capabilities,
        "audio_ready": audio.get("status") == "ok",
        "scene_ready": scenes.get("status") == "ok",
        "visual_ready": visual.get("status") == "ok",
        "audio_metrics": audio if audio.get("status") == "ok" else {},
        "scene_metrics": scenes if scenes.get("status") == "ok" else {},
        "visual_metrics": visual if visual.get("status") == "ok" else {},
    }


def _analytics_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    audio = [item for item in records if item["audio_ready"]]
    scenes = [item for item in records if item["scene_ready"]]
    visual = [item for item in records if item["visual_ready"]]
    tempos = [
        float(item["audio_metrics"].get("tempo_bpm") or 0)
        for item in audio
        if item["audio_metrics"].get("tempo_bpm") is not None
    ]
    scene_durations = [
        float(item["scene_metrics"].get("average_scene_duration") or 0)
        for item in scenes
        if item["scene_metrics"].get("average_scene_duration") is not None
    ]
    return {
        "video_count": total,
        "audio_ready_count": len(audio),
        "scene_ready_count": len(scenes),
        "visual_ready_count": len(visual),
        "audio_coverage": _coverage(len(audio), total),
        "scene_coverage": _coverage(len(scenes), total),
        "visual_coverage": _coverage(len(visual), total),
        "median_tempo_bpm": (
            round(statistics.median(tempos), 2) if tempos else None
        ),
        "median_scene_duration": (
            round(statistics.median(scene_durations), 2)
            if scene_durations
            else None
        ),
        "capability_evidence_count": sum(
            len(item["capabilities"]) for item in records
        ),
    }


def _empty_summary() -> dict[str, Any]:
    return {
        "video_count": 0,
        "audio_ready_count": 0,
        "scene_ready_count": 0,
        "visual_ready_count": 0,
        "audio_coverage": 0.0,
        "scene_coverage": 0.0,
        "visual_coverage": 0.0,
        "median_tempo_bpm": None,
        "median_scene_duration": None,
        "capability_evidence_count": 0,
    }


def _coverage(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


def _decode_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value in (None, ""):
        return {}
    try:
        decoded = json.loads(str(value))
        return decoded if isinstance(decoded, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _ensure_schema(connection: Any) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS artifact_ingest (
            video_id VARCHAR PRIMARY KEY,
            source_fingerprint VARCHAR NOT NULL,
            updated_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS videos (
            video_id VARCHAR PRIMARY KEY,
            platform VARCHAR,
            source_url VARCHAR,
            title VARCHAR,
            author VARCHAR,
            cover_url VARCHAR,
            publish_time VARCHAR,
            duration DOUBLE,
            stats_json JSON,
            extra_metadata_json JSON,
            updated_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS analyses (
            video_id VARCHAR PRIMARY KEY,
            transcript_source VARCHAR,
            transcript_chars BIGINT,
            summary VARCHAR,
            hook_json JSON,
            structure_json JSON,
            transitions_json JSON,
            emotion_json JSON,
            rhythm_json JSON,
            keywords_json JSON,
            learnings_json JSON,
            raw_llm_json JSON,
            updated_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS enrichments (
            video_id VARCHAR PRIMARY KEY,
            comments_json JSON,
            comments_analysis_json JSON,
            cover_analysis_json JSON,
            title_stats_json JSON,
            nlp_analysis_json JSON,
            scene_analysis_json JSON,
            audio_rhythm_json JSON,
            updated_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE VIEW video_intelligence AS
        SELECT
            v.*,
            a.transcript_source,
            a.transcript_chars,
            a.summary,
            a.hook_json,
            a.structure_json,
            a.emotion_json,
            a.rhythm_json,
            a.keywords_json,
            e.cover_analysis_json,
            e.scene_analysis_json,
            e.audio_rhythm_json
        FROM videos v
        LEFT JOIN analyses a USING (video_id)
        LEFT JOIN enrichments e USING (video_id)
        """
    )


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _artifact_matches_platform(
    video_id: str,
    platform: str,
    settings: Settings,
) -> bool:
    metadata = _read_json_file(
        settings.video_cache_dir / video_id / "metadata.json"
    )
    artifact_platform = str(metadata.get("platform") or "").strip().lower()
    if artifact_platform:
        return artifact_platform == platform.strip().lower()

    expected = platform.strip().lower()
    if expected == "bilibili":
        return video_id.upper().startswith("BV") or video_id.lower().startswith("av")
    if expected == "douyin":
        return video_id.upper().startswith("DY_")
    if expected == "youtube":
        return not (
            video_id.upper().startswith(("BV", "DY_"))
            or video_id.lower().startswith("av")
        )
    return True


def _replace_video(connection: Any, video: Video) -> None:
    connection.execute("DELETE FROM videos WHERE video_id = ?", [video.video_id])
    connection.execute(
        """
        INSERT INTO videos VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp
        )
        """,
        [
            video.video_id,
            video.platform,
            video.source_url,
            video.title,
            video.author,
            video.cover,
            video.publish_time,
            video.duration,
            _json(video.stats),
            _json(video.extra_metadata),
        ],
    )


def _replace_analysis(
    connection: Any,
    transcript: Transcript,
    analysis: AnalysisResult,
) -> None:
    connection.execute(
        "DELETE FROM analyses WHERE video_id = ?",
        [analysis.video_id],
    )
    connection.execute(
        """
        INSERT INTO analyses VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp
        )
        """,
        [
            analysis.video_id,
            transcript.source,
            len(transcript.text),
            analysis.one_sentence_summary,
            _json(analysis.hook),
            _json(analysis.structure),
            _json(analysis.transitions),
            _json(analysis.emotion),
            _json(analysis.rhythm),
            _json(analysis.keywords),
            _json(analysis.learnings),
            _json(analysis.raw_llm_result),
        ],
    )


def _replace_enrichment(
    connection: Any,
    video_id: str,
    enrichment: dict[str, Any] | None,
) -> None:
    payload = enrichment or {}
    connection.execute(
        "DELETE FROM enrichments WHERE video_id = ?",
        [video_id],
    )
    connection.execute(
        """
        INSERT INTO enrichments VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp
        )
        """,
        [
            video_id,
            _json(payload.get("comments")),
            _json(payload.get("comments_analysis")),
            _json(payload.get("cover_analysis")),
            _json(payload.get("title_stats")),
            _json(payload.get("nlp_analysis")),
            _json(payload.get("scene_analysis")),
            _json(payload.get("audio_rhythm_analysis")),
        ],
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
