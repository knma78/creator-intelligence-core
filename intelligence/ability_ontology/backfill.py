from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from config import SETTINGS, Settings

from .migration import migrate_legacy_data
from .repository import AbilityOntologyRepository
from .video_profile import VideoAbilityProfileService, read_json


def backfill_video_profiles(
    settings: Settings = SETTINGS,
    *,
    force: bool = False,
    save_observations: bool = True,
    database_path: Path | None = None,
) -> dict[str, Any]:
    repository = AbilityOntologyRepository(
        settings,
        database_path=database_path,
    )
    if not repository.latest_ontology_version():
        migrate_legacy_data(
            settings,
            database_path=database_path,
        )
    service = VideoAbilityProfileService(settings, repository)
    author_by_video = _load_video_authors(settings)
    completed = 0
    skipped = 0
    failed: list[dict[str, str]] = []
    output_files: list[str] = []
    for analysis_path in sorted(settings.output_dir.glob("*/analysis.json")):
        output_path = analysis_path.parent / "ability_profile.json"
        if output_path.exists() and not force:
            skipped += 1
            continue
        try:
            analysis = read_json(analysis_path, {})
            video_id = str(
                analysis.get("video_id")
                or analysis_path.parent.name
            )
            v3_path = analysis_path.parent / "v3.json"
            v3 = read_json(v3_path, {}) if v3_path.exists() else {}
            profile = service.extract(
                analysis,
                v3=v3,
                creator_name=author_by_video.get(video_id, ""),
                source_analysis_ref=str(analysis_path),
                save=save_observations,
            )
            output_path.write_text(
                json.dumps(profile, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            completed += 1
            output_files.append(str(output_path))
        except Exception as exc:
            failed.append(
                {
                    "analysis_path": str(analysis_path),
                    "error": str(exc),
                }
            )
    return {
        "status": "completed" if not failed else "partial",
        "ontology_version": repository.latest_ontology_version(),
        "completed_count": completed,
        "skipped_count": skipped,
        "failed_count": len(failed),
        "failed": failed,
        "output_files": output_files,
        "database_path": str(repository.database_path),
    }


def _load_video_authors(settings: Settings) -> dict[str, str]:
    integrated_path = (
        settings.output_dir / "integrated" / "integrated_summary.json"
    )
    integrated = read_json(integrated_path, {})
    return {
        str(item.get("video_id")): str(item.get("author") or "")
        for item in integrated.get("videos") or []
        if item.get("video_id")
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build additive ability_profile.json files from existing video "
            "analysis without modifying original analysis files."
        )
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild existing ability_profile.json files.",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Write profile JSON files without updating SQLite observations.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        help="Optional Ability Ontology SQLite path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = backfill_video_profiles(
        force=args.force,
        save_observations=not args.no_db,
        database_path=args.database,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
