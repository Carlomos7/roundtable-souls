"""Rebuild tools: programs that fold the parameter file (and other shared files) of earlier packages into the package
that must stay last. The launcher only finds, runs and checks them; it never merges files itself.

Every tool is described the same way, as a Recipe: the command to run, the files it combines, where it writes the
list of sources it used (path + sha256 of each input) and which folders are its own. Adapters build a Recipe from the
files next to a package, never from a mod's name:

    declared          a rebuild.json the package (or the user, in Options) provides; see docs/Rebuild tools.md
    manifest_refresh  a tool that keeps installation.json with a refresh protocol beside its package and its setup
                      files (an installer and the Python that runs it) in a folder of the profile

A Tool wraps a Recipe with what merge.py uses: label, package, own_folders(), merges(), sources(), report_time(),
problem(), approval_key(), describe() and run(log).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path


class BackendError(RuntimeError):
    pass


def local_path(path: str | Path, profile: Path, game_dir: Path | None = None) -> Path:
    """A path a tool wrote down, on this PC. Its list may have been written on another PC or user account, so a
    path that is not here is looked for below this profile's folder (by the part after the profile folder's name)
    and below the game folder (by the part after Game). Otherwise it is returned as written."""
    p = Path(str(path).replace("\\", "/"))
    if p.exists():
        return p
    parts = [x.lower() for x in p.parts]
    here = Path(profile).parent
    name = here.name.lower()
    if name in parts:
        at = len(parts) - 1 - parts[::-1].index(name)
        return here.joinpath(*p.parts[at + 1 :])
    if game_dir is not None and "game" in parts:
        at = len(parts) - 1 - parts[::-1].index("game")
        return Path(game_dir).joinpath(*p.parts[at + 1 :])
    return p


def read_sources(file: Path) -> list[dict] | None:
    """[{path, sha256}] from a JSON file that is either {"sources": [...]} or the list itself; None without one."""
    try:
        data = json.loads(Path(file).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    rows = data.get("sources") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return None
    out = [
        {"path": str(s["path"]), "sha256": str(s["sha256"]).lower()}
        for s in rows
        if isinstance(s, dict) and s.get("path") and s.get("sha256")
    ]
    return out or None


@dataclass
class Recipe:
    """How to run one rebuild tool and read what it did."""

    label: str
    package: dict  # the layer it writes into (see merge.layers)
    profile: Path
    command: list[str]
    cwd: Path
    sources_file: Path
    merges: set[str] = field(default_factory=set)  # relative to the package, lower-case
    own: list[Path] = field(default_factory=list)  # its own folders: sources there are not packages
    approval: str = ""  # changes when the tool changes, so a new version is asked about again
    problem: str | None = None  # why it cannot run on this PC now
    timeout: int = 1800


class Tool:
    """A rebuild tool as merge.py sees it."""

    def __init__(self, recipe: Recipe):
        self.recipe = recipe
        self.label = recipe.label
        self.package = recipe.package

    def own_folders(self) -> list[Path]:
        """Its own folders, never the profile's folder or one holding it (a rebuild.json kept in Documents, say):
        that would hide every package's files."""
        import os

        def canon(x: Path) -> Path:
            return Path(os.path.normcase(os.path.abspath(x)))

        profile_dir = canon(self.recipe.profile.parent)
        return [p for p in self.recipe.own if p is not None and canon(p) not in (profile_dir, *profile_dir.parents)]

    def merges(self) -> set[str]:
        return set(self.recipe.merges)

    def sources(self) -> list[dict] | None:
        return read_sources(self.recipe.sources_file)

    def report_time(self) -> float:
        try:
            return self.recipe.sources_file.stat().st_mtime
        except OSError:
            return 0.0

    def problem(self) -> str | None:
        return self.recipe.problem

    def approval_key(self) -> str:
        r = self.recipe
        return hashlib.sha256(f"{r.approval}|{r.command[0] if r.command else ''}|{r.cwd}".lower().encode()).hexdigest()

    def describe(self) -> str:
        """The command as it will run, for the one-time question before a tool runs."""
        shown = " ".join(f'"{c}"' if " " in c else c for c in self.recipe.command)
        return f"{shown}\nin {self.recipe.cwd}"

    def run(self, log) -> None:
        from roundtable_souls.system import common

        r = self.recipe
        if r.problem:
            raise BackendError(r.problem)
        log(f"rebuild tool: {self.describe()}")
        tail: list[str] = []
        start = time.time()
        try:
            proc = subprocess.Popen(
                r.command,
                cwd=str(r.cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=common.NO_WINDOW,
            )
        except OSError as e:
            raise BackendError(f"{self.label} could not start: {e}") from e
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                log(f"  {line}")
                tail = (tail + [line])[-6:]
            if time.time() - start > r.timeout:
                proc.kill()
                raise BackendError(f"{self.label} took longer than {r.timeout // 60} minutes and was stopped.")
        code = proc.wait()
        if code != 0:
            raise BackendError(f"{self.label} stopped (exit {code}): " + (" ".join(tail[-2:]) or "no output"))


def _adapters():
    from roundtable_souls.mods.backends import declared, manifest_refresh

    return (declared, manifest_refresh)


def detect(profile: Path, packs: list[dict]):
    """The rebuild tool that writes into one of these packages (checked from the last), or None."""
    for layer in reversed(packs):
        for kind in _adapters():
            recipe = kind.recipe(Path(profile), layer)
            if recipe is not None:
                return Tool(recipe)
    return None


def detect_for(profile: Path, layer: dict, rebuild_file: Path | None = None):
    """The rebuild tool of a package the user set as the parameter overlay: from the rebuild.json they picked, else
    looked for with looser rules (a fork or a newer version may name its files differently), or None."""
    from roundtable_souls.mods.backends import declared

    if rebuild_file is not None:
        recipe = declared.recipe(Path(profile), layer, file=Path(rebuild_file))
        return Tool(recipe) if recipe is not None else None
    for kind in _adapters():
        recipe = kind.recipe(Path(profile), layer) or kind.recipe(Path(profile), layer, relaxed=True)
        if recipe is not None:
            return Tool(recipe)
    return None
