"""Where the game is, for the rebuild code: the one value the mods layer is given instead of being handed it call by
call.

Detecting a rebuild tool fills its {game_dir}/{game_exe}/{me3} placeholders, and the profile is checked for that
on every write, so passing Locations down every mods call would reach almost every function. Until Phase 6 reshapes
the rebuild backends, the app context gives this module the Locations of the game the window shows (use()), and
the rebuild code, its backends and the conflicts overview read it here (get()).
"""

from __future__ import annotations

from roundtable_souls.game.locate import Locations

_LOCATIONS: Locations | None = None


def use(loc: Locations | None) -> None:
    """The game's locations from now on (app.AppContext calls this whenever they change; None forgets them)."""
    global _LOCATIONS
    _LOCATIONS = loc


def get() -> Locations:
    if _LOCATIONS is None:
        raise RuntimeError("the mods layer was not given the game's locations (app.create_app gives them)")
    return _LOCATIONS
