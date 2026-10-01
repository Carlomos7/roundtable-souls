"""The shared BND4 archive code (formats/bnd4.py) serving both general archives and the regulation's binder, on small
binders built here. Byte-exactness on the game's own files is a real-data check (scripts/verify/bnd4_roundtrip.py)."""

import struct

import pytest

from roundtable_souls import formats

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


def binder(tables: dict[str, bytes]) -> formats.bnd4.Bnd4:
    entries = [formats.bnd4.Entry(GAMEPARAM + name, i, data) for i, (name, data) in enumerate(tables.items())]
    return formats.bnd4.Bnd4(header(), formats.regulation.REGULATION_FORMAT, 0x74, True, 4, entries)


def test_the_regulation_layout_is_the_stored_format_0x74():
    assert formats.regulation.REGULATION_FORMAT == 0x2E  # IDs, both name bits, compression sizes: bit-reversed 0x74
    assert formats.bnd4._entry_size(formats.regulation.REGULATION_FORMAT) == formats.regulation.REGULATION_ENTRY == 36


def test_a_regulation_binder_round_trips_byte_for_byte_through_the_shared_code():
    body = formats.regulation.binder_bytes(binder({"A.param": b"a" * 40, "B.param": b"bb" * 33, "C.param": b"c" * 7}))
    back = formats.regulation.read_binder(body)
    assert [(e.name, e.id, e.data, e.flags) for e in back.entries] == [
        (GAMEPARAM + "A.param", 0, b"a" * 40, 0x40),
        (GAMEPARAM + "B.param", 1, b"bb" * 33, 0x40),
        (GAMEPARAM + "C.param", 2, b"c" * 7, 0x40),
    ]
    assert formats.regulation.binder_bytes(back) == formats.bnd4.write_bnd4(back) == body


def sizes(body: bytes, i: int) -> tuple[int, int]:
    """(stored size, uncompressed size) from the i-th entry header of a binder with 36-byte entries."""
    return struct.unpack_from("<qq", body, 0x40 + i * 36 + 8)


@pytest.mark.parametrize("new_length", [64, 5], ids=["grows", "shrinks"])
def test_an_entry_whose_data_changes_is_stored_with_its_new_size(new_length):
    body = formats.bnd4.write_bnd4(binder({"A.param": b"a" * 40, "B.param": b"b" * 24}))
    b = formats.bnd4.read_bnd4(body)
    assert b.entries[0].uncompressed == 40
    b.entries[0].data = b"z" * new_length  # replaced in place: the entry still holds the size it was read with
    out = formats.bnd4.write_bnd4(b)
    assert sizes(out, 0) == (new_length, new_length) and sizes(out, 1) == (24, 24)
    back = formats.bnd4.read_bnd4(out)
    assert [e.data for e in back.entries] == [b"z" * new_length, b"b" * 24]
    assert formats.regulation.binder_bytes(back) == out  # the regulation's binder follows the same rule


def test_an_unchanged_binder_is_written_back_byte_for_byte():
    body = formats.bnd4.write_bnd4(binder({"A.param": b"a" * 40, "B.param": b"", "C.param": b"c" * 17}))
    assert formats.bnd4.write_bnd4(formats.bnd4.read_bnd4(body)) == body


def test_a_compressed_entry_keeps_the_size_its_writer_gave():
    # Only the code that compressed an entry knows its decompressed size; the archive writer cannot recompute it.
    b = binder({"A.param": b"packed"})
    b.entries[0].flags = 0x40 | formats.bnd4.ENTRY_COMPRESSED
    b.entries[0].uncompressed = 1000
    assert sizes(formats.bnd4.write_bnd4(b), 0) == (6, 1000)


@pytest.mark.parametrize("text", ["a much longer replacement text than before", "x"], ids=["grows", "shrinks"])
def test_text_added_to_a_text_archive_is_stored_with_its_new_size(text):
    from fakegame import fmg

    from roundtable_souls.merging.rules import fmg as fmg_rule

    menu = fmg({1: "first", 2: "second entry"})
    archive = formats.bnd4.Bnd4(
        header(),
        formats.regulation.REGULATION_FORMAT,
        0x74,
        True,
        4,
        [formats.bnd4.Entry("N:\\GR\\data\\Menu.fmg", 0, menu)],
    )
    out = fmg_rule.add_text(formats.bnd4.write_bnd4(archive), "Menu.fmg", {2: text})
    entry = formats.bnd4.read_bnd4(out).entries[0]
    assert sizes(out, 0) == (len(entry.data), len(entry.data)) and len(entry.data) != len(menu)
    assert formats.fmg.read_fmg(entry.data).entries[2] == text


@pytest.mark.parametrize(
    "bad",
    [
        header(unicode=False),  # names in Shift-JIS
        header(raw_format=0x54, entry_size=28),  # no compression sizes: another entry layout
    ],
)
def test_another_layout_is_refused_as_a_regulation_binder(bad):
    b = formats.bnd4.Bnd4(bad, formats.bnd4._read_format(bad[0x31], not bad[0x0A]), bad[0x31], bool(bad[0x30]), 4, [])
    with pytest.raises(formats.FormatError):
        formats.regulation.read_binder(formats.bnd4.write_bnd4(b))


def test_entries_are_found_by_file_name_ignoring_case_and_folders():
    b = binder({"EquipParamWeapon.param": b"w", "SpEffectParam.param": b"s"})
    found = b.get("equipparamweapon.PARAM")
    assert found is not None and found.data == b"w"
    assert b.get("Missing.param") is None


def test_the_archive_hash_is_the_games():
    assert formats.bnd4.path_hash(GAMEPARAM + "merged\\DLC02\\ActionButtonParam.param") == 2001576758
