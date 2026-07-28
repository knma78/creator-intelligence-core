from __future__ import annotations

from typing import Any


def migrate(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import migrate as func

    return func(*args, **kwargs)


def get_ability(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
    from .api import get_ability as func

    return func(*args, **kwargs)


def map_creator_style(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    from .api import map_creator_style as func

    return func(*args, **kwargs)


def map_reviewer_dimension(
    *args: Any,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    from .api import map_reviewer_dimension as func

    return func(*args, **kwargs)


def get_creator_profile(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import get_creator_profile as func

    return func(*args, **kwargs)


def build_video_profile(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import build_video_profile as func

    return func(*args, **kwargs)


def compare_video_profile(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import compare_video_profile as func

    return func(*args, **kwargs)


def enrich_reviewer_result(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import enrich_reviewer_result as func

    return func(*args, **kwargs)


def backfill(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import backfill as func

    return func(*args, **kwargs)


__all__ = [
    "backfill",
    "build_video_profile",
    "compare_video_profile",
    "enrich_reviewer_result",
    "get_ability",
    "get_creator_profile",
    "map_creator_style",
    "map_reviewer_dimension",
    "migrate",
]
