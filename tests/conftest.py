"""Shared fixtures: an isolated settings file and data folder so tests never read or write the developer's own
(backups, the save library, deleted profiles), and no item names from whatever mods happen to be installed on the
machine running the tests (tests that read names build their own)."""

from pathlib import Path

import pytest

from roundtable_souls import folders, games, settings
from roundtable_souls.mods import item_names
from roundtable_souls.system import common


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "settings_path", lambda: tmp_path / "launcher_settings.json")
    monkeypatch.setattr(folders, "data_root", lambda: tmp_path / "launcher-data")
    # Moving older folders into the data folder only ever happens inside this test's own folder: a test that builds
    # the real window sees the developer's real saves and profiles, and must never move anything out of them.
    for name in ("adopt_legacy_save_folders", "adopt_legacy_profile_folders"):
        real = getattr(folders, name)

        def guarded(folder, *args, _real=real, **kwargs):
            if tmp_path.resolve() in Path(folder).resolve().parents:
                return _real(folder, *args, **kwargs)
            return None

        monkeypatch.setattr(folders, name, guarded)
    folders._adopted.clear()
    settings.get_settings.cache_clear()
    yield
    settings.get_settings.cache_clear()
    folders._adopted.clear()


@pytest.fixture(autouse=True)
def installed_me3_not_asked(monkeypatch):
    """A rebuild records the installed me3's version by running it: tests never run the developer's me3."""
    from roundtable_souls.mods.backends import builtin

    monkeypatch.setattr(builtin, "_me3_version", lambda: "0.13.0")


@pytest.fixture(autouse=True)
def run_in_a_temporary_folder(tmp_path, monkeypatch):
    """Every test runs from its own temporary folder, never the repository: a relative path gone wrong (an empty path
    is the current folder) can then only reach that folder."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def recycle_bin_left_clean(monkeypatch):
    """Removing a mod sends its folder to the real Recycle Bin: every item a test sends there is purged after it,
    so the bin is left as it was."""
    from roundtable_souls.system import trash

    made = []
    real = trash.send

    def send(path):
        rec = real(path)
        made.append(rec)
        return rec

    monkeypatch.setattr(trash, "send", send)
    yield
    for rec in made:
        trash.purge(rec)


@pytest.fixture(autouse=True)
def clean_logging():
    """No job, sink or standalone run survives a test, so one test's lines never reach another's files."""
    from roundtable_souls.system import logging as run_logging

    yield
    job = run_logging.current_job()
    if job is not None:
        run_logging.end_job(job)
    if run_logging._standalone is not None:
        run_logging.end_job(run_logging._standalone)
        run_logging._standalone = None
    run_logging.detach_sink()
    run_logging._dir_override = None


@pytest.fixture(autouse=True)
def no_installed_mod_names(request, monkeypatch):
    if request.module.__name__.endswith("test_gamefiles"):
        return
    monkeypatch.setattr(item_names, "item_names", lambda refresh=False: item_names.ItemNames({}))


@pytest.fixture(autouse=True)
def elden_ring_is_the_active_game():
    """Every test starts on Elden Ring, with no detection cached from a prior test that used a different environment."""
    common.GAME = games.DEFAULT
    common.clear_detection_cache()
    common._PROFILE_GAMES_CACHE.clear()
    common._SETUP_SAVE_NAMES.clear()
    yield
    common.GAME = games.DEFAULT
    common.clear_detection_cache()
    common._PROFILE_GAMES_CACHE.clear()
    common._SETUP_SAVE_NAMES.clear()
