"""Moving characters and whole files between saves. Runs on COPIES of a real co-op save (skipped without one); the
original is never written."""

import shutil
import struct

import pytest

from roundtable_souls.game import catalog as games
from roundtable_souls.saves import fix as F
from roundtable_souls.saves import layout as L
from roundtable_souls.saves import library as Lib
from roundtable_souls.saves import transfer as T
from support import copy_live_save as _copy

ER = games.ELDEN_RING


def _pair(tmp_path):
    co2 = _copy(tmp_path)
    sl2 = tmp_path / "ER0000.sl2"
    shutil.copy2(co2, sl2)
    return co2, sl2


def _first_and_free(path):
    chars = Lib.characters(path)
    if not chars:
        pytest.skip("this save has no characters")
    free = next((s for s in range(1, 11) if s not in {c["slot"] for c in chars}), None)
    if free is None:
        pytest.skip("this save has no free slot")
    return chars[0], free


def test_character_copies_into_a_free_slot_and_leaves_the_rest_byte_for_byte(tmp_path):
    co2, sl2 = _pair(tmp_path)
    who, free = _first_and_free(sl2)
    before = sl2.read_bytes()
    out = T.copy_character(co2, who["slot"], sl2, free)
    after = sl2.read_bytes()
    r = L.parse(str(sl2))
    assert r["ud10"]["active"][free - 1] and r["slot_md5_ok"][free - 1] and r["ud10_md5_ok"]
    got = next(c for c in Lib.characters(sl2) if c["slot"] == free)
    assert (got["name"], got["level"], got["seconds"]) == (who["name"], who["level"], who["seconds"])
    for c in Lib.characters(co2):  # every other slot is untouched
        o = L.HEADER + (c["slot"] - 1) * F.SLOT_STRIDE
        assert before[o : o + F.SLOT_STRIDE] == after[o : o + F.SLOT_STRIDE]
    assert before[r["ud11_pos"] :] == after[r["ud11_pos"] :]  # the regulation block too
    assert out["backup"].is_file() and out["replaces"] is None


def test_character_copy_moves_to_the_target_account(tmp_path):
    co2, sl2 = _pair(tmp_path)
    who, free = _first_and_free(sl2)
    data = bytearray(sl2.read_bytes())  # make the target another Steam account's save
    r = L.parse(str(sl2))
    other = r["ud10"]["steam_id"] + 1
    struct.pack_into("<Q", data, r["ud10_pos"] + 0x10 + 4, other)
    F._sign_ud10(data, r["ud10_pos"])
    sl2.write_bytes(bytes(data))
    plan = T.plan_character_copy(co2, who["slot"], sl2, free)
    assert plan["steam_id_changes"]
    T.copy_character(co2, who["slot"], sl2, free)
    assert L.parse(str(sl2))["slots"][free - 1]["steam_id"] == other


def test_compare_names_what_differs(tmp_path):
    co2, sl2 = _pair(tmp_path)
    assert all(r["change"] == "same" for r in T.compare(co2, sl2))
    who, free = _first_and_free(sl2)
    T.copy_character(co2, who["slot"], sl2, free)
    rows = {r["slot"]: r["change"] for r in T.compare(co2, sl2)}
    assert rows[free] == "b only"


def test_copying_a_whole_file_keeps_the_replaced_one_in_the_library(tmp_path):
    co2, sl2 = _pair(tmp_path)
    who, free = _first_and_free(sl2)
    T.copy_character(co2, who["slot"], sl2, free)  # now the two files differ
    changed = sl2.read_bytes()
    out = T.copy_file(co2, sl2, ER, keep_as="my standard run")
    assert sl2.read_bytes() == co2.read_bytes()
    kept = Lib.entry_path(tmp_path, out["kept"])
    assert kept.read_bytes() == changed and out["kept"]["name"] == "my standard run"
    assert [h["action"] for h in Lib.load(tmp_path)["history"]] == ["replaced"]
