"""What installing an overhaul into a me3 profile changes, worked out without writing anything.

plan() takes the profile's text and one build's install description (OverhaulConfig.builds[].install) and returns
the changes, as data the profile writer applies, and the problems that stop the install or that the player should
know. check() looks at a profile after an install, as the overhaul's own check does. Nothing here writes a file; the
only reads are the file checks passed in (is_file, is_dir), so tests pass their own.

The changes are those Nightreign Revive's installer makes to a profile on a LITE install (0.1.33-rc3,
installer/installer.py: clean_owned, then patched_profile), with its DLLs' load settings exactly as it writes them:
    remove   earlier installs' own entries (its package ids and DLL file names)
    set      top-level settings (profileVersion, start_online)
    update   Seamless Co-op's DLL switched back on (pointed at the Seamless found) when the profile has it switched
             off; a companion mod's DLL given its initializer when it has none
    add      Seamless Co-op's DLL when the profile has none; the overhaul's DLLs, after the profile's own, the one
             with after_enabled_natives loading after every enabled DLL; its package, after every enabled package
Paths of added entries are absolute, as the installer writes them; entries are matched by their path as the profile
writes it (packages by id). apply() makes the same changes to a parsed profile in memory: what the writer has to
produce, entry by entry.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Any, Literal

from roundtable_souls.overhauls.config import Build, Install, OverhaulConfig

Kind = Literal["setting", "package", "native"]


@dataclass(frozen=True)
class Change:
    action: Literal["set", "remove", "update", "add"]
    kind: Kind
    key: str = ""  # set: the setting; remove/update: the entry (a package's id, a DLL's path as the profile has it)
    values: dict[str, Any] = field(default_factory=dict)  # set: {key: value}; update: fields set; add: the entry
    why: str = ""


@dataclass(frozen=True)
class Problem:
    code: str
    message: str
    blocks: bool = True  # False: a notice, the install can go ahead


@dataclass
class Plan:
    changes: list[Change] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(p.blocks for p in self.problems)


# ----------------------------------------------------------------------------- the profile, as the installer reads it
def rows(data: dict, plural: str) -> list[dict]:
    """A profile's packages or natives, in either of me3's spellings (packages / package)."""
    found = data.get(plural, data.get(plural[:-1], []))
    return found if isinstance(found, list) else []


def package_id(row: dict) -> str:
    """Its id, or its folder's name when it has no id key (as me3 and the installer do)."""
    return str(row.get("id", PurePath(str(row.get("path", ""))).name))


def native_id(row: dict) -> str:
    return str(row.get("id", PurePath(str(row.get("path", ""))).name))


def dll_name(row: dict) -> str:
    return PurePath(str(row.get("path", "")).replace("\\", "/")).name.lower()


def absolute(profile: Path, path: str) -> str:
    """A profile entry's path made absolute against the profile's folder, with forward slashes (no file is read)."""
    return os.path.normpath(os.path.join(Path(profile).parent, path)).replace("\\", "/")


def _enabled(row: dict) -> bool:
    return bool(row.get("enabled", True))


def _ordered(packages: list[dict]) -> tuple[list[dict], Problem | None]:
    """Enabled packages in me3's order (installer.py ordered_packages): file order, each after what it loads after."""
    enabled = [r for r in packages if _enabled(r)]
    ids = [package_id(r) for r in enabled]
    if len(set(ids)) != len(ids):
        return [], Problem("duplicate-ids", "The profile has two enabled packages with the same id.")
    edges: dict[str, set[str]] = {k: set() for k in ids}
    for name, row in zip(ids, enabled, strict=True):
        for dep in row.get("load_after", []) or []:
            other = dep if isinstance(dep, str) else dep.get("id")
            if other in edges:
                edges[name].add(other)
        for dep in row.get("load_before", []) or []:
            other = dep if isinstance(dep, str) else dep.get("id")
            if other in edges:
                edges[other].add(name)
    out, done = [], set()
    while len(out) < len(enabled):
        i = next((i for i, k in enumerate(ids) if k not in done and edges[k] <= done), None)
        if i is None:
            return [], Problem("order-cycle", "The profile's packages load after each other in a circle.")
        done.add(ids[i])
        out.append(enabled[i])
    return out, None


