"""A build's outputs, staged beside the live folder, checked, then put in place through a journal.

    room     before anything is written: the drive must hold the outputs, a backup of what they replace, and spare
    stage    every output is written to .<live>.staging first; nothing live changes
    check    each staged file is read back (the caller says how) before anything is replaced
    activate a journal lists what is replaced; live files go to .<live>.backup, staged ones take their place, the
             record last; then the journal, the backup and the staging folder are removed
    recover  a journal still there means an activation was interrupted: every file it touched is put back as it was
             (from the backup), so the previous build stands, and the leftovers are removed

Each file is replaced by a rename; the set of files is not replaced at once. Recovery is what makes the set
consistent again after an interruption: either the whole new build (the journal was gone) or the whole old one.

An Operation extends this to several live changes made as one (a mod's folder, the profile's text and a build): each
is prepared beside what it replaces, then one journal applies them in order, the build last. recover_operations()
undoes an interrupted one as a whole; a build that was the last step of a finished operation is completed, not undone.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

from roundtable_souls.platform import filelock

JOURNAL = ".build-journal.json"
SPARE = 256 * 1024 * 1024  # left free on the drive after a build: the game and the system need room too


class BuildError(RuntimeError):
    pass


class Build:
    def __init__(self, live: Path, record: str):
        self.live = Path(live)
        self.record = record  # the record's file name: activated last, so a record always describes what is there
        self.stage = self.live.with_name("." + self.live.name + ".staging")  # a dot: not listed as a mod folder
        self.backup = self.live.with_name("." + self.live.name + ".backup")
        self.removes: list[str] = []
        recover(self.live)
        shutil.rmtree(self.stage, ignore_errors=True)
        self.stage.mkdir(parents=True)

    def make_room(self, new_bytes: int, free: Callable[[Path], int] | None = None) -> None:
        """Refuse before anything is written when the drive cannot hold the staged outputs (about new_bytes) and a
        backup of the live files they replace, with SPARE left over."""
        live_bytes = sum(p.stat().st_size for p in self.live.rglob("*") if p.is_file()) if self.live.is_dir() else 0
        need = new_bytes + live_bytes + SPARE
        where = self.live if self.live.exists() else self.live.parent
        while not where.exists() and where != where.parent:
            where = where.parent
        have = (free or (lambda p: shutil.disk_usage(p).free))(where)
        if have < need:
            self.discard()
            gb = 1024**3
            raise BuildError(
                f"not enough free space on {where.anchor or where}: a rebuild needs about {need / gb:.1f} GB, "
                f"{have / gb:.1f} GB is free"
            )

    def path(self, rel: str) -> Path:
        """Where to write an output (rel to the live folder)."""
        p = self.stage / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def remove(self, rel: str) -> None:
        """An output of the previous build this one no longer has."""
        if (self.live / rel).exists():
            self.removes.append(rel)

    def staged(self) -> list[str]:
        return sorted(p.relative_to(self.stage).as_posix() for p in self.stage.rglob("*") if p.is_file())

    def check(self, read: Callable[[str, bytes], None]) -> None:
        """read(rel, data) raises when a staged output is not what it should be; nothing live is touched then."""
        for rel in self.staged():
            if rel == self.record:
                continue
            try:
                read(rel, (self.stage / rel).read_bytes())
            except Exception as e:
                self.discard()
                raise BuildError(f"{rel} did not read back: {e}") from e

    def discard(self) -> None:
        shutil.rmtree(self.stage, ignore_errors=True)

    def activate(self, refuse: Callable[[], str | None] | None = None, operation: Operation | None = None) -> None:
        """Put the staged outputs in place. refuse(): why not now (the game is running, say), or None. operation:
        the Operation this activation is the last step of; it is marked done once every file is in place, and
        recovery then completes this activation rather than undoing it."""
        why = refuse() if refuse else None
        if why:
            self.discard()
            raise BuildError(why)
        files = self.staged()
        order = [f for f in files if f != self.record] + ([self.record] if self.record in files else [])
        journal: dict = {
            "replace": order,
            "remove": self.removes,
            "had": [r for r in order + self.removes if (self.live / r).exists()],
        }
        if operation is not None:
            journal["operation"] = str(operation.dir)
        shutil.rmtree(self.backup, ignore_errors=True)
        self.live.mkdir(parents=True, exist_ok=True)
        _write_journal(self.live, journal)
        for rel in journal["had"]:
            dest = self.backup / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.live / rel, dest)
        for rel in self.removes:
            (self.live / rel).unlink(missing_ok=True)
        for rel in order:
            dest = self.live / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(self.stage / rel, dest)
        if operation is not None:
            operation._done()  # the commit point of the whole operation
        (self.live / JOURNAL).unlink()
        shutil.rmtree(self.backup, ignore_errors=True)
        shutil.rmtree(self.stage, ignore_errors=True)


def _write_journal(live: Path, journal: dict) -> None:
    tmp = live / (JOURNAL + ".tmp")
    tmp.write_text(json.dumps(journal), encoding="utf-8")
    os.replace(tmp, live / JOURNAL)


def recover(live: Path) -> str | None:
    """Undo an interrupted activation of `live`, if there was one. Returns what was done, or None."""
    live = Path(live)
    journal_path = live / JOURNAL
    stage = live.with_name("." + live.name + ".staging")
    backup = live.with_name("." + live.name + ".backup")
    if not journal_path.is_file():
        shutil.rmtree(stage, ignore_errors=True)  # a staged build that was never activated
        return None
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    if journal.get("operation") and _state(Path(journal["operation"])) == ACTIVE:
        # every file was in place and the operation it belongs to was marked done: finish, don't undo
        journal_path.unlink()
        shutil.rmtree(backup, ignore_errors=True)
        shutil.rmtree(stage, ignore_errors=True)
        return "an interrupted rebuild was finished"
    had = set(journal.get("had") or [])
    for rel in journal.get("replace", []) + journal.get("remove", []):
        if rel in had:
            src = backup / rel
            if src.is_file():  # copied before anything was replaced: the previous file, as it was
                (live / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, live / rel)
        else:
            (live / rel).unlink(missing_ok=True)  # new in the interrupted build
    journal_path.unlink()
    shutil.rmtree(backup, ignore_errors=True)
    shutil.rmtree(stage, ignore_errors=True)
    return "an interrupted rebuild was undone: the previous result is back"


# ----------------------------------------------------------------------------- operations
OPS = ".roundtable-ops"  # beside the profile: one folder per operation, its journal and the bytes it restores
OP_JOURNAL = "journal.json"
PREPARED, ACTIVATING, ACTIVE = "prepared", "activating", "active"


def ops_lock(root: Path, timeout: float = 30.0) -> AbstractContextManager[None]:
    """Held while operations under root are prepared, applied or recovered, by every launcher process (the window,
    a Play from a shortcut): a recovery never takes another process's operation for an interrupted one."""
    return filelock.exclusive(
        Path(root) / OPS,
        timeout,
        lambda: BuildError("another launcher window is installing or removing a mod in this profile's folder"),
    )


