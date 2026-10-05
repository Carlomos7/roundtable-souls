"""Where Roundtable Souls keeps its own files: all of it in the launcher's data folder (settings.data_dir(),
%LOCALAPPDATA%\\RoundtableSouls for an installed copy, beside the exe for a portable one), never in the game's save
folder or me3's profiles folder, which belong to the game, Steam and me3.

  saves/<game>/<Steam account>/backups           a copy of a save before every change, each with a .json note
  saves/<game>/<Steam account>/library           named copies of whole saves, library.json, and removed/
  profiles/deleted/<profile folder>/             .me3 files deleted from the Mods page, with a note of their home
  temp/                                          archives unpacked while a mod installs; cleared on start

Saves are keyed by game (its --game key) and Steam account (the save folder's name), because a backup belongs to
one account's save and two accounts can share a PC.

Kept beside what they belong to, on purpose: <profile>.offline.me3 (me3 resolves a profile's paths from its own
folder), the single .bak next to an edited .me3 / .ini (where people look for it) and the brief .roundtable.tmp
next to a save being written (an atomic replace needs the same folder).

Older versions kept folders beside the saves (save-fix-backups, regulation-fix-backups, co2-to-sl2-backups,
sl2-to-co2-backups, roundtable-saves) and beside profiles (deleted-profiles, .roundtable-staging). They are moved
here the first time a save folder or profile folder is used, and any backup without a note gets one.
"""

from __future__ import annotations

import datetime
import json
import re
import time
from pathlib import Path

from roundtable_souls.game import catalog as games
from roundtable_souls.platform import data_folder
from roundtable_souls.platform.files import move_into

BACKUPS = "backups"
LIBRARY = "library"
LIBRARY_REMOVED = "removed"

# Backups are kept: the newest KEEP_NEWEST per save file, everything from the last KEEP_DAYS days, and any marked keep.
KEEP_NEWEST = 20
KEEP_DAYS = 7

_LEGACY_BACKUPS = {  # folder older versions kept beside the saves -> what a backup in it was taken before
    "save-fix-backups": "Before a save fix",
    "regulation-fix-backups": "Before repairing for save editors",
    "co2-to-sl2-backups": "Before copying the co-op save over it",
    "sl2-to-co2-backups": "Before copying the standard save over it",
}
_LEGACY_SOURCE = {
    "co2-to-sl2-backups": "The co-op save as it was copied",
    "sl2-to-co2-backups": "The standard save as it was copied",
}
_adopted: set[str] = set()


# ----------------------------------------------------------------------------- saves
def game_for_save_dir(save_dir: Path) -> games.Game:
    """The game an account folder belongs to, from its parent (…/EldenRing/<account>), else Elden Ring."""
    parent = Path(save_dir).parent.name.lower()
    return next((g for g in games.GAMES if g.save_dir.lower() == parent), games.ELDEN_RING)


def account_dir(save_dir: Path, game: games.Game | None = None) -> Path:
    game = game or game_for_save_dir(save_dir)
    return data_folder.data_root() / "saves" / game.key / Path(save_dir).name


def backups(save_dir: Path, game: games.Game | None = None) -> Path:
    """Where copies of this account's saves go before they change."""
    adopt_legacy_save_folders(save_dir, game)
    return account_dir(save_dir, game) / BACKUPS


def library(save_dir: Path, game: games.Game | None = None) -> Path:
    adopt_legacy_save_folders(save_dir, game)
    return account_dir(save_dir, game) / LIBRARY


_STAMP = re.compile(r"\.\d{8}-\d{6}(-\d+)?\.(bak|src)$", re.I)


def _saved_name(backup_name: str) -> str:
    """The save a backup is of, from its name: ER0000.co2.20260924-140632.bak -> ER0000.co2 (dots in a me3
    savefile name are kept: My.Run.sl2.20260924-140632.bak -> My.Run.sl2)."""
    m = _STAMP.search(backup_name)
    if m:
        return backup_name[: m.start()]
    parts = backup_name.split(".")
    return ".".join(parts[:2]) if len(parts) >= 3 else backup_name


def _note_backups(folder: Path, save_dir: Path, legacy: str) -> None:
    """Give every backup in an older folder a note naming what it was taken before and which save it is."""
    for f in folder.iterdir():
        if f.suffix not in (".bak", ".src"):
            continue
        note_path = Path(str(f) + ".json")
        try:
            note = json.loads(note_path.read_text(encoding="utf-8")) if note_path.is_file() else {}
        except OSError, ValueError:
            note = {}
        if not note.get("action"):
            note["action"] = _LEGACY_SOURCE.get(legacy) if f.suffix == ".src" else _LEGACY_BACKUPS[legacy]
        if not note.get("when"):
            note["when"] = datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        if not note.get("save"):
            note["save"] = str(Path(save_dir) / _saved_name(f.name))
        note.setdefault("changes", [])
        try:
            note_path.write_text(json.dumps(note, indent=1), encoding="utf-8")
        except OSError:
            pass


def adopt_legacy_save_folders(save_dir: Path, game: games.Game | None = None, again: bool = False) -> None:
    """Move an account folder's older launcher folders into the data folder. Checked once per session unless
    again (the Saves page asks again on Refresh, for folders older tools still write)."""
    save_dir = Path(save_dir)
    key = str(save_dir).lower()
    if key in _adopted and not again:
        return
    _adopted.add(key)
    dest = account_dir(save_dir, game)
    for legacy in _LEGACY_BACKUPS:
        old = save_dir / legacy
        if old.is_dir():
            _note_backups(old, save_dir, legacy)
            move_into(old, dest / BACKUPS)
    old_lib = save_dir / "roundtable-saves"
    if old_lib.is_dir():
        if (old_lib / "deleted").is_dir():
            move_into(old_lib / "deleted", dest / LIBRARY / LIBRARY_REMOVED)
        move_into(old_lib, dest / LIBRARY)


# ----------------------------------------------------------------------------- backup notes and retention
def note_of(bak: Path) -> dict:
    p = Path(str(bak) + ".json")
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except OSError, ValueError:
        return {}


def set_keep(bak: Path, keep: bool) -> None:
    """Mark a backup to be kept whatever its age (or not)."""
    note = note_of(bak)
    note["keep"] = bool(keep)
    Path(str(bak) + ".json").write_text(json.dumps(note, indent=1), encoding="utf-8")


def prune(folder: Path, save_name: str, now: float | None = None) -> list[Path]:
    """Remove backups of one save beyond the newest KEEP_NEWEST, unless younger than KEEP_DAYS or marked keep.
    Returns what was removed."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    now = time.time() if now is None else now
    mine = []
    for f in folder.iterdir():
        if f.suffix in (".bak", ".src") and _saved_name(f.name).lower() == save_name.lower():
            try:
                mine.append((f.stat().st_mtime, f))
            except OSError:
                pass
    mine.sort(reverse=True)
    removed = []
    for rank, (mtime, f) in enumerate(mine):
        if rank < KEEP_NEWEST or now - mtime < KEEP_DAYS * 86400 or note_of(f).get("keep"):
            continue
        for p in (f, Path(str(f) + ".json")):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
        removed.append(f)
    return removed
