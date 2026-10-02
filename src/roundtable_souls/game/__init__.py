"""The installed game: which games the launcher knows (catalog), its configuration from data/games (config), its
own packed archives (archives) and its Oodle library (oodle)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from roundtable_souls.game import (
        archives,
        catalog,
        config,
        oodle,
    )

__all__ = [
    "archives",
    "catalog",
    "config",
    "oodle",
]
