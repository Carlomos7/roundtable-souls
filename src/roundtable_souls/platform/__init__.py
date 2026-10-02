"""This machine: where things are (paths: the game, its saves, me3; data_folder: the launcher's own folder;
steam), what runs (proc, processes), the play session's steps (session), logging and the jobs index
(logging), single-instance and file locks (instance, filelock), files, trash, desktop, me3_info and
steam_shortcuts. The bottom layer: nothing here imports the launcher's other packages, except the
settings reads the app context replaces."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from roundtable_souls.platform import (
        data_folder,
        desktop,
        filelock,
        files,
        instance,
        logging,
        me3_info,
        paths,
        proc,
        processes,
        session,
        steam,
        steam_shortcuts,
        trash,
    )

__all__ = [
    "data_folder",
    "desktop",
    "filelock",
    "files",
    "instance",
    "logging",
    "me3_info",
    "paths",
    "proc",
    "processes",
    "session",
    "steam",
    "steam_shortcuts",
    "trash",
]
