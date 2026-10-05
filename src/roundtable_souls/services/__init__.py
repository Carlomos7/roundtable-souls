"""What the window and the command line call, without Qt: play (setups and the play session), mods, saves,
coop, settings and updates, and jobs (background work and the logged jobs the Activity page lists)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from roundtable_souls.services import (
        coop,
        jobs,
        mods,
        play,
        saves,
        settings,
        updates,
    )

__all__ = [
    "coop",
    "jobs",
    "mods",
    "play",
    "saves",
    "settings",
    "updates",
]
