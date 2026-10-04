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
    from roundtable_souls.mods import locations

    setup = _find_setup(profile, data)
    label = f"the rebuild tool of {layer['name']}"
    written_here = all(Path(str(data.get(k) or "")).exists() for k in ("maintenance", "game"))
    problem = None
    command: list[str] = []
    if setup is None:
        problem = missing_text(layer["name"], ["its setup folder (an installer and the Python that runs it)"])
    else:
        py, script = setup / "tools" / "python" / "python.exe", setup / "installer" / "installer.py"
        where = ["--profile", str(profile), "--target", str(profile.parent), "--non-interactive"]
        if written_here:
            command = [str(py), "-I", "-u", str(script), "refresh", *where]
        else:
            loc = locations.get()
            game_dir = loc.game_dir()
            exe = Path(game_dir) / loc.game_exe_name() if game_dir else None
            me3 = loc.me3_exe()
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
    built = _engine(profile, layer, setup)
    if built is not None:
        engine_problem, run, approval = built
        return Recipe(
            label=f"the launcher's build of {layer['name']}",
            package=layer,
            profile=profile,
            command=[],
            cwd=setup,
            sources_file=manifest,
            merges=_merges(setup),
            own=[p for p in (manifest.parent, setup) if p is not None],
            approval=approval,
            problem=engine_problem,
            engine=run,
        )
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


class _Build:
    """What Tool.run calls when the launcher builds the mod itself (mods.engine)."""

    def __init__(self, profile: Path, layer: dict, setup: Path, recipe: dict, version: str):
        self.profile, self.layer, self.setup, self.recipe, self.version = profile, layer, setup, recipe, version
        self.describe = (
            f"The launcher builds {recipe['label']} {version} itself from its download in {setup.name}, with the "
            f"recipe {recipe['id']}; it runs {recipe['tool']['path']} from there for the merges."
        )

    def __call__(self, log):
        from roundtable_souls.mods import engine

        engine.build(self.profile, Path(self.layer["folder"]), self.setup, self.recipe, self.version, log)


def _engine(profile: Path, layer: dict, setup: Path | None):
    """(problem, the build to run, approval key) when the launcher builds this mod itself: the switch on Settings is
    on and a recipe fits its download. None otherwise (its own installer runs)."""
    from roundtable_souls.config.settings import load_settings
    from roundtable_souls.mods import engine, locations

    if setup is None or not load_settings().build_merges:
        return None
    recipe, version, _why = engine.match(setup)
    if recipe is None:
        return None
    game_dir = locations.get().game_dir()
    problem = None if game_dir and Path(game_dir).is_dir() else "The game was not found."
    try:
        tool = hashlib.sha256((setup / recipe["tool"]["path"]).read_bytes()).hexdigest()
    except OSError:
        tool = ""
    return problem, _Build(profile, layer, setup, recipe, version or ""), f"engine|{setup}|{recipe['id']}|{tool}"


def missing_text(name: str, missing: list[str]) -> str:
    return (
        f"{name} must stay last and rebuilds the combined files itself, but its setup files are missing: "
        f"{' and '.join(missing)}. Run the installer it came with again (or put the files back from a backup); "
        "until then its merge cannot be rebuilt."
    )


def missing(profile: Path, layer: dict) -> list[str]:
    """For a package that looks like it keeps its merge this way but was not found as one: which of the files this
    layout needs are not there (the manifest beside the package, the setup folder in the profile's folder)."""
    folder = Path(layer["folder"])
    out = []
    manifest = next((c / MANIFEST for c in (folder, folder.parent) if (c / MANIFEST).is_file()), None)
    data = _read(manifest, relaxed=True) if manifest is not None else None
    if manifest is None:
        out.append(f"{MANIFEST} (next to {folder.name})")
    elif data is None:
        out.append(f"a readable {MANIFEST} (the one next to {folder.name} lists no sources)")
    if _find_setup(Path(profile), data or {}) is None:
        out.append("its setup folder (an installer and the Python that runs it)")
    return out
