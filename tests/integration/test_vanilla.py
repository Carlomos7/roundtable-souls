"""Remove mod items: the game item list, the scan, and the removal itself on a COPY of a real save
(skipped on a PC without one; the original is never written)."""

import shutil
import struct

import pytest

from roundtable_souls import core as g
from support import live_save as _live_save

A = g.save_analyze
F = g.save_fix
L = g.save_layout_check
V = g.save_vanilla

GOODS, ARMOR, TALISMAN = 0x40000000, 0x10000000, 0x20000000


def test_game_item_list_and_handles():
    known = A.known_item_ids()
    assert len(known) > 50000
    assert (GOODS | 2040) in known and (GOODS | 8158) in known  # Telescope, Spirit Calling Bell
    assert 9000900 in known and 1000114 in known and 110000 in known  # Cold Uchigatana, Heavy Dagger +14, Unarmed
    assert (GOODS | 207006) in known  # Mimic Tear Ashes +6
    assert (GOODS | 8380001) not in known and (ARMOR | 5350000) not in known and 3560000 not in known
    assert A.direct_item_id(0xB07FDE61) == GOODS | 8380001 and A.direct_item_id(0xA00003E8) == TALISMAN | 1000
    assert A.direct_item_id(0x808000C5) is None


def _slot(**kw):
    base = {
        "ga_items": [],
        "inventory": {"common": [], "key": [], "common_count": 0, "key_count": 0},
        "storage": {"common": [], "key": [], "common_count": 0, "key_count": 0},
        "chr_asm": [],
        "equipped_items": [],
        "quick": [(0, 0xFFFFFFFF)] * 10,
        "pouch": [(0, 0xFFFFFFFF)] * 6,
    }
    base.update(kw)
    return base


def test_scan_mod_items_finds_direct_goods_rows_and_worn():
    pot = 0xB07FDE61  # Tiny Great Pot, direct goods handle
    sword_h, hat_h, orphan_h = 0x80800010, 0x90800011, 0x80800012
    rows = [
        dict(gaitem_handle=sword_h, item_id=3560008, pos=0),
        dict(gaitem_handle=hat_h, item_id=ARMOR | 5360000, pos=21),
        dict(gaitem_handle=orphan_h, item_id=31540000, pos=37),
        dict(gaitem_handle=0x80800013, item_id=1000114, pos=58),
    ]
    inv = {
        "common": [(pot, 1, 5), (sword_h, 1, 6), (0, 0, 0), (hat_h, 1, 7), (0x80800013, 1, 8)],
        "key": [],
        "common_count": 3,
        "key_count": 0,
    }
    slot = _slot(
        ga_items=rows,
        inventory=inv,
        chr_asm=[5360000],
        equipped_items=[ARMOR | 5360000, GOODS | 8380001],
        pouch=[(pot, 9)] + [(0, 0xFFFFFFFF)] * 5,
    )
    scan = A.scan_mod_items(slot)
    by = {e["name"]: e for e in scan["held"]}
    pot_n, sword_n, hat_n = "Item 8380001", "Weapon 3560000 +8", "Armour 5360000"
    assert set(by) == {pot_n, sword_n, hat_n}
    assert by[pot_n]["pouch"] == [0] and not by[pot_n]["worn"] and by[pot_n]["row"] is None  # pouch goods strip
    assert by[hat_n]["worn"] and by[hat_n]["row"] == 1
    assert not by[sword_n]["worn"] and by[sword_n]["pos"] == 1  # past count still counts
    assert [o["name"] for o in scan["orphans"]] == ["Weapon 31540000"]
    plan = V.plan_restore({"ud10": {"active": [True]}, "slots": [slot]})
    assert [e["name"] for e in plan[0]["strip"]] == [pot_n, sword_n]  # worn goods strip via the pouch
    assert [b["name"] for b in plan[0]["blocked"]] == [hat_n]
    assert V.restore_needed(plan) and any(f"KEPT (worn) {hat_n}" in l for l in V.describe(plan))


