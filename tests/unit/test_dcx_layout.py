"""Kraken files are written with the tested Elden Ring layout (6/6): compression level 6, and the header the game's
own Kraken files carry, whatever the size of the file or the level its source recorded. Oodle itself is not needed
here: the compressor is stood in for, so these run on any platform."""

import struct

import pytest

from roundtable_souls import formats

# The 0x4C header of the game's own Kraken files, sizes zeroed (the layout the game's files and the public format
# libraries agree on: DCX version 0x11000, DCS / DCP "KRAK", level 6, 0x10100, DCA).
ER_KRAKEN_HEADER = (
    b"DCX\0"
    + struct.pack(">IIIII", 0x11000, 0x18, 0x24, 0x44, 0x4C)
    + b"DCS\0"
    + struct.pack(">II", 0, 0)
    + b"DCP\0KRAK"
    + struct.pack(">I", 0x20)
    + bytes([6, 0, 0, 0])
    + struct.pack(">III", 0, 0, 0)
    + struct.pack(">I", 0x10100)
    + b"DCA\0"
    + struct.pack(">I", 8)
)
assert len(ER_KRAKEN_HEADER) == 0x4C


def _without_sizes(header: bytes) -> bytes:
    h = bytearray(header[:0x4C])
    h[0x1C:0x24] = b"\0" * 8
    return bytes(h)


class FakeKraken:
    """Stands in for Oodle: records the level asked for and returns a small fake payload."""

    def __init__(self):
        self.levels: list[int] = []

    def compress_kraken(self, body: bytes, level: int) -> bytes:
        self.levels.append(level)
        return b"K" * 7


@pytest.mark.parametrize("source_level", [6, 9, 4])
@pytest.mark.parametrize("size", [100, (16 << 20) + 1])  # the old faster-level cutoff was 16 MB
def test_kraken_files_are_written_6_6_with_the_games_header(source_level, size):
    source = bytearray(ER_KRAKEN_HEADER)
    source[0x30] = source_level  # a source file that recorded another level
    kraken = FakeKraken()
    out = formats.dcx.pack(b"\0" * size, formats.dcx.Dcx(bytes(source), b"KRAK"), compressor=kraken)
    assert kraken.levels == [6]
    assert _without_sizes(out) == ER_KRAKEN_HEADER
    assert struct.unpack_from(">II", out, 0x1C) == (size, 7)
    assert len(out) % 0x10 == 0


def test_the_games_own_header_is_kept_byte_for_byte():
    out = formats.dcx.pack(b"body", formats.dcx.Dcx(ER_KRAKEN_HEADER, b"KRAK"), compressor=FakeKraken())
    assert out[:0x1C] == ER_KRAKEN_HEADER[:0x1C] and out[0x24:0x4C] == ER_KRAKEN_HEADER[0x24:0x4C]


def test_the_level_is_one_named_constant():
    assert formats.dcx.KRAKEN_LEVEL == 6
