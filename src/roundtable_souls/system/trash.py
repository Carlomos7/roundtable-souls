"""The Recycle Bin (Windows) or the desktop trash (Linux): send a folder there, find it again, put it back.

Windows: the shell deletes with undo allowed, the same as Delete in Explorer. It recycles silently, but still asks
before deleting for good when the bin cannot take the item (too big, or a drive without one), so nothing is deleted
permanently without a prompt. Each item in the bin has a small record ($I...) beside it ($R...) naming where it came
from and when; send() finds that pair, so restore() is a rename back on the same drive, however large the folder.

Linux: the freedesktop.org trash: the trash on the same drive as the item (the home trash, or .Trash-<uid> at the top
of that drive), with an info file saying where it came from.

A record is a small dict kept in the job's undo data: {kind, item, info, original, deleted}.
"""

from __future__ import annotations

import datetime
import os
import shutil
import struct
import sys
import time
import urllib.parse
from pathlib import Path


class TrashError(OSError):
    pass


def available() -> bool:
    return sys.platform == "win32" or sys.platform.startswith("linux")


def send(path: Path) -> dict:
    """Move a file or folder to the trash. Returns its record. Raises TrashError when it was not moved (cancelled,
    or no trash here); the item is then where it was."""
    path = Path(os.path.abspath(path))
    if not path.exists():
        raise TrashError(f"{path} is not there")
    if sys.platform == "win32":
        return _send_windows(path)
    if sys.platform.startswith("linux"):
        return _send_linux(path)
    raise TrashError("there is no trash to move it to on this system")


def _genuine(record: dict | None) -> tuple[Path, Path] | None:
    """(item, info) when the record names a real item in a trash, else None. Everything that touches files goes
    through this: an empty path means the current folder, and a record for something deleted for good, or one edited
    by hand, must never lead to deleting or moving anything else."""
    if not isinstance(record, dict):
        return None
    item_s, info_s = str(record.get("item") or ""), str(record.get("info") or "")
    if not item_s or not info_s:
        return None
    item, info = Path(item_s), Path(info_s)
    if not item.is_absolute() or not info.is_absolute():
        return None
    kind = record.get("kind")
    if kind == "windows":
        ok = (
            item.name.startswith("$R")
            and info.name.startswith("$I")
            and item.name[2:] == info.name[2:]
            and item.parent == info.parent
            and item.parent.parent.name.lower() == "$recycle.bin"
        )
    elif kind == "freedesktop":
        ok = (
            item.parent.name == "files"
            and info.parent.name == "info"
            and info.name == item.name + ".trashinfo"
            and item.parent.parent == info.parent.parent
        )
    else:
        ok = False
    return (item, info) if ok else None


def exists(record: dict | None) -> bool:
    """Whether the item is still in the trash (not restored, and the trash not emptied)."""
    got = _genuine(record)
    return got is not None and got[0].exists() and got[1].exists()


def restore(record: dict, dest: Path | None = None) -> Path:
    """Put the item back where it was (or at dest). Raises FileExistsError when something is there now, TrashError
    when it is no longer in the trash."""
    if not exists(record):
        raise TrashError("it is no longer in the trash (emptied, or restored already)")
    assert record is not None
    target = Path(dest or record["original"])
    if target.exists():
        raise FileExistsError(f"{target} exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    item = Path(record["item"])
    try:
        os.replace(item, target)  # same drive: instant
    except OSError:
        shutil.move(str(item), str(target))
    try:
        Path(record["info"]).unlink()
    except OSError:
        pass
    return target


def purge(record: dict | None) -> None:
    """Delete an item from the trash for good. Does nothing unless the record names a genuine trash item."""
    got = _genuine(record)
    if got is None:
        return
    item, info = got
    if item.is_dir() and not item.is_symlink():
        shutil.rmtree(item, ignore_errors=True)
    elif item.exists() or item.is_symlink():
        item.unlink()
    try:
        info.unlink()
    except OSError:
        pass


# ----------------------------------------------------------------------------- Windows
FO_DELETE = 3
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
FOF_WANTNUKEWARNING = 0x4000
_FILETIME_EPOCH = 116444736000000000  # 1601-01-01 to 1970-01-01, in 100 ns


def _send_windows(path: Path) -> dict:
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    started = time.time()
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = str(path) + "\0\0"
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI | FOF_WANTNUKEWARNING
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))  # type: ignore[attr-defined]
    if rc != 0 or op.fAnyOperationsAborted or path.exists():
        raise TrashError(f"the Recycle Bin did not take it (code {rc})" if rc else "cancelled")
    found = _find_windows(path, started)
    if found is None:  # deleted for good after Windows' own warning (no bin on that drive, or too big)
        return {"kind": "gone", "item": "", "info": "", "original": str(path), "deleted": time.time()}
    return found