def _state(op_dir: Path) -> str | None:
    try:
        return json.loads((Path(op_dir) / OP_JOURNAL).read_text(encoding="utf-8")).get("state")
    except OSError, ValueError:
        return None


def _move(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)


def _fingerprint(path: Path) -> str:
    """The sha256 of a file's bytes, or "missing" (what Operation.write_file's expect names)."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return "missing"


class Operation:
    """Several live changes made as one: folders replaced by staged ones, files rewritten, and a staged Build
    activated last. Everything is prepared first (nothing live changes); commit() then applies the steps in order
    under one journal. An interruption before the end is undone as a whole by recover_operations(); one that came
    after the last step is finished. The replaced folders and the files' previous bytes are kept (the journal says
    where) until release(), so the whole operation can still be rolled back.

        prepared    the steps are recorded, their staged folders and new bytes exist; nothing live changed
        activating  commit() is applying them ('done' says how many are applied)
        active      every step is applied; what they replaced is kept for a rollback
    """

    def __init__(self, root: Path, what: str, op_id: str | None = None):
        import time
        import uuid

        self.id = op_id or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.dir = Path(root) / OPS / self.id
        self.dir.mkdir(parents=True, exist_ok=False)
        self.what = what
        self.steps: list[dict] = []
        self.info: dict = {}  # the caller's own notes, kept in the journal (what was created, for an undo)
        self._builds: list[Build] = []
        self.state = PREPARED
        self.done = 0
        self.untouched = False  # commit() refused the step at done before starting it: nothing of it to undo
        self._save()

    @classmethod
    def load(cls, op_dir: Path) -> Operation:
        op_dir = Path(op_dir)
        data = json.loads((op_dir / OP_JOURNAL).read_text(encoding="utf-8"))
        op = cls.__new__(cls)
        op.id, op.dir, op.what = op_dir.name, op_dir, data.get("what", "")
        op.steps, op.info = list(data.get("steps") or []), dict(data.get("info") or {})
        op.state, op.done, op._builds = data.get("state", PREPARED), int(data.get("done", 0)), []
        op.untouched = False
        return op

    def _save(self) -> None:
        data = {"what": self.what, "state": self.state, "done": self.done, "steps": self.steps, "info": self.info}
        tmp = self.dir / (OP_JOURNAL + ".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, self.dir / OP_JOURNAL)

    def gone_when(self, path: Path) -> None:
        """then()'s last action removes path (sends a folder to the Recycle Bin, say): once every step is applied and
        path is gone, an interruption is finished, not undone."""
        self.info["gone_when"] = str(path)
        self._save()

    def note(self, **info) -> None:
        """Keep the caller's notes in the journal."""
        self.info.update(info)
        self._save()

    # -------------------------------------------------------------- preparing (nothing live changes)
    def replace_folder(self, live: Path, staged: Path) -> None:
        """staged (filled and checked beside live, on the same drive) takes live's place; a live folder already
        there is kept as .<name>.previous-<id> beside it."""
        live, staged = Path(live), Path(staged)
        prev = live.with_name(f".{live.name}.previous-{self.id}") if live.exists() else None
        self.steps.append({"type": "folder", "live": str(live), "staged": str(staged), "previous": str(prev or "")})
        self._save()

    def write_file(self, live: Path, data: bytes, expect: str | None = None) -> None:
        """live gets these bytes; the bytes it had (if any) are kept in the operation's folder. expect: the sha256
        of the bytes the caller read (or "missing": the file was not there): commit() checks the file still holds
        them right before this step and refuses the operation otherwise, so an edit made to the file outside the
        launcher meanwhile is never overwritten."""
        live = Path(live)
        n = len(self.steps)
        (self.dir / f"{n}.after").write_bytes(data)
        had = live.is_file()
        if had:
            shutil.copy2(live, self.dir / f"{n}.before")
        step = {"type": "file", "live": str(live), "before": f"{n}.before" if had else "", "after": f"{n}.after"}
        if expect:
            step["expect"] = expect
        self.steps.append(step)
        self._save()

    def activate_build(self, build: Build) -> None:
        """A staged, checked build, activated as the last step (its activation is the operation's commit point)."""
        self.steps.append({"type": "build", "live": str(build.live), "record": build.record})
        self._builds.append(build)
        self._save()

    def discard(self) -> None:
        """Give up before commit(): the staged folders and builds go, nothing live was touched."""
        for step in self.steps:
            if step["type"] == "folder":
                shutil.rmtree(step["staged"], ignore_errors=True)
            elif step["type"] == "build":
                shutil.rmtree(Path(step["live"]).with_name("." + Path(step["live"]).name + ".staging"), True)
        for b in self._builds:
            b.discard()
        shutil.rmtree(self.dir, ignore_errors=True)

    # -------------------------------------------------------------- applying
    def commit(self, refuse: Callable[[], str | None] | None = None, then: Callable[[], object] | None = None) -> None:
        """Apply every step in order, then run then() (work that needs the applied state, a rebuild say) before the
        operation counts as done. On a failure of either, the applied steps are undone and the error raised: the
        previous state stands. A last action then() takes outside the journal is named by gone_when(): recovery
        finishes the operation when that path is gone, rather than undoing it."""
        why = refuse() if refuse else None
        if why:
            self.discard()
            raise BuildError(why)
        if any(s["type"] == "build" for s in self.steps[:-1]) or (then is not None and self._builds):
            self.discard()
            raise BuildError("a build can only be the last step of an operation, with nothing run after it")
        self.state, self.done = ACTIVATING, 0
        self._save()
        builds = iter(self._builds)
        try:
            for step in self.steps:
                if step["type"] == "folder":
                    if step["previous"]:
                        _move(Path(step["live"]), Path(step["previous"]))
                    _move(Path(step["staged"]), Path(step["live"]))
                elif step["type"] == "file":
                    live = Path(step["live"])
                    if step.get("expect") and _fingerprint(live) != step["expect"]:
                        self.untouched = True  # this step was not started: nothing of it to put back
                        raise BuildError(f"{live.name} changed outside the launcher; reload and try again")
                    tmp = live.with_name(live.name + ".tmp")
                    shutil.copyfile(self.dir / step["after"], tmp)
                    os.replace(tmp, live)
                else:
                    next(builds).activate(operation=self)  # marks the operation done itself
                    return
                self.done += 1
                self._save()
            if then is not None:
                then()
        except BaseException:
            _undo(self)
            raise
        self._done()

    def _done(self) -> None:
        self.state, self.done = ACTIVE, len(self.steps)
        self._save()

    def release(self) -> None:
        """Let go of what an active operation kept for a rollback (the previous folders, the earlier bytes)."""
        for step in self.steps:
            if step["type"] == "folder" and step["previous"]:
                shutil.rmtree(step["previous"], ignore_errors=True)
        shutil.rmtree(self.dir, ignore_errors=True)


