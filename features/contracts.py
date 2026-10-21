from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class JobStorePort(Protocol):
    def is_cancel_requested(self, job_id: str) -> bool: ...

    def update(self, job_id: str, **changes: Any) -> dict[str, Any]: ...


class FeatureState(Protocol):
    settings: Any
    jobs: JobStorePort


FeatureHandler = Callable[
    [FeatureState, str, dict[str, Any], Callable[[], None]],
    None,
]


class FeatureRegistry(Protocol):
    def register(self, mode: str, handler: FeatureHandler) -> None: ...


@dataclass(frozen=True)
class FeatureJobServices:
    """Web-owned presentation callbacks injected into domain handlers."""

    update_progress: Callable[[Any, str, str, int, Any], None]
    file_item: Callable[[str, Path], dict[str, str]]
