"""The window (PySide6 with Fluent widgets): shell (the window), its widgets, theme and dialogs, and jobs (the window's side
of services/jobs.py). The only package that imports Qt."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from roundtable_souls.ui import (
        activity,
        config_files,
        dialogs,
        editor,
        find,
        install_dialog,
        jobs,
        notes,
        save_dialogs,
        shell,
        theme,
        widgets,
    )

__all__ = [
    "activity",
    "config_files",
    "dialogs",
    "editor",
    "find",
    "install_dialog",
    "jobs",
    "notes",
    "save_dialogs",
    "shell",
    "theme",
    "widgets",
]
