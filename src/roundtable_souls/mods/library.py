"""The launcher's mod folder for one game: rs-<game key> inside me3's profiles folder, with a fixed layout. Mods are
installed there once and listed by any profile; profiles point at them with paths relative to themselves, so the
folder can be copied or moved as one.

    profiles/<profile>.me3                 the profiles, side by side
    packages/<mod id>/                     asset mods, their own files untouched
    natives/<mod id>/                      DLL mods, their settings files shared by every profile
    overhauls/<overhaul id>/               an overhaul's runtime files, shared, with roundtable.json
    sources/<overhaul id>/                 what its builds read, by role: merge/ text/ hooks/ base/, with roundtable.json
    builds/<what>/<profile>/               what is made per profile (an overhaul's merged package, Combine's
                                           combined-parameters): build.json, merge-report.txt, .previous/
    .roundtable/                           the launcher's own (hidden): settings.json (per-profile choices), backups/,
                                           previous/ (an updated mod's old copy), ops/ and ops.lock (journals)

ModLibrary answers where each of these is, and mods.naming says what things are called.
Nothing is created until ensure() asks for it. Which profiles use which mod is never stored: scan() works it out from
the profiles' entries.

Today's installs, updates and Combine still use the folders they always have (3.21); this is the model they and the
adoption of existing setups will ask. Not to be confused with the save library (saves.library).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from roundtable_souls.formats import me3_profile
from roundtable_souls.platform import files

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations

PREFIX = "rs-"
STATE = ".roundtable"  # the launcher's own folder in the library
PREVIOUS = ".previous"  # a build's previous copy, for Undo rebuild
HIDDEN = (STATE, PREVIOUS)  # given Windows' hidden attribute when ensure() makes them
RECORD = "roundtable.json"  # the launcher's file beside a mod's files
ROLES = ("merge", "text", "hooks", "base")  # an overhaul's sources, by what its builds do with them
COLLECTIONS = ("packages", "natives", "overhauls")  # the folders holding one mod per folder


@dataclass(frozen=True)
class SourceFolders:
    """sources/<overhaul id>/: one folder per role and the record of where each file came from."""

    root: Path
    merge: Path
    text: Path
    hooks: Path
    base: Path
    record: Path

    def role(self, name: str) -> Path:
        if name not in ROLES:
            raise ValueError(f"not a source role: {name}")
        return self.root / name


@dataclass(frozen=True)
class BuildFolder:
    """builds/<what>/<profile>/: what one profile's build made, its inputs (build.json), its report, the previous
    build kept for Undo rebuild, and the install's side effects on the profile (roundtable.json)."""

    root: Path
    record: Path
    report: Path
    previous: Path
    side_effects: Path


@dataclass(frozen=True)
class StateFolders:
    """.roundtable/: the launcher's own files in the library."""

    root: Path
    settings: Path
    backups: Path
    previous: Path
    ops: Path
    ops_lock: Path