def _undo(op: Operation) -> None:
    """Put back what the applied steps (and the step that was being applied, unless it was never started) changed,
    last first; then forget the operation."""
    for step in reversed(op.steps[: op.done + (0 if op.untouched else 1)]):
        live = Path(step["live"])
        if step["type"] == "folder":
            prev, staged = (Path(step["previous"]) if step["previous"] else None), Path(step["staged"])
            if prev is not None:
                if prev.exists():  # live was moved aside: whatever sits there now is the staged one
                    if live.exists():
                        _move(live, staged)
                    _move(prev, live)
            elif live.exists() and not staged.exists():
                _move(live, staged)
        elif step["type"] == "file":
            if step["before"]:
                tmp = live.with_name(live.name + ".tmp")
                shutil.copyfile(op.dir / step["before"], tmp)
                os.replace(tmp, live)
            else:
                live.unlink(missing_ok=True)
        else:
            recover(live)  # the operation is not active: the build's own journal undoes it
    op.discard()


def recover_operations(root: Path, timeout: float = 30.0) -> list[str]:
    """Finish or undo the operations under root that were interrupted: one still activating is undone as a whole
    (the previous state stands), one only prepared is discarded. Active ones are left for a rollback. Returns what
    was done, one line each."""
    out: list[str] = []
    base = Path(root) / OPS
    if not base.is_dir():
        return out
    with ops_lock(root, timeout):
        _recover_all(base, out)
    return out