# ----------------------------------------------------------------------------- planning
def install_of(config: OverhaulConfig, edition: str | None = None) -> tuple[Build | None, Problem | None]:
    """The build to install for an edition (None: the first that has an install description), or why there is none."""
    if edition and edition in config.install_unsupported:
        why = config.install_unsupported[edition]
        return None, Problem("edition-unsupported", f"{config.label} {edition} is not installed by the launcher. {why}")
    for b in config.builds:
        if b.install is not None and (edition is None or any(c.equals == edition for c in b.match.json_)):
            return b, None
    return None, Problem("no-install", f"The launcher has no install description for {config.label} {edition or ''}.")


def plan(
    profile_text: str,
    profile: Path,
    install: Install,
    own: Path,
    *,
    game_dir: Path | None = None,
    seamless: Path | None = None,
    is_file: Callable[[Path], bool] = Path.is_file,
    is_dir: Callable[[Path], bool] = Path.is_dir,
) -> Plan:
    """The changes that install the overhaul (its own folder `own`) into the profile at `profile` whose text is
    profile_text, and the problems. seamless: the Seamless Co-op DLL to use when the profile has none switched on
    (else the install's candidates are tried)."""
    out = Plan()
    try:
        data = tomllib.loads(profile_text)
    except tomllib.TOMLDecodeError as e:
        out.problems.append(Problem("profile-unreadable", f"The profile could not be read: {e}"))
        return out
    profile = Path(profile)
    packages = [dict(r) for r in rows(data, "packages")]
    natives = [dict(r) for r in rows(data, "natives")]

    # clean_owned: an earlier install's own entries go first (any edition's)
    owned_ids, owned_dlls = set(install.owned_package_ids), {d.lower() for d in install.owned_dlls}
    for r in packages:
        if r.get("id") in owned_ids:
            out.changes.append(Change("remove", "package", package_id(r), why="an earlier install's own package"))
    for r in natives:
        if dll_name(r) in owned_dlls:
            out.changes.append(Change("remove", "native", str(r.get("path", "")), why="an earlier install's own DLL"))
    packages = [r for r in packages if r.get("id") not in owned_ids]
    natives = [r for r in natives if dll_name(r) not in owned_dlls]

    # install(): every enabled package's folder must be there, in an order me3 can follow
    _, problem = _ordered(packages)
    if problem:
        out.problems.append(problem)
    for r in packages:
        if _enabled(r) and r.get("path") and not is_dir(Path(absolute(profile, str(r["path"])))):
            out.problems.append(Problem("package-missing", f"An enabled mod's folder is missing: {r['path']}"))

    # patched_profile: top-level settings
    for key, value in install.profile_settings.items():
        if data.get(key) != value:
            out.changes.append(Change("set", "setting", key, {key: value}, "the overhaul's installer sets it"))

    # install() + patched_profile: Seamless Co-op switched on
    if install.seamless is not None:
        want = install.seamless.dll.lower()
        if not any(dll_name(n) == want and _enabled(n) for n in natives):
            found = seamless or _first_candidate(install, profile, game_dir, is_file)
            if found is None:
                out.problems.append(
                    Problem(
                        "seamless-missing", f"Seamless Co-op ({install.seamless.dll}) is required and was not found."
                    )
                )
            else:
                path = Path(found).as_posix()
                off = next((n for n in natives if dll_name(n) == want), None)
                if off is not None:
                    values = {"enabled": True, "path": path}
                    out.changes.append(
                        Change("update", "native", str(off.get("path", "")), values, "Seamless is required")
                    )
                    off.update(values)
                else:
                    entry = {"path": path}
                    out.changes.append(Change("add", "native", values=entry, why="Seamless is required"))
                    natives.append(dict(entry))

    deps = [{"id": native_id(n), "optional": True} for n in natives if _enabled(n)]

    # patched_profile: initializers for companion mods' DLLs that have none
    for rule in install.set_initializers:
        for n in natives:
            if dll_name(n).startswith(rule.name_prefix.lower()) and "initializer" not in n:
                values = {"initializer": {"function": rule.function}}
                out.changes.append(Change("update", "native", str(n.get("path", "")), values, "its initializer"))
                n.update(values)

    # patched_profile: the overhaul's own DLLs and package, last
    for spec in install.natives:
        entry: dict[str, Any] = {"path": (Path(own) / spec.file).as_posix()}
        if spec.load_early is not None:
            entry["load_early"] = spec.load_early
        if spec.initializer is not None:
            entry["initializer"] = {"function": spec.initializer.function}
        if spec.after_enabled_natives:
            entry["load_after"] = [dict(d) for d in deps]
        out.changes.append(Change("add", "native", values=entry, why="the overhaul's DLL"))
    if install.package is not None:
        entry = {"id": install.package.id, "path": (Path(own) / install.package.folder).as_posix()}
        if install.package.after_enabled_packages:
            entry["load_after"] = [{"id": package_id(p), "optional": True} for p in packages if _enabled(p)]
        out.changes.append(Change("add", "package", values=entry, why="the overhaul's package"))
    return out


