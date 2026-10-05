"""An exclusive lock on a file, shared by every launcher process of this user (the window, a Play from a Steam
shortcut, an older copy still closing). locked() is used around read-change-write of the settings file;
exclusive() around changes that must not run unlocked (backups, the save library). ReadWriteLock is held shared by
many processes or exclusively by one (the database: open connections, and its migration)."""

from __future__ import annotations

import functools
import os
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path


def _try_lock(fd: int) -> bool:
    if sys.platform == "win32":
        import msvcrt

        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


class Busy(OSError):
    """exclusive(): the lock wasn't free within the timeout, so the block did not run."""


_held = threading.local()  # per thread: lock key -> how deep this thread is inside exclusive()


@contextmanager
def exclusive(path: Path, timeout: float, busy: Callable[[], Exception] | None = None) -> Iterator[None]:
    """Hold <path>.lock while the block runs. Unlike locked(), the block never runs without it: after timeout this
    raises busy() (Busy by default) before the block starts. A call inside another for the same path on the same
    thread just enters; other threads and processes wait. A process that dies holding it releases it."""
    key = os.path.normcase(os.path.abspath(path))
    counts = getattr(_held, "counts", None)
    if counts is None:
        counts = _held.counts = {}
    if counts.get(key):
        counts[key] += 1
        try:
            yield
        finally:
            counts[key] -= 1
        return
    with locked(Path(path), timeout) as got:
        if not got:
            raise busy() if busy is not None else Busy(f"{path} is busy")
        counts[key] = 1
        try:
            yield
        finally:
            counts.pop(key, None)


class ReadWriteLock:
    """A lock file held shared (any number of processes) or exclusively (one), across processes: LockFileEx on
    Windows, flock elsewhere. Not re-entrant; one instance holds at most one lock at a time. A process that dies
    releases what it held with its handles."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.mode: str | None = None  # "shared" or "exclusive" while held
        self._fd: int | None = None

    def acquire(self, exclusive: bool, timeout: float) -> bool:
        """Wait up to timeout seconds; True when held."""
        if self.mode is not None:
            raise RuntimeError(f"{self.path} is already held ({self.mode})")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        deadline = time.monotonic() + timeout
        while not _try_rw(fd, exclusive):
            if time.monotonic() >= deadline:
                os.close(fd)
                return False
            time.sleep(0.02)
        self._fd, self.mode = fd, "exclusive" if exclusive else "shared"
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            _unlock_rw(self._fd)
        except OSError:
            pass
        os.close(self._fd)
        self._fd, self.mode = None, None


@functools.cache
def _win_lock_api():
    """LockFileEx / UnlockFileEx and their OVERLAPPED argument (Windows only)."""
    import ctypes
    from ctypes import wintypes

    class OVERLAPPED(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_void_p),
            ("InternalHigh", ctypes.c_void_p),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    lock, unlock = kernel32.LockFileEx, kernel32.UnlockFileEx
    lock.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(OVERLAPPED),
    ]
    unlock.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(OVERLAPPED)]
    lock.restype = unlock.restype = wintypes.BOOL
    return OVERLAPPED, lock, unlock


def _try_rw(fd: int, exclusive: bool) -> bool:
    if sys.platform == "win32":
        import ctypes
        import msvcrt

        overlapped, lock, _unlock_api = _win_lock_api()
        flags = 0x1 | (0x2 if exclusive else 0)  # LOCKFILE_FAIL_IMMEDIATELY | LOCKFILE_EXCLUSIVE_LOCK
        return bool(lock(msvcrt.get_osfhandle(fd), flags, 0, 1, 0, ctypes.byref(overlapped())))
    import fcntl

    try:
        fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock_rw(fd: int) -> None:
    if sys.platform == "win32":
        import ctypes
        import msvcrt

        overlapped, _lock_api, unlock = _win_lock_api()
        unlock(msvcrt.get_osfhandle(fd), 0, 1, 0, ctypes.byref(overlapped()))
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def locked(path: Path, timeout: float = 5.0) -> Iterator[bool]:
    """Hold <path>.lock while the block runs; yields whether the lock was taken.

    After timeout seconds the block runs without it (and yields False): a stuck process must never freeze the
    window, and the write itself is still atomic, so the worst case is one lost change, as before this lock.
    """
    lock_path = path.with_name(path.name + ".lock")
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        yield False
        return
    got = False
    try:
        deadline = time.monotonic() + timeout
        while not (got := _try_lock(fd)) and time.monotonic() < deadline:
            time.sleep(0.02)
        yield got
    finally:
        if got:
            try:
                _unlock(fd)
            except OSError:
                pass
        os.close(fd)
