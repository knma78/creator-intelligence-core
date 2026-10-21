from __future__ import annotations

import shutil
from pathlib import Path

from infrastructure.atomic_io import atomic_write_json, atomic_write_text
from production.contracts import ProductionAsset, ProductionManifest


def _resolve_asset(asset: ProductionAsset, manifest_dir: Path) -> Path | None:
    if asset.packaged_path:
        candidate = manifest_dir / asset.packaged_path
        if candidate.is_file():
            return candidate
    candidate = Path(asset.source_path)
    return candidate if candidate.is_file() else None


def create_capcut_package(
    manifest_path: Path,
    *,
    master_video: Path | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Export files for optional manual polish without touching CapCut internals."""

    manifest_path = Path(manifest_path).resolve()
    import json

    manifest = ProductionManifest.from_dict(
        json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    )
    manifest_dir = manifest_path.parent
    destination = (
        Path(output_dir).resolve()
        if output_dir is not None
        else manifest_dir / "capcut_package"
    )
    destination.mkdir(parents=True, exist_ok=True)

    exported: list[dict[str, str]] = []
    if master_video is not None:
        master_video = Path(master_video).resolve()
        if not master_video.is_file():
            raise FileNotFoundError(master_video)
        target = destination / f"master{master_video.suffix.lower()}"
        shutil.copy2(master_video, target)
        exported.append({"role": "master_video", "path": target.name})

    allowed_roles = {
        "subtitles",
        "transcript",
        "cover",
        "narration",
        "music",
        "sound_effects",
        "shot_plan",
    }
    used_names: set[str] = {item["path"] for item in exported}
    for asset in manifest.assets:
        if asset.role not in allowed_roles:
            continue
        source = _resolve_asset(asset, manifest_dir)
        if source is None:
            continue
        name = f"{asset.role}{source.suffix.lower()}"
        if name in used_names:
            continue
        shutil.copy2(source, destination / name)
        used_names.add(name)
        exported.append({"role": asset.role, "path": name})

    atomic_write_json(
        destination / "capcut_package.json",
        {
            "schema_version": "1.0",
            "source_manifest": str(manifest_path),
            "job_id": manifest.job_id,
            "files": exported,
        },
    )
    atomic_write_text(
        destination / "README.txt",
        (
            "CapCut manual polish package\n\n"
            "1. Import master video and subtitle file.\n"
            "2. Use CapCut only for final visual polish, stickers, template "
            "effects, or manual caption corrections.\n"
            "3. Keep the FFmpeg-rendered master unchanged as the rollback copy.\n"
            "4. Export the polished result to a separate filename.\n"
        ),
    )
    return destination
