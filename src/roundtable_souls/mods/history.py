"""Profile history: a copy of a .me3 before every change the launcher makes to it, so any change can be undone.

Copies live in the launcher's data folder (profiles/history/<profile>/<when>_<why>.me3), never beside the profile.
A copy identical to the newest one is not written again, so switching a mod off and on leaves one copy, not a pile.
The newest KEEP copies of each profile are kept; they are small text files.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
from pathlib import Path

KEEP = 30
INDEX = "versions.json"  # file name -> why, word for word (the file name only carries a short form)
_NAME = re.compile(r"^(\d{8}-\d{6}-\d{3})_(.*)\.me3$")


def folder(profile: Path) -> Path:
    """The history folder for one profile: its file name plus a short hash of its full path, so two profiles with
    the same name (one per game, say) never share it."""
    from roundtable_souls import folders

    profile = Path(profile)
    key = hashlib.sha1(os.path.normcase(os.path.abspath(profile)).encode()).hexdigest()[:8]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", profile.stem)[:40] or "profile"
    return folders.data_root() / "profiles" / "history" / f"{stem}-{key}"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:60] or "change"


def _index(d: Path) -> dict:
    try:
        data = json.loads((d / INDEX).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_index(d: Path, data: dict) -> None:
    try:
        tmp = d / (INDEX + ".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(d / INDEX)
    except OSError:
        pass


def versions(profile: Path) -> list[dict]:
    """Every copy, newest first: {path, when (datetime), why}."""
    d = folder(profile)
    whys = _index(d) if d.is_dir() else {}
    out = []
    for f in d.glob("*.me3") if d.is_dir() else []:
        m = _NAME.match(f.name)
        if not m:
            continue
        try:
            when = datetime.datetime.strptime(m.group(1), "%Y%m%d-%H%M%S-%f")
        except ValueError:
            continue
        out.append({"path": f, "when": when, "why": whys.get(f.name) or m.group(2).replace("-", " ")})
    out.sort(key=lambda v: (v["when"], v["path"].name), reverse=True)
    return out


def latest(profile: Path) -> Path | None:
    v = versions(profile)
    return v[0]["path"] if v else None


def snapshot(profile: Path, why: str = "change") -> Path | None:
    """Copy the profile as it is now, before a change. Returns the copy (the newest one when nothing changed since),
    or None when there is no profile or the data folder cannot be written."""
    profile = Path(profile)
    try:
        data = profile.read_bytes()
    except OSError:
        return None
    newest = latest(profile)
    try:
        if newest is not None and newest.read_bytes() == data:
            return newest
    except OSError:
        pass
    d = folder(profile)
    try:
        d.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        out = d / f"{stamp}_{_slug(why)}.me3"
        n = 2
        while out.exists():
            out = d / f"{stamp}_{_slug(why)}-{n}.me3"
            n += 1
        tmp = out.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(out)
    except OSError:
        return None
    whys = _index(d)
    whys[out.name] = str(why)
    _write_index(d, whys)
    prune(profile)
    return out


def prune(profile: Path, keep: int = KEEP) -> None:
    dropped = []
    for v in versions(profile)[keep:]:
        try:
            v["path"].unlink()
            dropped.append(v["path"].name)
        except OSError:
            pass
    if dropped:
        d = folder(profile)
        whys = _index(d)
        _write_index(d, {k: v for k, v in whys.items() if k not in dropped})


def restore(profile: Path, copy: Path) -> Path | None:
    """Put a copy back as the profile. The profile as it was is copied first, so a restore can be undone too.
    Returns that copy."""
    profile, copy = Path(profile), Path(copy)
    data = copy.read_bytes()
    before = snapshot(profile, "before restoring an earlier version")
    tmp = profile.with_name(profile.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(profile)
    return before
