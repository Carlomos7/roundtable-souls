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
    assert rec["me3_version"] == "0.13.0"
    older = {**rec, "merger_revision": record.MERGER_REVISION - 1}
    assert record.reasons(older) == ["the launcher's merging changed since this was built"]
    reordered = {**rec, "ordering": "an earlier model"}
    assert record.reasons(reordered) == ["the launcher's load order model changed since this was built"]
    assert record.reasons({**rec, "me3_version": "0.12.0"}) == []  # the ordering model decides, not the version
    assert record.reasons({"files": {}}) == []  # a record from before these fields: its inputs are still checked


def test_an_interrupted_rebuild_leaves_the_previous_result_and_the_next_one_finishes(prof, monkeypatch):
    from roundtable_souls.merging import build as B

    merge.rebuild(prof, lambda s: None)
    folder = builtin.find(prof, merge.layers(prof)).folder
    before = {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    real, n = B.os.replace, {"i": 0}

    def crash(src, dst, *a, **k):  # the first file put in place, after the journal is written
        if (folder / B.JOURNAL).exists() and str(dst).startswith(str(folder)) and not n["i"]:
            n["i"] += 1
            raise OSError("power cut")
        return real(src, dst, *a, **k)

    with monkeypatch.context() as m:  # only this patch: the fixture's sandbox stays
        m.setattr(B.os, "replace", crash)
        with pytest.raises(Exception):  # noqa: B017  (whatever the interruption raises)
            merge.rebuild(prof, lambda s: None)
    assert (folder / B.JOURNAL).exists()  # interrupted while being put in place
    merge.health(prof)  # looking at it undoes the interrupted rebuild
    assert not (folder / B.JOURNAL).exists()
    after = {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    assert after == before
    merge.rebuild(prof, lambda s: None)
    assert merge.health(prof)["state"] in ("current", "single")


def _add_mod(prof, name: str, change: dict) -> None:
    (prof.parent / "mod" / name / "menu/hi").mkdir(parents=True)
    (prof.parent / "mod" / name / REL).write_bytes(dcx(bnd({**GAME, **change})))
    text = prof.read_text(encoding="utf-8")
    at = text.index('[[packages]]\nid = "other"')
    prof.write_text(text[:at] + f"[[packages]]\nid = \"{name}\"\npath = 'mod/{name}'\n\n" + text[at:], encoding="utf-8")


def test_removing_a_mod_and_rebuilding_equals_building_without_it(prof, tmp_path, monkeypatch):
    from roundtable_souls.mods import manage

    _add_mod(prof, "map", {"SB_Map.layout": b"big map"})
    merge.rebuild(prof, lambda s: None)
    assert _merged(prof)["SB_Marker.layout"] == b"blue marker"
    idx = next(e["index"] for e in manage.entries(prof) if e["name"] == "marker")
    manage.uninstall(prof, idx)
    merge.rebuild(prof, lambda s: None)
    after_removal = (prof.parent / "mod" / "combined-parameters" / REL).read_bytes()
    assert files_of(after_removal) == {**GAME, "SB_KG.layout": b"ps5 buttons", "SB_Map.layout": b"big map"}
    # the same mods built from scratch in another profile: byte for byte the same file
    fresh = tmp_path / "fresh"
    (fresh / "mod").mkdir(parents=True)
    for name in ("buttons", "map"):
        os.replace(prof.parent / "mod" / name, fresh / "mod" / name)
    (fresh / "mod" / "other").mkdir()
    (fresh / "p.me3").write_text(
        "[[packages]]\nid = \"buttons\"\npath = 'mod/buttons'\n\n[[packages]]\nid = \"map\"\npath = 'mod/map'\n\n"
        "[[packages]]\nid = \"other\"\npath = 'mod/other'\n",
        encoding="utf-8",
    )
    merge.rebuild(fresh / "p.me3", lambda s: None)
    assert (fresh / "mod" / "combined-parameters" / REL).read_bytes() == after_removal


def test_a_rebuild_without_room_on_the_drive_is_not_started(prof, monkeypatch):
    from roundtable_souls.merging import build as B

    merge.rebuild(prof, lambda s: None)
    folder = builtin.find(prof, merge.layers(prof)).folder
    before = {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    _add_mod(prof, "map", {"SB_Map.layout": b"big map"})
    monkeypatch.setattr(B.shutil, "disk_usage", lambda p: type("U", (), {"free": B.SPARE // 2})())
    with pytest.raises(Exception, match="not enough free space"):
        merge.rebuild(prof, lambda s: None)
    after = {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    assert after == before and not folder.with_name("." + folder.name + ".staging").exists()
