"""Where things are on this machine (Steam, the game, the saves, me3) and what is running, on Windows and Linux.

Every game-specific answer is for the active game (GAME, set with set_game): Elden Ring unless the window's game tabs
or `--game` picked another. On Linux (desktop or Steam Deck) the game runs through Proton, so its saves live inside
the game's Proton prefix and the game process is a Wine process whose command line names the game's exe. Nothing
here writes to disk except the run log.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from roundtable_souls import games
from roundtable_souls.settings import data_dir, game_setting, load_settings
from roundtable_souls.system import logging as run_logging

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
ELDEN_RING_APP_ID = games.ELDEN_RING.app_id
GAME: games.Game = games.DEFAULT  # the game every lookup below answers for

LOGS_DIR = data_dir() / "logs"  # for opening the folder; code that writes asks run_logging.log_dir()

# A real game instance uses gigabytes. Failed launches leave dead game exe shells behind that sit
# under 1 MB with no threads; Steam counts those as "running", these tools do not.
REAL_GAME_MIN_KB = 100_000
# Child consoles must never pop up (the window has no console of its own).
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ----------------------------------------------------------------- logging


def log(msg=""):
    """One line for the current job's log (and the window), under the calling module's logger. Its level follows
    its wording: 'error: ...' is an error, 'warning: ...' a warning, anything else information."""
    caller = sys._getframe(1).f_globals.get("__name__", "")
    run_logging.log_line(msg, caller or None)


def start_log(title):
    """Name the job that is running (the window starts each job as one), or, outside the window (--play, --check),
    start a job of its own that ends at exit."""
    job = run_logging.current_job()
    if job is not None and not run_logging.is_standalone(job):
        run_logging.rename_job(title)
    else:
        run_logging.start_standalone(title, game=GAME.key)


def fail(msg, code=1):
    run_logging.log_line(f"error: {msg}", sys._getframe(1).f_globals.get("__name__", "") or None)
    sys.exit(code)


def open_path(target) -> None:
    """Open a folder, file or URL with the desktop's default handler."""
    target = str(target)
    if IS_WINDOWS:
        os.startfile(target)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --------------------------------------------------------------- processes


def _windows_processes(name):
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV"],
            capture_output=True,
            text=True,
            creationflags=NO_WINDOW,
        ).stdout
    except OSError:
        return []
    found = []
    for line in out.splitlines()[1:]:
        cols = [c.strip('"') for c in line.split('","')]
        if len(cols) >= 5 and cols[0].lower() == name.lower():
            digits = "".join(ch for ch in cols[4] if ch.isdigit())
            found.append((int(cols[1]), int(digits) if digits else 0))
    return found


def _linux_processes(name, proc_root=Path("/proc")):
    """Match the program name, or for Wine / Proton processes the Windows exe named in the command line."""
    wanted = name.lower()
    found = []
    for entry in proc_root.iterdir() if proc_root.is_dir() else ():
        if not entry.name.isdigit():
            continue
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
            comm = (entry / "comm").read_text(errors="ignore").strip()
            status = (entry / "status").read_text(errors="ignore")
        except OSError:
            continue
        first = argv[0].decode(errors="ignore").replace("\\", "/").rsplit("/", 1)[-1].lower() if argv else ""
        if wanted not in (first, comm.lower()):
            continue
        rss = re.search(r"^VmRSS:\s+(\d+)\s+kB", status, re.M)
        found.append((int(entry.name), int(rss.group(1)) if rss else 0))
    return found


def processes(name):
    """(pid, resident memory in KB) for every process with this program name."""
    if IS_WINDOWS:
        return _windows_processes(name)
    if IS_LINUX:
        return _linux_processes(name)
    return []


# Optional overrides the launcher sets from its settings (blank = detect): a custom me3, a custom game exe
# (me3 launches it with --exe), and a custom me3 profile folder.
ME3_OVERRIDE = None
GAME_EXE_OVERRIDE = None
PROFILE_DIR_OVERRIDE = None
PATH_SETTINGS = ("me3_path", "game_exe", "me3_profile_dir")  # Settings > Locations; blank = detect


