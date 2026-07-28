from __future__ import annotations

from typing import Any


def discover_creator(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import discover_creator as func

    return func(*args, **kwargs)


def recommend_creator(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import recommend_creator as func

    return func(*args, **kwargs)


def recommend_keyword(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import recommend_keyword as func

    return func(*args, **kwargs)


def recommend_platform(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import recommend_platform as func

    return func(*args, **kwargs)


def creator_exists(*args: Any, **kwargs: Any) -> bool:
    from .api import creator_exists as func

    return func(*args, **kwargs)


def add_candidate(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import add_candidate as func

    return func(*args, **kwargs)


def approve_candidate(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import approve_candidate as func

    return func(*args, **kwargs)


def start_analysis(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import start_analysis as func

    return func(*args, **kwargs)


def finish_analysis(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import finish_analysis as func

    return func(*args, **kwargs)


def update_creator_score(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import update_creator_score as func

    return func(*args, **kwargs)


def get_dashboard(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import get_dashboard as func

    return func(*args, **kwargs)


__all__ = [
    "add_candidate",
    "approve_candidate",
    "creator_exists",
    "discover_creator",
    "finish_analysis",
    "get_dashboard",
    "recommend_creator",
    "recommend_keyword",
    "recommend_platform",
    "start_analysis",
    "update_creator_score",
]
