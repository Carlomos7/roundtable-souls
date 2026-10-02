"""Play brings the merged mods up to date first: only when a merge exists and is out of date, never when a setup is
missing, keeping the previous result when it fails, and trimming a rebuild tool's backups afterwards."""

import json

import pytest
from test_mod_merge import World

from roundtable_souls import core
from roundtable_souls.mods import merge
from roundtable_souls.platform import paths as common


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def test_nothing_happens_when_the_merge_is_up_to_date(world):
    assert merge.health(world.profile)["state"] == "current"
    runs = world.runs
    assert merge.needs_update(world.profile) is None
    assert merge.update_before_play(world.profile, lambda s: None) is None
    assert world.runs == runs


def test_an_out_of_date_merge_is_rebuilt_before_play(world):
    world.pack("params")
    h = merge.needs_update(world.profile)
    assert h is not None and h["state"] == "stale"
    said = []
    out = merge.update_before_play(world.profile, said.append)
    assert out["undo"]["type"] == "rebuild"
    assert merge.health(world.profile)["state"] == "current"
    assert any("rebuilding first" in s for s in said)


def test_a_failed_update_raises_and_leaves_the_previous_result(world, monkeypatch):
    world.pack("params")
    before = (world.winner / "regulation.bin").read_bytes()
    monkeypatch.setattr("roundtable_souls.mods.backends.Tool.run", lambda b, log: world.fake_run(b, fail=True))
    with pytest.raises(merge.MergeError):
        merge.update_before_play(world.profile, lambda s: None)
    assert (world.winner / "regulation.bin").read_bytes() == before
    assert merge.health(world.profile)["state"] == "failed"
    assert merge.needs_update(world.profile) is not None  # still out of date: the next Play tries again


def test_a_missing_setup_is_not_rebuilt_play_only_warns(world):
    import shutil

    world.pack("params")
    shutil.rmtree(world.setup)
    assert merge.needs_update(world.profile) is None


def test_stacked_packs_without_a_merge_are_left_alone(tmp_path, monkeypatch):
    base = tmp_path / "p"
    for name in ("a", "b"):
        (base / "mod" / name).mkdir(parents=True)
        (base / "mod" / name / "regulation.bin").write_bytes(name.encode())
    prof = base / "p.me3"
    prof.write_text("[[packages]]\nid = \"a\"\npath = 'mod/a'\n\n[[packages]]\nid = \"b\"\npath = 'mod/b'\n")
    assert merge.health(prof)["state"] == "stacked"
    assert merge.needs_update(prof) is None  # making a combined package is the user's call


def test_only_the_newest_tool_backups_are_kept_after_an_automatic_rebuild(world, monkeypatch):
    from roundtable_souls.platform import trash

    if not trash.available():
        pytest.skip("no Recycle Bin here")
    import os

    for i in range(5):
        d = world.base / "Tool Backups" / f"old{i}"
        d.mkdir(parents=True)
        (d / "restore.json").write_text("{}")
        os.utime(d / "restore.json", (1_700_000_000 + i, 1_700_000_000 + i))
    world.pack("params")
    merge.update_before_play(world.profile, lambda s: None)
    left = sorted(p.name for p in (world.base / "Tool Backups").iterdir())
    assert left == ["old2", "old3", "old4"]


def test_play_without_the_window_updates_first_when_the_tool_is_allowed(world, monkeypatch):
    world.pack("params")
    setup = type("S", (), {"profile": str(world.profile)})()
    lines = []
    monkeypatch.setattr(common, "log", lines.append)
    assert core.update_merge_headless(setup) is None  # updated: the game may start
    assert merge.health(world.profile)["state"] == "current"
    assert any(l.startswith("done: merged mods updated") for l in lines)


def test_play_without_the_window_never_runs_a_tool_it_was_not_allowed_to(world, monkeypatch):
    world.pack("params")
    runs = world.runs
    monkeypatch.setattr(merge, "approved", lambda tool: False)
    lines = []
    monkeypatch.setattr(common, "log", lines.append)
    why = core.update_merge_headless(type("S", (), {"profile": str(world.profile)})())
    assert world.runs == runs and "has not been allowed" in why  # and so the game must not start


def test_play_without_the_window_does_not_start_when_the_update_fails(world, monkeypatch):
    world.pack("params")
    monkeypatch.setattr("roundtable_souls.mods.backends.Tool.run", lambda b, log: world.fake_run(b, fail=True))
    lines = []
    monkeypatch.setattr(common, "log", lines.append)
    why = core.update_merge_headless(type("S", (), {"profile": str(world.profile)})())
    assert why and why.startswith("The merged mods could not be updated")
    assert any(l.startswith("error: the merged mods could not be updated") for l in lines)


def test_play_without_the_window_asks_nothing_and_starts_nothing_when_automatic_rebuilds_are_off(world, monkeypatch):
    world.pack("params")
    runs = world.runs
    monkeypatch.setattr(common, "log", lambda s: None)
    why = core.update_merge_headless(type("S", (), {"profile": str(world.profile)})(), automatic=False)
    assert world.runs == runs and "turned off" in why


def test_play_without_the_window_does_not_start_when_the_merge_cannot_be_rebuilt(world, monkeypatch):
    world.pack("params")
    monkeypatch.setattr(merge, "setup_problem", lambda *a, **k: "the package that must stay last is missing")
    monkeypatch.setattr(common, "log", lambda s: None)
    assert merge.needs_update(world.profile) is None  # nothing to rebuild ...
    assert merge.play_check(world.profile)["blocked"]  # ... yet it is out of date
    why = core.update_merge_headless(type("S", (), {"profile": str(world.profile)})())
    assert "cannot be rebuilt" in why


def test_headless_play_does_not_launch_when_it_must_not(monkeypatch):
    setup = type("S", (), {"profile": "p.me3", "source": "x", "problems": lambda self: []})()
    monkeypatch.setattr(core, "discover", lambda remembered, game: [setup])
    monkeypatch.setattr(core, "same_source", lambda a, b: True)
    monkeypatch.setattr(core, "update_merge_headless", lambda s, automatic=True: "out of date")
    played, shown = [], []
    monkeypatch.setattr(core, "job_play", played.append)
    monkeypatch.setattr(common, "log", lambda s: None)
    assert core.play_headless(core.games.ELDEN_RING, notice=lambda game, why: shown.append(why)) == 1
    assert played == [] and shown == ["out of date"]
    monkeypatch.setattr(core, "update_merge_headless", lambda s, automatic=True: None)
    assert core.play_headless(core.games.ELDEN_RING) == 0 and played == [setup]


def test_automatic_rebuilds_are_on_by_default():
    assert core.play_options({})["play_update_merge"] is True
    assert json.dumps(core.PLAY_DEFAULTS)  # plain values, as the settings page reads them