def apply_overrides(settings: dict | None = None) -> dict:
    """Push the location settings into the tools layer. The profile folder falls back to what `me3 info` last
    reported (cached in settings), then to me3's default. Returns what is in effect."""
    global ME3_OVERRIDE, GAME_EXE_OVERRIDE, PROFILE_DIR_OVERRIDE
    s = load_settings() if settings is None else settings
    me3 = str(s.get("me3_path") or "").strip()
    game = str(game_setting(s, GAME.key, "game_exe") or "").strip()
    prof = (
        str(s.get("me3_profile_dir") or "").strip()
        or str((s.get("me3_info_cache") or {}).get("profile_dir") or "").strip()
    )
    ME3_OVERRIDE = me3 or None
    GAME_EXE_OVERRIDE = game or None
    PROFILE_DIR_OVERRIDE = prof or None
    _DETECT_CACHE.clear()  # Steam/me3/game folders may now resolve differently
    return {"me3": me3, "game_exe": game, "profile_dir": prof}


# Detection (Steam libraries, the game folder, me3.exe) scans PATH and the disk. The answers are stable within a
# session, but Setup.summary()/problems() ask for them many times per game-tab switch, so they are memoised here and
# cleared whenever an override changes (apply_overrides) or a Locations refresh happens.
_DETECT_CACHE: dict = {}


def _detected(key, compute):
    if key not in _DETECT_CACHE:
        _DETECT_CACHE[key] = compute()
    return _DETECT_CACHE[key]


def clear_detection_cache() -> None:
    _DETECT_CACHE.clear()


def set_game(game: games.Game | str, settings: dict | None = None) -> games.Game:
    """Make `game` the one every lookup answers for, and load its own location overrides."""
    global GAME
    GAME = game if isinstance(game, games.Game) else games.get(game)
    apply_overrides(settings)
    return GAME


def game_exe_name():
    return Path(GAME_EXE_OVERRIDE).name if GAME_EXE_OVERRIDE else GAME.exe


def game_running():
    return any(kb >= REAL_GAME_MIN_KB for _, kb in processes(game_exe_name()))


def dead_game_shells():
    """Leftover zero-memory copies of the game. A Windows problem; Proton cleans up after itself."""
    if not IS_WINDOWS:
        return []
    return [pid for pid, kb in processes(game_exe_name()) if kb < REAL_GAME_MIN_KB]


# ------------------------------------------------------------------- steam


def _reg_value(subkey, name):
    if not IS_WINDOWS:
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def _linux_steam_roots():
    home = Path.home()
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    return [
        data / "Steam",
        home / ".steam" / "steam",
        home / ".steam" / "root",
        home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",  # Flatpak
    ]


def _flatpak_steam() -> bool:
    return (Path.home() / ".var" / "app" / "com.valvesoftware.Steam").is_dir() and shutil.which("steam") is None


def steam_exe():
    if IS_WINDOWS:
        value = _reg_value(r"Software\Valve\Steam", "SteamExe")
        return Path(value) if value else None
    found = shutil.which("steam")
    return Path(found) if found else None


def steam_launch_command() -> list[str] | None:
    """How to start the Steam client, or None when it cannot be found."""
    if IS_LINUX and _flatpak_steam() and shutil.which("flatpak"):
        return ["flatpak", "run", "com.valvesoftware.Steam"]
    exe = steam_exe()
    return [str(exe)] if exe and exe.exists() else None


def steam_process_name() -> str:
    return "steam.exe" if IS_WINDOWS else "steam"


def steam_running() -> bool:
    return bool(processes(steam_process_name()))


def steam_root():
    if IS_WINDOWS:
        value = _reg_value(r"Software\Valve\Steam", "SteamPath")
        if value:
            return Path(value)
        exe = steam_exe()
        return exe.parent if exe else None
    return next((r.resolve() for r in _linux_steam_roots() if (r / "steamapps").is_dir()), None)


def _linux_active_user():
    """Steam on Linux mirrors its registry into ~/.steam/registry.vdf; ActiveUser is 0 while signed out."""
    for vdf in (Path.home() / ".steam" / "registry.vdf", Path.home() / ".steam" / "steam" / "registry.vdf"):
        try:
            m = re.search(r'"ActiveUser"\s+"(\d+)"', vdf.read_text(errors="ignore"))
        except OSError:
            continue
        if m:
            return int(m.group(1))
    return None


def steam_logged_in():
    if IS_WINDOWS:
        # Steam keeps the signed-in account id here; 0 while logged out or still starting up.
        return bool(_reg_value(r"Software\Valve\Steam\ActiveProcess", "ActiveUser"))
    return bool(_linux_active_user())


def steam_libraries():
    """Every Steam library root on this machine, the install itself first (cached for the session)."""
    return _detected("steam_libraries", _steam_libraries)


