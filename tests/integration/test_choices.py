"""Partial selections: each write action honours the chosen subset and leaves the rest alone.
Runs on COPIES of the live co-op save in a temp folder; skipped without one. The live file is never written."""
import shutil
import struct

import pytest

from roundtable_souls import core as g

A = g.save_analyze
F = g.save_fix
L = g.save_layout_check
V = g.save_vanilla
S = g.save_loading


def _copy(tmp_path):
    src = next((p for p in g.common.save_files() if p.suffix.lower() == ".co2" and p.exists()), None)
    if not src:
        pytest.skip("no live co-op save on this PC")
    copy = tmp_path / "ER0000.co2"; shutil.copy2(src, copy)
    return copy


def test_restore_only_the_ticked_items(tmp_path, monkeypatch):
    copy = _copy(tmp_path); monkeypatch.setattr(g.common, "game_running", lambda: False)
    r0 = L.parse(str(copy)); plan = V.plan_restore(r0)
    target = next((p for p in plan if len({e["source"] for e in p["strip"]}) >= 2), None) or next((p for p in plan if p["strip"]), None)
    if not target:
        pytest.skip("live save has nothing to strip right now")
    src = target["strip"][0]["source"]
    chosen = {e["handle"] for e in target["strip"] if e["source"] == src}
    kept = [e for e in target["strip"] if e["source"] != src]
    before = copy.read_bytes()
    out = g.restore_vanilla(copy, selection={target["slot"]: {"items": chosen, "orphans": False, "quest": []}})
    assert [d["slot"] for d in out["done"]] == [target["slot"]] and out["done"][0]["removed"] == len(chosen)
    after = copy.read_bytes(); r1 = L.parse(str(copy)); s1 = r1["slots"][target["slot"]]
    for e in target["strip"]:
        entry = s1[e["box"]][e["list"]][e["pos"]]
        assert (entry[0] == 0) == (e["handle"] in chosen), e["name"]
    for e in kept:
        assert s1[e["box"]][e["list"]][e["pos"]][0] == e["handle"]
    if target["orphans"]:
        assert not A._item_known(s1["ga_items"][target["orphans"][0]["row"]]["item_id"], A.known_item_ids())   # untouched
    for i in range(10):
        if i != target["slot"]:
            off = L.HEADER + i * F.SLOT_STRIDE
            assert after[off: off + F.SLOT_STRIDE] == before[off: off + F.SLOT_STRIDE]
    plan2 = V.plan_restore(r1)
    left = next((p for p in plan2 if p["slot"] == target["slot"]), None)
    assert {e["handle"] for e in (left["strip"] if left else [])} == {e["handle"] for e in kept}
    # a slot missing from the selection is never touched, even with an empty selection dict entry elsewhere
    assert V.select_plan(plan, {}) == []
    assert V.select_plan(plan, {target["slot"]: {"items": None}})[0]["strip"] == target["strip"]


def test_loading_fix_only_the_ticked_issue(tmp_path, monkeypatch):
    copy = _copy(tmp_path); monkeypatch.setattr(g.common, "game_running", lambda: False)
    data = bytearray(copy.read_bytes()); r = L.parse(str(copy)); i = next(k for k, a in enumerate(r["ud10"]["active"]) if a); s = r["slots"][i]
    struct.pack_into("<i", data, s["horse_pos"] + 32, 0); struct.pack_into("<I", data, s["horse_pos"] + 36, S.HORSE_ACTIVE)
    struct.pack_into("<H", data, s["weather_pos"], 3)
    F._sign_slot(data, i); copy.write_bytes(bytes(data))
    assert S.plan_loading_fixes(L.parse(str(copy)), True)[0]["issues"] == ["torrent", "weather"]
    out = g.fix_loading(copy, selection={i: ["torrent"]})
    assert out["fixed"][0]["issues"] == ["torrent"]
    r2 = L.parse(str(copy))
    assert r2["slots"][i]["horse"] == (0, S.HORSE_DEAD) and S.plan_loading_fixes(r2, True)[0]["issues"] == ["weather"]
    assert g.fix_loading(copy, selection={})["backup"] is None                    # nothing chosen: nothing written


def test_quest_fix_only_the_ticked_flag(tmp_path, monkeypatch):
    copy = _copy(tmp_path); monkeypatch.setattr(g.common, "game_running", lambda: False)
    if not A._bst_map():
        pytest.skip("flag BST not bundled")
    data = bytearray(copy.read_bytes()); r = L.parse(str(copy)); i = next(k for k, a in enumerate(r["ud10"]["active"]) if a); s = r["slots"][i]
    flags = bytearray(data[s["event_flags_pos"]: s["event_flags_pos"] + A.EVENT_FLAGS_SIZE])
    F.set_flag(flags, A.RANNI_BLOCKING, True); F.set_flag(flags, A.GOLEM_DEFEATED, True); F.set_flag(flags, A.GOLEM_DESTROYED, False)
    data[s["event_flags_pos"]: s["event_flags_pos"] + A.EVENT_FLAGS_SIZE] = flags
    F._sign_slot(data, i); copy.write_bytes(bytes(data))
    issues = next(p for p in F.plan_quest_fixes(L.parse(str(copy))) if p["slot"] == i)["issues"]
    assert "ranni_softlock" in issues and "unte_golem_stuck" in issues
    out = g.fix_quest_flags(copy, selection={i: ["unte_golem_stuck"]})
    assert out["fixed"][0]["issues"] == ["unte_golem_stuck"]
    left = next(p for p in F.plan_quest_fixes(L.parse(str(copy))) if p["slot"] == i)["issues"]
    assert "ranni_softlock" in left and "unte_golem_stuck" not in left
