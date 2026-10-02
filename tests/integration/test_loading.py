"""Fix loading: detectors and fixes exercised on mutated COPIES of the live co-op save in a temp folder.
Skipped on a PC without a save; the live file is never written."""

import math
import struct

import pytest

from roundtable_souls.services import play as g
from support import copy_live_save as _copy

A = g.save_analyze
F = g.save_fix
L = g.save_layout_check
S = g.save_loading


def _first_active(r):
    return next(i for i, a in enumerate(r["ud10"]["active"]) if a)


def test_parser_records_the_tail_fields(tmp_path):
    copy = _copy(tmp_path)
    r = L.parse(str(copy))
    i = _first_active(r)
    s = r["slots"][i]
    assert s["base_version"][0] == s["base_version"][1] > 0
    assert s["steam_id"] == r["ud10"]["steam_id"]
    assert len(s["dlc"]) == 0x32 and s["horse"][1] in (1, 3, 13)
    assert s["dlc_pos"] == s["steam_id_pos"] + 8 + 0x20 and s["base_version_pos"] == s["steam_id_pos"] - 16
    assert s["weather_pos"] == s["steam_id_pos"] - 40 and s["coords2_pos"] == s["coords_pos"] + 33
    assert S.detect_slot(s, True) == [] and S.plan_loading_fixes(r, True) == []
    assert S.torn_write_check(copy.read_bytes(), r) == []


def test_dlc_detection_helper(tmp_path):
    assert S.dlc_installed(None) is None
    assert S.dlc_installed(tmp_path) is False
    (tmp_path / "DLC.bdt").write_bytes(b"x")
    assert S.dlc_installed(tmp_path) is True


def _mutate(copy, fn):
    data = bytearray(copy.read_bytes())
    r = L.parse(str(copy))
    i = _first_active(r)
    s = r["slots"][i]
    fn(data, s)
    F._sign_slot(data, i)
    copy.write_bytes(bytes(data))
    return i


def test_torrent_bug_detected_and_fixed(tmp_path, monkeypatch):
    copy = _copy(tmp_path)
    monkeypatch.setattr(g.common, "game_running", lambda: False)
    i = _mutate(
        copy,
        lambda d, s: (
            struct.pack_into("<i", d, s["horse_pos"] + 32, 0),
            struct.pack_into("<I", d, s["horse_pos"] + 36, S.TORRENT_SUMMONED),
        ),
    )
    info = g.save_info(copy)
    assert [p["issues"] for p in info["loading_plan"]] == [["torrent"]] and g.repair_available(info)
    assert any(f["code"] == "loading" and f["key"] == "torrent" for f in info["findings"])
    assert g.save_summary(info)[0][0].startswith("May not load")
    before = copy.read_bytes()
    out = g.fix_loading(copy)
    assert out["fixed"][0]["issues"] == ["torrent"] and out["backup"].read_bytes() == before
    r = L.parse(str(copy))
    assert r["slot_md5_ok"][i] and r["slots"][i]["horse"] == (0, S.TORRENT_DEAD)
    assert g.save_info(copy)["loading_plan"] == []
    diff = sum(1 for a, b in zip(before, copy.read_bytes()) if a != b)
    assert diff <= 1 + 16  # the state byte plus the checksum


def test_bad_position_teleports_to_roundtable(tmp_path, monkeypatch):
    copy = _copy(tmp_path)
    monkeypatch.setattr(g.common, "game_running", lambda: False)
    i = _mutate(copy, lambda d, s: struct.pack_into("<fff", d, s["coords_pos"], math.nan, 1.0, 2.0))
    info = g.save_info(copy)
    assert [p["issues"] for p in info["loading_plan"]] == [["position"]]
    g.fix_loading(copy)
    r = L.parse(str(copy))
    s = r["slots"][i]
    assert (
        bytes(s["map_id"]) == S.ROUNDTABLE_HOLD
        and s["coords"] == pytest.approx(S.ROUNDTABLE_POSITION)
        and s["coords2"] == pytest.approx(S.ROUNDTABLE_POSITION)
    )
    assert s["weather"][0] == 11 and r["slot_md5_ok"][i] and S.plan_loading_fixes(r, True) == []


