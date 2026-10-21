from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
import time
import queue
import threading
from typing import Iterator, TypeVar


T = TypeVar("T")


class JobCancelledError(RuntimeError):
    """Raised when a cooperative job cancellation reaches a safe checkpoint."""


_CURRENT_CANCEL_REQUESTED: ContextVar[
    Callable[[], bool] | None
] = ContextVar("current_cancel_requested", default=None)
_CURRENT_YT_DLP_PROGRESS: ContextVar[
    Callable[[dict], None] | None
] = ContextVar("current_yt_dlp_progress", default=None)


@contextmanager
def cancellation_scope(
    cancel_requested: Callable[[], bool] | None,
    *,
    yt_dlp_progress: Callable[[dict], None] | None = None,
) -> Iterator[None]:
    cancel_token = _CURRENT_CANCEL_REQUESTED.set(cancel_requested)
    progress_token = _CURRENT_YT_DLP_PROGRESS.set(yt_dlp_progress)
    try:
        yield
    finally:
        _CURRENT_YT_DLP_PROGRESS.reset(progress_token)
        _CURRENT_CANCEL_REQUESTED.reset(cancel_token)


def raise_if_cancelled(
    cancel_requested: Callable[[], bool] | None,
) -> None:
    checker = cancel_requested or _CURRENT_CANCEL_REQUESTED.get()
    if checker is not None and checker():
        raise JobCancelledError("任务已由用户取消。")


def yt_dlp_cancel_hook(_status: dict) -> None:
    """A yt-dlp progress hook backed by the active cancellation scope."""

    raise_if_cancelled(None)
    callback = _CURRENT_YT_DLP_PROGRESS.get()
    if callback is not None:
        callback(_status)


def sleep_with_cancellation(
    seconds: float,
    cancel_requested: Callable[[], bool] | None = None,
    *,
    poll_seconds: float = 0.1,
) -> None:
    """Sleep in short intervals so retry backoff remains cancellable."""

    deadline = time.monotonic() + max(0.0, float(seconds))
    while True:
        raise_if_cancelled(cancel_requested)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(max(0.01, poll_seconds), remaining))


def run_cancellable_call(
    call: Callable[[], T],
    cancel_requested: Callable[[], bool] | None,
    *,
    on_cancel: Callable[[], None] | None = None,
    poll_seconds: float = 0.2,
) -> T:
    """Run a blocking external call without trapping the job thread.

    The worker is daemonized because some third-party clients do not expose an
    interruptible connect phase. ``on_cancel`` should close that client when
    possible so its worker exits promptly as well.
    """

    raise_if_cancelled(cancel_requested)
    result_queue: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)
    abandoned = threading.Event()

    def worker() -> None:
        try:
            result = call()
            if not abandoned.is_set():
                result_queue.put((True, result))
                return
            close = getattr(result, "close", None)
            if callable(close):
                close()
        except BaseException as exc:
            if not abandoned.is_set():
                result_queue.put((False, exc))

    thread = threading.Thread(
        target=worker,
        name="cancellable-external-call",
        daemon=True,
    )
    thread.start()
    while True:
        try:
            succeeded, value = result_queue.get(
                timeout=max(0.05, poll_seconds),
            )
        except queue.Empty:
            try:
                raise_if_cancelled(cancel_requested)
            except JobCancelledError:
                abandoned.set()
                if on_cancel is not None:
                    try:
                        on_cancel()
                    except Exception:
                        pass
                raise
            continue
        if succeeded:
            return value  # type: ignore[return-value]
        raise value  # type: ignore[misc]
