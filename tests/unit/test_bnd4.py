"""The shared BND4 archive code (mods/formats.py) serving both general archives and the regulation's binder, on small
binders built here. Byte-exactness on the game's own files is a real-data check (scripts/verify/bnd4_roundtrip.py)."""

import struct

import pytest

from roundtable_souls.mods import formats
from roundtable_souls.mods import paramfile as pf

GAMEPARAM = "N:\\GR\\data\\Param\\param\\GameParam\\"


def header(*, unicode: bool = True, raw_format: int = 0x74, entry_size: int = 36) -> bytes:
    """A 0x40 BND4 header as the game's own binders have it (little-endian, format bits in stored order)."""
    hdr = bytearray(0x40)
    hdr[0:4] = b"BND4"
    hdr[0x08:0x0C] = bytes.fromhex("00000100")
    struct.pack_into("<q", hdr, 0x10, 0x40)
    hdr[0x18:0x20] = b"11711000"
    struct.pack_into("<q", hdr, 0x20, entry_size)
    hdr[0x30:0x34] = bytes([int(unicode), raw_format, 4, 0])
    return bytes(hdr)


def binder(tables: dict[str, bytes]) -> formats.Bnd4:
    entries = [formats.Entry(GAMEPARAM + name, i, data) for i, (name, data) in enumerate(tables.items())]
    return formats.Bnd4(header(), pf.REGULATION_FORMAT, 0x74, True, 4, entries)


def test_the_regulation_layout_is_the_stored_format_0x74():
    assert pf.REGULATION_FORMAT == 0x2E  # IDs, both name bits, compression sizes: bit-reversed 0x74
    assert formats._entry_size(pf.REGULATION_FORMAT) == pf.REGULATION_ENTRY == 36


def test_a_regulation_binder_round_trips_byte_for_byte_through_the_shared_code():
    body = pf.binder_bytes(binder({"A.param": b"a" * 40, "B.param": b"bb" * 33, "C.param": b"c" * 7}))
    back = pf.read_binder(body)
    assert [(e.name, e.id, e.data, e.flags) for e in back.entries] == [
        (GAMEPARAM + "A.param", 0, b"a" * 40, 0x40),
        (GAMEPARAM + "B.param", 1, b"bb" * 33, 0x40),
        (GAMEPARAM + "C.param", 2, b"c" * 7, 0x40),
    ]
    assert pf.binder_bytes(back) == formats.write_bnd4(back) == body


def test_an_edited_table_is_stored_with_its_new_size():
    # The regulation's rule: a table's stored uncompressed size is its length. The general writer keeps the size an
    # entry was read with (unchanged behaviour for other archives), so the binder is written through binder_bytes.
    back = pf.read_binder(pf.binder_bytes(binder({"A.param": b"a" * 40})))
    back.entries[0].data = b"z" * 64
    body = pf.binder_bytes(back)
    row = 0x40
    assert struct.unpack_from("<qq", body, row + 8) == (64, 64)
    assert struct.unpack_from("<qq", formats.write_bnd4(back), row + 8) == (64, 40)


@pytest.mark.parametrize(
    "bad",
    [
        header(unicode=False),  # names in Shift-JIS
        header(raw_format=0x54, entry_size=28),  # no compression sizes: another entry layout
    ],
)
def test_another_layout_is_refused_as_a_regulation_binder(bad):
    b = formats.Bnd4(bad, formats._read_format(bad[0x31], not bad[0x0A]), bad[0x31], bool(bad[0x30]), 4, [])
    with pytest.raises(formats.FormatError):
        pf.read_binder(formats.write_bnd4(b))


def test_entries_are_found_by_file_name_ignoring_case_and_folders():
    b = binder({"EquipParamWeapon.param": b"w", "SpEffectParam.param": b"s"})
    found = b.get("equipparamweapon.PARAM")
    assert found is not None and found.data == b"w"
    assert b.get("Missing.param") is None


def test_the_archive_hash_is_the_games():
    assert formats.path_hash(GAMEPARAM + "merged\\DLC02\\ActionButtonParam.param") == 2001576758
