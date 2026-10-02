"""The application's context: one place that holds what the launcher's code used to read from module globals.

create_app() builds it when the program starts (cli.main, or the window when a test builds one on its own), never at
import time. It holds the build's identity, the settings as last read, the game the window shows (or --game asked
for) and that game's Locations; code is handed what it needs from it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from roundtable_souls.config import identity
from roundtable_souls.config.settings import LauncherSettings, data_dir, load_settings
from roundtable_souls.game import catalog
from roundtable_souls.game.locate import Locations
from roundtable_souls.platform import paths


@dataclass
class AppContext:
    identity: identity.Identity
    settings: LauncherSettings
    game: catalog.Game
    locations: Locations
    data_dir: Path

    def reload_settings(self) -> LauncherSettings:
        """Read the settings file again (another part of the program, or another process, changed it) and apply its
        location overrides."""
        self.settings = load_settings()
        names = self.locations.setup_save_names
        self.locations = Locations.from_settings(self.settings, self.game).with_setup_save_names(names)
        paths.clear_detection_cache()  # Steam/me3/game folders may now resolve differently
        paths.set_game(self.game, self.settings)  # until every caller is handed its Locations
        return self.settings

    def select_game(self, game: catalog.Game | str) -> Locations:
        """Make game the one the window shows: its own location overrides, no setup save names yet."""
        self.game = game if isinstance(game, catalog.Game) else catalog.get(game)
        self.settings = load_settings()
        self.locations = Locations.from_settings(self.settings, self.game)
        paths.clear_detection_cache()
        paths.set_game(self.game, self.settings)  # until every caller is handed its Locations
        return self.locations

    def note_setup_saves(self, names: Mapping[str, str]) -> Locations:
        """The setup in use names its own save files (role -> file name): they are listed and repaired too."""
        self.locations = self.locations.with_setup_save_names(names)
        paths.set_setup_save_names(self.game, dict(names))  # until every caller is handed its Locations
        return self.locations


def create_app(start_game: catalog.Game | None = None) -> AppContext:
    """The context for one run: the game is start_game (--game), else the tab the window last showed."""
    settings = load_settings()
    game = start_game or catalog.get(settings.game)
    ctx = AppContext(identity.get(), settings, game, Locations.from_settings(settings, game), data_dir())
    paths.set_game(game, settings)  # until every caller is handed its Locations
    return ctx
