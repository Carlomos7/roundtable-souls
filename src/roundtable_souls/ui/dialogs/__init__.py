"""The window's dialogs: common (confirm, text, choices, versions, mod options, unsaved changes), saves (copy a
file or a character, swap from the library), install (installing a mod), config_files (a mod's settings files),
editor (the TOML / JSON editor), notes (how save findings read) and activity (the Activity page's view)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from roundtable_souls.ui.dialogs import (
        activity,
        common,
        config_files,
        editor,
        install,
        notes,
        saves,
    )

__all__ = [
    "activity",
    "common",
    "config_files",
    "editor",
    "install",
    "notes",
    "saves",
]
