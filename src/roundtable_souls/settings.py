"""Launcher settings: a validated JSON file next to the exe, or under the user's app data when that is not writable."""

from __future__ import annotations

import json
import os
import sys
import threading
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from roundtable_souls.system import filelock

FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR_NAME = "RoundtableSouls"
LEGACY_APP_DIR_NAMES = ("Roundtable",)


def exe_dir() -> Path:
    if FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _writable(folder: Path) -> bool:
    try:
        probe = folder / ".write-test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def is_installed() -> bool:
    """Installed by the setup (its uninstaller sits beside the exe), as opposed to unzipped as a portable copy."""
    return FROZEN and (exe_dir() / "unins000.exe").is_file()


def data_dir() -> Path:
    """Where launcher_settings.json and logs live. A portable copy keeps them beside the exe; an installed copy, or a
    portable one in a folder it cannot write, keeps them in %LOCALAPPDATA%\\RoundtableSouls (migrated once from
    older folder names)."""
    here = exe_dir()
    if not is_installed() and _writable(here):
        return here
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    new = root / APP_DIR_NAME
    if not new.exists():
        for legacy in LEGACY_APP_DIR_NAMES:
            old = root / legacy
            if old.is_dir():
                try:
                    old.rename(new)
                    break
                except OSError:
                    pass
    new.mkdir(parents=True, exist_ok=True)
    return new


class LauncherSettings(BaseModel):
    """Everything the window remembers between runs. Unknown keys are kept so older builds' values survive."""

    model_config = ConfigDict(extra="allow")

    setup: str | None = None  # Elden Ring's remembered setup; other games keep theirs under `games`
    game: str = "eldenring"  # the tab the window opens on
    games: dict[str, dict[str, Any]] = Field(default_factory=dict)  # per-game values for games other than Elden Ring
    theme: Literal["dark", "light"] = "dark"
    logo: Literal["auto", "dark", "light"] = "auto"
    native_configs: dict[str, list[str]] = Field(default_factory=dict)  # DLL path -> settings files tied to it
    parameter_overlays: dict[str, Any] = Field(default_factory=dict)  # profile -> {package, rebuild} set in Options
    rebuild_approved: list[str] = Field(default_factory=list)  # rebuild tools the user allowed to run
    activity_seen: float = 0.0  # when the Activity page was last looked at: failures after it are counted

    offline_strip_revive: bool = False
    offline_start_steam: bool = True
    offline_skip_confirm: bool = False

    play_update_merge: bool = True
    build_merges: bool = False
    play_backup_before: bool = False
    play_repair_after: bool = True
    play_clear_before: bool = True
    play_clear_after: bool = True
    warn_dead_shells: bool = True
    play_boot_boost: bool = True
    play_show_logos: bool = False
    play_diagnostics: bool = False
    check_me3_updates: bool = True
    check_launcher_updates: bool = True

    me3_path: str = ""
    game_exe: str = ""
    me3_profile_dir: str = ""

    me3_latest: dict[str, Any] | None = None
    me3_latest_checked: float = 0.0
    me3_info_cache: dict[str, str] = Field(default_factory=dict)
    launcher_latest: dict[str, Any] | None = None  # the newest release GitHub named, for launcher_channel
    launcher_latest_checked: float = 0.0  # when GitHub last answered (a 304 counts)
    launcher_latest_etag: str = ""  # sent back as If-None-Match; a 304 does not count against GitHub's hourly limit
    launcher_update_skipped: str = ""
    launcher_channel: Literal["stable", "beta"] = "stable"  # beta also offers pre-releases
    launcher_check_failures: int = 0  # failed checks in a row; each one doubles the wait before the next
    launcher_next_check: float = 0.0  # no automatic check before this (after failures, or GitHub's limit)
    launcher_check_error: str = ""  # why the last check failed, shown on Settings; empty after a good one
    launcher_advisory: dict[str, Any] | None = None  # the project's minimum-version notice, as last fetched
    launcher_advisory_etag: str = ""
    launcher_advisory_checked: float = 0.0
    update_pending: dict[str, Any] | None = None  # an update handed to the setup or a new exe, until it is confirmed
    update_result: dict[str, Any] | None = None  # how the last update went, shown once on the next start


def settings_path() -> Path:
    return data_dir() / "launcher_settings.json"


def load_settings() -> dict[str, Any]:
    """The settings as a plain dict (validated, defaults filled). A broken file yields the defaults."""
    try:
        raw = json.loads(settings_path().read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except OSError, ValueError:
        raw = {}
    try:
        return LauncherSettings.model_validate(raw).model_dump()
    except ValidationError as e:
        bad = {err["loc"][0] for err in e.errors() if err["loc"]}
        clean = {k: v for k, v in raw.items() if k not in bad}
        return LauncherSettings.model_validate(clean).model_dump()


_WRITE_LOCK = threading.RLock()  # threads of this process; the lock file covers other processes
_tmp_count = 0


def _write(values: dict[str, Any]) -> None:
    global _tmp_count
    model = LauncherSettings.model_validate(values)
    path = settings_path()
    _tmp_count += 1
    tmp = path.with_name(f"{path.name}.{os.getpid()}-{_tmp_count}.tmp")  # never shared with another writer
    try:
        tmp.write_text(json.dumps(model.model_dump(), indent=1), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def change_settings(change: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    """Read, change and write the file as one step: change(current) returns the keys to set. No other thread or
    launcher process writes in between, so a value computed from the current one (a counter) is never lost.
    Returns the settings as written."""
    with _WRITE_LOCK, filelock.locked(settings_path()):
        current = load_settings()
        current.update(change(dict(current)))
        _write(current)
        return current


def save_settings(**changes: Any) -> None:
    """Merge changes into the file, atomically, without losing another thread's or process's change."""
    change_settings(lambda current: changes)


GAME_KEYS = ("setup", "game_exe")  # values each game keeps for itself


def game_setting(settings: dict[str, Any], game: str, key: str, default: Any = None) -> Any:
    """One per-game value. Elden Ring's live at the top level, where builds before multi-game support kept them, so
    an older build still finds them; every other game keeps its own under `games`."""
    if game == "eldenring":
        value = settings.get(key)
    else:
        value = ((settings.get("games") or {}).get(game) or {}).get(key)
    return default if value is None else value


def save_game_settings(game: str, **changes: Any) -> None:
    """Merge per-game values for one game into the file."""
    if game == "eldenring":
        save_settings(**changes)
        return
    current = load_settings()
    games = dict(current.get("games") or {})
    games[game] = {**(games.get(game) or {}), **changes}
    save_settings(games=games)


@lru_cache
def get_settings() -> LauncherSettings:
    """Cached typed view for code that only reads. Call get_settings.cache_clear() after save_settings()."""
    return LauncherSettings.model_validate(load_settings())
