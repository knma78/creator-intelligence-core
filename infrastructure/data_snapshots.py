"""Verified directory snapshots and isolated restore drills (never overwrite live data)."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from infrastructure.atomic_io import atomic_write_json
from infrastructure.data_inventory import inventory, linked, roots


def file_hash(path: Path, check=lambda: None) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            check()
            result.update(block)
    return result.hexdigest()


def safe_child(root: Path, key: str) -> Path:
    root = Path(root).absolute()
    if not isinstance(key, str) or not key or "\\" in key or ":" in key:
        raise ValueError("备份路径无效。")
    relative = PurePosixPath(key)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in key.split("/")):
        raise ValueError("备份路径越界。")
    path = root.joinpath(*relative.parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("备份路径越界。")
    for current in (path, *path.parents):
        if current.exists() and linked(current):
            raise ValueError("备份不能包含链接。")
    return path


def is_sqlite(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(16) == b"SQLite format 3\x00"


def _copy(source: Path, target: Path, check=lambda: None) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    if is_sqlite(source):
        deadline = time.monotonic() + 30
        def progress(*_args):
            check()
            if time.monotonic() > deadline:
                raise TimeoutError("SQLite 备份等待超时。")
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=5)) as src:
            with closing(sqlite3.connect(target)) as dst:
                src.backup(dst, pages=256, progress=progress, sleep=0.1)
                dst.execute("PRAGMA journal_mode=DELETE")
        return "sqlite_online_backup"
    if source.suffix.lower() == ".duckdb":
        import duckdb
        from infrastructure.analytics_store import _WRITE_LOCK
        # Windows does not allow Python to reopen a DuckDB-locked file.
        # Copy schema and data through DuckDB itself, including committed WAL.
        with _WRITE_LOCK, duckdb.connect(":memory:") as connection:
            source_sql = str(source).replace("'", "''")
            target_sql = str(target).replace("'", "''")
            connection.execute(f"ATTACH '{source_sql}' AS snapshot_source (READ_ONLY)")
            connection.execute(f"ATTACH '{target_sql}' AS snapshot_target")
            check()
            connection.execute("COPY FROM DATABASE snapshot_source TO snapshot_target")
            connection.execute("CHECKPOINT snapshot_target")
            check()
        return "duckdb_logical_copy"
    _stream_copy(source, target, check)
    return "file"


def _stream_copy(source: Path, target: Path, check):
    with source.open("rb") as src, target.open("xb") as dst:
        while block := src.read(1024 * 1024):
            check()
            dst.write(block)
        dst.flush()
        os.fsync(dst.fileno())


def verify_snapshot(snapshot: Path, *, check=lambda: None, progress=lambda *_: None) -> dict:
    snapshot = Path(snapshot).absolute()
    manifest_path = safe_child(snapshot, "manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "content-research-snapshot/v1":
        raise ValueError("不支持的备份格式。")
    seen, total, warnings = set(), 0, []
    for item in manifest["files"]:
        check()
        key = item["key"]
        if key.casefold() in seen:
            raise ValueError("备份清单存在重复路径。")
        seen.add(key.casefold())
        path = safe_child(snapshot / "files", key)
        if not path.is_file() or path.stat().st_size != item["size"] or file_hash(path, check) != item["sha256"]:
            raise ValueError(f"备份校验失败：{key}")
        if item["method"] == "sqlite_online_backup":
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
                if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError(f"SQLite 完整性检查失败：{key}")
        elif item["method"] in {"duckdb_checkpoint", "duckdb_logical_copy"}:
            import duckdb
            with duckdb.connect(str(path), read_only=True) as db:
                db.execute("SHOW TABLES").fetchall()
        elif path.suffix.lower() == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8-sig"))
            except (ValueError, UnicodeError) as exc:
                # A backup must preserve even pre-existing malformed artifacts.
                # Matching bytes does not imply semantically healthy source data.
                warnings.append({"key": key, "issue": str(exc)})
        total += item["size"]
        progress(len(seen), len(manifest["files"]), "校验：" + key)
    actual = {p.relative_to(snapshot / "files").as_posix().casefold()
              for p in (snapshot / "files").rglob("*") if p.is_file()}
    if actual != seen:
        raise ValueError("备份内容与清单不一致。")
    return {"verified": True, "file_count": len(seen), "bytes": total,
            "omitted_count": len(manifest.get("omitted", [])), "snapshot": str(snapshot),
            "format_warning_count": len(warnings), "format_warnings": warnings}


def create_snapshot(settings, *, include_media=False, include_models=False,
                    check=lambda: None, progress=lambda *_: None) -> dict:
    catalog = inventory(settings, check=check)
    backup_root = settings.base_dir / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    if linked(backup_root) or any(backup_root.resolve().is_relative_to(p) for p in roots(settings).values()):
        raise ValueError("备份目录不能在待备份数据内或指向链接。")
    snapshot_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    temporary = backup_root / (snapshot_id + ".partial")
    temporary.mkdir(exist_ok=False)
    (temporary / "files").mkdir()
    selected, omitted = [], []
    for item in catalog["files"]:
        if item["backup_default"] or (include_media and item["category"] == "source_media") or (include_models and item["category"] == "model"):
            selected.append(item)
        else:
            omitted.append({"key": item["key"], "category": item["category"], "size": item["size"]})
    entries = []
    for index, item in enumerate(selected):
        check()
        source = Path(item["path"])
        target = safe_child(temporary / "files", item["key"])
        method = _copy(source, target, check)
        after = source.stat()
        if method == "file" and (after.st_size != item["size"] or after.st_mtime_ns != item["mtime_ns"]):
            raise RuntimeError(f"备份期间源文件变化，请重试：{item['key']}")
        entries.append({"key": item["key"], "source_path": item["path"], "category": item["category"],
                        "size": target.stat().st_size, "sha256": file_hash(target, check), "method": method})
        progress(index + 1, 2 * len(selected), "备份：" + item["key"])
    # Ensure stable non-database artifacts across the entire copy, not just each read.
    after_catalog = inventory(settings, check=check)
    file_keys = {entry["key"] for entry in entries if entry["method"] == "file"}
    before = {x["key"]: (x["size"], x["mtime_ns"]) for x in selected if x["key"] in file_keys}
    after = {x["key"]: (x["size"], x["mtime_ns"]) for x in after_catalog["files"]}
    if any(after.get(key) != value for key, value in before.items()) or {x['key'] for x in catalog['files']} != set(after):
        raise RuntimeError("备份期间数据集合发生变化；未发布不完整快照，请等待任务结束后重试。")
    manifest = {"schema_version": "content-research-snapshot/v1", "snapshot_id": snapshot_id,
                "created_at": datetime.now(timezone.utc).isoformat(), "files": entries,
                "omitted": omitted, "excluded": catalog["excluded"],
                "scope": "managed_data_only; external_CapCut_drafts_and_credentials_not_copied"}
    atomic_write_json(temporary / "manifest.json", manifest)
    verification = verify_snapshot(temporary, check=check,
                                   progress=lambda n, t, k: progress(len(selected) + n, 2 * len(selected), k))
    final = backup_root / snapshot_id
    temporary.rename(final)
    return {**verification, "snapshot": str(final), "snapshot_id": snapshot_id,
            "manifest": str(final / "manifest.json"), "scope": manifest["scope"]}


def list_snapshots(settings) -> list[dict]:
    root = settings.base_dir / "backups"
    result = []
    if root.is_dir():
        for path in sorted(root.glob("*/manifest.json"), reverse=True):
            if path.parent.name.endswith(".partial") or linked(path.parent):
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                result.append({"snapshot_id": path.parent.name, "created_at": value["created_at"],
                               "file_count": len(value["files"]), "omitted_count": len(value.get("omitted", []))})
            except (ValueError, KeyError):
                continue
    return result


def selected_snapshot(settings, snapshot_id: str) -> Path:
    if not snapshot_id or any(c not in "0123456789TZ-abcdef" for c in snapshot_id):
        raise ValueError("备份编号无效。")
    return safe_child(settings.base_dir / "backups", snapshot_id)


def restore_drill(settings, snapshot_id: str, *, check=lambda: None, progress=lambda *_: None) -> dict:
    snapshot = selected_snapshot(settings, snapshot_id)
    verification = verify_snapshot(snapshot, check=check, progress=lambda n, t, k: progress(n, 2 * t, k))
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    restore_root = settings.base_dir / "restores"
    restore_root.mkdir(parents=True, exist_ok=True)
    if linked(restore_root) or any(restore_root.resolve().is_relative_to(p) for p in roots(settings).values()):
        raise ValueError("恢复演练目录不能与现用数据重叠。")
    target = restore_root / (snapshot_id + "-" + uuid.uuid4().hex[:8])
    target.mkdir(exist_ok=False)
    mapping = {}
    for index, item in enumerate(manifest["files"]):
        check()
        source = safe_child(snapshot / "files", item["key"])
        destination = safe_child(target, item["key"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        _stream_copy(source, destination, check)
        if file_hash(destination, check) != item["sha256"]:
            raise RuntimeError(f"恢复校验失败：{item['key']}")
        mapping[item["source_path"]] = str(destination)
        count = len(manifest["files"])
        progress(count + index + 1, 2 * count, "恢复：" + item["key"])
    report = {**verification, "restored_to": str(target), "live_data_modified": False,
              "path_mapping": mapping, "path_rebinding_required": True,
              "note": "已验证隔离恢复；现用路径未切换。迁移到其他机器时需按 path_mapping 重绑定工程和数据库内的绝对路径。"}
    atomic_write_json(target / "restore_report.json", report)
    return {k: v for k, v in report.items() if k != "path_mapping"}
