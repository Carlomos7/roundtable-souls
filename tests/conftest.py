"""Shared fixtures: an isolated settings file so tests never read or write the developer's own."""

import pytest

from roundtable_souls import settings


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "settings_path", lambda: tmp_path / "launcher_settings.json")
    settings.get_settings.cache_clear()
    yield
    settings.get_settings.cache_clear()
