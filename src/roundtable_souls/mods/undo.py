"""Taking a job back, from what it recorded (run_logging.set_undo) in the jobs index.

    remove   an entry removed from a profile: its text and where it was, and the folder when it went to the
             Recycle Bin (see system.trash). Restore puts both back.

available() says whether it still can be done (the profile is still there, the folder is still in the bin, the
entry is not back already), so the Activity page only offers what works; run() does it and says what it did.
"""

from __future__ import annotations

from pathlib import Path

from roundtable_souls.mods import manage as mod_manage

LABEL = {"remove": "Restore"}


class UndoError(RuntimeError):
    pass


def label(undo: dict | None) -> str:
    return LABEL.get((undo or {}).get("type", ""), "Undo")


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
    from roundtable_souls.system import trash

    return trash.exists(undo.get("trash"))


def available(undo: dict | None) -> bool:
    if not undo:
        return False
    if undo.get("type") == "remove":
        profile = Path(undo.get("profile") or "")
        if not undo.get("profile") or not profile.is_file() or not undo.get("entry_text"):
            return False
        return not _listed(profile, undo.get("path") or "") or _in_bin(undo)
    return False


def run(undo: dict, log) -> str:
    """Do it. Returns a line saying what was done. Raises UndoError when it cannot be done any more, and
    FileExistsError when a folder is back at the old place already (nothing is overwritten)."""
    if undo.get("type") == "remove":
        return _restore_removed(undo, log)
    raise UndoError(f"Nothing to undo for {undo.get('type')!r}.")


def _restore_removed(undo: dict, log) -> str:
    from roundtable_souls.system import trash

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
