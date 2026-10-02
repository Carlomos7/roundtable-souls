"""Checksum repair on a COPY of a real co-op save (skipped without one); the original is never touched."""

import shutil

import pytest

from roundtable_souls.services import play as g
from support import live_save as _live_save

F = g.save_fix
L = g.save_layout_check


def test_checksum_fix_on_a_copy_of_the_live_save(tmp_path, monkeypatch):
    src = _live_save()
    if not src:
        pytest.skip("no live co-op save on this PC")
    monkeypatch.setattr(g.common, "game_running", lambda: False)
    copy = tmp_path / "ER0000.co2"
    shutil.copy2(src, copy)
    data = bytearray(copy.read_bytes())
    r = L.parse(str(copy))
    slot = next(i for i, a in enumerate(r["ud10"]["active"]) if a)
    assert F.repair_checksums(copy)["backup"] is None  # nothing stale: nothing written
    off = L.HEADER + slot * F.SLOT_STRIDE
    data[off] ^= 0xFF
    copy.write_bytes(data)  # stale slot checksum
    info = g.save_info(copy)
    assert info["checksum_fixes"]["slots"] == [slot] and g.repair_available(info)
    assert any(f["code"] == "slot_checksum" for f in info["findings"])
    out = g.fix_checksums(copy)
    assert out["slots"] == [slot] and out["backup"].is_file()
    assert L.parse(str(copy))["slot_md5_ok"][slot]
    assert g.save_info(copy)["checksum_fixes"] == {"slots": [], "ud10": False}


def test_fixes_refuse_while_game_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(g.common, "game_running", lambda: True)
    p = tmp_path / "ER0000.co2"
    p.write_bytes(b"x")
    with pytest.raises(RuntimeError):
        g.fix_loading(p)
    with pytest.raises(RuntimeError):
        g.fix_checksums(p)
    assert p.read_bytes() == b"x"
