from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class CreatorProgressStore:
    """Durable creator/video queue, intentionally separate from media caches."""

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    def state(self, platform: str, creator_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT scan_limit, scan_exhausted
                FROM creator_scan_state
                WHERE platform = ? AND creator_id = ?
                """,
                (platform, creator_id),
            ).fetchone()
        if row is None:
            return {"scan_limit": 0, "scan_exhausted": False}
        return {"scan_limit": int(row[0] or 0), "scan_exhausted": bool(row[1])}

    def completed_video_ids(self, platform: str, creator_id: str) -> frozenset[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT video_id FROM creator_videos
                WHERE platform = ? AND creator_id = ? AND status = 'analyzed'
                """,
                (platform, creator_id),
            ).fetchall()
        return frozenset(str(row[0]) for row in rows)

    def analyzed_count(self, platform: str, creator_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) FROM creator_videos
                WHERE platform = ? AND creator_id = ? AND status = 'analyzed'
                """,
                (platform, creator_id),
            ).fetchone()
        return int(row[0] or 0)

    def pending_videos(
        self,
        platform: str,
        creator_id: str,
        limit: int,
    ) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT video_id, source_url, title
                FROM creator_videos
                WHERE platform = ? AND creator_id = ?
                  AND status IN ('queued', 'failed', 'processing')
                ORDER BY sequence_id
                LIMIT ?
                """,
                (platform, creator_id, max(0, int(limit))),
            ).fetchall()
        return [
            {"video_id": str(row[0]), "source_url": str(row[1] or ""), "title": str(row[2] or "")}
            for row in rows
        ]

    def pending_count(self, platform: str, creator_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) FROM creator_videos
                WHERE platform = ? AND creator_id = ?
                  AND status IN ('queued', 'failed', 'processing')
                """,
                (platform, creator_id),
            ).fetchone()
        return int(row[0] or 0)

    def record_candidates(
        self,
        platform: str,
        creator_id: str,
        source: str,
        videos: list[dict[str, Any]],
        *,
        scan_limit: int,
        scan_exhausted: bool,
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for video in videos:
                video_id = str(video.get("video_id") or "").strip()
                source_url = str(video.get("source_url") or "").strip()
                if not video_id or not source_url:
                    continue
                connection.execute(
                    """
                    INSERT INTO creator_videos
                        (platform, creator_id, video_id, source_url, title, status)
                    VALUES (?, ?, ?, ?, ?, 'queued')
                    ON CONFLICT(platform, creator_id, video_id) DO NOTHING
                    """,
                    (
                        platform,
                        creator_id,
                        video_id,
                        source_url,
                        str(video.get("title") or ""),
                    ),
                )
            connection.execute(
                """
                INSERT INTO creator_scan_state
                    (platform, creator_id, source, scan_limit, scan_exhausted)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(platform, creator_id) DO UPDATE SET
                    source = excluded.source,
                    scan_limit = MAX(creator_scan_state.scan_limit, excluded.scan_limit),
                    scan_exhausted = excluded.scan_exhausted,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (platform, creator_id, source, max(0, int(scan_limit)), int(scan_exhausted)),
            )

    def record_legacy_completed(
        self,
        platform: str,
        creator_id: str,
        video_ids: list[str] | set[str] | frozenset[str],
        *,
        source: str,
    ) -> None:
        ids = sorted({str(item).strip() for item in video_ids if str(item).strip()})
        if not ids:
            return
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO creator_videos
                    (platform, creator_id, video_id, source_url, title, status)
                VALUES (?, ?, ?, ?, '', 'analyzed')
                ON CONFLICT(platform, creator_id, video_id) DO NOTHING
                """,
                [(platform, creator_id, item, source) for item in ids],
            )

    def mark_processing(self, platform: str, creator_id: str, video_id: str) -> None:
        self._set_status(platform, creator_id, video_id, "processing", None)

    def mark_analyzed(
        self,
        platform: str,
        creator_id: str,
        video_id: str,
        source_url: str,
        title: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO creator_videos
                    (platform, creator_id, video_id, source_url, title, status)
                VALUES (?, ?, ?, ?, ?, 'analyzed')
                ON CONFLICT(platform, creator_id, video_id) DO UPDATE SET
                    source_url = excluded.source_url,
                    title = excluded.title,
                    status = 'analyzed',
                    last_error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (platform, creator_id, video_id, source_url, title),
            )

    def mark_failed(
        self,
        platform: str,
        creator_id: str,
        video_id: str,
        error: str,
    ) -> None:
        self._set_status(platform, creator_id, video_id, "failed", error)

    def _set_status(
        self,
        platform: str,
        creator_id: str,
        video_id: str,
        status: str,
        error: str | None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE creator_videos SET
                    status = ?, last_error = ?, updated_at = CURRENT_TIMESTAMP
                WHERE platform = ? AND creator_id = ? AND video_id = ?
                """,
                (status, error, platform, creator_id, video_id),
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS creator_scan_state (
                platform TEXT NOT NULL,
                creator_id TEXT NOT NULL,
                source TEXT NOT NULL,
                scan_limit INTEGER NOT NULL DEFAULT 0,
                scan_exhausted INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(platform, creator_id)
            );
            CREATE TABLE IF NOT EXISTS creator_videos (
                sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                creator_id TEXT NOT NULL,
                video_id TEXT NOT NULL,
                source_url TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued',
                last_error TEXT,
                discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(platform, creator_id, video_id)
            );
            CREATE INDEX IF NOT EXISTS idx_creator_videos_queue
                ON creator_videos(platform, creator_id, status, sequence_id);
            """
        )
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def migrate_legacy_creator_outputs(
    output_dir: Path,
    store: CreatorProgressStore,
) -> int:
    """Import trusted successful IDs from creator-specific legacy manifests."""

    if not output_dir.is_dir():
        return 0
    migrated = 0
    for creator_dir in output_dir.iterdir():
        if not creator_dir.is_dir():
            continue
        if creator_dir.name.startswith("up_"):
            platform = "bilibili"
        elif creator_dir.name.startswith("channel_youtube_"):
            platform = "youtube"
        else:
            continue

        ids: set[str] = set()
        source = creator_dir.name
        index_path = creator_dir / "creator_video_index.json"
        manifest_path = creator_dir / "batch_manifest.json"
        for path in (index_path, manifest_path):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            if payload.get("source"):
                source = str(payload["source"])
            legacy_ids = payload.get("video_ids")
            if isinstance(legacy_ids, list):
                ids.update(str(item).strip() for item in legacy_ids if str(item).strip())
            outputs = payload.get("outputs")
            if isinstance(outputs, list):
                ids.update(
                    str(item.get("video_id") or "").strip()
                    for item in outputs
                    if isinstance(item, dict)
                    and str(item.get("video_id") or "").strip()
                )

        if ids:
            store.record_legacy_completed(
                platform,
                creator_dir.name,
                ids,
                source=source,
            )
            migrated += len(ids)
    return migrated
