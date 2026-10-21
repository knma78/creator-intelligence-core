from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterator

from config import SETTINGS, Settings
from infrastructure.cancellation import raise_if_cancelled


class ResourceKind(str, Enum):
    NETWORK_IO = "network_io"
    CPU_HEAVY = "cpu_heavy"
    GPU_INFERENCE = "gpu_inference"
    REALTIME_AUDIO = "realtime_audio"


class ResourceAcquireTimeout(TimeoutError):
    pass


@dataclass(frozen=True)
class ResourceLease:
    kind: ResourceKind
    owner: str
    family: str | None
    wait_seconds: float
    reentrant: bool = False


class ResourceManager:
    def __init__(
        self,
        *,
        network_slots: int,
        cpu_heavy_slots: int,
        gpu_slots: int,
        acquire_timeout: float,
        realtime_audio_slots: int = 1,
    ) -> None:
        self._limits = {
            ResourceKind.NETWORK_IO: max(1, int(network_slots)),
            ResourceKind.CPU_HEAVY: max(1, int(cpu_heavy_slots)),
            ResourceKind.GPU_INFERENCE: max(1, int(gpu_slots)),
            ResourceKind.REALTIME_AUDIO: max(
                1,
                int(realtime_audio_slots),
            ),
        }
        self._semaphores = {
            kind: threading.BoundedSemaphore(limit)
            for kind, limit in self._limits.items()
        }
        self._timeout = max(0.01, float(acquire_timeout))
        self._state_lock = threading.RLock()
        self._state_changed = threading.Condition(self._state_lock)
        self._active = {kind: 0 for kind in self._limits}
        self._waiting = {kind: 0 for kind in self._limits}
        self._local = threading.local()
        self._gpu_family: str | None = None
        self._gpu_cleanup: dict[str, Callable[[], None]] = {}

    def register_gpu_family(
        self,
        family: str,
        cleanup: Callable[[], None],
    ) -> None:
        with self._state_lock:
            self._gpu_cleanup[family] = cleanup

    @contextmanager
    def lease(
        self,
        kind: ResourceKind | str,
        *,
        owner: str,
        family: str | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> Iterator[ResourceLease]:
        resource = ResourceKind(kind)
        held = getattr(self._local, "held", None)
        if held is None:
            held = {}
            self._local.held = held
        if held.get(resource, 0):
            held[resource] += 1
            try:
                yield ResourceLease(resource, owner, family, 0.0, True)
            finally:
                held[resource] -= 1
            return

        started = time.monotonic()
        with self._state_lock:
            self._waiting[resource] += 1
        acquired = False
        try:
            deadline = started + self._timeout
            while not acquired:
                raise_if_cancelled(cancel_requested)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                acquired = self._semaphores[resource].acquire(
                    timeout=min(0.2, remaining),
                )
        finally:
            waited = max(0.0, time.monotonic() - started)
            with self._state_lock:
                self._waiting[resource] = max(
                    0,
                    self._waiting[resource] - 1,
                )
        if not acquired:
            raise ResourceAcquireTimeout(
                f"Timed out after {waited:.1f}s waiting for "
                f"{resource.value}: {owner}"
            )

        held[resource] = 1
        try:
            raise_if_cancelled(cancel_requested)
            if resource is ResourceKind.GPU_INFERENCE and family:
                self._activate_gpu_family(
                    family,
                    cancel_requested=cancel_requested,
                )
            else:
                with self._state_lock:
                    self._active[resource] += 1
            yield ResourceLease(resource, owner, family, waited)
        finally:
            with self._state_lock:
                self._active[resource] = max(0, self._active[resource] - 1)
                self._state_changed.notify_all()
            held.pop(resource, None)
            self._semaphores[resource].release()

    def snapshot(self) -> dict[str, object]:
        with self._state_lock:
            return {
                "limits": {
                    kind.value: value for kind, value in self._limits.items()
                },
                "active": {
                    kind.value: value for kind, value in self._active.items()
                },
                "waiting": {
                    kind.value: value for kind, value in self._waiting.items()
                },
                "gpu_family": self._gpu_family,
                "acquire_timeout_seconds": self._timeout,
            }

    def _activate_gpu_family(
        self,
        family: str,
        *,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> None:
        with self._state_changed:
            previous = self._gpu_family
            if previous == family:
                self._active[ResourceKind.GPU_INFERENCE] += 1
                return
            deadline = time.monotonic() + self._timeout
            while self._active[ResourceKind.GPU_INFERENCE] > 0:
                raise_if_cancelled(cancel_requested)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ResourceAcquireTimeout(
                        "Timed out waiting to switch GPU model family "
                        f"from {previous or 'none'} to {family}"
                    )
                self._state_changed.wait(timeout=min(0.2, remaining))
            raise_if_cancelled(cancel_requested)
            cleanup = self._gpu_cleanup.get(previous or "")
            if cleanup:
                cleanup()
            self._gpu_family = family
            self._active[ResourceKind.GPU_INFERENCE] += 1


_MANAGERS_LOCK = threading.Lock()
_MANAGERS: dict[tuple[int, int, int, int, float], ResourceManager] = {}


def get_resource_manager(settings: Settings = SETTINGS) -> ResourceManager:
    key = (
        max(1, settings.resource_network_slots),
        max(1, settings.resource_cpu_heavy_slots),
        max(1, settings.resource_gpu_slots),
        max(1, settings.resource_realtime_audio_slots),
        max(0.01, float(settings.resource_acquire_timeout)),
    )
    with _MANAGERS_LOCK:
        manager = _MANAGERS.get(key)
        if manager is None:
            manager = ResourceManager(
                network_slots=key[0],
                cpu_heavy_slots=key[1],
                gpu_slots=key[2],
                realtime_audio_slots=key[3],
                acquire_timeout=key[4],
            )
            _MANAGERS[key] = manager
        return manager