def _steam_libraries():
    roots = []
    root = steam_root()
    if root:
        roots.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            for line in vdf.read_text(errors="ignore").splitlines():
                line = line.strip()
                if line.startswith('"path"'):
                    value = line[len('"path"') :].strip().strip('"')
                    roots.append(Path(value.replace("\\\\", "\\") if IS_WINDOWS else value))
    guesses = (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam") if IS_WINDOWS else _linux_steam_roots()
    roots.extend(Path(g) for g in guesses)
    seen, unique = set(), []
    for r in roots:
        key = str(r).lower() if IS_WINDOWS else str(r)
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def game_dir():
    if GAME_EXE_OVERRIDE and Path(GAME_EXE_OVERRIDE).is_file():
        return Path(GAME_EXE_OVERRIDE).parent
    return installed_dir(GAME)


def installed_dir(game: games.Game):
    """The folder with this game's exe in any Steam library, or None (cached per game for the session)."""

    def find():
        for root in steam_libraries():
            candidate = root / "steamapps" / "common" / Path(game.install_dir)
            if (candidate / game.exe).exists():
                return candidate
        return None

    return _detected(("installed_dir", game.key), find)


def regulation_bin():
    game = game_dir()
    if game and (game / "regulation.bin").exists():
        return game / "regulation.bin"
    return None


# ------------------------------------------------------------------- saves


def save_roots(game: games.Game | None = None) -> list[Path]:
    """Folders that hold the per-account save folders: %APPDATA%\\<game> on Windows, the same folder inside the
    game's Proton prefix on Linux (in whichever Steam library the prefix lives)."""
    game = game or GAME
    if IS_WINDOWS:
        appdata = os.environ.get("APPDATA")
        return [Path(appdata) / game.save_dir] if appdata else []
    roaming = Path("pfx") / "drive_c" / "users" / "steamuser" / "AppData" / "Roaming" / game.save_dir
    roots: list[Path] = []
    for lib in steam_libraries():
        candidate = lib / "steamapps" / "compatdata" / game.app_id / roaming
        if candidate.is_dir() and candidate.resolve() not in [r.resolve() for r in roots]:
            roots.append(candidate)
    return roots


# Save names a setup configures beyond the defaults (me3's savefile, Seamless Co-op's save_file_extension), per game.
# The window and the Play session set them from the setup in use, so those files are listed and repaired too.
_SETUP_SAVE_NAMES: dict[str, dict[str, str]] = {}


def set_setup_save_names(game: games.Game, names: dict[str, str]) -> None:
    """names: role -> file name, e.g. {"standard": "ER0000.sl2", "coop": "ER0000.co3"}."""
    _SETUP_SAVE_NAMES[game.key] = {k: v for k, v in names.items() if v}


def setup_save_names(game: games.Game | None = None) -> dict[str, str]:
    return dict(_SETUP_SAVE_NAMES.get((game or GAME).key) or {})


def save_names(game: games.Game | None = None) -> list[str]:
    """The default names (ER0000.sl2, ER0000.co2) and any the current setup configures, without repeats."""
    game = game or GAME
    out = []
    for n in (*game.save_names, *setup_save_names(game).values()):
        if n.lower() not in (x.lower() for x in out):
            out.append(n)
    return out


def save_files(game: games.Game | None = None):
    """Every save the game or the current setup uses (ER0000.sl2 / ER0000.co2, plus any name the setup configures)
    in the game's save folders, one folder per Steam account."""
    game = game or GAME
    names = save_names(game)
    found = []
    for root in save_roots(game):
        for profile in sorted(root.glob("*")):
            if profile.is_dir():
                found.extend(p for p in (profile / n for n in names) if p.exists())
    return found


# --------------------------------------------------------------------- me3


def me3_exe():
    """The me3 set in the launcher's settings, else me3 on PATH, else its default per-user install location.
    The PATH search and default-folder check are cached for the session (cleared when an override changes)."""
    if ME3_OVERRIDE and Path(ME3_OVERRIDE).is_file():
        return Path(ME3_OVERRIDE)
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


def me3_profiles_dir():
    if PROFILE_DIR_OVERRIDE and Path(PROFILE_DIR_OVERRIDE).is_dir():
        return Path(PROFILE_DIR_OVERRIDE)
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


def me3_profiles(game: games.Game | None = None):
    """User-made .me3 profiles for the game (the *-default.me3 ones me3 generates are skipped). A profile that names
    no game in [[supports]] counts for Elden Ring, the only game older profiles were written for."""
    game = game or GAME
    root = me3_profiles_dir()
    if not root or not root.exists():
        return []
    return sorted(
        (
            p
            for p in _iter_me3_files(root)
            if not p.name.endswith("-default.me3") and game.key in (profile_games(p) or (games.ELDEN_RING.key,))
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