@dataclass(frozen=True)
class ModLibrary:
    """Where everything goes in one game's library (paths only; nothing is read or made here but by ensure and
    scan)."""

    root: Path
    game: str

    @classmethod
    def for_game(cls, loc: Locations) -> ModLibrary | None:
        """The library for loc's game in its me3 profiles folder (Settings > Locations may move that), or None when
        there is no such folder on this machine."""
        profiles = loc.me3_profiles_dir()
        return cls.at(profiles, loc.game.key) if profiles is not None else None

    @classmethod
    def at(cls, profiles_dir: Path, game: str) -> ModLibrary:
        return cls(Path(profiles_dir) / f"{PREFIX}{game}", game)

    # ------------------------------------------------------------------ the layout
    @property
    def profiles(self) -> Path:
        return self.root / "profiles"

    @property
    def packages(self) -> Path:
        return self.root / "packages"

    @property
    def natives(self) -> Path:
        return self.root / "natives"

    @property
    def overhauls(self) -> Path:
        return self.root / "overhauls"

    @property
    def sources_root(self) -> Path:
        return self.root / "sources"

    @property
    def builds(self) -> Path:
        return self.root / "builds"

    def profile(self, name: str) -> Path:
        return self.profiles / f"{name}.me3"

    def package(self, mod_id: str) -> Path:
        return self.packages / mod_id

    def native(self, mod_id: str) -> Path:
        return self.natives / mod_id

    def overhaul(self, overhaul_id: str) -> Path:
        return self.overhauls / overhaul_id

    def overhaul_record(self, overhaul_id: str) -> Path:
        return self.overhaul(overhaul_id) / RECORD

    def sources(self, overhaul_id: str) -> SourceFolders:
        root = self.sources_root / overhaul_id
        return SourceFolders(root, root / "merge", root / "text", root / "hooks", root / "base", root / RECORD)

    def build(self, what: str, profile: str) -> BuildFolder:
        """what: an overhaul's id, or combined-parameters; profile: the profile's name (its file name without .me3)."""
        root = self.builds / what / profile
        return BuildFolder(root, root / "build.json", root / "merge-report.txt", root / PREVIOUS, root / RECORD)

    @property
    def state(self) -> StateFolders:
        root = self.root / STATE
        return StateFolders(
            root, root / "settings.json", root / "backups", root / "previous", root / "ops", root / "ops.lock"
        )

    # ------------------------------------------------------------------ making folders
    def ensure(self, *folders: Path) -> list[Path]:
        """Make these folders (inside the library) and the ones above them, only these; .roundtable and .previous
        get Windows' hidden attribute when made. Returns the folders made."""
        made: list[Path] = []
        root = Path(os.path.abspath(self.root))
        for folder in folders:
            folder = Path(os.path.abspath(folder))
            if folder != root and root not in folder.parents:
                raise ValueError(f"{folder} is not inside {self.root}")
            chain = [folder, *(p for p in folder.parents if p == root or root in p.parents)]
            for p in reversed(chain):
                if p.is_dir():
                    continue
                p.mkdir()
                made.append(p)
                if p.name in HIDDEN:
                    files.hide(p)
        return made

    # ------------------------------------------------------------------ what is there
    def scan(self) -> Contents:
        """What the library holds and which profiles use what, read from the folders and the profiles' entries.
        Reads only; an unreadable profile is listed with no entries."""
        out = Contents(self)
        if self.profiles.is_dir():
            out.profiles = sorted((p for p in self.profiles.glob("*.me3") if p.is_file()), key=lambda p: p.name.lower())
        for name in COLLECTIONS:
            folder = self.root / name
            out.mods[name] = _folders(folder)
        if self.builds.is_dir():
            out.builds = {what: _folders(self.builds / what) for what in _folders(self.builds)}
        for profile in out.profiles:
            try:
                rows = me3_profile.entries(me3_profile.read_text(profile))
            except OSError, ValueError:
                continue
            for row in rows:
                if not row.get("path"):
                    continue
                where = self.place_of(me3_profile.resolve(profile, row["path"]))
                use = Use(profile, row["kind"], row["name"], row.get("enabled", True))
                if where is None:
                    out.outside.append(use)
                else:
                    out.users.setdefault(where, []).append(use)
        return out

    def place_of(self, path: Path) -> tuple[str, str] | None:
        """(collection, id) of the library folder a path points into: ("packages", "hair"), ("natives", "x") for
        natives/x/x.dll, ("builds", "<what>") for an overhaul's build; None outside the library's mod folders."""
        try:
            rel = Path(os.path.abspath(path)).relative_to(os.path.abspath(self.root))
        except ValueError:
            return None
        parts = rel.parts
        if len(parts) >= 2 and parts[0] in (*COLLECTIONS, "builds"):
            return parts[0], parts[1]
        return None


@dataclass(frozen=True)
class Use:
    """One profile entry pointing at something."""

    profile: Path
    kind: str  # package or native
    name: str  # its id, else its file or folder name
    enabled: bool


@dataclass
class Contents:
    """What scan() found: profiles, the mods in each collection, builds per overhaul (what -> profiles), which
    profiles' entries point at each mod, and the entries that point outside the library."""

    library: ModLibrary
    profiles: list[Path] = field(default_factory=list)
    mods: dict[str, list[str]] = field(default_factory=dict)  # packages / natives / overhauls -> ids
    builds: dict[str, list[str]] = field(default_factory=dict)  # what -> profile names with a build
    users: dict[tuple[str, str], list[Use]] = field(default_factory=dict)  # (collection, id) -> entries using it
    outside: list[Use] = field(default_factory=list)

    def used_by(self, collection: str, mod_id: str) -> list[Path]:
        """The profiles with an entry pointing at this mod, each once, in profile order."""
        seen: list[Path] = []
        for use in self.users.get((collection, mod_id), []):
            if use.profile not in seen:
                seen.append(use.profile)
        return seen

    def unused(self, collection: str) -> list[str]:
        """The mods in a collection no profile points at."""
        return [m for m in self.mods.get(collection, []) if (collection, m) not in self.users]


def _folders(folder: Path) -> list[str]:
    """The names of the folders directly in `folder` (not hidden ones), sorted."""
    if not folder.is_dir():
        return []
    return sorted((p.name for p in folder.iterdir() if p.is_dir() and not p.name.startswith(".")), key=str.lower)
