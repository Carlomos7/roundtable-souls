"""A rebuild tool that keeps a manifest beside the package it writes (installation.json with a refresh protocol and
the sources of its last run, each with a sha256) and its setup files in a folder of the profile: an installer script
and the Python that runs it. This adapter turns that layout into a Recipe, so it runs like any declared tool.

It is run with `refresh` when the manifest was written on this PC, and with `install` from its setup folder when it
was not (refresh refuses a manifest whose paths are not here); both merge the same way and rewrite the manifest.
What it combines: the files its setup ships to merge into (payload/mod) and the ones it patches onto the last
package's copy or the game's (payload/settings/vanilla)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from roundtable_souls.mods.backends import Recipe, local_path

MANIFEST = "installation.json"


def _setup_ok(folder: Path) -> bool:
    return (folder / "installer" / "installer.py").is_file() and (folder / "tools" / "python" / "python.exe").is_file()


def _read(manifest: Path, relaxed: bool = False) -> dict | None:
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        return None
    if not relaxed and not isinstance(data.get("refreshProtocol"), int):
        return None
    return data


def recipe(profile: Path, layer: dict, relaxed: bool = False) -> Recipe | None:
    """strict: installation.json with a refresh protocol and sources. relaxed (a package the user set as the
    parameter overlay): any .json beside it, or beside its folder, that lists sources."""
    folder = Path(layer["folder"])
    for cand in (folder, folder.parent):
        found = [cand / MANIFEST] if not relaxed else sorted(cand.glob("*.json"), key=lambda p: p.name != MANIFEST)
        for manifest in found:
            if manifest.is_file() and manifest.name != "rebuild.json":
                data = _read(manifest, relaxed)
                if data is not None:
                    return _recipe(Path(profile), layer, manifest, data)
    return None


def _find_setup(profile: Path, data: dict) -> Path | None:
    written = data.get("maintenance")
    if written:
        here = local_path(written, profile)
        if _setup_ok(here):
            return here
    kids = sorted((c for c in profile.parent.iterdir() if c.is_dir()), key=lambda x: x.name.lower())
    for c in kids:  # its folder, found by content
        if any(c.glob("*maintenance.json")) and _setup_ok(c):
            return c
    for c in kids:
        if _setup_ok(c):
            return c
    return None


def _merges(setup: Path | None) -> set[str]:
    out: set[str] = set()
    for sub in ("payload/mod", "payload/settings/vanilla"):
        base = setup / sub if setup else None
        for f in base.rglob("*") if base is not None and base.is_dir() else []:
            if f.is_file() and not f.name.lower().endswith(".manifest.json"):
                out.add(f.relative_to(base).as_posix().lower())
    return out


def _recipe(profile: Path, layer: dict, manifest: Path, data: dict) -> Recipe:
    from roundtable_souls.system import common

    setup = _find_setup(profile, data)
    label = f"the rebuild tool of {layer['name']}"
    written_here = all(Path(str(data.get(k) or "")).exists() for k in ("maintenance", "game"))
    problem = None
    command: list[str] = []
    if setup is None:
        problem = f"The setup files of {label} were not found in the profile's folder."
    else:
        py, script = setup / "tools" / "python" / "python.exe", setup / "installer" / "installer.py"
        where = ["--profile", str(profile), "--target", str(profile.parent), "--non-interactive"]
        if written_here:
            command = [str(py), "-I", "-u", str(script), "refresh", *where]
        else:
            game_dir = common.game_dir()
            exe = Path(game_dir) / common.game_exe_name() if game_dir else None
            me3 = common.me3_exe()
            if exe is None or not exe.is_file():
                problem = "The game was not found."
            elif not me3:
                problem = "me3 was not found."
            command = [str(py), "-I", "-u", str(script), "install", "--package", str(setup), *where]
            command += ["--game", str(exe or ""), "--me3", str(me3 or "")]
            seamless = data.get("seamless")
            if seamless and local_path(seamless, profile).is_file():
                command += ["--seamless", str(local_path(seamless, profile))]
    try:
        tool = hashlib.sha256((setup / "installer" / "installer.py").read_bytes()).hexdigest() if setup else ""
    except OSError:
        tool = ""
    return Recipe(
        label=label,
        package=layer,
        profile=profile,
        command=command,
        cwd=setup or manifest.parent,
        sources_file=manifest,
        merges=_merges(setup),
        own=[p for p in (manifest.parent, setup) if p is not None],
        approval=f"{setup}|{tool}",
        problem=problem,
    )
