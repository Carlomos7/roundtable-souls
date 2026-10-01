"""One window at a time, and knowing what else of ours is running.

Three names, each held for as long as the thing it stands for runs:
  WINDOW  the launcher window (a second start asks it to come forward, or to Play, and exits)
  PLAY    a Play started from a Steam shortcut (--play), which runs without a window
  SETUP   the installer while it installs (named by the installer itself, SetupMutex in RoundtableSouls.iss)

On Windows these are named mutexes, the same objects the installer's AppMutex checks, so a silent update never
replaces the program while one of them runs. On Linux they are lock files in the runtime folder.

A second start talks to the window through a local socket (a named pipe on Windows) the window serves with
QLocalServer; only this user can connect to it.
"""

from __future__ import annotations

import getpass
import hashlib
import os
import socket
import sys
import tempfile
from pathlib import Path

WINDOW = "RoundtableSouls.Window"
PLAY = "RoundtableSouls.Play"
SETUP = "RoundtableSouls.Setup"

_ERROR_ALREADY_EXISTS = 183
_SYNCHRONIZE = 0x00100000


def _user_tag() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return hashlib.sha256(user.encode("utf-8")).hexdigest()[:12]


def _lock_dir() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())


def _lock_file(name: str) -> Path:
    return _lock_dir() / f"{name}-{_user_tag()}.lock"


class Hold:
    """A held name; release() (or the process ending) frees it."""

    def __init__(self, name: str, handle: int):
        self.name = name
        self._handle = handle

    def release(self) -> None:
        handle, self._handle = self._handle, 0
        if not handle:
            return
        if sys.platform == "win32":
            import ctypes

            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(handle)
        else:
            os.close(handle)  # closing the descriptor drops its flock


def acquire(name: str) -> Hold | None:
    """Hold name, or None when another process (or another Hold in this one) already does."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = wintypes.HANDLE
        k32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
        handle = k32.CreateMutexW(None, False, name)
        if not handle:
            return None
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            k32.CloseHandle(handle)
            return None
        return Hold(name, handle)
    import fcntl

    path = _lock_file(name)
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return Hold(name, fd)


def held(name: str) -> bool:
    """Whether some process holds name right now."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenMutexW.restype = wintypes.HANDLE
        k32.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
        handle = k32.OpenMutexW(_SYNCHRONIZE, False, name)
        if not handle:
            return False
        k32.CloseHandle(handle)
        return True
    probe = acquire(name)
    if probe is None:
        return True
    probe.release()
    return False


# ---------------------------------------------------------------------------- talking to the window


def server_name() -> str:
    """What the window's QLocalServer listens on: a pipe name on Windows, a socket path on Linux (per user)."""
    base = f"RoundtableSouls-{_user_tag()}"
    if sys.platform == "win32":
        return base
    return str(_lock_dir() / f"{base}.sock")


def send(message: str, name: str | None = None, timeout: float = 2.0) -> bool:
    """Send one line to the running window. False when no window answers."""
    name = name or server_name()
    data = (message.strip() + "\n").encode("utf-8")
    if sys.platform == "win32":
        try:
            with open(rf"\\.\pipe\{name}", "wb", buffering=0) as pipe:
                pipe.write(data)
            return True
        except OSError:
            return False
    unix = getattr(socket, "AF_UNIX", None)
    if unix is None:
        return False
    try:
        with socket.socket(unix, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(name)
            s.sendall(data)
        return True
    except OSError:
        return False
