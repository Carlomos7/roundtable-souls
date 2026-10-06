"""Installing, updating and removing a mod as one recoverable operation (merging.build.Operation), and taking one
back.

    install   the files are staged beside their place and the new profile text worked out first; then the folder
              and the profile change under one journal, with the rebuild (when asked for) run before it counts as
              done. A failure, or an interruption found on the next start, undoes it as a whole.
    update    the same, with the installed folder kept aside (.<name>.previous-<id>) until it is let go of (keep())
              or the version is rolled back. Files the user changed since the last install are kept, the new
              version's copy beside them as <name>.new.
    undo      of a fresh install: the profile's exact previous bytes come back (when the profile has not changed
              since; otherwise only the install's entries leave it), and only the files the install created and
              nobody changed since are removed. What was changed or added is left and reported.
    rollback  of an update: the previous folder and profile come back as a set; the version rolled back is kept
              aside, so edits made to it are not lost.

Shared dependencies (Seamless Co-op: a folder holding the game's co-op DLL, its entry in the profile) are never
removed or switched off by an undo or a rollback. An operation that did not finish blocks Play (problem()).

The records live beside the profile (.roundtable-ops/<id>/): they protect the files beside them (§8.8).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from roundtable_souls.formats import me3_profile
from roundtable_souls.game import catalog as games
from roundtable_souls.merging import build
from roundtable_souls.mods.checks import same_folder


class OperationError(RuntimeError):
    pass


def _root(profile: Path) -> Path:
    return Path(profile).parent


def lock(profile: Path):
    """Held around an operation on this profile's folder, by every launcher process."""
    return build.ops_lock(_root(profile))


def recover(profile: Path, timeout: float = 30.0) -> list[str]:
    """Finish or undo what an interrupted operation in this profile's folder left (see merging.build). Raises
    merging.build.BuildError when another launcher process holds the folder past timeout."""
    return build.recover_operations(_root(profile), timeout)


def start(profile: Path, what: str) -> build.Operation:
    op = build.Operation(_root(profile), what)
    op.note(profile=str(Path(profile)))
    return op


def commit(op: build.Operation, then=None) -> None:
    """Apply op (then() run before it counts as done). An older operation on the same folder lets go of what it
    kept: the newest one is the one a rollback or an undo takes back."""
    op.commit(then=then)
    dest = op.info.get("dest")
    if not dest:
        return
    for other in build.active(op.dir.parent.parent):
        if other.id != op.id and other.info.get("dest") and same_folder(Path(other.info["dest"]), Path(dest)):
            other.release()


def pending(profile: Path) -> list[str]:
    return build.pending(_root(profile))


def problem(profile: Path) -> str | None:
    """Why Play must not start with this profile now: an install, update or removal in its folder that did not
    finish (its folder, profile and build may not match). None when there is none."""
    try:
        left = pending(profile)
    except OSError, ValueError:
        return None
    if not left:
        return None
    return (
        f"the {left[0]} did not finish, so the mods and the profile may not match. Open the Mods page: it is "
        "finished or undone there"
    )


# ----------------------------------------------------------------------------- what an install created
def manifest(folder: Path) -> dict[str, list[int]]:
    """Every file below folder: relative path -> [size, modified time in ns]. Enough to tell whether a file was
    changed since (a copy keeps the time; an edit changes it)."""
    out: dict[str, list[int]] = {}
    folder = Path(folder)
    if not folder.is_dir():
        return out
    for p in folder.rglob("*"):
        if p.is_file():
            st = p.stat()
            out[p.relative_to(folder).as_posix()] = [st.st_size, st.st_mtime_ns]
    return out


def _unchanged(path: Path, rec: list[int]) -> bool:
    try:
        st = path.stat()
    except OSError:
        return False
    return [st.st_size, st.st_mtime_ns] == list(rec)


