"""What the window and the command line call, without Qt: play (setups and the play session), mods, saves,
coop, settings and updates."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from roundtable_souls.services import (
        coop,
        mods,
        play,
        saves,
        settings,
        updates,
    )

__all__ = [
    "coop",
    "mods",
    "play",
    "saves",
    "settings",
    "updates",
]
