"""Shared by the real-data checks in this folder.

Inputs come from the command line or from scripts/verify/local.toml (ignored by git), e.g.

    game = 'C:/Program Files (x86)/Steam/steamapps/common/ELDEN RING/Game'
    out = 'D:/rs-verify'

Real files are only read. Everything a check writes goes to its own output folder, which may not be inside the game,
me3's profiles, a save folder or this repository. The launcher's code runs with its data folder moved into that
output folder, so it never touches the real launcher data either.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
LOCAL = HERE / "local.toml"
OWNED = ".roundtable-verify"  # marks an output folder a check made, so it may be emptied on the next run


def parser(description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--game", type=Path, help="the game folder (with eldenring.exe); default: local.toml or Steam")
    p.add_argument("--out", type=Path, help="where results go; default: local.toml or a temp folder")
    return p


def settings() -> dict:
    try:
        return tomllib.loads(LOCAL.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def game_dir(given: Path | None) -> Path:
    game = given or (Path(settings()["game"]) if "game" in settings() else None)
    if game is None:
        from roundtable_souls.game import catalog
        from roundtable_souls.game.locate import Locations

        game = Locations(catalog.ELDEN_RING).game_dir()
    if game is None or not (Path(game) / "eldenring.exe").is_file():
        sys.exit(f"no eldenring.exe in {game}; pass --game or set game in {LOCAL.name}")
    return Path(game)


def _protected() -> list[Path]:
    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")
    out = [REPO]
    if local:
        out += [Path(local) / "garyttierney", Path(local) / "RoundtableSouls"]
    if roaming:
        out += [Path(roaming) / "EldenRing", Path(roaming) / "Nightreign"]
    return out


def _within(inner: Path, outer: Path) -> bool:
    try:
        inner.resolve().relative_to(outer.resolve())
        return True
    except ValueError:
        return False


def output_dir(given: Path | None, name: str, game: Path | None = None) -> Path:
    """An empty folder for this check's results. Refuses a place where real files live, and a non-empty folder this
    folder's checks did not make."""
    base = given or (Path(settings()["out"]) if "out" in settings() else Path(tempfile.gettempdir()) / "rs-verify")
    out = Path(base) / name
    for real in _protected() + ([game] if game else []):
        if _within(out, real):
            sys.exit(f"refusing to write into {real}: choose an output folder of its own (--out)")
    if out.exists() and any(out.iterdir()):
        if not (out / OWNED).is_file():
            sys.exit(f"{out} has files this check did not make; choose another --out")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / OWNED).write_text("made by scripts/verify; emptied on the next run\n", encoding="utf-8")
    return out


def sandbox_launcher(out: Path, game: Path):
    """Point the launcher's code at a data folder inside `out` and at `game`. Its settings, caches, history and logs
    then live there (run from source, the launcher would otherwise keep them beside the code). Returns the Locations
    to hand the mods code: Elden Ring in `game`."""
    from roundtable_souls.config import settings

    data = out / "launcher-data"
    data.mkdir(parents=True, exist_ok=True)
    settings.data_dir = lambda: data
    from roundtable_souls.game import catalog
    from roundtable_souls.game.locate import Locations, Overrides
    from roundtable_souls.platform import data_folder, paths

    data_folder.use(data)
    paths.clear_detection_cache()
    return Locations(catalog.ELDEN_RING, Overrides(game_exe=str(game / catalog.ELDEN_RING.exe)))


def commit() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(REPO), "describe", "--always", "--dirty"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except OSError, subprocess.CalledProcessError:
        return "unknown"


def me3_exe() -> Path | None:
    found = shutil.which("me3")
    if found:
        return Path(found)
    local = os.environ.get("LOCALAPPDATA")
    exe = Path(local) / "Programs" / "garyttierney" / "me3" / "bin" / "me3.exe" if local else None
    return exe if exe and exe.is_file() else None