def _first_candidate(install: Install, profile: Path, game_dir: Path | None, is_file) -> Path | None:
    assert install.seamless is not None
    for c in install.seamless.candidates:
        if "{game_dir}" in c and game_dir is None:
            continue
        p = Path(c.replace("{profile_dir}", str(Path(profile).parent)).replace("{game_dir}", str(game_dir or "")))
        if is_file(p):
            return p
    return None


def apply(data: dict, changes: list[Change]) -> dict:
    """The changes made to a parsed profile in memory (what the profile writer has to produce), entries in plural
    form. The input is not changed."""
    out = {k: v for k, v in data.items() if k not in ("package", "native")}
    packages = [dict(r) for r in rows(data, "packages")]
    natives = [dict(r) for r in rows(data, "natives")]
    for c in changes:
        if c.action == "set":
            out.update(c.values)
        elif c.action == "remove" and c.kind == "package":
            packages = [r for r in packages if package_id(r) != c.key]
        elif c.action == "remove":
            natives = [r for r in natives if str(r.get("path", "")) != c.key]
        elif c.action == "update":
            target = packages if c.kind == "package" else natives
            for r in target:
                if (package_id(r) if c.kind == "package" else str(r.get("path", ""))) == c.key:
                    r.update(c.values)
                    break
        elif c.action == "add":
            (packages if c.kind == "package" else natives).append(dict(c.values))
    out["packages"], out["natives"] = packages, natives
    return out


# ----------------------------------------------------------------------------- after an install
def check(
    profile_text: str,
    profile: Path,
    install: Install,
    own: Path,
    *,
    is_file: Callable[[Path], bool] = Path.is_file,
    is_dir: Callable[[Path], bool] = Path.is_dir,
    has_files: Callable[[Path], bool] = lambda p: any(p.iterdir()),
) -> list[Problem]:
    """What is wrong with an installed overhaul (its check, installer.py check(), the parts a LITE install has):
    its files, its package switched on, every switched-on DLL there, and an order me3 can follow."""
    problems: list[Problem] = []
    own = Path(own)
    for rel in install.required_files:
        if not is_file(own / rel):
            problems.append(Problem("file-missing", f"A file of the overhaul is missing: {rel}"))
    for rel in install.required_folders:
        if not is_dir(own / rel) or not has_files(own / rel):
            problems.append(Problem("folder-empty", f"The overhaul's {rel} folder is missing or empty."))
    try:
        data = tomllib.loads(profile_text)
    except tomllib.TOMLDecodeError as e:
        return [*problems, Problem("profile-unreadable", f"The profile could not be read: {e}")]
    packages, natives = rows(data, "packages"), rows(data, "natives")
    if install.package is not None and not any(r.get("id") == install.package.id and _enabled(r) for r in packages):
        problems.append(Problem("not-enabled", f"The overhaul's package ({install.package.id}) is not switched on."))
    for n in natives:
        if _enabled(n) and n.get("path") and not is_file(Path(absolute(profile, str(n["path"])))):
            problems.append(Problem("dll-missing", f"A switched-on DLL is missing: {n['path']}"))
    _, problem = _ordered(list(packages))
    if problem:
        problems.append(problem)
    return problems
