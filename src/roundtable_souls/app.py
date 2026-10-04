"""The application's context: one place that holds what the launcher's code used to read from module globals.

create_app() builds it when the program starts (cli.main, or a test), never at import time. It holds the build's
identity, the settings as last read, the game the window shows (or --game asked for) and that game's Locations; code
is handed what it needs from it. use_data_folder() runs first of all (the command line calls it before logging
starts): the platform layer is told the data folder and the build's instance scope instead of reading the settings.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from roundtable_souls.config import identity
from roundtable_souls.config.settings import LauncherSettings, data_dir, load_settings
from roundtable_souls.game import catalog
from roundtable_souls.game.locate import Locations
from roundtable_souls.mods import locations as mod_locations
from roundtable_souls.platform import data_folder, instance, paths


@dataclass
class AppContext:
    identity: identity.Identity
    settings: LauncherSettings
    game: catalog.Game
    locations: Locations
    data_dir: Path

    def _located(self, loc: Locations) -> Locations:
        self.locations = loc
        mod_locations.use(loc)  # the rebuild code's one injected value, until Phase 6 hands it Locations
        return loc

    def reload_settings(self) -> LauncherSettings:
        """Read the settings file again (another part of the program, or another process, changed it) and apply its
        location overrides."""
        self.settings = load_settings()
        names = self.locations.setup_save_names
        paths.clear_detection_cache()  # Steam/me3/game folders may now resolve differently
        self._located(Locations.from_settings(self.settings, self.game).with_setup_save_names(names))
        return self.settings

    def select_game(self, game: catalog.Game | str) -> Locations:
        """Make game the one the window shows: its own location overrides, no setup save names yet."""
        self.game = game if isinstance(game, catalog.Game) else catalog.get(game)
        self.settings = load_settings()
        paths.clear_detection_cache()
        return self._located(Locations.from_settings(self.settings, self.game))

    def note_setup_saves(self, names: Mapping[str, str]) -> Locations:
        """The setup in use names its own save files (role -> file name): they are listed and repaired too."""
        return self._located(self.locations.with_setup_save_names(names))


def use_data_folder() -> Path:
    """Tell the platform layer where the data folder is and scope the instance names to this build and folder."""
    data = data_dir()
    data_folder.use(data)
    instance.use_scope(identity.get().instance_prefix, data)
    return data


def create_app(start_game: catalog.Game | None = None) -> AppContext:
    """The context for one run: the game is start_game (--game), else the tab the window last showed."""
    data = use_data_folder()
    settings = load_settings()
    game = start_game or catalog.get(settings.game)
    ctx = AppContext(identity.get(), settings, game, Locations.from_settings(settings, game), data)
    mod_locations.use(ctx.locations)
    return ctx
