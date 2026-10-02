"""The launcher settings and install facts the window reads and writes (the file itself: config.settings)."""

from roundtable_souls.config.settings import (
    FROZEN,
    data_dir,
    exe_dir,
    game_setting,
    launch_target,
    load_settings,
    save_game_settings,
    save_settings,
)
from roundtable_souls.platform.paths import PATH_SETTINGS, apply_overrides

__all__ = [
    "FROZEN",
    "data_dir",
    "exe_dir",
    "game_setting",
    "launch_target",
    "load_settings",
    "save_game_settings",
    "save_settings",
    "PATH_SETTINGS",
    "apply_overrides",
]
