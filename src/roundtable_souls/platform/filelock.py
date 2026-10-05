"""An exclusive lock on a file, shared by every launcher process of this user (the window, a Play from a Steam
shortcut, an older copy still closing). Used around read-change-write of the settings file."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator
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
