"""Tests for the analyzer tuning and the save_fix repairs. The write tests run on a COPY of the
live ER0000.co2 in a temp folder and are skipped when this PC has no save; the live file is never touched."""
import shutil

import pytest

from roundtable_souls import core as g
from support import live_save as _live_save

A = g.save_analyze
F = g.save_fix
L = g.save_layout_check


def test_item_known_handles_placeholders_and_affinity():
    known = {9000000, 9000001, 9000025, 1020000, 67700000, 0x40000000 | 100}
    assert A._item_known(0, known) and A._item_known(0xFFFFFFFF, known)
    assert A._item_known(A.UNARMED_WEAPON, known)                      # fist placeholder in every empty weapon slot
    for naked in A.NAKED_ARMOR:
        assert A._item_known(0x10000000 | naked, known)                 # empty armour slots
    assert A._item_known(9000914, known)                                # Heavy Uchigatana +14 -> base row 9000000
    assert A._item_known(9001225, known)                                # affinity 12 +25 -> 9000025 or base
    assert A._item_known(1020300, known)
    assert not A._item_known(34910004, known)                           # not a vanilla seal
    assert not A._item_known(0x10000000 | 742000, known)                # mod armour
    assert not A._item_known(0x40000000 | 101, known)


def test_info_findings_do_not_block_conversion():
    info = [{"level": "info", "code": "orphan_item", "title": "t", "detail": ""},
            {"level": "ok", "code": "regulation", "title": "t", "detail": ""},
            {"level": "ok", "code": "layout", "title": "t", "detail": ""}]
    assert A.findings_are_clean(info)
    assert not A.findings_are_clean(info + [{"level": "warn", "code": "unknown_item", "title": "t", "detail": ""}])
    text = A.format_health_report({"findings": info})
    assert "[INFO]" in text


def test_referenced_handles_cover_inventory_storage_and_equipment():
    slot = {"inventory": {"common_count": 1, "common": [(0xB0000001, 1, 0), (0xB0000009, 1, 1)], "key_count": 0, "key": []},
            "storage": {"common_count": 0, "common": [], "key_count": 1, "key": [(0xB0000002, 1, 0)]},
            "equip_data": [0x80800003, 0], "chr_asm": [], "chr_asm2": [0x90800004], "equipped_items": [110000],
            "quick": [(0x40000005, 0)], "pouch": []}
    refs = A._referenced_handles(slot)
    # every non-zero entry counts, past the count too: the game keeps sparse arrays
    assert refs == {0xB0000001, 0xB0000009, 0xB0000002, 0x80800003, 0x90800004, 110000, 0x40000005}


def test_set_flag_roundtrip_and_fixers_clear_detection():
    if not A._bst_map():
        pytest.skip("flag BST not bundled")
    flags = bytearray(A.EVENT_FLAGS_SIZE)
    assert A.get_flag(bytes(flags), A.GOLEM_DEFEATED) is False
    F.set_flag(flags, A.GOLEM_DEFEATED, True)
    assert A.get_flag(bytes(flags), A.GOLEM_DEFEATED) is True
    assert "unte_golem_stuck" in A.detect_flag_issues(bytes(flags))
    F.FIXERS["unte_golem_stuck"](flags)
    assert A.get_flag(bytes(flags), A.GOLEM_DESTROYED) is True
    assert "unte_golem_stuck" not in A.detect_flag_issues(bytes(flags))
    F.set_flag(flags, A.GOLEM_DEFEATED, False)
    assert A.get_flag(bytes(flags), A.GOLEM_DEFEATED) is False
    # every detector key has a fixer, and each fixer clears its own detection
    for key in A._FLAG_ISSUE_TITLES:
        assert key in F.FIXERS
    flags = bytearray(A.EVENT_FLAGS_SIZE)
    F.set_flag(flags, A.RANNI_BLOCKING, True); assert "ranni_softlock" in A.detect_flag_issues(bytes(flags))
    F.FIXERS["ranni_softlock"](flags); assert "ranni_softlock" not in A.detect_flag_issues(bytes(flags))
    flags = bytearray(A.EVENT_FLAGS_SIZE)
    F.set_flag(flags, A.MORGOTT_DEFEATED, True); assert "morgott_warp" in A.detect_flag_issues(bytes(flags))
    F.FIXERS["morgott_warp"](flags); assert "morgott_warp" not in A.detect_flag_issues(bytes(flags))
    with pytest.raises(F.FixError):
        F.set_flag(bytearray(10), 1, True)


