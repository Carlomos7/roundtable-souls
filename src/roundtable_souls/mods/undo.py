"""Taking a job back, from what it recorded (run_logging.set_undo) in the jobs index.

    remove   an entry removed from a profile: its text and where it was, and the folder when it went to the
             Recycle Bin (see system.trash). Restore puts both back.
    install  a fresh install, update an update, rollback a rollback (see mods.operations): the operation's own
             folder (.roundtable-ops/<id>) says what to take back. An install is undone (the profile's exact
             previous bytes, the files it created that nobody changed); an update or a rollback is rolled back as
             a set, with a rebuild when the install asked for one.
    rebuild  a rebuild of combined parameters: the profile as it was before (mods.history), the combined output it
             replaced (kept in the data folder), and the rebuild tool's own backup (its restore.json). Undo swaps each
             back by renaming, so it takes no time or space, and doing it again redoes the rebuild.

available() says whether it still can be done (the profile is still there, the folder is still in the bin, the
entry is not back already), so the Activity page only offers what works; run() does it and says what it did.
"""

from __future__ import annotations

from pathlib import Path

from roundtable_souls.mods import profile_edit as mod_manage

LABEL = {
    "remove": "Restore",
    "rebuild": "Undo rebuild",
    "install": "Undo install",
    "update": "Roll back",
    "rollback": "Roll back again",
}
OPERATIONS = ("install", "update", "rollback")


class UndoError(RuntimeError):
    pass


def label(undo: dict | None) -> str:
    undo = undo or {}
    if undo.get("type") == "rebuild" and undo.get("redo"):
        return "Redo rebuild"
    return LABEL.get(undo.get("type", ""), "Undo")


def _listed(profile: Path, path: str) -> bool:
    if not path:
        return False
    try:
        want = mod_manage.resolve(profile, path)
        return any(
            e.get("path") and mod_manage.resolve(profile, e["path"]) == want for e in mod_manage.entries(profile)
        )
    except OSError:
        return False


def _in_bin(undo: dict) -> bool:
    from roundtable_souls.platform import trash

    return trash.exists(undo.get("trash"))


def available(undo: dict | None) -> bool:
    if not undo:
        return False
    if undo.get("type") == "remove":
        profile = Path(undo.get("profile") or "")
        if not undo.get("profile") or not profile.is_file() or not undo.get("entry_text"):
            return False
        return not _listed(profile, undo.get("path") or "") or _in_bin(undo)
    if undo.get("type") in OPERATIONS:
        from roundtable_souls.merging import build

        op = Path(str(undo.get("operation") or ""))
        return bool(undo.get("operation")) and build._state(op) == build.ACTIVE
    if undo.get("type") == "rebuild":
        profile = Path(undo.get("profile") or "")
        if not undo.get("profile") or not profile.is_file():
            return False
        return any(
            [
                bool(undo.get("profile_before")) and Path(undo["profile_before"]).is_file(),
                bool(undo.get("combined_before")) and Path(undo["combined_before"]).is_dir(),
                bool(undo.get("tool_restore")) and _tool_swaps(undo) is not None,
            ]
        )
    return False


def run(undo: dict, log) -> str:
    """Do it. Returns a line saying what was done. Raises UndoError when it cannot be done any more, and
    FileExistsError when a folder is back at the old place already (nothing is overwritten)."""
    if undo.get("type") == "remove":
        return _restore_removed(undo, log)
    if undo.get("type") == "rebuild":
        return _undo_rebuild(undo, log)
    if undo.get("type") in OPERATIONS:
        return _take_back(undo, log)
    raise UndoError(f"Nothing to undo for {undo.get('type')!r}.")


def _restore_removed(undo: dict, log) -> str:
    from roundtable_souls.platform import trash

    profile = Path(undo.get("profile") or "")
    name = undo.get("name") or "the mod"
    if not undo.get("profile") or not profile.is_file():
        raise UndoError(f"{profile.name or 'The profile'} is no longer there.")
    said = []
    record = undo.get("trash")
    if record:
        if trash.exists(record):
            back = trash.restore(record)
            log(f"restore: {name}'s folder is back at {back}")
            said.append("its folder")
        elif not Path(str(record.get("original") or "")).exists():
            log(f"warning: {name}'s folder is no longer in the Recycle Bin; only the entry comes back")
    if _listed(profile, undo.get("path") or ""):
        log(f"restore: {name} is already in {profile.name}")
    else:
        text = mod_manage.read_text(profile)
        if mod_manage.is_array_form(text):
            text = mod_manage.to_blocks(text)
        new = mod_manage.restore_entry(text, undo["entry_text"], undo.get("where") or {})
        mod_manage._write(profile, new, f"before restoring {name}")
        log(f"restore: {name}'s entry is back in {profile.name}, where it was")
        said.insert(0, "its entry")
    return f"restored {name}" + (f" ({' and '.join(said)})" if said else "")


