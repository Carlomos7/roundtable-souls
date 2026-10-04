"""Where things are on this machine (a game's folder and saves, whether it runs, me3), on Windows and Linux. Steam is
in steam.py, the process list in proc.py.

These are the primitives: each takes what it looks for (an exe name, a save folder, an override). A game's own answers,
with the Settings > Locations overrides applied, are game/locate.py's Locations. On Linux (desktop or Steam Deck) the
game runs through Proton, so its saves live inside the game's Proton prefix and the game process is a Wine process
whose command line names the game's exe. Nothing here writes to disk.
"""

import os
import shutil
import sys
from pathlib import Path

from roundtable_souls.platform import proc, steam

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

# A real game instance uses gigabytes. Failed launches leave dead game exe shells behind that sit
# under 1 MB with no threads; Steam counts those as "running", these tools do not.
REAL_GAME_MIN_KB = 100_000


# Detection (Steam libraries, the game folder, me3.exe) scans PATH and the disk. The answers are stable within a
# session, but Setup.summary()/problems() ask for them many times per game-tab switch, so they are memoised here and
# cleared whenever the settings or the game change (app.AppContext).
_DETECT_CACHE: dict = {}


def _detected(key, compute):
    if key not in _DETECT_CACHE:
        _DETECT_CACHE[key] = compute()
    return _DETECT_CACHE[key]


def clear_detection_cache() -> None:
    _DETECT_CACHE.clear()
    steam.clear_cache()


def exe_running(exe_name: str) -> bool:
    """A real copy of the game whose exe is exe_name runs (one using gigabytes, not a dead shell)."""
    return any(kb >= REAL_GAME_MIN_KB for _, kb in proc.processes(exe_name))


def dead_exe_shells(exe_name: str) -> list[int]:
    """Leftover zero-memory copies of the game. A Windows problem; Proton cleans up after itself."""
    if not IS_WINDOWS:
        return []
    return [pid for pid, kb in proc.processes(exe_name) if kb < REAL_GAME_MIN_KB]


def find_installed(key: str, install_dir: str, exe: str) -> Path | None:
    """The folder with exe under steamapps/common/install_dir in any Steam library, or None (cached per key for the
    session)."""

    def find():
        for root in steam.steam_libraries():
            candidate = root / "steamapps" / "common" / Path(install_dir)
            if (candidate / exe).exists():
                return candidate
        return None

    return _detected(("installed_dir", key), find)


# ------------------------------------------------------------------- saves


def save_roots_for(save_dir: str, app_id: str) -> list[Path]:
    """The per-account save folders' parent for a game whose saves go to %APPDATA%/<save_dir> on Windows, or the
    same folder inside its Proton prefix (compatdata/<app_id>) on Linux, in whichever Steam library that lives."""
    if IS_WINDOWS:
        appdata = os.environ.get("APPDATA")
        return [Path(appdata) / save_dir] if appdata else []
    roaming = Path("pfx") / "drive_c" / "users" / "steamuser" / "AppData" / "Roaming" / save_dir
    roots: list[Path] = []
    for lib in steam.steam_libraries():
        candidate = lib / "steamapps" / "compatdata" / app_id / roaming
        if candidate.is_dir() and candidate.resolve() not in [r.resolve() for r in roots]:
            roots.append(candidate)
    return roots


# --------------------------------------------------------------------- me3


def me3_exe(override: str | None = None):
    """The me3 set in the launcher's settings (override), else me3 on PATH, else its default per-user install
    location. The PATH search and default-folder check are cached for the session (cleared when the settings
    change)."""
    if override and Path(override).is_file():
        return Path(override)
    return _detected("me3_exe", _me3_exe_detected)


def _me3_exe_detected():
    found = shutil.which("me3")
    if found:
        return Path(found)
    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA")
        candidate = Path(local) / "Programs" / "garyttierney" / "me3" / "bin" / "me3.exe" if local else None
    else:
        candidate = Path.home() / ".local" / "bin" / "me3"
    return candidate if candidate and candidate.exists() else None


def me3_config_dir():
    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA")
        return Path(local) / "garyttierney" / "me3" / "config" if local else None
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "me3"


def me3_profiles_dir(override: str | None = None):
    """The me3 profile folder set in the launcher's settings (override), else me3's own."""
    if override and Path(override).is_dir():
        return Path(override)
    config = me3_config_dir()
    return config / "profiles" if config else None


# A .me3 profile sits at the top of the profiles folder or one level down in a "<name>-mods" folder beside its assets.
# Those asset folders (mod overrides, natives, ReShade) can hold thousands of files, so the walk stops at this depth
# and skips folders that clearly hold mod content rather than profiles: a full rglob here took seconds on real setups.
_PROFILE_SCAN_DEPTH = 2
_PROFILE_PRUNE = {"mod", "natives", "reshade", "reshade-shaders", "modengine2", "cache", "sd", "movie", "logs"}


def _iter_me3_files(root: Path, depth: int = 0):
    try:
        entries = list(os.scandir(root))
    except OSError:
        return
    for e in entries:
        if e.is_file() and e.name.endswith(".me3"):
            yield Path(e.path)
        elif e.is_dir() and depth < _PROFILE_SCAN_DEPTH and e.name.lower() not in _PROFILE_PRUNE:
            yield from _iter_me3_files(Path(e.path), depth + 1)


def find_profiles(root: Path | None, game_key: str, unnamed_key: str) -> list[Path]:
    """The user-made .me3 profiles under root for one game (the *-default.me3 ones me3 generates are skipped); a
    profile that names no game in [[supports]] counts for unnamed_key."""
    if not root or not root.exists():
        return []
    return sorted(
        (
            p
            for p in _iter_me3_files(root)
            if not p.name.endswith("-default.me3") and game_key in (profile_games(p) or (unnamed_key,))
        ),
        key=lambda p: (p.name.lower(), str(p).lower()),  # the Play list shows file names, so order by those
    )


_PROFILE_GAMES_CACHE: dict = {}  # path -> (mtime, games); parsing every .me3 on each game-tab switch is pure waste


def profile_games(profile: Path) -> tuple[str, ...]:
    """The games a .me3 profile says it supports ([[supports]] game = ...), lower-case; empty when it names none.
    Cached by file modification time, so a profile is parsed once until it changes on disk."""
    import tomllib

    profile = Path(profile)
    try:
        mtime = profile.stat().st_mtime
    except OSError:
        return ()
    cached = _PROFILE_GAMES_CACHE.get(profile)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        data = tomllib.loads(profile.read_text(encoding="utf-8", errors="replace"))
    except OSError, tomllib.TOMLDecodeError:
        data = {}  # unreadable counts as naming no game, and is cached like any answer until the file changes
    rows = data.get("supports") or []
    if isinstance(rows, dict):
        rows = [rows]
    result = tuple(
        str(r.get("game") or "").strip().lower()
        for r in rows
        if isinstance(r, dict) and str(r.get("game") or "").strip()
    )
    _PROFILE_GAMES_CACHE[profile] = (mtime, result)
    return result
