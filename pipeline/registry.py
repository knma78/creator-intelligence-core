from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

ContextT = TypeVar("ContextT")
ResultT = TypeVar("ResultT")


class UnsupportedSourceError(ValueError):
    pass


@dataclass(frozen=True)
class SourceHandler(Generic[ContextT, ResultT]):
    key: str
    matches: Callable[[str], bool]
    resolve: Callable[[str, ContextT], ResultT]


class SourceRegistry(Generic[ContextT, ResultT]):
    def __init__(self, label: str) -> None:
        self.label = label
        self._lock = threading.RLock()
        self._handlers: list[SourceHandler[ContextT, ResultT]] = []

    def register(
        self,
        handler: SourceHandler[ContextT, ResultT],
        *,
        prepend: bool = False,
        replace: bool = False,
    ) -> None:
        key = handler.key.strip().lower()
        if not key:
            raise ValueError("Source handler key cannot be empty")
        with self._lock:
            existing = next(
                (item for item in self._handlers if item.key.lower() == key),
                None,
            )
            if existing and not replace:
                raise ValueError(f"Source handler already registered: {handler.key}")
            if existing:
                self._handlers.remove(existing)
            if prepend:
                self._handlers.insert(0, handler)
            else:
                self._handlers.append(handler)

    def resolve(self, source: str, context: ContextT) -> ResultT:
        with self._lock:
            handlers = tuple(self._handlers)
        for handler in handlers:
            if handler.matches(source):
                return handler.resolve(source, context)
        raise UnsupportedSourceError(
            f"Unsupported {self.label} source: {source}"
        )

    def keys(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(handler.key for handler in self._handlers)