def test_repair_available_predicate():
    assert not g.repair_available({"needs_repair": False, "quest_fixes": [], "checksum_fixes": {"slots": [], "ud10": False}})
    assert g.repair_available({"needs_repair": True})
    assert g.repair_available({"quest_fixes": [{"slot": 1}]})
    assert g.repair_available({"checksum_fixes": {"slots": [0], "ud10": False}})
    assert g.repair_available({"checksum_fixes": {"slots": [], "ud10": True}})


def test_quest_fix_on_a_copy_of_the_live_save(tmp_path, monkeypatch):
    src = _live_save()
    if not src:
        pytest.skip("no live co-op save on this PC")
    monkeypatch.setattr(g.common, "game_running", lambda: False)
    copy = tmp_path / "ER0000.co2"; shutil.copy2(src, copy)
    before = L.parse(str(copy))
    plan = F.plan_quest_fixes(before)
    if not plan:
        pytest.skip("live save has no soft-lock to fix right now")
    original = copy.read_bytes()
    out = g.fix_quest_flags(copy)
    assert [p["slot"] for p in out["fixed"]] == [p["slot"] for p in plan]
    assert out["backup"] and out["backup"].read_bytes() == original and out["backup"].parent.name == F.BACKUP_DIR
    after = L.parse(str(copy))
    assert all(after["slot_md5_ok"][p["slot"]] for p in plan)
    assert after["ud10_md5_ok"] == before["ud10_md5_ok"] and after["ud11_md5_ok"] == before["ud11_md5_ok"]
    assert not F.plan_quest_fixes(after)
    # untouched slots are byte-identical; touched slots differ only inside the flag table and the checksum
    new = copy.read_bytes(); touched = {p["slot"] for p in plan}
    for i in range(10):
        off = L.HEADER + i * F.SLOT_STRIDE
        if i not in touched:
            assert new[off: off + F.SLOT_STRIDE] == original[off: off + F.SLOT_STRIDE]
        else:
            fp = before["slots"][i]["event_flags_pos"]
            assert new[off + 0x10: fp] == original[off + 0x10: fp]
            assert new[fp + A.EVENT_FLAGS_SIZE: off + F.SLOT_STRIDE] == original[fp + A.EVENT_FLAGS_SIZE: off + F.SLOT_STRIDE]
    assert new[before["ud10_pos"]:] == original[before["ud10_pos"]:]
    assert g.save_info(copy)["quest_fixes"] == []


def test_checksum_fix_on_a_copy_of_the_live_save(tmp_path, monkeypatch):
    src = _live_save()
    if not src:
        pytest.skip("no live co-op save on this PC")
    monkeypatch.setattr(g.common, "game_running", lambda: False)
    copy = tmp_path / "ER0000.co2"; shutil.copy2(src, copy)
    data = bytearray(copy.read_bytes())
    r = L.parse(str(copy)); slot = next(i for i, a in enumerate(r["ud10"]["active"]) if a)
    assert F.repair_checksums(copy)["backup"] is None                    # nothing stale: nothing written
    off = L.HEADER + slot * F.SLOT_STRIDE
    data[off] ^= 0xFF; copy.write_bytes(data)                            # stale slot checksum
    info = g.save_info(copy)
    assert info["checksum_fixes"]["slots"] == [slot] and g.repair_available(info)
    assert any(f["code"] == "slot_checksum" for f in info["findings"])
    out = g.fix_checksums(copy)
    assert out["slots"] == [slot] and out["backup"].is_file()
    assert L.parse(str(copy))["slot_md5_ok"][slot]
    assert g.save_info(copy)["checksum_fixes"] == {"slots": [], "ud10": False}


def test_fixes_refuse_while_game_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(g.common, "game_running", lambda: True)
    p = tmp_path / "ER0000.co2"; p.write_bytes(b"x")
    with pytest.raises(RuntimeError):
        g.fix_quest_flags(p)
    with pytest.raises(RuntimeError):
        g.fix_checksums(p)
    assert p.read_bytes() == b"x"