def test_neutral_rows_keep_length():
    assert len(V._neutral_row(3560008)) == 21 - 4 and V._neutral_row(3560008)[:4] == struct.pack("<I", 110000)
    assert len(V._neutral_row(ARMOR | 5360000)) == 16 - 4 and V._neutral_row(ARMOR | 5360000)[:4] == struct.pack(
        "<I", ARMOR | 10000
    )
    assert V._neutral_row(0x80001234) == b"" and V.row_size(0x80001234) == 8 and V.row_size(0) == 8
    assert V.row_size(1000000) == 21 and V.row_size(ARMOR | 40000) == 16


def test_restore_vanilla_on_a_copy_of_the_live_save(tmp_path, monkeypatch):
    src = _live_save()
    if not src:
        pytest.skip("no live co-op save on this PC")
    monkeypatch.setattr(g.common, "game_running", lambda: False)
    copy = tmp_path / "ER0000.co2"
    shutil.copy2(src, copy)
    before = copy.read_bytes()
    r0 = L.parse(str(copy))
    plan = V.plan_restore(r0)
    if not V.restore_needed(plan):
        pytest.skip("live save has nothing to restore right now")
    info0 = g.save_info(copy)
    assert g.restore_available(info0) and g.repair_available(info0) and not info0["convert_ok"]
    out = g.restore_vanilla(copy)
    assert out["backup"] and out["backup"].read_bytes() == before
    after = copy.read_bytes()
    r1 = L.parse(str(copy))
    assert len(after) == len(before)
    touched = {d["slot"] for d in out["done"]}
    assert touched == {p["slot"] for p in plan if p["strip"] or p["orphans"]}
    for i in range(10):
        off = L.HEADER + i * F.SLOT_STRIDE
        if i not in touched:
            assert after[off : off + F.SLOT_STRIDE] == before[off : off + F.SLOT_STRIDE]
        else:
            assert r1["slot_md5_ok"][i]
            s0, s1 = r0["slots"][i], r1["slots"][i]
            # the flag table, coordinates and everything after the gaItem/inventory area are untouched
            p = next(p for p in plan if p["slot"] == i)
            assert (
                after[s0["event_flags_pos"] : off + F.SLOT_STRIDE]
                == before[s0["event_flags_pos"] : off + F.SLOT_STRIDE]
            )
            assert after[off + 0x10 : s0["ga_items_pos"]] == before[off + 0x10 : s0["ga_items_pos"]]
            # counts went down by exactly the number of stripped entries per list
            for box in ("inventory", "storage"):
                for lst in ("common", "key"):
                    n = sum(1 for e in p["strip"] if e["box"] == box and e["list"] == lst)
                    assert s1[box][lst + "_count"] == max(0, s0[box][lst + "_count"] - n)
            scan = A.scan_mod_items(s1, A.Catalog.for_save(r1))
            assert all(e["worn"] for e in scan["held"]) and not scan["orphans"]
            for e in p["strip"]:
                for qi in e["quick"]:
                    assert s1["quick"][qi] == (0, 0xFFFFFFFF) and s1["equipped_items"][22 + qi] == 0xFFFFFFFF
                for pi in e["pouch"]:
                    assert s1["pouch"][pi] == (0, 0xFFFFFFFF) and s1["equipped_items"][32 + pi] == 0xFFFFFFFF
    assert after[r0["ud10_pos"] :] == before[r0["ud10_pos"] :]
    plan2 = V.plan_restore(r1)
    assert not V.restore_needed(plan2)  # only blocked (worn) entries may remain
    assert {b["name"] for p in plan2 for b in p["blocked"]} == {b["name"] for b in out["blocked"]}
    again = V.apply_restore(copy)
    assert again["backup"] is None and again["done"] == []  # idempotent: nothing written the second time


def test_restore_refuses_while_game_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(g.common, "game_running", lambda: True)
    p = tmp_path / "ER0000.co2"
    p.write_bytes(b"x")
    with pytest.raises(RuntimeError):
        g.restore_vanilla(p)
    assert p.read_bytes() == b"x"
