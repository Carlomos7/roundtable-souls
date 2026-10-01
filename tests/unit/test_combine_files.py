"""Files two ordinary mods both ship are merged into the launcher's combined package, so both mods' changes apply:
offered, merged, checked for staleness, shown as combined in Load order, and undoable."""

import os
import time

import pytest
from fakegame import bnd, dcx, files_of
from test_param_merge import vanilla

from roundtable_souls.mods import merge, overview, undo
from roundtable_souls.mods.backends import builtin
from roundtable_souls.system import common

REL = "menu/hi/01_common.sblytbnd.dcx"
GAME = {"SB_KG.layout": b"xbox buttons", "SB_Marker.layout": b"white marker", "SB_Map.layout": b"map"}


@pytest.fixture
def prof(tmp_path, monkeypatch):
    import fakegame

    game = tmp_path / "Game"
    game.mkdir()
    (game / "regulation.bin").write_bytes(vanilla())
    monkeypatch.setattr(common, "game_dir", lambda: game)
    monkeypatch.setattr(common, "game_running", lambda: False)
    fakegame.game(monkeypatch, {REL: dcx(bnd(GAME))})
    base = tmp_path / "p"
    for name, change in (
        ("buttons", {"SB_KG.layout": b"ps5 buttons"}),
        ("marker", {"SB_Marker.layout": b"blue marker"}),
    ):
        (base / "mod" / name / "menu/hi").mkdir(parents=True)
        (base / "mod" / name / REL).write_bytes(dcx(bnd({**GAME, **change})))
    (base / "mod" / "other").mkdir(parents=True)
    p = base / "p.me3"
    p.write_text(
        "[[packages]]\nid = \"buttons\"\npath = 'mod/buttons'\n\n"
        "[[packages]]\nid = \"marker\"\npath = 'mod/marker'\n\n"
        "[[packages]]\nid = \"other\"\npath = 'mod/other'\n",
        encoding="utf-8",
    )
    return p


def _merged(prof) -> dict:
    return files_of((prof.parent / "mod" / "combined-parameters" / REL).read_bytes())


def test_two_mods_shipping_one_file_are_offered_a_combine(prof):
    h = merge.health(prof)
    assert h["shared_files"] == [REL] and h["can_combine"] and not h["combine"]
    assert any("can be merged" in r for r in h["reasons"])


def test_a_rebuild_merges_both_mods_changes_after_them(prof):
    out = merge.rebuild(prof, lambda s: None)
    assert _merged(prof) == {
        "SB_KG.layout": b"ps5 buttons",
        "SB_Marker.layout": b"blue marker",
        "SB_Map.layout": b"map",
    }
    order = [l["name"] for l in merge.layers(prof)]
    assert order.index("combined-parameters") > order.index("marker")  # after the mods it merges
    assert not (prof.parent / "mod" / "combined-parameters" / "regulation.bin").exists()  # no packs: no parameters
    assert merge.health(prof)["state"] in ("current", "single") and not merge.health(prof)["reasons"]
    rec = builtin.find(prof, merge.layers(prof)).record()
    assert rec["files"][REL.lower()]["output"] and len(rec["files"][REL.lower()]["sources"]) == 2
    assert out["undo"]["type"] == "rebuild"


def test_load_order_says_the_copies_are_combined(prof):
    from roundtable_souls.mods import profile as profile_tools

    merge.rebuild(prof, lambda s: None)
    got = overview.classify(prof, profile_tools.scan_conflicts(prof))
    row = next(c for c in got["conflicts"] if c["path"].replace("\\", "/").lower() == REL)
    assert row["winner"] == "combined-parameters"
    assert {l["outcome"] for l in row["losers"]} == {"combined"}


def test_a_changed_copy_makes_it_out_of_date_and_a_rebuild_takes_it(prof):
    merge.rebuild(prof, lambda s: None)
    time.sleep(0.01)
    (prof.parent / "mod/marker" / REL).write_bytes(dcx(bnd({**GAME, "SB_Marker.layout": b"green marker"})))
    h = merge.health(prof)
    assert h["state"] == "stale" and any("copies changed" in r for r in h["reasons"])
    assert merge.needs_update(prof) is not None  # Play would merge it again first
    merge.rebuild(prof, lambda s: None)
    assert _merged(prof)["SB_Marker.layout"] == b"green marker"


def test_a_file_no_longer_shared_is_dropped_from_the_combined_package(prof):
    merge.rebuild(prof, lambda s: None)
    os.remove(prof.parent / "mod/marker" / REL)
    assert any("no longer needs merging" in r for r in merge.health(prof)["reasons"])
    merge.rebuild(prof, lambda s: None)
    assert not (prof.parent / "mod" / "combined-parameters" / REL).exists()


def test_undo_rebuild_puts_the_previous_merge_back(prof):
    merge.rebuild(prof, lambda s: None)
    first = _merged(prof)
    (prof.parent / "mod/buttons" / REL).write_bytes(dcx(bnd({**GAME, "SB_KG.layout": b"switch buttons"})))
    time.sleep(1.1)  # kept copies are named by the second
    out = merge.rebuild(prof, lambda s: None)
    assert _merged(prof)["SB_KG.layout"] == b"switch buttons"
    undo.run(out["undo"], lambda s: None)
    assert _merged(prof) == first


def test_a_file_the_launcher_cannot_merge_is_left_to_the_later_mod(prof, monkeypatch):
    import fakegame

    fakegame.game(monkeypatch, {})  # the game has no such file: nothing to compare with
    merge.rebuild(prof, lambda s: None, combine=True)
    rec = builtin.find(prof, merge.layers(prof)).record()
    assert "nothing to compare" in rec["files"][REL.lower()]["skipped"]
    assert not (prof.parent / "mod" / "combined-parameters" / REL).exists()
    assert not merge.health(prof)["reasons"]  # known and unchanged: not out of date


def test_the_record_says_how_the_build_was_made_and_other_rules_make_it_out_of_date(prof):
    from roundtable_souls.merging import record

    merge.rebuild(prof, lambda s: None)
    tool = builtin.find(prof, merge.layers(prof))
    rec = tool.record()
    assert rec["merger_revision"] == record.MERGER_REVISION and rec["ordering"].startswith("me3 sort_dependencies")
    assert rec["removal_choice"] == record.REMOVAL_CHOICE and len(rec["game_config_sha256"]) == 64
    assert "removed" in rec["files"][REL.lower()]
    assert merge.health(prof)["state"] in ("current", "single")
    older = {**rec, "merger_revision": record.MERGER_REVISION - 1}
    assert record.reasons(older) == ["the launcher's merging changed since this was built"]
    assert record.reasons({"files": {}}) == []  # a record from before these fields: its inputs are still checked
