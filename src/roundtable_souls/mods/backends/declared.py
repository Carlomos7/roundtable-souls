"""A rebuild tool described by a rebuild.json: beside the package that must stay last, beside its folder, or picked by
the user in that package's Options. The format is documented for mod authors in docs/Rebuild tools.md:

    {
      "rebuild": 1,
      "name": "Example rebuild tool",
      "command": ["{here}/tools/merge.exe", "--profile", "{profile}", "--out", "{package}"],
      "cwd": "{here}",
      "merges": ["regulation.bin", "script/talk/m00_00_00_00.talkesdbnd.dcx"],
      "merges_from": ["{here}/payload"],
      "sources": "{package}/rebuild-sources.json",
      "timeout_minutes": 30
    }

Placeholders: {here} (the folder holding rebuild.json), {package} (the package it writes into), {profile} (the .me3),
{profile_dir}, {game_dir}, {game_exe}, {me3}. A relative path in cwd, sources, merges_from or the program is taken
from {here}. The command runs without a shell.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from roundtable_souls.mods.backends import Recipe

FILE = "rebuild.json"
_PLACE = re.compile(r"\{(here|package|profile|profile_dir|game_dir|game_exe|me3)\}")


def _values(profile: Path, layer: dict, here: Path) -> dict[str, str]:
    from roundtable_souls.system import common

    game_dir = common.game_dir()
    return {
        "here": str(here),
        "package": str(layer["folder"]),
        "profile": str(profile),
        "profile_dir": str(profile.parent),
        "game_dir": str(game_dir or ""),
        "game_exe": str(Path(game_dir) / common.game_exe_name()) if game_dir else "",
        "me3": str(common.me3_exe() or ""),
    }


def _fill(text: str, values: dict[str, str]) -> str:
    return _PLACE.sub(lambda m: values[m.group(1)], str(text))


def _path(text: str, values: dict[str, str], here: Path) -> Path:
    p = Path(_fill(text, values))
    return p if p.is_absolute() else here / p


def load(file: Path) -> dict | None:
    try:
        data = json.loads(Path(file).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    if not isinstance(data, dict) or data.get("rebuild") != 1:
        return None
    cmd = data.get("command")
    if not isinstance(cmd, list) or not cmd or not all(isinstance(c, str) and c for c in cmd):
        return None
    if not isinstance(data.get("sources"), str):
        return None
    return data


def recipe(profile: Path, layer: dict, relaxed: bool = False, file: Path | None = None) -> Recipe | None:
    """relaxed changes nothing here: rebuild.json is the same wherever it is found."""
    folder = Path(layer["folder"])
    candidates = [Path(file)] if file is not None else [folder / FILE, folder.parent / FILE]
    for f in candidates:
        data = load(f) if f.is_file() else None
        if data is not None:
            return _recipe(Path(profile), layer, f, data)
    return None


def _recipe(profile: Path, layer: dict, file: Path, data: dict) -> Recipe:
    here = file.parent
    values = _values(profile, layer, here)
    program = _fill(data["command"][0], values)
    if not Path(program).is_absolute() and ("/" in program or "\\" in program):
        program = str(here / program)  # a program shipped with the tool; a bare name is looked up on PATH
    command = [program, *(_fill(c, values) for c in data["command"][1:])]
    merges = {str(m).replace("\\", "/").lower() for m in data.get("merges") or [] if isinstance(m, str)}
    own = [here]
    for sub in data.get("merges_from") or []:
        base = _path(sub, values, here)
        own.append(base)
        for f in base.rglob("*") if base.is_dir() else []:
            if f.is_file():
                merges.add(f.relative_to(base).as_posix().lower())
    problem = None
    needs = {m.group(1) for c in data["command"] for m in _PLACE.finditer(c)}
    if "game_exe" in needs and not values["game_exe"]:
        problem = "The game was not found."
    elif "me3" in needs and not values["me3"]:
        problem = "me3 was not found."
    elif (Path(program).is_absolute() or "/" in program) and not Path(program).is_file():
        problem = f"The rebuild tool's program was not found: {program}"
    try:
        minutes = int(data.get("timeout_minutes") or 30)
    except TypeError, ValueError:
        minutes = 30
    return Recipe(
        label=str(data.get("name") or f"the rebuild tool of {layer['name']}"),
        package=layer,
        profile=profile,
        command=command,
        cwd=_path(data.get("cwd") or "{here}", values, here),
        sources_file=_path(data["sources"], values, here),
        merges=merges,
        own=own,
        approval=str(file) + "|" + hashlib.sha256(file.read_bytes()).hexdigest(),
        problem=problem,
        timeout=max(1, minutes) * 60,
    )
