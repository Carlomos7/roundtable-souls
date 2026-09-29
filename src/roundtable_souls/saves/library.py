"""The save library: named copies of whole save files kept beside the live ones, and the swaps between them.

Each Steam account's saves get a library folder in the launcher's data folder (folders.library) with the copies
and a `library.json` that tracks them:

  entries  one per copy: its name, the file it came from, when, the game, the save format, a summary of its
           characters and a SHA-256 of the copy, so a file changed outside the launcher is noticed.
  history  every stash, swap, rename, import and delete, newest last.

A swap never loses anything: the live file goes into the library under a name first (the user's, or a default built
from its characters and the time), then the chosen copy is written over the live file. Entries stay in the library
after they are swapped in. Callers check the game is closed (service.assert_writable) before any write here.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import shutil
import struct
import uuid
from pathlib import Path

from roundtable_souls import folders, games
from roundtable_souls.files import atomic_write
from roundtable_souls.saves import container as save_container
from roundtable_souls.saves import fix as save_fix
from roundtable_souls.saves import layout as L
from roundtable_souls.saves import regulation as save_regulation

MANIFEST = "library.json"
SUMMARY_STRIDE = 0x24C  # one character's entry in the profile summary list after the ten active flags
NAME_MAX = 80


class LibraryError(Exception):
    pass


# ----------------------------------------------------------------------------- reading a save's characters
def characters(path: Path, game: games.Game | None = None) -> list[dict]:
    """Active characters as {slot, name, level, seconds} from the profile summary. Empty for saves this launcher
    cannot read inside (Nightreign encrypts its saves) or that do not parse."""
    game = game or games.for_save(path) or games.ELDEN_RING
    if game.save_reader != "eldenring":
        return []
    try:
        data = Path(path).read_bytes()
        r = L.parse(str(path))
    except OSError, L.ParseError, EOFError, ValueError, struct.error:
        return []
    base = r["ud10"]["active_pos"] + 10
    out = []
    for i, on in enumerate(r["ud10"]["active"]):
        if not on:
            continue
        off = base + i * SUMMARY_STRIDE
        name = data[off : off + 0x22].decode("utf-16-le", "replace").split("\0")[0]
        level, seconds = struct.unpack_from("<II", data, off + 0x22)
        out.append({"slot": i + 1, "name": name, "level": level, "seconds": seconds})
    return out


def default_name(path: Path, game: games.Game | None = None, when: datetime.datetime | None = None) -> str:
    """A name that says what is inside: the most played character, how many more, and when it was set aside."""
    when = when or datetime.datetime.now()
    chars = characters(path, game)
    stamp = when.strftime("%Y-%m-%d %H:%M")
    if not chars:
        return f"{Path(path).name} · {stamp}"
    top = max(chars, key=lambda c: c["seconds"])
    more = f" +{len(chars) - 1}" if len(chars) > 1 else ""
    return f"{top['name']} lvl {top['level']}{more} · {stamp}"


def clean_name(name: str) -> str:
    name = " ".join(str(name or "").split())[:NAME_MAX]
    if not name:
        raise LibraryError("Give the copy a name.")
    return name


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_whole(data: bytes, game: games.Game) -> None:
    """Refuse bytes that are not a whole save of this game."""
    if game.save_reader == "eldenring":
        if not save_regulation.is_pc_save(data):
            raise LibraryError(f"That file is not a PC {game.name} save.")
        return
    try:
        save_container.check(data, game.save_sections)
    except save_container.ContainerError as e:
        raise LibraryError(f"That file is not a whole {game.name} save: {e}.") from e


# ----------------------------------------------------------------------------- the manifest
def folder_for(save_dir: Path) -> Path:
    """The library for one account's saves (save_dir: the folder holding ER0000.sl2)."""
    return folders.library(save_dir)


def load(save_dir: Path) -> dict:
    """The library for one account folder. Missing or unreadable manifests read as empty; entries whose file is
    gone are kept but flagged, so nothing silently disappears from the list."""
    folder = folder_for(save_dir)
    doc = {"version": 1, "entries": [], "history": []}
    try:
        raw = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            doc["entries"] = [e for e in raw.get("entries") or [] if isinstance(e, dict) and e.get("id")]
            doc["history"] = [h for h in raw.get("history") or [] if isinstance(h, dict)]
    except OSError, ValueError:
        pass
    for e in doc["entries"]:
        e["missing"] = not (folder / e.get("file", "")).is_file()
    return doc


def _save(save_dir: Path, doc: dict) -> None:
    folder = folder_for(save_dir)
    folder.mkdir(parents=True, exist_ok=True)
    clean = {
        "version": 1,
        "entries": [{k: v for k, v in e.items() if k != "missing"} for e in doc["entries"]],
        "history": doc["history"][-500:],
    }
    atomic_write(folder / MANIFEST, json.dumps(clean, indent=1, ensure_ascii=False))


