"""roundtable.json: the launcher's decisions about a profile kept beside it, so they travel with the folder."""

import json
import shutil

from test_mod_merge import World

from roundtable_souls.config import settings
from roundtable_souls.mods import profile_settings
from roundtable_souls.mods import rebuild as merge


def test_settings_round_trip_and_keep_what_this_version_does_not_know(tmp_path):
    prof = tmp_path / "p.me3"
    prof.write_text("")
    file = tmp_path / "roundtable.json"
    file.write_text(
        json.dumps({"schema": 1, "future": {"x": 1}, "profiles": {"p.me3": {"later": 2}, "other.me3": {"y": 3}}})
    )
    profile_settings.update(prof, after_overlay=["a"])
    data = json.loads(file.read_text(encoding="utf-8"))
    assert data["future"] == {"x": 1} and data["profiles"]["other.me3"] == {"y": 3}
    assert data["profiles"]["p.me3"] == {"later": 2, "after_overlay": ["a"]}
    assert profile_settings.load(prof) == {"later": 2, "after_overlay": ["a"]}
    profile_settings.update(prof, after_overlay=None)
    assert profile_settings.load(prof) == {"later": 2}
    assert not (tmp_path / "roundtable.json.tmp").exists()


def test_a_newer_schema_is_kept(tmp_path):
    prof = tmp_path / "p.me3"
    prof.write_text("")
    (tmp_path / "roundtable.json").write_text(json.dumps({"schema": 7, "profiles": {}}))
    profile_settings.update(prof, after_overlay=["a"])
    assert json.loads((tmp_path / "roundtable.json").read_text())["schema"] == 7


def test_an_unreadable_file_is_left_alone_and_the_launchers_setting_is_used(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    file = w.base / "roundtable.json"
    file.write_text("{ not json", encoding="utf-8")
    note = merge.set_overlay_override(w.profile, w.winner)
    assert note and "launcher's own settings" in note
    assert file.read_text(encoding="utf-8") == "{ not json"
    assert profile_settings.problem(w.profile) and profile_settings.load(w.profile) == {}
    assert merge.overlay_mark(w.profile)["package"] == w.winner


def test_a_mark_from_before_3_10_moves_into_roundtable_json(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    settings.save_settings(parameter_overlays={merge._key(w.profile): {"package": str(w.winner), "rebuild": None}})
    mark = merge.overlay_mark(w.profile)
    assert mark["package"] == w.winner
    stored = profile_settings.load(w.profile)["overlay"]
    assert stored == {"package": "Merger/mod", "rebuild": None}  # relative: it travels with the folder
    merge.set_overlay_override(w.profile, None)
    assert profile_settings.load(w.profile)["overlay"] is None and merge.overlay_mark(w.profile) is None
    assert merge._key(w.profile) not in (settings.load_settings().parameter_overlays or {})


def test_a_copied_profile_folder_resolves_the_same_way(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    rebuild = w.base / "Merger" / "rebuild.json"
    rebuild.write_text("{}")
    merge.set_overlay_override(w.profile, w.winner, rebuild)
    copy = tmp_path / "elsewhere" / "er"
    shutil.copytree(w.base, copy)
    mark = merge.overlay_mark(copy / "p.me3")
    assert mark == {"package": copy / "Merger" / "mod", "rebuild": copy / "Merger" / "rebuild.json"}


def test_a_folder_that_cannot_be_written_falls_back_to_the_launchers_setting(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)

    def refuse(*a, **k):
        raise PermissionError("read-only")

    monkeypatch.setattr(profile_settings, "update", refuse)
    note = merge.set_overlay_override(w.profile, w.winner)
    assert "read-only" in note
    assert merge.overlay_mark(w.profile)["package"] == w.winner