def describe(op: build.Operation, profile: Path, plan: dict, dest: Path, in_place: bool, update: bool, added, kept):
    """Keep in op's journal what an undo or a rollback needs: what kind it is, the folder, the files it created
    (as staged: a rename keeps their times) and the entries it added."""
    staged = next((Path(s["staged"]) for s in op.steps if s["type"] == "folder"), None)
    op.note(
        kind="update" if update else "install",
        name=plan["name"],
        dest=str(dest),
        fresh=not update and not in_place,
        created=manifest(staged) if staged is not None else {},
        entries=[e["path"] for e in added],
        kept=list(kept),
    )


def _last_record(profile: Path, dest: Path) -> build.Operation | None:
    found = [
        o
        for o in build.active(_root(profile))
        if o.info.get("dest") and same_folder(Path(o.info["dest"]), dest) and o.info.get("created") is not None
    ]
    return found[-1] if found else None


def keep_user_edits(profile: Path, dest: Path, staged: Path) -> list[str]:
    """Before an update replaces dest with staged: a file in dest the user changed since the last install (its size
    or time differs from what that install recorded) is carried into staged, the new version's copy beside it as
    <name>.new; a file the user added is carried over as it is. Without a record of the last install nothing is
    carried (an old file cannot be told from an edited one); the previous folder is kept for a rollback either way.
    Returns the relative paths kept."""
    rec = _last_record(profile, dest)
    if rec is None:
        return []
    created = rec.info.get("created") or {}
    kept = []
    for rel in manifest(dest):
        live = dest / rel
        new = staged / rel
        if rel in created and _unchanged(live, created[rel]):
            continue  # as installed: the new version replaces it
        if rel not in created and new.exists():
            continue  # it was not the install's and the new version ships one: the new version's stands
        new.parent.mkdir(parents=True, exist_ok=True)
        if new.exists():
            os.replace(new, new.with_name(new.name + ".new"))
        shutil.copy2(live, new)
        kept.append(rel)
    return sorted(kept)


# ----------------------------------------------------------------------------- shared dependencies
def _coop_dlls() -> set[str]:
    return {g.coop_dll.lower() for g in games.GAMES if g.coop_dll}


def _shared_folder(folder: Path) -> bool:
    """A folder holding a co-op DLL (Seamless Co-op): never removed by an undo or a rollback."""
    dlls = _coop_dlls()
    try:
        return any(p.name.lower() in dlls for p in Path(folder).rglob("*.dll"))
    except OSError:
        return False


def _coop_entries(text: str) -> set[str]:
    """The co-op DLL entries this profile text loads (switched on), by path."""
    dlls = _coop_dlls()
    try:
        found = me3_profile.entries(text)
    except ValueError:
        return set()
    return {
        e["path"].replace("\\", "/").lower()
        for e in found
        if e["kind"] == "native" and e["enabled"] and Path(e["path"]).name.lower() in dlls
    }


# ----------------------------------------------------------------------------- taking one back
def _profile_step(op: build.Operation) -> dict | None:
    return next((s for s in op.steps if s["type"] == "file"), None)


def _profile_back(op: build.Operation, profile: Path, notes: list[str]) -> bytes | None:
    """The profile's bytes once op is taken back: its exact previous bytes when it has not changed since; else the
    current text without the entries op added. None: leave it as it is."""
    from roundtable_souls.mods import profile_edit

    step = _profile_step(op)
    if step is None:
        return None
    now = profile.read_bytes()
    after = (op.dir / step["after"]).read_bytes()
    before = (op.dir / step["before"]).read_bytes() if step["before"] else b""
    current = now.decode("utf-8", errors="replace")
    if now == after:
        back = before.decode("utf-8", errors="replace")
        if _coop_entries(current) <= _coop_entries(back):
            return before
        notes.append("Seamless Co-op stays in the profile (it was added with this mod and other mods use it)")
    else:
        notes.append(f"{profile.name} changed since, so only this mod's entries were taken out of it")
    text = me3_profile.to_blocks(current) if me3_profile.is_array_form(current) else current
    mine = {str(p).replace("\\", "/").lower() for p in op.info.get("entries") or []}
    for e in reversed(me3_profile.entries(text)):
        if e["path"].replace("\\", "/").lower() in mine and e["path"].replace("\\", "/").lower() not in _coop_entries(
            text
        ):
            text = profile_edit.remove_block(text, e["index"])
    return text.encode("utf-8") if text != current else None


