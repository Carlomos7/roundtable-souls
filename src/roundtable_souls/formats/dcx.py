"""DCX: the compressed wrapper around most game files. A 0x4C-byte header (kind, sizes, compression level) and the
payload: KRAK (Oodle Kraken, with the game's own library), DFLT (zlib) or ZSTD."""

from __future__ import annotations

import struct
import zlib
from compression import zstd
from dataclasses import dataclass

from roundtable_souls.formats import FormatError
from roundtable_souls.game import oodle as game_oodle

DCX_DATA_OFFSET = 0x4C
# Kraken files are written with the layout of the tested Elden Ring files: compression level 6 in the payload and the
# same 6 in the header (the "6/6" layout). Other levels and header values are not written until tested in game.
KRAKEN_LEVEL = 6


def dcx_decompress(data: bytes, oodle=None) -> bytes:
    """Unpack a DCX file (ZSTD, DFLT or, with the game's Oodle, KRAK)."""
    if data[:4] != b"DCX\0":
        raise FormatError("not a DCX file")
    usize, csize = struct.unpack_from(">II", data, 0x1C)
    kind = data[0x28:0x2C]
    payload = data[DCX_DATA_OFFSET : DCX_DATA_OFFSET + csize]
    if kind == b"ZSTD":
        return zstd.decompress(payload)
    if kind == b"DFLT":
        return zlib.decompress(payload)
    if kind == b"KRAK":
        if oodle is None:
            raise FormatError("Oodle compression needs the game's oo2core DLL (Windows only)")
        return game_oodle.decompress(oodle, payload, usize)
    raise FormatError(f"unknown DCX compression {kind!r}")


@dataclass
class Dcx:
    header: bytes  # the 0x4C header as read (kind, compression level, flags)
    kind: bytes  # b"KRAK", b"DFLT" or b"ZSTD"


def unpack(raw: bytes, oodle=None) -> tuple[bytes, Dcx | None]:
    """(the file's content, how it was compressed) for a DCX file, or (raw, None) when it is not one."""
    if raw[:4] != b"DCX\0":
        return raw, None
    return dcx_decompress(raw, oodle), Dcx(bytes(raw[:DCX_DATA_OFFSET]), bytes(raw[0x28:0x2C]))


def pack(body: bytes, how: Dcx | None, compressor=None) -> bytes:
    """Compress content the way `how` says (as the game's own copy was), or return it as is when it was not a DCX."""
    if how is None:
        return body
    header = bytearray(how.header)
    if how.kind == b"KRAK":
        if compressor is None:
            raise FormatError("writing Oodle-compressed files needs the game's oo2core DLL (Windows only)")
        header[0x30] = KRAKEN_LEVEL
        payload = game_oodle.compress_kraken(body, KRAKEN_LEVEL, compressor)
    elif how.kind == b"DFLT":
        payload = zlib.compress(body, header[0x30] or 9)
    elif how.kind == b"ZSTD":
        payload = zstd.compress(body, header[0x30] or 15)
    else:
        raise FormatError(f"unknown DCX compression {how.kind!r}")
    struct.pack_into(">II", header, 0x1C, len(body), len(payload))
    out = bytes(header) + payload
    return out + b"\0" * (-len(out) % 0x10)
