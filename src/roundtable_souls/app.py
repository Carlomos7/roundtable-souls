"""The application's context: one place that holds what the launcher's code used to read from module globals.

create_app() builds it when the program starts (cli.main, or a test), never at import time. It holds the build's
identity, the settings as last read, the game the window shows (or --game asked for) and that game's Locations; code
is handed what it needs from it. use_data_folder() runs first of all (the command line calls it before logging
starts): the platform layer is told the data folder and the build's instance scope instead of reading the settings.

create_app() also opens the launcher's database (storage.db), migrating it first when needed. When storage is
refused for the run (storage.db.StorageUnavailable) the context has no database and says why; when a migration
fails, MigrationFailed reaches the caller, which must not report the version ready. With a database, the hash
cache and the activity log use it (once their old files' import is verified); without one, the hash cache is
bypassed and activity records stay in logs/jobs.jsonl. start_imports() runs those imports once the caller has
reported ready.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from roundtable_souls.config import identity
from roundtable_souls.config.settings import LauncherSettings, data_dir, load_settings
from roundtable_souls.game import catalog
from roundtable_souls.game.locate import Locations
from roundtable_souls.mods import locations as mod_locations
from roundtable_souls.mods import rebuild as mod_rebuild
from roundtable_souls.platform import data_folder, instance, paths
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.storage import db as storage_db
from roundtable_souls.storage.activity import ActivityLog
from roundtable_souls.storage.cache import HashCache
from roundtable_souls.storage.imports import run_imports


@dataclass
class AppContext:
    identity: identity.Identity
    settings: LauncherSettings
    game: catalog.Game
    locations: Locations
    data_dir: Path
    storage: storage_db.Database | None = field(default=None, repr=False)
    storage_problem: str = ""  # why there is no database this run, when there isn't
    hash_cache: HashCache | None = field(default=None, repr=False)
    activity: ActivityLog | None = field(default=None, repr=False)

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

    def start_imports(self) -> threading.Thread | None:
        """Import the old record files into the database in the background (storage.imports); call it only after
        reporting ready. None without a database."""
        if self.storage is None or self.hash_cache is None or self.activity is None:
            return None
        cache, activity = self.hash_cache, self.activity
        hashes, jobs = data_folder.data_root() / "cache" / "hashes.json", run_logging.log_dir() / run_logging.JOBS_INDEX
        thread = threading.Thread(
            target=run_imports,
            args=(hashes, jobs, cache, activity, run_logging.log),
            name="storage-imports",
            daemon=True,
        )
        thread.start()
        return thread

    def close(self) -> None:
        """Close the database (its connections and its shared lock); the process ending does the same. The hash
        cache and the activity log go back to their files."""
        if self.storage is not None:
            mod_rebuild.use_hash_store(None)
            run_logging.use_job_store(None)
            self.storage.close()
            self.storage = None

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
    try:
        ctx.storage = storage_db.open_database(data_folder.data_root())
    except storage_db.StorageUnavailable as e:
        ctx.storage_problem = str(e)
        run_logging.log(f"storage: {e}")
    if ctx.storage is not None:
        ctx.hash_cache = HashCache(ctx.storage, run_logging.log)
        ctx.activity = ActivityLog(ctx.storage, run_logging.log)
        mod_rebuild.use_hash_store(ctx.hash_cache)
        run_logging.use_job_store(ctx.activity)
    else:  # storage off for this run: no persistent hash cache; job records go to jobs.jsonl
        mod_rebuild.use_hash_store(None, file_in_use=False)
        run_logging.use_job_store(None)
    return ctx
