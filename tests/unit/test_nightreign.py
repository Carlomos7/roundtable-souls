"""Nightreign save crypto: checksum identity, encrypt round-trip, regulation restore. Never writes a live save."""

from pathlib import Path

import pytest

from roundtable_souls.platform import paths as common
from roundtable_souls.saves import container
from roundtable_souls.saves import nightreign as nr
from roundtable_souls.services import saves

LIVE_NR = Path.home() / "AppData" / "Roaming" / "Nightreign"


def _payloads(reg=b"RSLT" + bytes(12)):
    return [(reg if i == 12 else bytes([i]) + bytes(15)) for i in range(14)]


def _ivs():
    return [bytes([i, *range(1, 16)]) for i in range(14)]


def _live_nr_save() -> Path | None:
    if not LIVE_NR.is_dir():
        return None
    for p in LIVE_NR.rglob("NR0000.co2"):
        if p.is_file():
            return p
    return None


def test_encrypt_round_trip_and_checksum_identity():
    payload = b"RSLT" + bytes(12)
    iv = bytes(range(16))
    dec = nr.wrap_plaintext(payload)
    assert nr.checksum_ok(dec) and nr.padding_ok(dec) and nr.rslt_payload(dec)
    blob = nr.encrypt_entry(iv, dec)
    iv2, dec2 = nr.decrypt_entry(blob)
    assert iv2 == iv and dec2 == dec
    patched = bytearray(dec2)
    nr.patch_checksum(patched)
    assert bytes(patched) == dec
    assert nr.encrypt_entry(iv, patched) == blob


def test_packed_save_is_healthy_and_rewrite_is_identity():
    data = nr.pack_save(_payloads(), ivs=_ivs())
    st = nr.inspect(data)
    assert st["checksum_all_ok"] and st["rslt"] and st["healthy"]
    assert nr.rewrite(data) == data


def test_stale_checksum_is_restored_without_changing_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "game_running", lambda: False)
    data = bytearray(nr.pack_save(_payloads(), ivs=_ivs()))
    orig = bytes(data)
    sec = container.sections(orig)[0]
    iv, dec = nr.decrypt_entry(orig[sec.offset : sec.offset + sec.size])
    dec = bytearray(dec)
    dec[nr.checksum_offset(dec)] ^= 0xFF
    data[sec.offset : sec.offset + sec.size] = nr.encrypt_entry(iv, dec)
    dirty = bytes(data)
    assert not nr.inspect(dirty)["checksum_all_ok"]
    assert nr.payload_of(nr.decrypt_entry(dirty[sec.offset : sec.offset + sec.size])[1]) == nr.payload_of(
        nr.decrypt_entry(orig[sec.offset : sec.offset + sec.size])[1]
    )
    p = tmp_path / "NR0000.co2"
    p.write_bytes(dirty)
    assert nr.repair(p, log=lambda *_: None)
    assert p.read_bytes() == orig
    assert nr.inspect(p.read_bytes())["healthy"]


def test_garbled_regulation_is_restored_from_sibling(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "game_running", lambda: False)
    ivs = _ivs()
    healthy = nr.pack_save(_payloads(), ivs=ivs)
    garbled = nr.pack_save(_payloads(reg=b"XXXX" + bytes(12)), ivs=ivs)
    assert not nr.inspect(garbled)["rslt"]
    dest = tmp_path / "NR0000.co2"
    dest.write_bytes(garbled)
    (tmp_path / "NR0000.co2.bak").write_bytes(healthy)
    assert nr.repair(dest, log=lambda *_: None)
    out = dest.read_bytes()
    assert nr.inspect(out)["healthy"]
    sec12 = container.sections(out)[12]
    assert nr.payload_of(nr.decrypt_entry(out[sec12.offset : sec12.offset + sec12.size])[1]).startswith(b"RSLT")


def test_healthy_save_repair_does_not_write(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "game_running", lambda: False)
    p = tmp_path / "NR0000.sl2"
    p.write_bytes(nr.pack_save(_payloads(), ivs=_ivs()))
    before = p.read_bytes()
    assert nr.repair(p, log=lambda *_: None) is False
    assert p.read_bytes() == before
    from roundtable_souls.saves import backups as save_backups

    assert not save_backups.backups(tmp_path).exists()


def test_save_info_flags_stale_checksum(tmp_path):
    data = bytearray(nr.pack_save(_payloads(), ivs=_ivs()))
    sec = container.sections(bytes(data))[3]
    iv, dec = nr.decrypt_entry(bytes(data)[sec.offset : sec.offset + sec.size])
    dec = bytearray(dec)
    dec[nr.checksum_offset(dec)] ^= 1
    data[sec.offset : sec.offset + sec.size] = nr.encrypt_entry(iv, dec)
    p = tmp_path / "NR0000.co2"
    p.write_bytes(data)
    info = saves.save_info(p)
    assert info["needs_repair"] and saves.repair_available(info)
    assert [f["code"] for f in info["findings"]] == ["layout", "checksum", "regulation"]
    assert info["findings"][1]["level"] == "warn"


def test_live_unmodified_save_checksums_and_rewrite_identity():
    src = _live_nr_save()
    if src is None:
        pytest.skip("no Nightreign NR0000.co2 on this PC")
    data = src.read_bytes()
    st = nr.inspect(data)
    assert st["checksum_all_ok"] and st["padding_ok"] and all(st["padding_ok"])
    assert st["rslt"] and st["healthy"]
    assert nr.rewrite(data) == data
    assert src.read_bytes() == data  # live file was only read
