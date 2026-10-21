from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)

TERMINAL_JOB_STATUSES = {"done", "failed", "cancelled"}
ACTIVE_JOB_STATUSES = {"queued", "running"}


class JobQueueFullError(RuntimeError):
    pass


class JobStore:
    def __init__(
        self,
        database_path: Path,
        *,
        schema_version: str = "1.2",
        history_limit: int = 20,
        log_limit: int = 500,
        queue_capacity: int = 100,
    ) -> None:
        self.database_path = database_path
        self.schema_version = schema_version
        self.history_limit = max(1, history_limit)
        self.log_limit = max(1, log_limit)
        self.queue_capacity = max(1, queue_capacity)
        self._lock = threading.RLock()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:12]
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            active_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM jobs
                    WHERE status IN ('queued', 'running')
                    """
                ).fetchone()[0]
            )
            if active_count >= self.queue_capacity:
                connection.rollback()
                raise JobQueueFullError(
                    f"任务队列已满，最多允许 {self.queue_capacity} 个等待或运行任务。"
                )
            connection.execute(
                """
                INSERT INTO jobs (
                    id,
                    schema_version,
                    status,
                    progress,
                    stage,
                    progress_detail_json,
                    payload_json,
                    result_json,
                    error,
                    revision,
                    created_at,
                    started_at,
                    finished_at,
                    updated_at,
                    worker_id,
                    attempt_count
                ) VALUES (?, ?, 'queued', 0, 'queued', NULL, ?, NULL, NULL, 0, ?, NULL, NULL, ?, NULL, 0)
                """,
                (
                    job_id,
                    self.schema_version,
                    _json(payload),
                    now,
                    now,
                ),
            )
            self._insert_event(
                connection,
                job_id,
                "created",
                stage="queued",
                message="任务已创建。",
                payload={"status": "queued", "progress": 0},
                created_at=now,
            )
            connection.commit()
        job = self.get(job_id)
        if job is None:  # pragma: no cover - guarded by the transaction above
            raise RuntimeError(f"Failed to read newly created job: {job_id}")
        return job

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_job(connection, row)

    def list(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM (
                    SELECT *
                    FROM jobs
                    ORDER BY created_at DESC
                    LIMIT ?
                )
                ORDER BY created_at ASC
                """,
                (self.history_limit,),
            ).fetchall()
            return [self._row_to_job(connection, row) for row in rows]

    def update(self, job_id: str, **updates: Any) -> None:
        log_message = updates.pop("log", None)
        allowed = {
            "status",
            "progress",
            "stage",
            "progress_detail",
            "result",
            "error",
            "worker_id",
        }
        unknown = set(updates) - allowed
        if unknown:
            raise ValueError(
                "Unsupported job update fields: " + ", ".join(sorted(unknown))
            )

        assignments: list[str] = []
        values: list[Any] = []
        for key, value in updates.items():
            column = {
                "progress_detail": "progress_detail_json",
                "result": "result_json",
            }.get(key, key)
            if key in {"progress_detail", "result"}:
                value = _json(value) if value is not None else None
            assignments.append(f"{column} = ?")
            values.append(value)

        now = time.time()
        status = str(updates.get("status") or "")
        if status == "running":
            assignments.append("started_at = COALESCE(started_at, ?)")
            values.append(now)
        if status in TERMINAL_JOB_STATUSES:
            assignments.append("finished_at = ?")
            values.append(now)
            assignments.append("worker_id = NULL")
        assignments.extend(["revision = revision + 1", "updated_at = ?"])
        values.append(now)
        values.append(job_id)

        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                f"UPDATE jobs SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
            if cursor.rowcount == 0:
                connection.rollback()
                raise KeyError(job_id)
            if log_message is not None:
                self._insert_event(
                    connection,
                    job_id,
                    "log",
                    stage=str(updates.get("stage") or ""),
                    message=str(log_message),
                    payload={
                        key: value
                        for key, value in updates.items()
                        if key not in {"result", "progress_detail"}
                    },
                    created_at=now,
                )
            elif status:
                self._insert_event(
                    connection,
                    job_id,
                    "status",
                    stage=str(updates.get("stage") or ""),
                    message=None,
                    payload={"status": status},
                    created_at=now,
                )
            connection.commit()

    def request_cancel(self, job_id: str) -> dict[str, Any] | None:
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None

            status = str(row["status"])
            if status in TERMINAL_JOB_STATUSES:
                connection.rollback()
                return self.get(job_id)

            if status == "queued":
                next_status = "cancelled"
                stage = "已取消"
                finished_at = now
                message = "排队中的任务已取消。"
            else:
                next_status = "running"
                stage = "正在取消"
                finished_at = None
                message = "已收到取消请求；任务将在安全检查点停止。"

            connection.execute(
                """
                UPDATE jobs
                SET
                    status = ?,
                    stage = ?,
                    cancel_requested = 1,
                    cancel_requested_at = COALESCE(cancel_requested_at, ?),
                    finished_at = COALESCE(?, finished_at),
                    worker_id = CASE WHEN ? = 'cancelled' THEN NULL ELSE worker_id END,
                    updated_at = ?,
                    revision = revision + 1
                WHERE id = ? AND status IN ('queued', 'running')
                """,
                (
                    next_status,
                    stage,
                    now,
                    finished_at,
                    next_status,
                    now,
                    job_id,
                ),
            )
            self._insert_event(
                connection,
                job_id,
                "cancel_requested",
                stage=stage,
                message=message,
                payload={
                    "status": next_status,
                    "cancel_requested": True,
                },
                created_at=now,
            )
            connection.commit()
        return self.get(job_id)

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT cancel_requested FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            return bool(row and row["cancel_requested"])

    def claim_next(self, worker_id: str) -> dict[str, Any] | None:
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT *
                FROM jobs
                WHERE status = 'queued' AND cancel_requested = 0
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            connection.execute(
                """
                UPDATE jobs
                SET
                    status = 'running',
                    worker_id = ?,
                    attempt_count = attempt_count + 1,
                    started_at = ?,
                    updated_at = ?,
                    revision = revision + 1
                WHERE id = ? AND status = 'queued' AND cancel_requested = 0
                """,
                (worker_id, now, now, row["id"]),
            )
            self._insert_event(
                connection,
                str(row["id"]),
                "claimed",
                stage=str(row["stage"]),
                message=None,
                payload={"worker_id": worker_id},
                created_at=now,
            )
            connection.commit()
        return self.get(str(row["id"]))

    def recover_interrupted(self) -> list[str]:
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT id, payload_json, cancel_requested
                FROM jobs
                WHERE status = 'running'
                ORDER BY created_at ASC
                """
            ).fetchall()
            recovered_ids: list[str] = []
            for row in rows:
                job_id = str(row["id"])
                if bool(row["cancel_requested"]):
                    connection.execute(
                        """
                        UPDATE jobs
                        SET
                            status = 'cancelled',
                            stage = '已取消',
                            progress_detail_json = NULL,
                            result_json = NULL,
                            error = NULL,
                            worker_id = NULL,
                            finished_at = ?,
                            updated_at = ?,
                            revision = revision + 1
                        WHERE id = ?
                        """,
                        (now, now, job_id),
                    )
                    self._insert_event(
                        connection,
                        job_id,
                        "cancelled",
                        stage="已取消",
                        message="服务恢复时检测到取消请求，任务保持取消状态。",
                        payload={"status": "cancelled"},
                        created_at=now,
                    )
                    continue
                payload = _decode_json(row["payload_json"], {})
                interactive_capture = bool(
                    payload.get("allow_playback_capture")
                )
                if interactive_capture:
                    message = (
                        "服务在交互式播放采集任务期间中断。"
                        "为避免无人确认时重新录制系统音频，"
                        "请重新提交任务。"
                    )
                    connection.execute(
                        """
                        UPDATE jobs
                        SET
                            status = 'failed',
                            stage = '需要重新确认',
                            progress_detail_json = NULL,
                            result_json = NULL,
                            error = ?,
                            worker_id = NULL,
                            finished_at = ?,
                            updated_at = ?,
                            revision = revision + 1
                        WHERE id = ?
                        """,
                        (message, now, now, job_id),
                    )
                    self._insert_event(
                        connection,
                        job_id,
                        "recovery_blocked",
                        stage="需要重新确认",
                        message=message,
                        payload={"status": "failed"},
                        created_at=now,
                    )
                else:
                    recovered_ids.append(job_id)
                    connection.execute(
                        """
                        UPDATE jobs
                        SET
                            status = 'queued',
                            progress = 0,
                            stage = '恢复排队',
                            progress_detail_json = NULL,
                            result_json = NULL,
                            error = NULL,
                            worker_id = NULL,
                            started_at = NULL,
                            finished_at = NULL,
                            updated_at = ?,
                            revision = revision + 1
                        WHERE id = ?
                        """,
                        (now, job_id),
                    )
                    self._insert_event(
                        connection,
                        job_id,
                        "recovered",
                        stage="恢复排队",
                        message="检测到程序上次中断，任务已重新排队。",
                        payload={"status": "queued"},
                        created_at=now,
                    )
            connection.commit()
        return recovered_ids

    def queued_count(self) -> int:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE status = 'queued'"
            ).fetchone()
            return int(row[0])

    def status_counts(self) -> dict[str, int]:
        counts = {
            "queued": 0,
            "running": 0,
            "done": 0,
            "failed": 0,
            "cancelled": 0,
        }
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS total
                FROM jobs
                GROUP BY status
                """
            ).fetchall()
        for row in rows:
            counts[str(row["status"])] = int(row["total"])
        return counts

    def events(self, job_id: str, limit: int = 500) -> list[dict[str, Any]]:
        maximum = max(1, min(int(limit), 5000))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, event_type, stage, message, payload_json, created_at
                FROM job_events
                WHERE job_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (job_id, maximum),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "event_type": str(row["event_type"]),
                "stage": str(row["stage"] or ""),
                "message": row["message"],
                "payload": _decode_json(row["payload_json"], {}),
                "created_at": float(row["created_at"]),
            }
            for row in reversed(rows)
        ]

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    stage TEXT NOT NULL DEFAULT 'queued',
                    progress_detail_json TEXT,
                    payload_json TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    revision INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    updated_at REAL NOT NULL,
                    worker_id TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    cancel_requested_at REAL
                );

                CREATE TABLE IF NOT EXISTS job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    stage TEXT,
                    message TEXT,
                    payload_json TEXT,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_status_created
                ON jobs(status, created_at);

                CREATE INDEX IF NOT EXISTS idx_job_events_job_id_id
                ON job_events(job_id, id);
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(jobs)")
            }
            if "cancel_requested" not in columns:
                connection.execute(
                    "ALTER TABLE jobs ADD COLUMN "
                    "cancel_requested INTEGER NOT NULL DEFAULT 0"
                )
            if "cancel_requested_at" not in columns:
                connection.execute(
                    "ALTER TABLE jobs ADD COLUMN cancel_requested_at REAL"
                )
            connection.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.database_path,
            timeout=10,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
        finally:
            connection.close()

    def _row_to_job(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        log_rows = connection.execute(
            """
            SELECT message
            FROM (
                SELECT id, message
                FROM job_events
                WHERE job_id = ? AND message IS NOT NULL
                ORDER BY id DESC
                LIMIT ?
            )
            ORDER BY id ASC
            """,
            (row["id"], self.log_limit),
        ).fetchall()
        return {
            "schema_version": str(row["schema_version"]),
            "id": str(row["id"]),
            "status": str(row["status"]),
            "progress": int(row["progress"]),
            "stage": str(row["stage"]),
            "progress_detail": _decode_json(
                row["progress_detail_json"],
                None,
            ),
            "logs": [str(item["message"]) for item in log_rows],
            "payload": _decode_json(row["payload_json"], {}),
            "result": _decode_json(row["result_json"], None),
            "error": row["error"],
            "revision": int(row["revision"]),
            "created_at": float(row["created_at"]),
            "started_at": (
                float(row["started_at"])
                if row["started_at"] is not None
                else None
            ),
            "finished_at": (
                float(row["finished_at"])
                if row["finished_at"] is not None
                else None
            ),
            "updated_at": float(row["updated_at"]),
            "worker_id": row["worker_id"],
            "attempt_count": int(row["attempt_count"]),
            "cancel_requested": bool(row["cancel_requested"]),
            "cancel_requested_at": (
                float(row["cancel_requested_at"])
                if row["cancel_requested_at"] is not None
                else None
            ),
        }

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        job_id: str,
        event_type: str,
        *,
        stage: str,
        message: str | None,
        payload: dict[str, Any] | None,
        created_at: float,
    ) -> None:
        connection.execute(
            """
            INSERT INTO job_events (
                job_id,
                event_type,
                stage,
                message,
                payload_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                event_type,
                stage,
                message,
                _json(payload) if payload is not None else None,
                created_at,
            ),
        )


class LocalJobRunner:
    def __init__(
        self,
        store: JobStore,
        execute: Callable[[str], None],
        *,
        worker_count: int = 1,
    ) -> None:
        self.store = store
        self.execute = execute
        self.worker_count = max(1, worker_count)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._started = False

    @property
    def started(self) -> bool:
        with self._lock:
            return self._started

    def start(self, *, recover: bool = False) -> list[str]:
        with self._lock:
            if self._started:
                return []
            recovered = self.store.recover_interrupted() if recover else []
            self._stop.clear()
            self._threads = [
                threading.Thread(
                    target=self._worker_loop,
                    args=(f"local-{index + 1}",),
                    name=f"content-research-worker-{index + 1}",
                    daemon=True,
                )
                for index in range(self.worker_count)
            ]
            self._started = True
            for thread in self._threads:
                thread.start()
            self._wake.set()
            return recovered

    def notify(self) -> None:
        if not self.started:
            self.start()
        self._wake.set()

    def shutdown(self, *, wait: bool = False, timeout: float = 5.0) -> None:
        with self._lock:
            if not self._started:
                return
            threads = list(self._threads)
            self._stop.set()
            self._wake.set()
        if wait:
            deadline = time.monotonic() + max(0.0, timeout)
            for thread in threads:
                remaining = max(0.0, deadline - time.monotonic())
                thread.join(remaining)
        with self._lock:
            self._threads = []
            self._started = False

    def _worker_loop(self, worker_id: str) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            job = self.store.claim_next(worker_id)
            if job is None:
                self._wake.wait(timeout=1.0)
                continue
            job_id = str(job["id"])
            try:
                self.execute(job_id)
            except Exception as exc:  # pragma: no cover - final safety net
                logger.exception("Unhandled job runner failure: %s", job_id)
                self.store.update(
                    job_id,
                    status="failed",
                    stage="失败",
                    error=str(exc),
                    log=f"任务执行器异常：{exc}",
                )
            current = self.store.get(job_id)
            if current and current["status"] not in TERMINAL_JOB_STATUSES:
                self.store.update(
                    job_id,
                    status="failed",
                    stage="失败",
                    error="job returned without a terminal status",
                    log="任务执行结束但没有写入完成状态。",
                )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _decode_json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return default
