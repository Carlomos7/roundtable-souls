"""The launcher's own data folder (where settings, logs, backups and caches live): its root, the temp folder installs
unpack into, and the deleted-profiles folder. The program sets the root once when it starts (app.use_data_folder,
from config.settings.data_dir)."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from roundtable_souls.platform.files import move_into

_ROOT: Path | None = None


def use(root: Path) -> None:
    """The data folder from now on (set once at startup)."""
    global _ROOT
    _ROOT = Path(root)


def data_root() -> Path:
    if _ROOT is None:
        raise RuntimeError("the data folder was not set (app.use_data_folder sets it when the program starts)")
    return _ROOT


def deleted_profiles(profile_dir: Path) -> Path:
    adopt_legacy_profile_folders(profile_dir)
    return data_root() / "profiles" / "deleted" / Path(profile_dir).name


def adopt_legacy_profile_folders(profile_dir: Path) -> None:
    profile_dir = Path(profile_dir)
    old = profile_dir / "deleted-profiles"
    if old.is_dir():
        move_into(old, data_root() / "profiles" / "deleted" / profile_dir.name)
    staging = profile_dir / ".roundtable-staging"
    if staging.is_dir():
        shutil.rmtree(staging, ignore_errors=True)  # unpacks from installs that never finished


def temp(name: str) -> Path:
    p = data_root() / "temp" / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def clear_temp(older_than: float = 3600) -> None:
    """Remove temporary files left by a crash. Anything younger may belong to another running copy."""
    root = data_root() / "temp"
    if not root.is_dir():
        return
    for d in (d for d in root.iterdir() if d.is_dir()):
        for item in d.iterdir():
            try:
                if time.time() - item.stat().st_mtime <= older_than:
                    continue
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink()
            except OSError:
                pass
