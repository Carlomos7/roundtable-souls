"""Launcher settings: a validated JSON file next to the exe, or under the user's app data when that is not writable."""

from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR_NAME = "RoundtableSouls"
LEGACY_APP_DIR_NAMES = ("Roundtable", "PlayEldenRing")


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


def data_dir() -> Path:
    """Where launcher_settings.json and logs live. Migrates from older folder names once."""
    here = exe_dir()
    if _writable(here):
        return here
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home())
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

    setup: str | None = None
    theme: Literal["dark", "light"] = "dark"
    logo: Literal["auto", "dark", "light"] = "auto"

    offline_strip_revive: bool = False
    offline_start_steam: bool = True
    offline_skip_confirm: bool = False

    play_backup_before: bool = False
    play_repair_after: bool = True
    play_clear_before: bool = True
    play_clear_after: bool = True
    warn_dead_shells: bool = True
    play_boot_boost: bool = True
    play_show_logos: bool = False
    play_diagnostics: bool = False
    check_me3_updates: bool = True

    tarnished_owned: Literal["auto", "yes", "no"] = "auto"
    dlc_owned: Literal["auto", "yes", "no"] = "auto"

    me3_path: str = ""
    game_exe: str = ""
    me3_profile_dir: str = ""

    me3_latest: dict[str, Any] | None = None
    me3_latest_checked: float = 0.0
    me3_info_cache: dict[str, str] = Field(default_factory=dict)


def settings_path() -> Path:
    return data_dir() / "launcher_settings.json"


def load_settings() -> dict[str, Any]:
    """The settings as a plain dict (validated, defaults filled). A broken file yields the defaults."""
    try:
        raw = json.loads(settings_path().read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except (OSError, ValueError):
        raw = {}
    try:
        return LauncherSettings.model_validate(raw).model_dump()
    except ValidationError as e:
        bad = {err["loc"][0] for err in e.errors() if err["loc"]}
        clean = {k: v for k, v in raw.items() if k not in bad}
        return LauncherSettings.model_validate(clean).model_dump()


def save_settings(**changes: Any) -> None:
    """Merge changes into the file, atomically."""
    current = load_settings()
    current.update(changes)
    model = LauncherSettings.model_validate(current)
    path = settings_path()
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(model.model_dump(), indent=1), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


@lru_cache
def get_settings() -> LauncherSettings:
    """Cached typed view for code that only reads. Call get_settings.cache_clear() after save_settings()."""
    return LauncherSettings.model_validate(load_settings())
