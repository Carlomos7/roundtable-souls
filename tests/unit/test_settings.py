"""The pydantic settings file: defaults, tolerance of broken files, unknown keys kept, atomic merge."""

import json

from roundtable_souls.config import settings


def test_defaults_when_missing_or_broken(tmp_path):
    assert settings.load_settings()["theme"] == "dark"
    settings.settings_path().write_text("{not json", encoding="utf-8")
    assert settings.load_settings()["play_repair_after"] is True


def test_save_merges_and_keeps_unknown_keys():
    settings.settings_path().write_text(json.dumps({"future_key": 1, "theme": "light"}), encoding="utf-8")
    settings.save_settings(play_show_logos=True)
    on_disk = json.loads(settings.settings_path().read_text(encoding="utf-8"))
    assert on_disk["future_key"] == 1 and on_disk["theme"] == "light" and on_disk["play_show_logos"] is True
    assert not settings.settings_path().with_suffix(".json.tmp").exists()


def test_invalid_value_falls_back_to_default_for_that_key():
    settings.settings_path().write_text(json.dumps({"theme": "purple", "me3_path": "x"}), encoding="utf-8")
    loaded = settings.load_settings()
    assert loaded["theme"] == "dark" and loaded["me3_path"] == "x"