def _log(doc: dict, action: str, entry: dict | None, **detail) -> None:
    doc["history"].append(
        {
            "when": datetime.datetime.now().isoformat(timespec="seconds"),
            "action": action,
            "entry": entry["id"] if entry else None,
            "name": entry["name"] if entry else None,
            **detail,
        }
    )


def entry_path(save_dir: Path, entry: dict) -> Path:
    return folder_for(save_dir) / entry["file"]


def find(doc: dict, entry_id: str) -> dict:
    e = next((e for e in doc["entries"] if e["id"] == entry_id), None)
    if e is None:
        raise LibraryError("That copy is no longer in the library.")
    return e


def changed_outside(save_dir: Path, entry: dict) -> bool:
    """The copy's bytes no longer match what the library recorded (edited or replaced outside the launcher)."""
    p = entry_path(save_dir, entry)
    return p.is_file() and bool(entry.get("sha256")) and _sha256(p) != entry["sha256"]


# ----------------------------------------------------------------------------- operations
def add(save_dir: Path, source: Path, name: str, game: games.Game, action: str = "stash", note: str = "") -> dict:
    """Copy a whole save file into the library under a name. The source is left as it is."""
    source = Path(source)
    data = source.read_bytes()
    check_whole(data, game)
    doc = load(save_dir)
    entry_id = uuid.uuid4().hex[:12]
    fmt = source.suffix.lower().lstrip(".") or "sl2"
    entry = {
        "id": entry_id,
        "name": clean_name(name),
        "file": f"{entry_id}.{fmt}",
        "format": fmt,
        "game": game.key,
        "from": source.name,
        "from_path": str(source),
        "added": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_modified": datetime.datetime.fromtimestamp(source.stat().st_mtime).isoformat(timespec="seconds"),
        "note": note,
        "characters": characters(source, game),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    folder = folder_for(save_dir)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / entry["file"]
    atomic_write(target, data)
    if _sha256(target) != entry["sha256"]:
        target.unlink(missing_ok=True)
        raise LibraryError("The copy did not read back the same; nothing was added.")
    doc["entries"].append(entry)
    _log(doc, action, entry, source=source.name)
    _save(save_dir, doc)
    return entry


def swap_in(save_dir: Path, entry_id: str, live: Path, outgoing_name: str | None, game: games.Game) -> dict:
    """Put a library copy in place of the live save. The live file goes into the library first under outgoing_name
    (skipped only when there is no live file), and a regular backup is kept for Undo. Returns
    {entry, outgoing, backup}."""
    live = Path(live)
    doc = load(save_dir)
    entry = find(doc, entry_id)
    src = entry_path(save_dir, entry)
    if not src.is_file():
        raise LibraryError(f"The file for '{entry['name']}' is missing from {folder_for(save_dir)}.")
    data = src.read_bytes()
    check_whole(data, game)
    outgoing, bak = None, None
    if live.exists():
        outgoing = add(save_dir, live, outgoing_name or default_name(live, game), game, action="swapped out")
        bak = save_fix.backup(live, {"action": f"Before swapping in '{entry['name']}'", "changes": [entry["name"]]})
    tmp = live.with_name(live.name + ".roundtable.tmp")
    tmp.write_bytes(data)
    tmp.replace(live)
    if hashlib.sha256(live.read_bytes()).hexdigest() != hashlib.sha256(data).hexdigest():
        raise LibraryError(f"{live.name} did not read back the same after the swap; restore it from Backups.")
    doc = load(save_dir)  # add() above rewrote it
    _log(
        doc,
        "swap in",
        find(doc, entry_id),
        target=live.name,
        outgoing=outgoing["id"] if outgoing else None,
        backup=bak.name if bak else None,
    )
    _save(save_dir, doc)
    return {"entry": entry, "outgoing": outgoing, "backup": bak}


def rename(save_dir: Path, entry_id: str, name: str) -> dict:
    doc = load(save_dir)
    entry = find(doc, entry_id)
    old = entry["name"]
    entry["name"] = clean_name(name)
    _log(doc, "rename", entry, was=old)
    _save(save_dir, doc)
    return entry


def remove(save_dir: Path, entry_id: str) -> Path | None:
    """Take a copy out of the library. Its file moves to the library's removed folder rather than being erased."""
    doc = load(save_dir)
    entry = find(doc, entry_id)
    src = entry_path(save_dir, entry)
    moved = None
    if src.is_file():
        trash = folder_for(save_dir) / folders.LIBRARY_REMOVED
        trash.mkdir(parents=True, exist_ok=True)
        moved = trash / f"{entry['file']}"
        shutil.move(str(src), str(moved))
        (trash / f"{entry['file']}.json").write_text(json.dumps(entry, indent=1, ensure_ascii=False), encoding="utf-8")
    doc["entries"] = [e for e in doc["entries"] if e["id"] != entry_id]
    _log(doc, "delete", entry, moved_to=str(moved) if moved else None)
    _save(save_dir, doc)
    return moved
