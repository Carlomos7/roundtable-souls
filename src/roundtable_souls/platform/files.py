"""Atomic file writes, and moving a folder's contents into another (each file's .json note moves with it)."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path


def atomic_write(path: Path, data, backup=False):
    """Write to a temp file next to the target and rename over it (atomic on Windows), keeping one .bak. A write
    that fails leaves the target as it was and removes the temp file. Each write has its own temp file
    (<name>.<pid>.<random>.tmp), so two writers of the same file (threads or processes) never write into one."""
    path = Path(path)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:12]}.tmp")
    try:
        if isinstance(data, str):
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                f.write(data)
        else:
            tmp.write_bytes(data)
        if backup and path.exists():
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def move_into(src_dir: Path, dest_dir: Path) -> None:
    """Move everything in src_dir into dest_dir (a rename on the same drive), renaming on a clash; drop src_dir
    when it ends up empty. A file in use stays for the next time."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    for item in sorted(src_dir.iterdir()):
        if item.name.endswith((".bak.json", ".src.json")):
            continue  # moves with its backup, below
        target = dest_dir / item.name
        n = 2
        while target.exists():  # a clash keeps the extension, so the file still lists: x.20260924-140632-2.bak
            target = dest_dir / f"{item.stem}-{n}{item.suffix}"
            n += 1
        try:
            shutil.move(str(item), str(target))
        except OSError:
            continue
        note = Path(str(item) + ".json")
        if note.is_file():
            try:
                shutil.move(str(note), str(target) + ".json")
            except OSError:
                pass
    for stray in list(src_dir.iterdir()):  # a note whose backup is gone
        if stray.name.endswith(".json"):
            target = dest_dir / stray.name
            if not target.exists():
                try:
                    shutil.move(str(stray), str(target))
                except OSError:
                    pass
    try:
        src_dir.rmdir()
    except OSError:
        pass
