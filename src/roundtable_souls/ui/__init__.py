"""The window (PySide6 with Fluent widgets), the only package that imports Qt: shell (the window: title bar, game
switcher, navigation, Activity, job status), pages (each page's view), widgets and dialogs by kind, theme, find (the
editor's find bar) and jobs (the window's side of services/jobs.py)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from roundtable_souls.ui import (
        dialogs,
        find,
        jobs,
        pages,
        shell,
        theme,
        widgets,
    )

__all__ = [
    "dialogs",
    "find",
    "jobs",
    "pages",
    "shell",
    "theme",
    "widgets",
]
