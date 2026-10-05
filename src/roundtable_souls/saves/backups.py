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
from roundtable_souls.platform.files import atomic_write, move_into

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
    """Give every backup in an older folder a note naming what it was taken before and which save it is. An
    unreadable note is left as it is (the backup is then always kept, see is_kept)."""
    for f in folder.iterdir():
        if f.suffix not in (".bak", ".src"):
            continue
        try:
            note = read_note(f) or {}
        except UnreadableNote:
            continue
        if not note.get("action"):
            note["action"] = _LEGACY_SOURCE.get(legacy) if f.suffix == ".src" else _LEGACY_BACKUPS[legacy]
        if not note.get("when"):
            note["when"] = datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        if not note.get("save"):
            note["save"] = str(Path(save_dir) / _saved_name(f.name))
        note.setdefault("changes", [])
        try:
            write_note(f, note)
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
class UnreadableNote(Exception):
    """A backup's note exists but can't be read, isn't JSON or isn't a JSON object (a damaged or half-written
    note). What it said is unknown, so it may have said keep."""


def read_note(bak: Path) -> dict | None:
    """A backup's note, or None when it has none. Raises UnreadableNote when one exists but can't be read."""
    p = Path(str(bak) + ".json")
    if not p.exists():
        return None
    try:
        note = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except OSError, ValueError:
        raise UnreadableNote(p) from None
    if not isinstance(note, dict):
        raise UnreadableNote(p)
    return note


def note_of(bak: Path) -> dict:
    """A backup's note for showing it: empty when it has none or it can't be read (see read_note, is_kept)."""
    try:
        return read_note(bak) or {}
    except UnreadableNote:
        return {}


KEPT, NOT_KEPT, UNREADABLE = "kept", "not kept", "unreadable"


def protection(bak: Path) -> str:
    """KEPT (the note says keep: true), NOT_KEPT (no note, or no keep, or keep: false) or UNREADABLE (the note can't
    be read, or its keep isn't true or false). Pruning leaves KEPT and UNREADABLE backups alone: protection that
    can't be read may have said keep."""
    try:
        note = read_note(bak) or {}
    except UnreadableNote:
        return UNREADABLE
    keep = note.get("keep", False)
    if not isinstance(keep, bool):
        return UNREADABLE
    return KEPT if keep else NOT_KEPT


def is_kept(bak: Path) -> bool:
    """Whether pruning leaves a backup alone whatever its age (see protection)."""
    return protection(bak) != NOT_KEPT


def write_note(bak: Path, note: dict) -> None:
    """Write a backup's note atomically, so an interrupted write leaves the previous note whole."""
    atomic_write(Path(str(bak) + ".json"), json.dumps(note, indent=1))


def note_files(bak: Path) -> list[Path]:
    """A backup's note and any unreadable notes set_keep set aside, which go when the backup goes."""
    note = Path(str(bak) + ".json")
    aside = note.name + ".unreadable"
    try:
        return [note] + [p for p in bak.parent.iterdir() if p.name.startswith(aside)]
    except OSError:
        return [note]


def _copy_aside(note_path: Path) -> Path:
    """Copy a note's bytes to <note>.unreadable (-2, -3… if taken). The note itself stays where it is."""
    data = note_path.read_bytes()
    aside = note_path.with_name(note_path.name + ".unreadable")
    n = 2
    while aside.exists():
        aside = note_path.with_name(f"{note_path.name}.unreadable-{n}")
        n += 1
    atomic_write(aside, data)
    return aside


def set_keep(bak: Path, keep: bool) -> None:
    """Mark a backup to be kept whatever its age (or not); the note's other fields stay. When its protection can't
    be read (protection() is UNREADABLE), the note's bytes are first copied to <backup>.json.unreadable. The note
    is only ever replaced atomically, so a write that fails leaves it, and the protection it gives, as it was."""
    note_path = Path(str(bak) + ".json")
    try:
        note = read_note(bak) or {}
    except UnreadableNote:
        note = None
    if note is None or not isinstance(note.get("keep", False), bool):
        _copy_aside(note_path)
    note = note or {}
    note["keep"] = bool(keep)
    write_note(bak, note)


def prune(folder: Path, save_name: str, now: float | None = None) -> list[Path]:
    """Remove backups of one save beyond the newest KEEP_NEWEST, unless younger than KEEP_DAYS, marked keep or
    with protection that can't be read (is_kept). Returns what was removed."""
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
        if rank < KEEP_NEWEST or now - mtime < KEEP_DAYS * 86400 or is_kept(f):
            continue
        for p in [f, *note_files(f)]:
            try:
                p.unlink()
            except FileNotFoundError:
                pass
        removed.append(f)
    return removed
