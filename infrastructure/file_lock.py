"""OS-backed shared/exclusive locks; no stale lock ownership after a crash."""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def file_lock(path: Path, *, exclusive: bool = True, check=lambda: None, timeout=60):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if os.name == "nt":
            import ctypes
            import msvcrt
            from ctypes import wintypes

            class OVERLAPPED(ctypes.Structure):
                _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                            ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                            ("hEvent", wintypes.HANDLE)]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            lock = kernel.LockFileEx
            lock.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                             wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(OVERLAPPED)]
            lock.restype = wintypes.BOOL
            unlock = kernel.UnlockFileEx
            unlock.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                               wintypes.DWORD, ctypes.POINTER(OVERLAPPED)]
            unlock.restype = wintypes.BOOL
            native = msvcrt.get_osfhandle(handle.fileno())
            overlapped = OVERLAPPED()

            def acquire():
                if lock(native, 1 | (2 if exclusive else 0), 0, 1, 0, ctypes.byref(overlapped)):
                    return True
                code = ctypes.get_last_error()
                if code not in {32, 33}:
                    raise ctypes.WinError(code)
                return False

            def release():
                unlock(native, 0, 1, 0, ctypes.byref(overlapped))
        else:
            import fcntl

            def acquire():
                try:
                    fcntl.flock(handle, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                    return True
                except BlockingIOError:
                    return False

            def release():
                fcntl.flock(handle, fcntl.LOCK_UN)

        deadline = time.monotonic() + timeout
        while not acquire():
            check()
            if time.monotonic() >= deadline:
                raise TimeoutError("其他任务仍在使用数据，请稍后重试。")
            time.sleep(0.1)
        try:
            check()
            yield
        finally:
            release()


def maintenance_lock(settings, *, exclusive=True, check=lambda: None):
    return file_lock(settings.base_dir / "state" / ".data-maintenance.lock",
                     exclusive=exclusive, check=check)
