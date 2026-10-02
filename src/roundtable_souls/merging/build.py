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
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path

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

    def activate(self, refuse: Callable[[], str | None] | None = None) -> None:
        """Put the staged outputs in place. refuse(): why not now (the game is running, say), or None."""
        why = refuse() if refuse else None
        if why:
            self.discard()
            raise BuildError(why)
        files = self.staged()
        order = [f for f in files if f != self.record] + ([self.record] if self.record in files else [])
        journal = {
            "replace": order,
            "remove": self.removes,
            "had": [r for r in order + self.removes if (self.live / r).exists()],
        }
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
