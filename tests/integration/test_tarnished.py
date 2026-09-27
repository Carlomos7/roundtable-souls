"""Tarnished Edition gear is official content: vanilla when the pack flag is set, mod items when forced off.
Runs on COPIES of the live co-op save in a temp folder; the live file is never written."""

import pytest

from roundtable_souls import core as g
from support import copy_live_save as _copy

A = g.save_analyze
L = g.save_layout_check
V = g.save_vanilla

ARMOR = 0x10000000


def test_pack_ids_and_labels():
    ids = A.tarnished_ids()
    assert (ARMOR | 5350000) in ids and 3560000 in ids and (0x40000000 | 8380001) not in ids
    assert A.item_label(ARMOR | 5350000) == ("Silver Grooved Helm", "Tarnished Edition")
    assert A.item_label(0x40000000 | 8380001)[1] == "Seamless Co-op"
    assert (
        A.item_label(ARMOR | 5361000) == ("Leontiel's Hat (altered)", "Tarnished Edition") and (ARMOR | 5361000) in ids
    )
    assert A.effective_known({}, "yes") >= ids and not (A.effective_known({}, "no") & ids)
    assert (
        A.tarnished_owned({}, "yes") is True and A.tarnished_owned({}, "no") is False and A.tarnished_owned({}) is False
    )


def test_flag_on_the_save_makes_pack_gear_vanilla(tmp_path):
    copy = _copy(tmp_path)
    r = L.parse(str(copy))
    if not A.tarnished_flag(r):
        pytest.skip("live save has no Tarnished pack flag")
    auto = V.plan_restore(r)
    forced_off = V.plan_restore(r, "no")
    sources_auto = {e["source"] for p in auto for e in list(p["strip"]) + list(p["blocked"])}
    sources_off = {e["source"] for p in forced_off for e in list(p["strip"]) + list(p["blocked"])}
    assert "Tarnished Edition" not in sources_auto
    if "Tarnished Edition" in sources_off:  # the live characters do hold pack gear
        assert not any(
            b["source"] == "Tarnished Edition" for p in auto for b in p["blocked"]
        )  # no pack gear is blocked as worn
        assert sum(len(p["strip"]) for p in auto) < sum(len(p["strip"]) for p in forced_off)
    findings = A.analyze_parsed(r)
    assert any(f["code"] == "tarnished" and f["level"] == "ok" for f in findings)
    assert not any("Tarnished" in (f.get("detail") or "") and f["code"] == "unknown_item" for f in findings)
    off = A.analyze_parsed(r, tarnished="no")
    assert any(f["code"] == "tarnished" and f["level"] == "info" for f in off)


def test_dlc_items_count_as_foreign_when_the_dlc_is_missing(tmp_path, monkeypatch):
    names = A.dlc_item_names()
    assert len(names) > 500
    dlc_weapon = next(i for i in names if (i & 0xF0000000) == 0)
    assert A.item_label(dlc_weapon)[1] == A.DLC_SOURCE and A.item_label(dlc_weapon)[0]
    assert dlc_weapon in A.effective_known({}, "no") and dlc_weapon not in A.effective_known({}, "no", dlc_owned=False)
    assert (0x40000000 | 8380001) not in A.effective_known({}, dlc_owned=False)  # Seamless stays foreign either way
    copy = _copy(tmp_path)
    r = L.parse(str(copy))
    with_dlc = V.plan_restore(r, None, True)
    without = V.plan_restore(r, None, False)
    n_with = sum(len(p["strip"]) + len(p["blocked"]) for p in with_dlc)
    n_without = sum(len(p["strip"]) + len(p["blocked"]) for p in without)
    assert n_without >= n_with
    if n_without > n_with:  # the live characters hold DLC gear
        assert any(e["source"] == A.DLC_SOURCE for p in without for e in list(p["strip"]) + list(p["blocked"]))
    assert any(f["code"] == "dlc" for f in A.analyze_parsed(r, dlc_owned=False)) and not any(
        f["code"] == "dlc" for f in A.analyze_parsed(r, dlc_owned=True)
    )
    monkeypatch.setattr(g.saves_service, "load_settings", lambda: {"dlc_owned": "no"})
    assert g.dlc_owned() is False and g.dlc_setting() == "no"
    info = g.save_info(copy)
    assert info["dlc_owned"] is False
    monkeypatch.setattr(g.saves_service, "load_settings", lambda: {"dlc_owned": "yes"})
    assert g.dlc_owned() is True
    monkeypatch.setattr(g.saves_service, "load_settings", lambda: {})
    assert g.dlc_setting() is None


def test_save_info_reports_pack_pieces_and_honours_the_setting(tmp_path, monkeypatch):
    copy = _copy(tmp_path)
    monkeypatch.setattr(g.saves_service, "load_settings", lambda: {"tarnished_owned": "auto"})
    info = g.save_info(copy)
    assert info["tarnished_flag"] == info["tarnished_owned"]
    assert all("pack_items" in c for c in info["characters"])
    if info["tarnished_flag"]:
        assert all(e["source"] != "Tarnished Edition" for p in info["vanilla_plan"] for e in p["strip"])
        d = g.character_detail(info, info["characters"][0]["slot"] - 1)
        assert "pack_items" in d
    monkeypatch.setattr(g.saves_service, "load_settings", lambda: {"tarnished_owned": "no"})
    info2 = g.save_info(copy)
    assert info2["tarnished_owned"] is False
    assert g.tarnished_setting() == "no"
    monkeypatch.setattr(g.saves_service, "load_settings", lambda: {"tarnished_owned": "weird"})
    assert g.tarnished_setting() is None
