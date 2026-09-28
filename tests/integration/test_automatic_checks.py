"""Tarnished Edition and Shadow of the Erdtree are both read automatically: the pack flag from the save, the DLC from
DLC.bdt next to the game. Runs on COPIES of a real co-op save (skipped without one); the original is never written."""

import pytest

from roundtable_souls import core as g
from support import copy_live_save as _copy

A = g.save_analyze
L = g.save_layout_check
V = g.save_vanilla


def test_pack_flag_on_the_save_leaves_unlisted_gear_alone(tmp_path):
    copy = _copy(tmp_path)
    r = L.parse(str(copy))
    if not A.tarnished_flag(r):
        pytest.skip("this save has no Tarnished Edition flag")
    plan = V.plan_restore(r)
    entries = [e for p in plan for e in list(p["strip"]) + list(p["blocked"]) + list(p["orphans"])]
    assert not any(A.kind_of(e["item_id"]) in A.EQUIPMENT for e in entries)  # equipment counts as pack gear
    findings = A.analyze_parsed(r)
    assert any(f["code"] == "tarnished" and f["level"] == "ok" for f in findings)


def test_without_the_flag_unlisted_gear_is_foreign(tmp_path):
    copy = _copy(tmp_path)
    r = L.parse(str(copy))
    for _i, slot in A.active_slots(r):
        dlc = bytearray(slot.get("dlc") or bytes(50))
        dlc[A.TARNISHED_FLAG_BYTE] = 0
        slot["dlc"] = bytes(dlc)
    assert not A.tarnished_flag(r)
    assert not any(f["code"] == "tarnished" for f in A.analyze_parsed(r))


def test_dlc_is_read_from_the_game_folder(tmp_path, monkeypatch):
    game = tmp_path / "Game"
    game.mkdir()
    monkeypatch.setattr(g.common, "game_dir", lambda: game)
    assert g.dlc_owned() is False
    (game / "DLC.bdt").write_bytes(b"x")
    assert g.dlc_owned() is True
    monkeypatch.setattr(g.common, "game_dir", lambda: None)
    assert g.dlc_owned() is None  # unknown game folder: treated as installed


def test_save_info_reports_the_pack_flag(tmp_path):
    copy = _copy(tmp_path)
    info = g.save_info(copy)
    assert isinstance(info["tarnished_flag"], bool)
    d = g.character_detail(info, info["characters"][0]["slot"] - 1)
    assert set(d) >= {"mods", "loading"}
