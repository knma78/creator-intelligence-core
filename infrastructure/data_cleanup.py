"""Only explicitly rebuildable indexes may be quarantined, after verified backup."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from infrastructure.atomic_io import atomic_write_json
from infrastructure.data_inventory import INDEX_SOURCES, inventory, roots
from infrastructure.data_snapshots import file_hash, safe_child, selected_snapshot, verify_snapshot
from infrastructure.rule_versions import digest


def _sources_intact(key, settings, path):
    if key == "cache/creator_knowledge_base/rule_index.json":
        source = settings.output_dir / "creator_knowledge_base/rules/rule_library.json"
        return source.is_file() and bool(json.loads(source.read_text(encoding="utf-8")).get("rag_index"))
    index = json.loads(path.read_text(encoding="utf-8"))
    documents = index.get("documents") or []
    for doc in documents:
        value = doc.get("source_path")
        if not value:
            return False
        source = Path(value)
        if not source.is_absolute():
            source = settings.base_dir / source
        if source.is_dir():
            if not all((source / name).is_file() for name in ("analysis.json", "subtitle.txt", "v3.json")):
                return False
        elif source.resolve() != settings.analytics_database_path.resolve() or not source.is_file():
            return False
    return bool(documents)


def cleanup_plan(settings, snapshot_id, *, check=lambda: None) -> dict:
    snapshot = selected_snapshot(settings, snapshot_id)
    verify_snapshot(snapshot, check=check)
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    backed_up = {entry["key"]: entry for entry in manifest["files"]}
    catalog = inventory(settings, check=check)
    candidates, blocked = [], []
    for item in catalog["files"]:
        if item["key"] not in INDEX_SOURCES:
            continue
        check()
        path = Path(item["path"])
        hashed = file_hash(path, check)
        if backed_up.get(item["key"], {}).get("sha256") != hashed:
            blocked.append({"key": item["key"], "reason": "当前版本未包含在所选备份中。"})
            continue
        try:
            ready = _sources_intact(item["key"], settings, path)
        except (ValueError, OSError):
            ready = False
        if not ready:
            blocked.append({"key": item["key"], "reason": "重建来源不完整或无法确认。"})
            continue
        candidates.append({**item, "sha256": hashed})
    token = digest({"snapshot_id": snapshot_id, "files": [(x["key"], x["sha256"]) for x in candidates]})
    return {"snapshot_id": snapshot_id, "plan_token": token, "candidates": candidates,
            "blocked": blocked, "bytes_to_quarantine": sum(x["size"] for x in candidates),
            "disk_bytes_freed": 0, "note": "只将可重建索引移入隔离区，可撤销；不会永久删除文件。"}


def quarantine_indexes(settings, snapshot_id, token, *, check=lambda: None) -> dict:
    plan = cleanup_plan(settings, snapshot_id, check=check)
    if plan["plan_token"] != token:
        raise ValueError("清理清单已变化，请重新预览。")
    if not plan["candidates"]:
        return {"moved_count": 0, "message": "没有满足条件的可清理索引。"}
    quarantine_id = uuid.uuid4().hex
    directory = safe_child(settings.base_dir / "state", f"quarantine/{quarantine_id}")
    directory.mkdir(parents=True, exist_ok=False)
    journal = {"snapshot_id": snapshot_id, "quarantine_id": quarantine_id,
               "files": [{**item, "state": "pending"} for item in plan["candidates"]]}
    manifest = directory / "manifest.json"
    atomic_write_json(manifest, journal)
    for item in journal["files"]:
        check()
        source = Path(item["path"])
        if file_hash(source, check) != item["sha256"]:
            raise ValueError("索引已变化，已停止清理；已隔离的文件可恢复。")
        target = safe_child(directory / "files", item["key"])
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
        item["state"] = "quarantined"
        atomic_write_json(manifest, journal)
    return {"quarantine_id": quarantine_id, "moved_count": len(journal["files"]),
            "manifest": str(manifest), "disk_bytes_freed": 0, "recoverable": True}


def restore_quarantine(settings, quarantine_id, *, check=lambda: None) -> dict:
    if len(quarantine_id) != 32 or any(c not in "0123456789abcdef" for c in quarantine_id):
        raise ValueError("隔离记录编号无效。")
    directory = safe_child(settings.base_dir / "state", f"quarantine/{quarantine_id}")
    manifest = directory / "manifest.json"
    journal = json.loads(manifest.read_text(encoding="utf-8"))
    candidates = []
    for item in journal["files"]:
        check()
        key = item["key"]
        if key not in INDEX_SOURCES:
            raise ValueError("隔离记录包含非索引路径。")
        source = safe_child(directory / "files", key)
        destination = safe_child(roots(settings)["cache"], key.removeprefix("cache/"))
        if not source.exists():
            # A crash may occur before the first move or after undo's rename
            # but before its journal write. Reconcile only identical bytes.
            if destination.is_file() and file_hash(destination, check) == item["sha256"]:
                item["state"] = "restored"
                continue
            raise ValueError("隔离文件缺失，且现用文件与记录不符；请检查备份。")
        if destination.exists():
            raise ValueError("目标已有文件，不会覆盖；请保留现有版本或另行检查。")
        if file_hash(source, check) != item["sha256"]:
            raise ValueError("隔离文件校验失败。")
        candidates.append((item, source, destination))
    for item, source, destination in candidates:
        check()
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        item["state"] = "restored"
        atomic_write_json(manifest, journal)
    atomic_write_json(manifest, journal)
    return {"restored_count": len(candidates), "quarantine_id": quarantine_id}
