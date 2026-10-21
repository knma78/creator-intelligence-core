from __future__ import annotations

import json
import time
from functools import wraps
from http import HTTPStatus

from infrastructure.cancellation import JobCancelledError, raise_if_cancelled
from infrastructure.data_cleanup import cleanup_plan, quarantine_indexes, restore_quarantine
from infrastructure.data_inventory import inventory
from infrastructure.data_snapshots import create_snapshot, list_snapshots, restore_drill, selected_snapshot, verify_snapshot
from infrastructure.file_lock import maintenance_lock
from infrastructure.jobs import JobQueueFullError

OPERATIONS = {"backup", "verify", "restore-drill", "cleanup-plan", "quarantine", "undo-quarantine"}


def guarded_job(function):
    @wraps(function)
    def wrapped(state, job_id):
        job = state.jobs.get(job_id)
        if not job:
            return
        maintenance = job["payload"].get("mode") == "data_maintenance"
        check = lambda: raise_if_cancelled(lambda: state.jobs.is_cancel_requested(job_id))
        try:
            state.jobs.update(job_id, stage="等待数据访问", log="检查数据访问状态；数据保护任务与制作/学习任务互斥。")
            with maintenance_lock(state.settings, exclusive=maintenance, check=check):
                return function(state, job_id)
        except JobCancelledError:
            state.jobs.update(job_id, status="cancelled", stage="已取消", log="等待数据访问已取消。")
        except Exception as exc:
            state.jobs.update(job_id, status="failed", stage="失败", error=str(exc), log=str(exc))
    return wrapped


def register_data_jobs(registry, services):
    def run(state, job_id, payload, check):
        operation = payload.get("operation")
        snapshot_id = str(payload.get("snapshot_id") or "")
        last_progress = 0.0
        def progress(current, total, key):
            nonlocal last_progress
            now = time.monotonic()
            if current != total and now - last_progress < 0.5:
                return
            last_progress = now
            services.update_progress(state, job_id, "数据保护", 10 + int(current / max(total, 1) * 75),
                                     f"处理 {current}/{total}：{key}")
        services.update_progress(state, job_id, "数据保护", 10, "正在检查文件清单与校验值。")
        if operation == "backup":
            result = create_snapshot(state.settings, include_media=bool(payload.get("include_media")),
                                     include_models=bool(payload.get("include_models")), check=check, progress=progress)
        elif operation == "verify":
            result = verify_snapshot(selected_snapshot(state.settings, snapshot_id), check=check, progress=progress)
        elif operation == "restore-drill":
            result = restore_drill(state.settings, snapshot_id, check=check, progress=progress)
        elif operation == "cleanup-plan":
            result = cleanup_plan(state.settings, snapshot_id, check=check)
        elif operation == "quarantine":
            result = quarantine_indexes(state.settings, snapshot_id, str(payload.get("plan_token") or ""), check=check)
        elif operation == "undo-quarantine":
            result = restore_quarantine(state.settings, str(payload.get("quarantine_id") or ""), check=check)
        else:
            raise ValueError("未知的数据保护操作。")
        state.jobs.update(job_id, status="done", stage="完成", progress=100,
                          result={"type": "data_maintenance", "operation": operation, "details": result, "files": []},
                          log="数据保护完成：" + json.dumps(result, ensure_ascii=False))
    registry.register("data_maintenance", run)


def handle_data_request(handler, state, parsed, method):
    if not parsed.path.startswith("/api/data/"):
        return False
    try:
        if method == "GET" and parsed.path == "/api/data/status":
            catalog = inventory(state.settings)
            quarantines = []
            for path in (state.settings.base_dir / "state/quarantine").glob("*/manifest.json"):
                record = json.loads(path.read_text(encoding="utf-8"))
                if any(x.get("state") != "restored" for x in record.get("files", [])):
                    quarantines.append({"quarantine_id": path.parent.name, "file_count": len(record["files"])})
            handler._send_json({"file_count": catalog["file_count"], "bytes_by_category": catalog["bytes_by_category"],
                                "excluded_count": len(catalog["excluded"]), "snapshots": list_snapshots(state.settings),
                                "quarantines": quarantines,
                                "backup_directory": str(state.settings.base_dir / "backups")})
        elif method == "POST" and parsed.path.removeprefix("/api/data/") in OPERATIONS:
            payload = handler._read_json_object(max_bytes=8192)
            if payload is None:
                return True
            operation = parsed.path.removeprefix("/api/data/")
            handler._send_json(state.submit({
                "mode": "data_maintenance", "source": "数据保护", "operation": operation,
                "snapshot_id": payload.get("snapshot_id"), "plan_token": payload.get("plan_token"),
                "quarantine_id": payload.get("quarantine_id"),
                "include_media": payload.get("include_media") is True,
                "include_models": payload.get("include_models") is True,
            }), HTTPStatus.ACCEPTED)
        else:
            handler._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
    except JobQueueFullError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.TOO_MANY_REQUESTS)
    except (ValueError, OSError) as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
    return True
