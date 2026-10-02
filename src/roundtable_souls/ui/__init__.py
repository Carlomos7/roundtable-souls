"""The window (PySide6 with Fluent widgets): window, its widgets, theme and dialogs. The only package that
imports Qt."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from roundtable_souls.ui import (
        activity,
        config_files,
        dialogs,
        editor,
        find,
        install_dialog,
        notes,
        save_dialogs,
        theme,
        widgets,
        window,
    )

__all__ = [
    "activity",
    "config_files",
    "dialogs",
    "editor",
    "find",
    "install_dialog",
    "notes",
    "save_dialogs",
    "theme",
    "widgets",
    "window",
]