def _recover_all(base: Path, out: list[str]) -> None:
    for op_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        state = _state(op_dir)
        if state == ACTIVE:
            for step in Operation.load(op_dir).steps:
                if step["type"] == "build":
                    recover(Path(step["live"]))  # finishes a build whose journal outlived the commit point
            continue
        if state is None:
            shutil.rmtree(op_dir, ignore_errors=True)  # never got a journal: nothing was staged under it
            continue
        op = Operation.load(op_dir)
        gone = op.info.get("gone_when")
        if state == ACTIVATING and op.done >= len(op.steps) and gone and not Path(gone).exists():
            op._done()  # its last action happened: finish it
            out.append(f"an interrupted {op.what} was finished")
        elif state == ACTIVATING:
            _undo(op)
            out.append(f"an interrupted {op.what} was undone: the previous state is back")
        else:
            op.discard()
            out.append(f"the {op.what}, prepared but never applied, was cleaned up")


def pending(root: Path) -> list[str]:
    """What the operations under root that are not finished are doing (empty when there are none)."""
    base = Path(root) / OPS
    if not base.is_dir():
        return []
    return [
        Operation.load(d).what
        for d in sorted(p for p in base.iterdir() if p.is_dir())
        if _state(d) in (PREPARED, ACTIVATING)
    ]


def active(root: Path) -> list[Operation]:
    """The finished operations under root that still keep what they replaced, oldest first."""
    base = Path(root) / OPS
    if not base.is_dir():
        return []
    return [Operation.load(d) for d in sorted(p for p in base.iterdir() if p.is_dir()) if _state(d) == ACTIVE]
