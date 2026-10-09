"""What an overhaul config says about profile entries, decided in one place: whether a requirement (another mod it
needs) is met by a profile's entries, and which entries an overhaul owns (the ones its install adds, so a second
install replaces them). The build engine, the install planner and the profile writer's Requires rule all ask here.

An entry is a dict with kind ("package" or "native"), and the profile's id, path and enabled as written (enabled
defaults to true): formats.me3_profile.entries() gives that shape, and a row of a parsed profile with a kind added.
A package is named by its id (its folder's name when it has none), a DLL by its file name, case aside.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import PurePath
from typing import Literal

from roundtable_souls.overhauls.config import Build, Install, OverhaulConfig, Requirement

State = Literal["on", "off", "missing"]


def entry_name(kind: str, row: dict) -> str:
    """How a requirement names an entry: a package's id (its folder's name without one), a DLL's file name."""
    path = PurePath(str(row.get("path") or "").replace("\\", "/")).name
    if kind == "package":
        return str(row.get("id") or path)
    return path


def is_enabled(row: dict) -> bool:
    return bool(row.get("enabled", True))


def matches(req: Requirement, kind: str, row: dict) -> bool:
    return kind == req.kind and entry_name(kind, row).lower() == req.name.lower()


def state(req: Requirement, entries: Iterable[dict]) -> tuple[State, dict | None]:
    """Whether the profile meets the requirement: "on" (an entry for it is switched on), "off" (only switched-off
    ones), "missing"; with the entry found (the switched-on one, else the first switched-off one)."""
    off = None
    for e in entries:
        if matches(req, e["kind"], e):
            if is_enabled(e):
                return "on", e
            off = off or e
    return ("off", off) if off is not None else ("missing", None)


def unmet(requires: Sequence[Requirement], entries: Iterable[dict]) -> list[tuple[Requirement, State]]:
    """The requirements the entries do not meet, each with why (off or missing), in the config's order."""
    entries = list(entries)
    out: list[tuple[Requirement, State]] = []
    for req in requires:
        found, _ = state(req, entries)
        if found != "on":
            out.append((req, found))
    return out


def refusal(label: str, req: Requirement) -> str:
    """The build's refusal for an unmet requirement."""
    return f"{label} needs {req.shown()} switched on in the profile."


# ----------------------------------------------------------------------------- owned entries
def owns(install: Install, kind: str, row: dict) -> bool:
    """Whether the entry is one an install of this edition puts in the profile (or an earlier version's install
    did): its package ids, its DLL file names."""
    if kind == "package":
        return str(row.get("id") or "") in install.owned_package_ids
    return entry_name("native", row).lower() in {d.lower() for d in install.owned_dlls}


def owner(configs: Iterable[OverhaulConfig], kind: str, row: dict) -> tuple[OverhaulConfig, Build] | None:
    """The overhaul (and the edition) that owns this entry, or None: the player's own entry."""
    for config in configs:
        for build in config.builds:
            if build.install is not None and owns(build.install, kind, row):
                return config, build
    return None


def owned_by(configs: Iterable[OverhaulConfig], entries: Iterable[dict]) -> dict[str, list[dict]]:
    """The entries each overhaul owns in a profile, by config id (overhauls with none are left out)."""
    configs = list(configs)
    out: dict[str, list[dict]] = {}
    for e in entries:
        found = owner(configs, e["kind"], e)
        if found is not None:
            out.setdefault(found[0].id, []).append(e)
    return out


def needed_by(configs: Iterable[OverhaulConfig], kind: str, row: dict) -> list[Requirement]:
    """What an entry needs because an overhaul owns it: its edition's requires list ([] for the player's own)."""
    found = owner(configs, kind, row)
    return list(found[1].requires) if found is not None else []
