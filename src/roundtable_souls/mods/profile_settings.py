"""The launcher's decisions about a profile, kept next to it (roundtable.json in the profile's folder), so copying the
folder to another PC copies them too:

    {"schema": 1,
     "profiles": {"myprofile.me3": {"overlay": {"package": "NightreignRevive/mod", "rebuild": null},
                                    "after_overlay": ["some-mod"]}}}

    overlay        the package set by hand (Options) as the one that must stay last, and the rebuild.json picked for
                   it; null when it was turned off (then it is found from its files again)
    after_overlay  entries kept after that package on purpose (see mods.order), by the name load order uses

One file serves every profile in the folder, keyed by the profile's file name. Paths are relative to the folder when
they are inside it. The file is written to a temporary file first and then renamed over the old one. Keys this
version does not know are kept, so a newer launcher's settings survive an older one. A file that cannot be read is
never overwritten: the launcher then falls back to its own settings (see mods.merge.overlay_mark).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

FILE = "roundtable.json"
SCHEMA = 1


class Unreadable(RuntimeError):
    """roundtable.json is there but is not a settings file this launcher can read; it is left alone."""


def path(profile: Path) -> Path:
    return Path(profile).parent / FILE


def _read(file: Path) -> dict:
    """The whole file: {} when there is none. Raises Unreadable when it cannot be parsed."""
    try:
        raw = file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as e:
        raise Unreadable(f"{file.name} could not be read: {e}") from e
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise Unreadable(f"{file.name} is not valid JSON ({e}); it is left as it is") from e
    if not isinstance(data, dict) or not isinstance(data.get("profiles", {}), dict):
        raise Unreadable(f"{file.name} is not a Roundtable Souls settings file; it is left as it is")
    return data


def load(profile: Path) -> dict:
    """This profile's settings ({} when none are kept, or the file cannot be read)."""
    try:
        data = _read(path(profile))
    except Unreadable:
        return {}
    got = (data.get("profiles") or {}).get(Path(profile).name)
    return dict(got) if isinstance(got, dict) else {}


def problem(profile: Path) -> str | None:
    """Why roundtable.json next to this profile cannot be used, or None."""
    try:
        _read(path(profile))
    except Unreadable as e:
        return str(e)
    return None


def update(profile: Path, **changes) -> None:
    """Set (or, with None, clear) keys of this profile's settings; other keys and other profiles are kept. Raises
    Unreadable when the file cannot be read and OSError when it cannot be written (a read-only folder)."""
    file = path(profile)
    data = _read(file)
    profiles = dict(data.get("profiles") or {})
    mine = dict(profiles.get(Path(profile).name) or {})
    for k, v in changes.items():
        if v is None and k != "overlay":  # overlay: None is kept: it says "found from its files", not "never set"
            mine.pop(k, None)
        else:
            mine[k] = v
    if mine:
        profiles[Path(profile).name] = mine
    else:
        profiles.pop(Path(profile).name, None)
    out = {**data, "schema": max(int(data.get("schema") or 0), SCHEMA), "profiles": profiles}
    tmp = file.with_name(file.name + ".tmp")
    tmp.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, file)


def to_stored(profile: Path, target: Path | None) -> str | None:
    """A path as stored: relative (with /) when it is inside the profile's folder, else as it is."""
    if target is None:
        return None
    base = Path(profile).parent
    try:
        return Path(os.path.abspath(target)).relative_to(Path(os.path.abspath(base))).as_posix()
    except ValueError:
        return str(target)


def from_stored(profile: Path, stored: str | None) -> Path | None:
    if not stored:
        return None
    p = Path(stored)
    return p if p.is_absolute() else Path(profile).parent / p