def _new_op(op: build.Operation, what: str) -> build.Operation:
    return start(Path(op.info["profile"]), what)


def undo_install(op_dir: Path, log=lambda s: None) -> str:
    """Take a fresh install back (see the module notes). Returns what was done, in a line."""
    op = build.Operation.load(op_dir)
    profile = Path(op.info["profile"])
    dest = Path(op.info["dest"])
    name = op.info.get("name") or dest.name
    notes: list[str] = []
    with lock(profile):
        new = _new_op(op, f"undo of the install of {name}")
        try:
            data = _profile_back(op, profile, notes)
            if data is not None:
                new.write_file(profile, data)
            left: list[str] = []
            if dest.is_dir() and op.info.get("fresh") and not _shared_folder(dest):
                created = op.info.get("created") or {}
                staged = dest.with_name(f".{dest.name}.staging-{new.id}")
                staged.mkdir()
                for rel in manifest(dest):
                    if rel in created and _unchanged(dest / rel, created[rel]):
                        continue
                    (staged / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dest / rel, staged / rel)
                    left.append(rel)
                new.replace_folder(dest, staged)
            elif dest.is_dir() and _shared_folder(dest):
                notes.append(f"{dest.name} holds Seamless Co-op, so its folder stays")
            if left:
                notes.append(f"kept in {dest.name}, changed or added since: {', '.join(left[:5])}")
        except BaseException:
            new.discard()
            raise
        new.commit()
        new.release()  # an undo is final: the files it removed are not kept
        if dest.is_dir() and not any(dest.iterdir()):
            dest.rmdir()
        op.release()
    for n in notes:
        log(f"undo: {n}")
    return f"took back the install of {name}" + (f" ({'; '.join(notes)})" if notes else "")


def rollback(op_dir: Path, log=lambda s: None, then=None) -> str:
    """Put the version an update replaced back, as a set (folder and profile). The version rolled back is kept aside
    (a rollback is an operation too, kept until keep()). then(): a rebuild for the restored version; when it fails
    the rollback is undone."""
    op = build.Operation.load(op_dir)
    profile = Path(op.info["profile"])
    dest = Path(op.info["dest"])
    name = op.info.get("name") or dest.name
    folder = next((s for s in op.steps if s["type"] == "folder"), None)
    previous = Path(folder["previous"]) if folder and folder["previous"] else None
    if previous is None or not previous.is_dir():
        raise OperationError(f"The version of {name} before the update is no longer kept.")
    notes: list[str] = []
    created = op.info.get("created") or {}
    changed = [rel for rel in manifest(dest) if rel not in created or not _unchanged(dest / rel, created[rel])]
    if changed:
        notes.append(f"files changed in the newer version are kept with it ({', '.join(changed[:5])})")
    with lock(profile):
        new = _new_op(op, f"rollback of the update of {name}")
        try:
            new.replace_folder(dest, previous)
            data = _profile_back(op, profile, notes)
            if data is not None:
                new.write_file(profile, data)
            new.note(kind="rollback", name=name, dest=str(dest), created=None, entries=[])
        except BaseException:
            new.discard()
            raise
        commit(new, then)  # lets go of op itself (same folder); the previous folder it kept is in place now
    for n in notes:
        log(f"rollback: {n}")
    return f"rolled {name} back to the version before the update" + (f" ({'; '.join(notes)})" if notes else "")


def keep(op_dir: Path) -> None:
    """Keep an update (or a rollback): what it replaced is let go of."""
    build.Operation.load(op_dir).release()


def kept_versions(profile: Path) -> list[dict]:
    """The finished operations in this profile's folder that can still be taken back: {dir, kind, name, what}."""
    return [
        {"dir": str(o.dir), "kind": o.info.get("kind", ""), "name": o.info.get("name", ""), "what": o.what}
        for o in build.active(_root(profile))
    ]