def _take_back(undo: dict, log) -> str:
    from roundtable_souls.mods import operations

    if not available(undo):
        raise UndoError(f"{undo.get('name') or 'It'} can no longer be taken back.")
    op = Path(undo["operation"])
    if undo["type"] == "install":
        return operations.undo_install(op, log)

    def rebuild_after() -> None:
        from roundtable_souls.mods import rebuild

        rebuild.rebuild(Path(undo["profile"]), log)

    try:
        return operations.rollback(op, log, rebuild_after if undo.get("rebuild") else None)
    except operations.OperationError as e:
        raise UndoError(str(e)) from e


# ----------------------------------------------------------------------------- rebuilds
def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return path.resolve() != root.resolve()


def _tool_swaps(undo: dict) -> list[tuple[Path, Path]] | None:
    """The (live, backup) pairs the tool's restore list names, when all of them are inside the profile's folder and
    exist; else None (nothing is touched outside the profile's folder, and a half-there backup is not used)."""
    import json

    listing = Path(str(undo.get("tool_restore") or ""))
    profile = Path(str(undo.get("profile") or ""))
    if not undo.get("tool_restore") or not listing.is_file() or not undo.get("profile"):
        return None
    try:
        data = json.loads(listing.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    root = profile.parent
    pairs = []
    for key in ("files", "directories"):
        for row in data.get(key) or []:
            if not isinstance(row, dict) or not row.get("path") or not row.get("original"):
                return None
            live = Path(row["path"])
            backup = Path(row["original"])
            if not backup.is_absolute():
                backup = listing.parent / backup
            if not (_inside(live, root) and _inside(backup, root)) or not backup.exists():
                return None
            pairs.append((live, backup))
    return pairs or None


def _move(src: Path, dst: Path) -> None:
    """A rename on the same drive (instant); a move across drives."""
    import os
    import shutil

    try:
        os.replace(src, dst)
    except OSError:
        shutil.move(str(src), str(dst))


def _swap(a: Path, b: Path) -> None:
    """Exchange two files or folders (renames on one drive); put everything back if a step fails."""
    if not a.exists():
        _move(b, a)
        return
    tmp = a.with_name(a.name + ".undo-swap")
    _move(a, tmp)
    try:
        _move(b, a)
    except OSError:
        _move(tmp, a)
        raise
    try:
        _move(tmp, b)
    except OSError:
        _move(a, b)
        _move(tmp, a)
        raise


def _undo_rebuild(undo: dict, log) -> str:
    from roundtable_souls.mods import history

    profile = Path(undo["profile"])
    said = []
    # The profile as it is now, before anything is swapped (a tool's own backup may swap the profile file too):
    # the copy doing it again puts back.
    now = history.snapshot(profile, "before redoing the rebuild" if undo.get("redo") else "before undoing the rebuild")
    pairs = _tool_swaps(undo) if undo.get("tool_restore") else None
    if pairs:
        for live, backup in pairs:
            _swap(live, backup)
        log(f"undo: the rebuild tool's output is back as it was ({len(pairs)} item(s) swapped with its backup)")
        said.append("the rebuild tool's output")
    combined_before = Path(str(undo.get("combined_before") or ""))
    folder = Path(str(undo.get("combined_folder") or ""))
    if undo.get("combined_before") and undo.get("combined_folder") and combined_before.is_dir() and folder.is_dir():
        for f in sorted(combined_before.rglob("*")):
            if f.is_file():
                live = folder / f.relative_to(combined_before)
                live.parent.mkdir(parents=True, exist_ok=True)
                _swap(live, f)
        log("undo: the combined files are back as they were")
        said.append("the combined files")
    before = Path(str(undo.get("profile_before") or ""))
    if undo.get("profile_before") and before.is_file():
        history.restore(profile, before)
        undo["profile_before"] = str(now) if now else None  # so doing it again swaps back (redo)
        log(f"undo: {profile.name} is back as it was {'after' if undo.get('redo') else 'before'} the rebuild")
        said.append("the profile")
    if not said:
        raise UndoError("What the rebuild replaced is no longer kept.")
    if undo.get("redo"):
        return "redid the rebuild: " + ", ".join(said) + " as the rebuild left them"
    return "undid the rebuild: " + ", ".join(said) + " back as before"
