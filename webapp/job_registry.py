from __future__ import annotations

from collections.abc import Callable
from typing import Any


JobModeHandler = Callable[
    [Any, str, dict[str, Any], Callable[[], None]],
    None,
]


class JobModeRegistry:
    """Small explicit registry for domain-specific Web job handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, JobModeHandler] = {}

    def register(self, mode: str, handler: JobModeHandler) -> None:
        normalized = str(mode or "").strip().lower()
        if not normalized:
            raise ValueError("Job mode must not be empty.")
        if normalized in self._handlers:
            raise ValueError(f"Job mode is already registered: {normalized}")
        self._handlers[normalized] = handler

    def resolve(self, mode: str) -> JobModeHandler | None:
        return self._handlers.get(str(mode or "").strip().lower())

    def modes(self) -> tuple[str, ...]:
        return tuple(self._handlers)
