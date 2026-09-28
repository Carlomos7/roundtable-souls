"""Shared fixtures: an isolated settings file so tests never read or write the developer's own, and no item names from
whatever mods happen to be installed on the machine running the tests (tests that read names build their own)."""

import pytest

from roundtable_souls import games, settings
from roundtable_souls.mods import item_names
from roundtable_souls.system import common


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "settings_path", lambda: tmp_path / "launcher_settings.json")
    settings.get_settings.cache_clear()
    yield
    settings.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def no_installed_mod_names(request, monkeypatch):
    if request.module.__name__.endswith("test_gamefiles"):
        return
    monkeypatch.setattr(item_names, "item_names", lambda refresh=False: item_names.ItemNames({}))


@pytest.fixture(autouse=True)
def elden_ring_is_the_active_game():
    """Every test starts on Elden Ring, and one that switches games cannot leak the switch into the next."""
    common.GAME = games.DEFAULT
    yield
    common.GAME = games.DEFAULT
