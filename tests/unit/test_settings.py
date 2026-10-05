"""The pydantic settings file: defaults, tolerance of broken files, unknown keys kept, atomic merge."""

import json

from roundtable_souls.config import settings


def test_defaults_when_missing_or_broken(tmp_path):
    assert settings.load_settings().theme == "dark"
    settings.settings_path().write_text("{not json", encoding="utf-8")
    assert settings.load_settings().play_repair_after is True


def test_save_merges_and_keeps_unknown_keys():
    settings.settings_path().write_text(json.dumps({"future_key": 1, "theme": "light"}), encoding="utf-8")
    settings.save_settings(play_show_logos=True)
    on_disk = json.loads(settings.settings_path().read_text(encoding="utf-8"))
    assert on_disk["future_key"] == 1 and on_disk["theme"] == "light" and on_disk["play_show_logos"] is True
    assert not settings.settings_path().with_suffix(".json.tmp").exists()


def test_invalid_value_falls_back_to_default_for_that_key():
    settings.settings_path().write_text(json.dumps({"theme": "purple", "me3_path": "x"}), encoding="utf-8")
    loaded = settings.load_settings()
    assert loaded.theme == "dark" and loaded.me3_path == "x"


def test_the_file_keeps_its_keys():
    """An older build restored by the update watchdog reads the same flat file: a save writes back every key it
    had (another build's included), and the keys declared later only once something sets them."""
    old = settings.LauncherSettings().model_dump()
    for key in settings.WRITTEN_WHEN_SET:
        old.pop(key)
    old["from_a_newer_build"] = {"x": 1}
    settings.settings_path().write_text(json.dumps(old), encoding="utf-8")
    settings.save_settings(theme="light")
    written = json.loads(settings.settings_path().read_text(encoding="utf-8"))
    assert set(written) == set(old) and written["theme"] == "light" and written["from_a_newer_build"] == {"x": 1}
    settings.save_settings(update_blocked=["9.9.9"])
    written = json.loads(settings.settings_path().read_text(encoding="utf-8"))
    assert written["update_blocked"] == ["9.9.9"] and "inno_migration" not in written
    assert settings.load_settings().update_blocked == ["9.9.9"]
