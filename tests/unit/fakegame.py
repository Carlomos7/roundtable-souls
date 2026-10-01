"""Tiny game files for tests: archives (BND4), text tables (FMG) and DCX (zlib, so no Oodle is needed), built with the
launcher's own writers, and a stand-in for the game's archives (game.archives.read)."""

import struct

from roundtable_souls import formats
from roundtable_souls.game import archives as gamearchive

BND_HEADER = (
    b"BND4\0\0\0\0\0\0\x01\0"
    + b"\0\0\0\0"  # file count
    + struct.pack("<q", 0x40)
    + b"07D7R6\0\0"
    + struct.pack("<q", 0x24)
    + b"\0" * 8  # headers end
    + bytes([1, 0x74, 4, 0])
    + b"\0\0\0\0"
    + b"\0" * 8  # hash table
)
FMG_HEADER = bytes([0, 0, 2, 0]) + b"\0" * 4 + bytes([1, 0, 0, 0]) + b"\0" * 8 + struct.pack("<i", 0xFF) + b"\0" * 16
DCX_HEADER = (
    b"DCX\0"
    + struct.pack(">IIIII", 0x11000, 0x18, 0x24, 0x44, 0x4C)
    + b"DCS\0"
    + struct.pack(">II", 0, 0)
    + b"DCP\0DFLT"
    + struct.pack(">I", 0x20)
    + bytes([9, 0, 0, 0])
    + struct.pack(">III", 0, 0, 0)
    + struct.pack(">I", 0x10100)
    + b"DCA\0"
    + struct.pack(">I", 8)
)
assert len(BND_HEADER) == 0x40 and len(FMG_HEADER) == 0x28 and len(DCX_HEADER) == 0x4C


def bnd(files: dict[str, bytes]) -> bytes:
    """An archive of these files (name -> bytes), IDs in order."""
    entries = [formats.bnd4.Entry(f"N:\\GR\\data\\{name}", i, data) for i, (name, data) in enumerate(files.items())]
    return formats.bnd4.write_bnd4(formats.bnd4.Bnd4(BND_HEADER, 0x2E, 0x74, True, 4, entries))


def fmg(texts: dict[int, str | None]) -> bytes:
    return formats.fmg.write_fmg(formats.fmg.Fmg(FMG_HEADER, dict(texts)))


def dcx(body: bytes) -> bytes:
    return formats.dcx.pack(body, formats.dcx.Dcx(DCX_HEADER, b"DFLT"))


def files_of(raw: bytes) -> dict[str, bytes]:
    """name (the part after the last backslash) -> bytes of a (DCX) archive."""
    body, _ = formats.dcx.unpack(raw)
    return {(e.name or "").rsplit("\\", 1)[-1]: e.data for e in formats.bnd4.read_bnd4(body).entries}


def texts_of(raw: bytes, table: str) -> dict[int, str | None]:
    return formats.fmg.read_fmg(files_of(raw)[table]).entries


def game(monkeypatch, files: dict[str, bytes]) -> None:
    """The game's archives, as far as the tests ask: relative path -> the game's bytes."""
    low = {k.lower(): v for k, v in files.items()}
    monkeypatch.setattr(gamearchive, "read", lambda game_dir, rel: low.get(rel.replace("\\", "/").lower()))