def _read_i(p: Path) -> tuple[str, float] | None:
    try:
        b = p.read_bytes()
        version, _size, filetime = struct.unpack_from("<qqq", b, 0)
        if version == 2:
            n = struct.unpack_from("<i", b, 24)[0]
            original = b[28 : 28 + n * 2].decode("utf-16-le").rstrip("\0")
        else:
            original = b[24 : 24 + 520].decode("utf-16-le").split("\0")[0]
    except OSError, struct.error, UnicodeDecodeError:
        return None
    return original, (filetime - _FILETIME_EPOCH) / 10_000_000


def _find_windows(path: Path, since: float) -> dict | None:
    root = Path(path.anchor) / "$Recycle.Bin"
    want = os.path.normcase(str(path))
    best = None
    try:
        folders = [d for d in root.iterdir() if d.is_dir()]
    except OSError:
        return None
    for d in folders:
        try:
            infos = list(d.glob("$I*"))
        except OSError:
            continue  # another user's bin
        for i in infos:
            got = _read_i(i)
            if got is None or os.path.normcase(got[0]) != want or got[1] < since - 5:
                continue
            item = d / ("$R" + i.name[2:])
            if item.exists() and (best is None or got[1] > best["deleted"]):
                best = {"kind": "windows", "item": str(item), "info": str(i), "original": got[0], "deleted": got[1]}
    return best


# ----------------------------------------------------------------------------- Linux (freedesktop.org trash)
def _home_trash() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "Trash"


def _mount_top(path: Path) -> Path:
    p = path.resolve()
    while not os.path.ismount(p) and p != p.parent:
        p = p.parent
    return p


def _trash_for(path: Path) -> Path:
    home = _home_trash()
    home.mkdir(parents=True, exist_ok=True)
    try:
        if os.stat(home).st_dev == os.stat(path.parent).st_dev:
            return home
    except OSError:
        return home
    top = _mount_top(path)
    uid = os.getuid() if hasattr(os, "getuid") else 0
    d = top / f".Trash-{uid}"
    d.mkdir(mode=0o700, exist_ok=True)
    return d


def _send_linux(path: Path) -> dict:
    trash = _trash_for(path)
    files, info = trash / "files", trash / "info"
    files.mkdir(parents=True, exist_ok=True)
    info.mkdir(parents=True, exist_ok=True)
    name, n = path.name, 1
    while True:
        try:
            fd = os.open(info / f"{name}.trashinfo", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError:
            n += 1
            name = f"{path.stem}.{n}{path.suffix}"
    when = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"[Trash Info]\nPath={urllib.parse.quote(str(path))}\nDeletionDate={when}\n")
    target = files / name
    try:
        os.replace(path, target)
    except OSError:
        try:
            shutil.move(str(path), str(target))
        except OSError as e:
            (info / f"{name}.trashinfo").unlink(missing_ok=True)
            raise TrashError(str(e)) from e
    return {
        "kind": "freedesktop",
        "item": str(target),
        "info": str(info / f"{name}.trashinfo"),
        "original": str(path),
        "deleted": time.time(),
    }
