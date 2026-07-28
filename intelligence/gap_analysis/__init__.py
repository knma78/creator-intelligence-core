from __future__ import annotations

from typing import Any


def run_gap_analysis(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import run_gap_analysis as func

    return func(*args, **kwargs)


def get_gap(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import get_gap as func

    return func(*args, **kwargs)


def recommend_creator(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import recommend_creator as func

    return func(*args, **kwargs)


def recommend_video(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import recommend_video as func

    return func(*args, **kwargs)


def predict_growth(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import predict_growth as func

    return func(*args, **kwargs)


def get_health(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import get_health as func

    return func(*args, **kwargs)


def get_dashboard(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .api import get_dashboard as func

    return func(*args, **kwargs)


__all__ = [
    "get_dashboard",
    "get_gap",
    "get_health",
    "predict_growth",
    "recommend_creator",
    "recommend_video",
    "run_gap_analysis",
]
