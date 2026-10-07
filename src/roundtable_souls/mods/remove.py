"""Removing a mod from a profile: its entry (and the comments that belong to it) leaves the file, its folder optionally goes to the Recycle Bin, as one recoverable operation (mods.operations), and what is needed to put both back is returned for undo."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from roundtable_souls.mods.profile_edit import (
    _ordered,
    _stage_write,
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
    from roundtable_souls.mods import operations, stay_last

    profile = Path(profile)
    with operations.lock(profile):
        operations.recover(profile)
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
        goes = False
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
            coop = operations._shared_folder(folder) and Path(o["path"]).name.lower() not in operations._coop_dlls()
            goes = inside and not shared and not coop and folder.resolve() != profile.parent.resolve()
        # The profile change and the folder's removal are one operation: an interruption between them is undone
        # (the entry comes back) unless the folder had already left, then it is finished.
        op = operations.start(profile, f"removal of {name}")
        try:
            new_text, problem = _ordered(profile, new_text, tgt)
            bak = _stage_write(op, profile, new_text, f"before removing {name}")
            op.note(kind="remove", name=name)
            if goes and folder is not None:
                op.note(dest=str(folder))
                op.gone_when(folder)
        except BaseException:
            op.discard()
            raise
        gone: dict = {"removed": False, "trash": None}

        def take_folder() -> None:
            if not goes or folder is None:
                return
            from roundtable_souls.platform import trash as trash_bin

            if to_trash and trash_bin.available():
                try:
                    gone["trash"] = trash_bin.send(folder)
                    gone["removed"] = True
                except trash_bin.TrashError:
                    gone["trash"] = None  # cancelled at Windows' warning, or no bin: the folder stays
            else:
                aside = folder.with_name(f".{folder.name}.removing-{op.id}")
                os.replace(folder, aside)  # gone in one rename; the files go after
                shutil.rmtree(aside, ignore_errors=True)
                gone["removed"] = True

        operations.commit(op, take_folder)
        op.release()  # put back through the entry and the Recycle Bin (mods.undo), not this record
    removed_folder, trashed = gone["removed"], gone["trash"]
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
