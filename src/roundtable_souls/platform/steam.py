"""Steam on this machine: where it is installed (registry on Windows; the usual folders, Flatpak included, on Linux),
its library folders, whether it runs and is signed in, and how to start it. Library lookups are cached for the
session; paths.clear_detection_cache() clears them with the rest."""

import os
import re
import shutil
import sys
from pathlib import Path

from roundtable_souls.platform import proc

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

_CACHE: dict = {}


def _detected(key, compute):
    if key not in _CACHE:
        _CACHE[key] = compute()
    return _CACHE[key]


def clear_cache() -> None:
    _CACHE.clear()


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
    return bool(proc.processes(steam_process_name()))


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
