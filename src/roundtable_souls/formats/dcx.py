"""DCX: the compressed wrapper around most game files. A 0x4C-byte header (kind, sizes, compression level) and the
payload: KRAK (Oodle Kraken, with the game's own library), DFLT (zlib) or ZSTD.

Kraken needs the game's Oodle library, which this module never looks for: callers pass its codecs in (game.oodle
makes them; tests pass stand-ins). Anything with decompress(payload, size) or compress_kraken(body, level) will do;
a ValueError from either becomes a FormatError here."""

from __future__ import annotations

import struct
import zlib
from compression import zstd
from dataclasses import dataclass
from typing import Protocol

from roundtable_souls.formats import FormatError

DCX_DATA_OFFSET = 0x4C
# The layouts written, each loaded in game (Elden Ring; data/games/eldenring.json lists them and a test keeps the two
# the same). Kraken: level 6 in the payload and in the header (the "6/6" layout). DFLT fallback: zlib level 9. ZSTD: a
# 64 KB window and no content size in the frame (the game's decoder keeps 64 KB of history: zstd's defaults crash it).
KRAKEN_LEVEL = 6
DFLT_FALLBACK_LEVEL = 9
ZSTD_LEVEL = 9
ZSTD_WINDOW_LOG = 16


class KrakenDecompressor(Protocol):
    def decompress(self, payload: bytes, usize: int) -> bytes: ...


class KrakenCompressor(Protocol):
    def compress_kraken(self, body: bytes, level: int) -> bytes: ...


def zstd_frame(body: bytes, level: int = ZSTD_LEVEL) -> bytes:
    """A zstd frame the game reads: a 64 KB window, and the content size left out of the frame header."""
    P = zstd.CompressionParameter
    return zstd.compress(
        body, options={P.compression_level: level, P.content_size_flag: 0, P.window_log: ZSTD_WINDOW_LOG}
    )


def dcx_decompress(data: bytes, oodle: KrakenDecompressor | None = None) -> bytes:
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
        try:
            return oodle.decompress(payload, usize)
        except FormatError:
            raise
        except ValueError as e:
            raise FormatError(str(e)) from e
    raise FormatError(f"unknown DCX compression {kind!r}")


@dataclass
class Dcx:
    header: bytes  # the 0x4C header as read (kind, compression level, flags)
    kind: bytes  # b"KRAK", b"DFLT" or b"ZSTD"


def unpack(raw: bytes, oodle: KrakenDecompressor | None = None) -> tuple[bytes, Dcx | None]:
    """(the file's content, how it was compressed) for a DCX file, or (raw, None) when it is not one."""
    if raw[:4] != b"DCX\0":
        return raw, None
    return dcx_decompress(raw, oodle), Dcx(bytes(raw[:DCX_DATA_OFFSET]), bytes(raw[0x28:0x2C]))


def pack(
    body: bytes, how: Dcx | None, compressor: KrakenCompressor | None = None, dflt_fallback: bool = False
) -> bytes:
    """Compress content the way `how` says (as the game's own copy was), or return it as is when it was not a DCX.
    dflt_fallback: without the game's Oodle library, write a KRAK file as DFLT instead (only for file types the game
    has loaded so; see game.config) rather than stop."""
    if how is None:
        return body
    header = bytearray(how.header)
    if how.kind == b"KRAK" and compressor is None and dflt_fallback:
        header[0x28:0x2C] = b"DFLT"
        header[0x30] = DFLT_FALLBACK_LEVEL
        payload = zlib.compress(body, DFLT_FALLBACK_LEVEL)
    elif how.kind == b"KRAK":
        if compressor is None:
            raise FormatError("writing Oodle-compressed files needs the game's oo2core DLL (Windows only)")
        header[0x30] = KRAKEN_LEVEL
        try:
            payload = compressor.compress_kraken(body, KRAKEN_LEVEL)
        except FormatError:
            raise
        except ValueError as e:
            raise FormatError(str(e)) from e
    elif how.kind == b"DFLT":
        payload = zlib.compress(body, header[0x30] or 9)
    elif how.kind == b"ZSTD":
        header[0x30] = ZSTD_LEVEL
        payload = zstd_frame(body)
    else:
        raise FormatError(f"unknown DCX compression {how.kind!r}")
    struct.pack_into(">II", header, 0x1C, len(body), len(payload))
    out = bytes(header) + payload
    return out + b"\0" * (-len(out) % 0x10)
