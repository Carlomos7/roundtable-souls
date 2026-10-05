"""Checksum repair on a COPY of a real co-op save (skipped without one); the original is never touched."""

import shutil

import pytest

from roundtable_souls.platform import paths
from roundtable_souls.saves import layout as save_layout_check
from roundtable_souls.services import play as g
from roundtable_souls.services import saves as saves_service
from support import er
from support import live_save as _live_save

F = g.save_fix
L = save_layout_check


def test_checksum_fix_on_a_copy_of_the_live_save(tmp_path, monkeypatch):
    src = _live_save()
    if not src:
        pytest.skip("no live co-op save on this PC")
    monkeypatch.setattr(paths, "exe_running", lambda _exe: False)
    copy = tmp_path / "ER0000.co2"
    shutil.copy2(src, copy)
    data = bytearray(copy.read_bytes())
    r = L.parse(str(copy))
    slot = next(i for i, a in enumerate(r["ud10"]["active"]) if a)
    assert F.repair_checksums(copy)["backup"] is None  # nothing stale: nothing written
    off = L.HEADER + slot * F.SLOT_STRIDE
    data[off] ^= 0xFF
    copy.write_bytes(data)  # stale slot checksum
    info = g.save_info(copy, loc=er())
    assert info["checksum_fixes"]["slots"] == [slot] and saves_service.repair_available(info)
    assert any(f["code"] == "slot_checksum" for f in info["findings"])
    out = saves_service.fix_checksums(copy, loc=er())
    assert out["slots"] == [slot] and out["backup"].is_file()
    assert L.parse(str(copy))["slot_md5_ok"][slot]
    assert g.save_info(copy, loc=er())["checksum_fixes"] == {"slots": [], "ud10": False}


def test_fixes_refuse_while_game_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "exe_running", lambda _exe: True)
    p = tmp_path / "ER0000.co2"
    p.write_bytes(b"x")
    with pytest.raises(RuntimeError):
        saves_service.fix_loading(p, loc=er())
    with pytest.raises(RuntimeError):
        saves_service.fix_checksums(p, loc=er())
    assert p.read_bytes() == b"x"
