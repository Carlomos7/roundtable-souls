"""Removing a mod from a profile: its entry (and the comments that belong to it) leaves the file, its folder optionally goes to the Recycle Bin, and what is needed to put both back is returned for undo."""

from __future__ import annotations

import shutil
from pathlib import Path

from roundtable_souls.mods.profile_edit import (
    _write_ordered,
    block_options,
    blocks,
    is_array_form,
    read_text,
    remove_entry,
    resolve,
    to_blocks,
)


def uninstall(profile: Path, index: int, delete_folder: bool = True, to_trash: bool = True) -> dict:
    """Remove one block, with its own comments (see remove_entry). With delete_folder, the mod's folder goes too when
    it lies beside the profile and no other entry still points into it (a natives folder shared by several DLLs is
    kept): to the Recycle Bin (to_trash), so it can come back, else deleted. Returns what was removed and where, so
    it can be put back (see mods.undo)."""
    from roundtable_souls.mods import stay_last

    profile = Path(profile)
    tgt = stay_last.target(profile)
    text = read_text(profile)
    if is_array_form(text):
        text = to_blocks(text)
    o = block_options(text, index)
    target = resolve(profile, o["path"]) if o["path"] else None
    folder = None
    if target is not None:
        folder = target if o["kind"] == "package" else target.parent
    name = o["id"] or Path(o["path"]).name or f"entry {index + 1}"
    new_text, chunk, where = remove_entry(text, index)
    removed_folder = False
    trashed = None
    if delete_folder and folder is not None and folder.is_dir():
        inside = profile.parent.resolve() in folder.resolve().parents
        still = [block_options(new_text, b["index"])["path"] for b in blocks(new_text)]
        shared = any(
            p
            and (
                folder.resolve() == resolve(profile, p).resolve()
                or folder.resolve() in resolve(profile, p).resolve().parents
            )
            for p in still
        )
        if inside and not shared and folder.resolve() != profile.parent.resolve():
            from roundtable_souls.platform import trash as trash_bin

            if to_trash and trash_bin.available():
                try:
                    trashed = trash_bin.send(folder)
                    removed_folder = True
                except trash_bin.TrashError:
                    trashed = None  # cancelled at Windows' warning, or no bin: the folder stays
            else:
                shutil.rmtree(folder)
                removed_folder = True
    bak, problem = _write_ordered(profile, new_text, f"before removing {name}", tgt)
    return {
        "order_problem": problem,
        "kind": o["kind"],
        "path": o["path"],
        "name": name,
        "folder": folder,
        "removed_folder": removed_folder,
        "backup": bak,
        "entry_text": chunk,
        "where": where,
        "trash": trashed,  # where the folder went in the Recycle Bin (system.trash), when it went there
    }
