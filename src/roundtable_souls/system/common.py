"""Where things are on this machine (Steam, the game, the saves, me3) and what is running.

Nothing here writes to disk except the run log.
"""
import os
import subprocess
import sys
from pathlib import Path

from roundtable_souls.settings import data_dir
from roundtable_souls.system.logging import get_logger, start_run_log

LOGS_DIR = data_dir() / "logs"
LOG_FILE = LOGS_DIR / "last_run.log"

# A real game instance uses gigabytes. Failed launches leave dead eldenring.exe shells behind that sit
# under 1 MB with no threads; Steam counts those as "running", these tools do not.
REAL_GAME_MIN_KB = 100_000
# Child consoles must never pop up (the window has no console of its own).
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_log = get_logger("run")


# ----------------------------------------------------------------- logging

def log(msg=""):
    """One line to the run log (and to the window, when it is listening)."""
    _log.info("%s", msg)


def start_log(title):
    """Start a fresh last_run.log for one job."""
    start_run_log(LOGS_DIR, title, LOG_FILE.name)


def fail(msg, code=1):
    log(f"error: {msg}")
    sys.exit(code)


# --------------------------------------------------------------- processes

def processes(name):
    """(pid, working set in KB) for every process with this image name."""
    if os.name != "nt":
        return []
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV"],
                             capture_output=True, text=True, creationflags=NO_WINDOW).stdout
    except OSError:
        return []
    found = []
    for line in out.splitlines()[1:]:
        cols = [c.strip('"') for c in line.split('","')]
        if len(cols) >= 5 and cols[0].lower() == name.lower():
            digits = "".join(ch for ch in cols[4] if ch.isdigit())
            found.append((int(cols[1]), int(digits) if digits else 0))
    return found


# Optional overrides the launcher sets from its settings (blank = detect): a custom me3.exe, a custom game exe
# (me3 launches it with --exe), and a custom me3 profile folder.
ME3_OVERRIDE = None
GAME_EXE_OVERRIDE = None
PROFILE_DIR_OVERRIDE = None


def game_exe_name():
    return Path(GAME_EXE_OVERRIDE).name if GAME_EXE_OVERRIDE else "eldenring.exe"


def game_running():
    return any(kb >= REAL_GAME_MIN_KB for _, kb in processes(game_exe_name()))


def dead_game_shells():
    return [pid for pid, kb in processes(game_exe_name()) if kb < REAL_GAME_MIN_KB]


# ------------------------------------------------------------------- steam

def _reg_value(subkey, name):
    if os.name != "nt":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def steam_exe():
    value = _reg_value(r"Software\Valve\Steam", "SteamExe")
    return Path(value) if value else None


def steam_root():
    value = _reg_value(r"Software\Valve\Steam", "SteamPath")
    if value:
        return Path(value)
    exe = steam_exe()
    return exe.parent if exe else None


def steam_logged_in():
    # Steam keeps the signed-in account id here; 0 while logged out or still
    # starting up.
    value = _reg_value(r"Software\Valve\Steam\ActiveProcess", "ActiveUser")
    return bool(value)


def steam_libraries():
    """Every Steam library root on this machine, the install itself first."""
    roots = []
    root = steam_root()
    if root:
        roots.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            for line in vdf.read_text(errors="ignore").splitlines():
                line = line.strip()
                if line.startswith('"path"'):
                    value = line[len('"path"'):].strip().strip('"').replace("\\\\", "\\")
                    roots.append(Path(value))
    # Fallbacks for a machine where the registry is unhelpful.
    for guess in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
        roots.append(Path(guess))
    seen, unique = set(), []
    for r in roots:
        key = str(r).lower()
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def game_dir():
    if GAME_EXE_OVERRIDE and Path(GAME_EXE_OVERRIDE).is_file():
        return Path(GAME_EXE_OVERRIDE).parent
    for root in steam_libraries():
        candidate = root / "steamapps" / "common" / "ELDEN RING" / "Game"
        if (candidate / "eldenring.exe").exists():
            return candidate
    return None


def regulation_bin():
    game = game_dir()
    if game and (game / "regulation.bin").exists():
        return game / "regulation.bin"
    return None


# ------------------------------------------------------------------- saves

def save_files():
    """Every ER0000.sl2 / ER0000.co2 under %APPDATA%\\EldenRing."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return []
    found = []
    for profile in sorted((Path(appdata) / "EldenRing").glob("*")):
        if profile.is_dir():
            found.extend(p for p in (profile / "ER0000.sl2", profile / "ER0000.co2") if p.exists())
    return found


# --------------------------------------------------------------------- me3

def me3_exe():
    """The me3 set in the launcher's settings, else me3 on PATH, else its default per-user install location."""
    if ME3_OVERRIDE and Path(ME3_OVERRIDE).is_file():
        return Path(ME3_OVERRIDE)
    from shutil import which
    found = which("me3")
    if found:
        return Path(found)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidate = Path(local) / "Programs" / "garyttierney" / "me3" / "bin" / "me3.exe"
        if candidate.exists():
            return candidate
    return None


def me3_profiles_dir():
    if PROFILE_DIR_OVERRIDE and Path(PROFILE_DIR_OVERRIDE).is_dir():
        return Path(PROFILE_DIR_OVERRIDE)
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    return Path(local) / "garyttierney" / "me3" / "config" / "profiles"


def me3_profiles():
    """User-made .me3 profiles (the *-default.me3 ones me3 generates are skipped)."""
    root = me3_profiles_dir()
    if not root or not root.exists():
        return []
    return sorted(p for p in root.rglob("*.me3") if not p.name.endswith("-default.me3"))
