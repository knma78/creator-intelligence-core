"""Conservative inventory: unknown data is protected, never assumed disposable."""
from __future__ import annotations

import os
import stat
from collections import Counter
from pathlib import Path

from config import Settings

MEDIA = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".mp3", ".wav", ".m4a", ".aac"}
MODELS = {".safetensors", ".onnx", ".pt", ".pth"}
INDEX_SOURCES = {
    "cache/knowledge_base/index.json": "output",
    "cache/creator_knowledge_base/rule_index.json": "output/creator_knowledge_base/rules/rule_library.json",
}


def linked(path: Path) -> bool:
    return path.is_symlink() or bool(
        getattr(path.lstat(), "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def roots(settings: Settings) -> dict[str, Path]:
    def checked(path):
        path = Path(path).absolute()
        for part in (path, *path.parents):
            if part.exists() and linked(part):
                raise ValueError(f"数据路径不能经过链接：{part}")
        return path.resolve()
    result = {"output": checked(settings.output_dir), "cache": checked(settings.cache_dir),
              "state": checked(settings.base_dir / "state")}
    production = checked(settings.video_production_dir)
    if not any(production.is_relative_to(root) for root in result.values()):
        result["production"] = production
    # Explicit single-file roots for configured databases outside standard folders.
    for name, path in (("jobs", settings.job_database_path), ("progress", settings.creator_progress_database_path),
                       ("analytics", settings.analytics_database_path)):
        path = checked(path)
        if not any(path.is_relative_to(root) for root in result.values()):
            result[f"database_{name}"] = path
    return result


def excluded_name(path: Path) -> bool:
    name = path.name.lower()
    return (
        name in {"platform_auth", "browser_profile", "browser_profiles", "cookies", "quarantine", "restores"}
        or "cookie" in name or name.startswith(".env")
        or name.endswith((".lock", ".pem", ".key", ".pfx"))
        or name.endswith(("-wal", "-shm", ".duckdb.wal"))
    )


def inventory(settings: Settings, *, check=lambda: None) -> dict:
    files, excluded = [], []
    seen = set()
    for label, root in roots(settings).items():
        if not root.exists():
            continue
        if linked(root):
            raise ValueError(f"数据根目录不能是链接：{root}")
        candidates = []
        if root.is_file():
            candidates = [root]
        else:
            for directory, dirs, names in os.walk(root, followlinks=False):
                check()
                parent = Path(directory)
                for name in list(dirs):
                    child = parent / name
                    if excluded_name(child) or linked(child):
                        dirs.remove(name)
                        excluded.append(str(child))
                candidates.extend(parent / name for name in names)
        for path in sorted(candidates):
            check()
            if excluded_name(path) or linked(path):
                excluded.append(str(path))
                continue
            absolute = path.resolve()
            if absolute in seen:
                continue
            seen.add(absolute)
            key = f"{label}/{path.name if root.is_file() else path.relative_to(root).as_posix()}"
            category = "protected"
            if key in INDEX_SOURCES:
                category = "rebuildable_index"
            elif key.startswith("cache/models/") or path.suffix.lower() in MODELS:
                category = "model"
            elif MEDIA.intersection(suffix.lower() for suffix in path.suffixes):
                category = "project_asset" if absolute.is_relative_to(settings.video_production_dir.resolve()) else "source_media"
            info = path.stat()
            files.append({"key": key, "path": str(absolute), "category": category,
                          "size": info.st_size, "mtime_ns": info.st_mtime_ns,
                          "backup_default": category not in {"source_media", "model"}})
    totals = Counter()
    for item in files:
        totals[item["category"]] += item["size"]
    return {"files": files, "file_count": len(files), "bytes_by_category": dict(totals),
            "excluded": excluded, "policy": "unknown_is_protected; credentials_and_links_excluded"}
