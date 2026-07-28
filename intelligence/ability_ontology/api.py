from __future__ import annotations

from pathlib import Path
from typing import Any

from config import SETTINGS, Settings

from .backfill import backfill_video_profiles
from .migration import migrate_legacy_data
from .repository import AbilityOntologyRepository
from .reviewer_adapter import OntologyReviewerAdapter
from .video_profile import VideoAbilityProfileService


def migrate(
    settings: Settings = SETTINGS,
    dry_run: bool = False,
    database_path: Path | None = None,
) -> dict[str, Any]:
    return migrate_legacy_data(
        settings=settings,
        dry_run=dry_run,
        database_path=database_path,
    )


def get_ability(
    ability_key: str,
    settings: Settings = SETTINGS,
    database_path: Path | None = None,
) -> dict[str, Any] | None:
    return AbilityOntologyRepository(
        settings,
        database_path=database_path,
    ).get_ability(ability_key)


def map_creator_style(
    style: str,
    settings: Settings = SETTINGS,
    database_path: Path | None = None,
) -> list[dict[str, Any]]:
    return AbilityOntologyRepository(
        settings,
        database_path=database_path,
    ).map_term("creator_style", style)


def map_reviewer_dimension(
    dimension: str,
    settings: Settings = SETTINGS,
    database_path: Path | None = None,
) -> list[dict[str, Any]]:
    return AbilityOntologyRepository(
        settings,
        database_path=database_path,
    ).map_term("reviewer_dimension", dimension)


def get_creator_profile(
    creator_name: str,
    platform: str = "bilibili",
    settings: Settings = SETTINGS,
    database_path: Path | None = None,
) -> dict[str, Any]:
    return AbilityOntologyRepository(
        settings,
        database_path=database_path,
    ).get_creator_profile(creator_name, platform)


def build_video_profile(
    analysis: dict[str, Any],
    *,
    v3: dict[str, Any] | None = None,
    creator_name: str = "",
    source_analysis_ref: str = "",
    save: bool = False,
    settings: Settings = SETTINGS,
    database_path: Path | None = None,
) -> dict[str, Any]:
    repository = AbilityOntologyRepository(
        settings,
        database_path=database_path,
    )
    return VideoAbilityProfileService(
        settings,
        repository,
    ).extract(
        analysis,
        v3=v3,
        creator_name=creator_name,
        source_analysis_ref=source_analysis_ref,
        save=save,
    )


def compare_video_profile(
    profile: dict[str, Any],
    required_abilities: list[str | dict[str, Any]],
    *,
    default_target_score: float = 60.0,
    settings: Settings = SETTINGS,
    database_path: Path | None = None,
) -> dict[str, Any]:
    repository = AbilityOntologyRepository(
        settings,
        database_path=database_path,
    )
    return VideoAbilityProfileService(
        settings,
        repository,
    ).compare(
        profile,
        required_abilities,
        default_target_score=default_target_score,
    )


def enrich_reviewer_result(
    reviewer_result: dict[str, Any],
    video_analysis: dict[str, Any],
    *,
    v3: dict[str, Any] | None = None,
    required_abilities: list[str | dict[str, Any]] | None = None,
    minimum_score: float = 60.0,
    source_analysis_ref: str = "",
    save_observations: bool = False,
    settings: Settings = SETTINGS,
    database_path: Path | None = None,
) -> dict[str, Any]:
    repository = AbilityOntologyRepository(
        settings,
        database_path=database_path,
    )
    return OntologyReviewerAdapter(
        settings,
        repository,
    ).enrich(
        reviewer_result,
        video_analysis,
        v3=v3,
        required_abilities=required_abilities,
        minimum_score=minimum_score,
        source_analysis_ref=source_analysis_ref,
        save_observations=save_observations,
    )


def backfill(
    settings: Settings = SETTINGS,
    *,
    force: bool = False,
    save_observations: bool = True,
    database_path: Path | None = None,
) -> dict[str, Any]:
    return backfill_video_profiles(
        settings,
        force=force,
        save_observations=save_observations,
        database_path=database_path,
    )
