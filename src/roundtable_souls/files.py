"""Atomic file writes."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def atomic_write(path: Path, data, backup=False):
    """Write to a temp file next to the target and rename over it (atomic on Windows), keeping one .bak."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    if isinstance(data, str):
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(data)
    else:
        tmp.write_bytes(data)
    if backup and path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    os.replace(tmp, path)