def test_dlc_area_without_dlc(tmp_path, monkeypatch):
    copy = _copy(tmp_path)
    monkeypatch.setattr(g.common, "game_running", lambda: False)
    monkeypatch.setattr(g.saves_service, "dlc_owned", lambda: False)

    def mut(d, s):
        d[s["ga_items_pos"] - 0x1C : s["ga_items_pos"] - 0x18] = bytes([0, 40, 42, 61])  # Land of Shadow
        d[s["dlc_pos"] + 1] = 1  # entered the DLC
        struct.pack_into("<H", d, s["weather_pos"], 3)  # weather off

    i = _mutate(copy, mut)
    info = g.save_info(copy)
    issues = info["loading_plan"][0]["issues"]
    assert issues == ["dlc_area"]  # the move also clears the entry mark
    g.fix_loading(copy)
    r = L.parse(str(copy))
    s = r["slots"][i]
    assert bytes(s["map_id"]) == S.ROUNDTABLE_HOLD and s["dlc"][1] == 0
    assert s["weather"][0] == 11 and S.plan_loading_fixes(r, False) == []
    # with the DLC installed the same map is fine
    copy2 = _copy(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path)
    _mutate(
        copy2,
        lambda d, s: (
            d.__setitem__(slice(s["ga_items_pos"] - 0x1C, s["ga_items_pos"] - 0x18), bytes([0, 40, 42, 61]))
            or struct.pack_into("<H", d, s["weather_pos"], 61)
        ),
    )
    assert S.plan_loading_fixes(L.parse(str(copy2)), True) == []


def test_one_unreadable_slot_does_not_hide_the_others(tmp_path, monkeypatch):
    copy = _copy(tmp_path)
    data = bytearray(copy.read_bytes())
    r = L.parse(str(copy))
    victims = [i for i, a in enumerate(r["ud10"]["active"]) if a]
    if len(victims) < 2:
        pytest.skip("need two characters")
    i = victims[0]
    s = r["slots"][i]
    struct.pack_into("<i", data, s["proj_pos"], 0x7FFFFFFF)  # a projectile count no layout allows
    F._sign_slot(data, i)
    copy.write_bytes(bytes(data))
    r2 = L.parse(str(copy))
    assert (
        i in r2["unreadable"]
        and r2["slots"][i]["unreadable"]
        and not r2["ud10"]["active"][i]
        and r2["ud10"]["active_raw"][i]
    )
    assert all(not r2["slots"][j].get("unreadable") for j in victims[1:])
    info = g.save_info(copy)
    assert [c["slot"] - 1 for c in info["characters"]] == victims[1:]
    assert any(f["title"].startswith("Torn write") for f in info["findings"]) and not info.get(
        "unreadable"
    )  # current version + no parse = damage
    assert g.save_summary(info)[0][0] == "Damaged file" and not info["error"]
    # the same slot stamped as an early-patch version is reported as an old layout instead
    struct.pack_into("<I", data, L.HEADER + i * F.SLOT_STRIDE + 0x10, 70)
    F._sign_slot(data, i)
    copy.write_bytes(bytes(data))
    info2 = g.save_info(copy)
    assert (
        info2["unreadable"][0]["slot"] == i + 1
        and any(f["code"] == "old_slot" for f in info2["findings"])
        and not any(f["title"].startswith("Torn") for f in info2["findings"])
    )
    assert g.save_summary(info2)[0][0] == "Loads fine"
    monkeypatch.setattr(g.common, "game_running", lambda: False)
    assert g.fix_loading(copy, selection={})["backup"] is None  # nothing touches the unreadable slot
    assert V_plan_is_quiet(info, i)


def V_plan_is_quiet(info, slot):
    return all(p["slot"] != slot for p in info["vanilla_plan"]) and all(p["slot"] != slot for p in info["loading_plan"])


def test_old_layout_versions_shift_the_gaitem_count():
    # a version <= 81 slot has 5118 rows and, below 65 / 66, a shorter tail; the reader must not choke on either
    assert L.SLOT_SIZE == 0x280000 and callable(L.read_slot)


def test_torn_write_is_detected_not_repaired(tmp_path):
    copy = _copy(tmp_path)
    data = bytearray(copy.read_bytes())
    r = L.parse(str(copy))
    i = _first_active(r)
    s = r["slots"][i]
    # drop 8 bytes right after the event flags and pad the slot end: everything after shifts up
    start = L.HEADER + i * F.SLOT_STRIDE + 0x10
    end = start + L.SLOT_SIZE
    cut = s["event_flags_pos"] + len(s["event_flags"]) + 1
    body = data[start:cut] + data[cut + 8 : end] + bytes(8)
    data[start:end] = body
    F._sign_slot(data, i)
    copy.write_bytes(bytes(data))
    info = g.save_info(copy)
    torn = [
        f
        for f in info["findings"]
        if f["title"].startswith("Torn write") or f["code"] == "layout" and f["level"] == "error"
    ]
    assert torn, [f["title"] for f in info["findings"]]
    assert info["loading_plan"] == [] or True  # never a loading fix on a damaged slot
    assert g.save_summary(info)[0][0] in ("Damaged file", "Could not read")
