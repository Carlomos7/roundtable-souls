"""Partial selections: each write action honours the chosen subset and leaves the rest alone.
Runs on COPIES of the live co-op save in a temp folder; skipped without one. The live file is never written."""

import struct

import pytest

from roundtable_souls.saves import layout as save_layout_check
from roundtable_souls.saves import loading as save_loading
from roundtable_souls.saves import vanilla as save_vanilla
from roundtable_souls.services import play as g
from roundtable_souls.services import saves as saves_service
from support import copy_live_save as _copy

A = g.save_analyze
F = g.save_fix
L = save_layout_check
V = save_vanilla
S = save_loading


def test_restore_only_the_ticked_items(tmp_path, monkeypatch):
    copy = _copy(tmp_path)
    monkeypatch.setattr(g.common, "game_running", lambda: False)
    r0 = L.parse(str(copy))
    plan = V.plan_restore(r0)
    target = next((p for p in plan if len(p["strip"]) >= 2), None) or next((p for p in plan if p["strip"]), None)
    if not target:
        pytest.skip("live save has nothing to strip right now")
    half = max(1, len(target["strip"]) // 2)
    chosen = {e["handle"] for e in target["strip"][:half]}
    kept = [e for e in target["strip"] if e["handle"] not in chosen]
    before = copy.read_bytes()
    out = saves_service.restore_vanilla(copy, selection={target["slot"]: {"items": chosen, "orphans": False}})
    assert [d["slot"] for d in out["done"]] == [target["slot"]] and out["done"][0]["removed"] == len(chosen)
    after = copy.read_bytes()
    r1 = L.parse(str(copy))
    s1 = r1["slots"][target["slot"]]
    for e in target["strip"]:
        entry = s1[e["box"]][e["list"]][e["pos"]]
        assert (entry[0] == 0) == (e["handle"] in chosen), e["name"]
    for e in kept:
        assert s1[e["box"]][e["list"]][e["pos"]][0] == e["handle"]
    if target["orphans"]:
        assert not A.Catalog.for_save(r1).is_game_item(
            s1["ga_items"][target["orphans"][0]["row"]]["item_id"]
        )  # untouched
    for i in range(10):
        if i != target["slot"]:
            off = L.HEADER + i * F.SLOT_STRIDE
            assert after[off : off + F.SLOT_STRIDE] == before[off : off + F.SLOT_STRIDE]
    plan2 = V.plan_restore(r1)
    left = next((p for p in plan2 if p["slot"] == target["slot"]), None)
    assert {e["handle"] for e in (left["strip"] if left else [])} == {e["handle"] for e in kept}
    # a slot missing from the selection is never touched, even with an empty selection dict entry elsewhere
    assert V.select_plan(plan, {}) == []
    assert V.select_plan(plan, {target["slot"]: {"items": None}})[0]["strip"] == target["strip"]


def test_loading_fix_only_the_ticked_issue(tmp_path, monkeypatch):
    copy = _copy(tmp_path)
    monkeypatch.setattr(g.common, "game_running", lambda: False)
    data = bytearray(copy.read_bytes())
    r = L.parse(str(copy))
    i = next(k for k, a in enumerate(r["ud10"]["active"]) if a)
    s = r["slots"][i]
    struct.pack_into("<i", data, s["horse_pos"] + 32, 0)
    struct.pack_into("<I", data, s["horse_pos"] + 36, S.TORRENT_SUMMONED)
    struct.pack_into("<fff", data, s["coords_pos"], float("nan"), 0.0, 0.0)
    F._sign_slot(data, i)
    copy.write_bytes(bytes(data))
    assert S.plan_loading_fixes(L.parse(str(copy)), True)[0]["issues"] == ["torrent", "position"]
    out = saves_service.fix_loading(copy, selection={i: ["torrent"]})
    assert out["fixed"][0]["issues"] == ["torrent"]
    r2 = L.parse(str(copy))
    assert r2["slots"][i]["horse"] == (0, S.TORRENT_DEAD) and S.plan_loading_fixes(r2, True)[0]["issues"] == [
        "position"
    ]
    assert saves_service.fix_loading(copy, selection={})["backup"] is None  # nothing chosen: nothing written
