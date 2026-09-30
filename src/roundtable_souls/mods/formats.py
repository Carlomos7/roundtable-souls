"""The containers the file merger reads and writes: DCX (a compressed file), BND4 (an archive of files) and FMG (a
text table). Layouts as the public modding libraries document them (SoulsFormats, GPL-3.0).

Everything round-trips: reading a file and writing it back without changes gives the same content, so a merged
file differs from its inputs only where they did.
"""

from __future__ import annotations

import ctypes
import struct
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from roundtable_souls.gamefiles import DCX_DATA_OFFSET, FormatError, dcx_decompress


# ----------------------------------------------------------------------------- DCX
@dataclass
class Dcx:
    header: bytes  # the 0x4C header as read (kind, compression level, flags)
    kind: bytes  # b"KRAK", b"DFLT" or b"ZSTD"


def unpack(raw: bytes, oodle=None) -> tuple[bytes, Dcx | None]:
    """(the file's content, how it was compressed) for a DCX file, or (raw, None) when it is not one."""
    if raw[:4] != b"DCX\0":
        return raw, None
    return dcx_decompress(raw, oodle), Dcx(bytes(raw[:DCX_DATA_OFFSET]), bytes(raw[0x28:0x2C]))


_compressor = None


def oodle_compressor(game_dir: Path | None):
    """The game's Oodle DLL's compressor, loaded once, or None (not Windows, or not found)."""
    global _compressor
    if _compressor is not None:
        return _compressor
    if sys.platform != "win32" or not game_dir:
        return None
    for dll in sorted(Path(game_dir).glob("oo2core_*_win64.dll"), reverse=True):
        try:
            lib = ctypes.WinDLL(str(dll))
        except OSError:
            continue
        _compressor = lib
        lib.OodleLZ_Compress.restype = ctypes.c_ssize_t
        lib.OodleLZ_Compress.argtypes = [
            ctypes.c_int, ctypes.c_char_p, ctypes.c_ssize_t, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ssize_t,
        ]  # fmt: skip
        lib.OodleLZ_CompressOptions_GetDefault.restype = ctypes.c_void_p
        lib.OodleLZ_CompressOptions_GetDefault.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.OodleLZ_GetCompressedBufferSizeNeeded.restype = ctypes.c_ssize_t
        lib.OodleLZ_GetCompressedBufferSizeNeeded.argtypes = [ctypes.c_ssize_t]
        return lib
    return None


class _Options(ctypes.Structure):
    _fields_ = [
        ("verbosity", ctypes.c_uint),
        ("minMatchLen", ctypes.c_int),
        ("seekChunkReset", ctypes.c_int),
        ("seekChunkLen", ctypes.c_int),
        ("profile", ctypes.c_int),
        ("dictionarySize", ctypes.c_int),
        ("spaceSpeedTradeoffBytes", ctypes.c_int),
        ("maxHuffmansPerChunk", ctypes.c_int),
        ("sendQuantumCRCs", ctypes.c_int),
        ("maxLocalDictionarySize", ctypes.c_int),
        ("makeLongRangeMatcher", ctypes.c_int),
        ("matchTableSizeLog2", ctypes.c_int),
    ]


KRAKEN = 8
BIG = 16 << 20  # above this, a faster compression level


def _kraken(body: bytes, level: int, lib) -> bytes:
    opts = _Options.from_address(lib.OodleLZ_CompressOptions_GetDefault(KRAKEN, level))
    mine = _Options()
    ctypes.memmove(ctypes.addressof(mine), ctypes.addressof(opts), ctypes.sizeof(_Options))
    mine.seekChunkReset = 1  # the game needs it
    mine.seekChunkLen = 0x40000
    size = lib.OodleLZ_GetCompressedBufferSizeNeeded(len(body))
    out = ctypes.create_string_buffer(size)
    got = lib.OodleLZ_Compress(KRAKEN, body, len(body), out, level, ctypes.byref(mine), None, None, None, 0)
    if got <= 0:
        raise FormatError("Oodle could not compress the file")
    return out.raw[:got]


def pack(body: bytes, how: Dcx | None, compressor=None) -> bytes:
    """Compress content the way `how` says (as the game's own copy was), or return it as is when it was not a DCX."""
    if how is None:
        return body
    header = bytearray(how.header)
    if how.kind == b"KRAK":
        if compressor is None:
            raise FormatError("writing Oodle-compressed files needs the game's oo2core DLL (Windows only)")
        level = header[0x30] or 6
        if len(body) > BIG:
            level = min(level, 4)  # about 40 times faster on the largest archives, a fifth bigger; read the same
        header[0x30] = level
        payload = _kraken(body, level, compressor)
    elif how.kind == b"DFLT":
        payload = zlib.compress(body, header[0x30] or 9)
    elif how.kind == b"ZSTD":
        from roundtable_souls.gamefiles import zstd

        payload = zstd.compress(body, header[0x30] or 15)
    else:
        raise FormatError(f"unknown DCX compression {how.kind!r}")
    struct.pack_into(">II", header, 0x1C, len(body), len(payload))
    out = bytes(header) + payload
    return out + b"\0" * (-len(out) % 0x10)


# ----------------------------------------------------------------------------- BND4
IDS, NAMES1, NAMES2, LONG_OFFSETS, COMPRESSION = 0x02, 0x04, 0x08, 0x10, 0x20


@dataclass
class Entry:
    name: str | None
    id: int
    data: bytes  # as stored (a file compressed inside the archive stays compressed)
    flags: int = 0x40
    uncompressed: int = -1

    @property
    def key(self) -> str:
        """What the merger matches entries by: the name (case-insensitive), else the ID."""
        return self.name.replace("\\", "/").lower() if self.name else f"#{self.id}"


@dataclass
class Bnd4:
    header: bytes  # the first 0x40 bytes as read
    format: int  # the format bits, in the order read (see _read_format)
    raw_format: int
    unicode: bool
    extended: int
    entries: list[Entry] = field(default_factory=list)


def _read_format(raw: int, bit_big_endian: bool) -> int:
    reverse = bit_big_endian or ((raw & 1) != 0 and (raw & 0x80) == 0)
    return raw if reverse else int(f"{raw:08b}"[::-1], 2)


def _entry_size(fmt: int) -> int:
    return (
        0x10
        + (8 if fmt & LONG_OFFSETS else 4)
        + (8 if fmt & COMPRESSION else 0)
        + (4 if fmt & IDS else 0)
        + (4 if fmt & (NAMES1 | NAMES2) else 0)
        + (8 if fmt == NAMES1 else 0)
    )


def is_bnd4(body: bytes) -> bool:
    return body[:4] == b"BND4"


def read_bnd4(body: bytes) -> Bnd4:
    if body[:4] != b"BND4":
        raise FormatError("not a BND4 archive")
    if body[9]:
        raise FormatError("big-endian archives are not supported")
    bit_big_endian = not body[0x0A]
    count = struct.unpack_from("<i", body, 0x0C)[0]
    entry_size = struct.unpack_from("<q", body, 0x20)[0]
    unicode = bool(body[0x30])
    raw_fmt = body[0x31]
    fmt = _read_format(raw_fmt, bit_big_endian)
    extended = body[0x32]
    if entry_size != _entry_size(fmt):
        raise FormatError(f"unexpected BND4 entry size {entry_size:#x}")
    out = Bnd4(bytes(body[:0x40]), fmt, raw_fmt, unicode, extended)
    for i in range(count):
        o = 0x40 + i * entry_size
        flags = body[o]
        at = o + 8
        csize = struct.unpack_from("<q", body, at)[0]
        at += 8
        usize = -1
        if fmt & COMPRESSION:
            usize = struct.unpack_from("<q", body, at)[0]
            at += 8
        if fmt & LONG_OFFSETS:
            data_at = struct.unpack_from("<q", body, at)[0]
            at += 8
        else:
            data_at = struct.unpack_from("<I", body, at)[0]
            at += 4
        fid = -1
        if fmt & IDS:
            fid = struct.unpack_from("<i", body, at)[0]
            at += 4
        name = None
        if fmt & (NAMES1 | NAMES2):
            name_at = struct.unpack_from("<I", body, at)[0]
            if unicode:
                end = name_at
                while body[end : end + 2] != b"\0\0":
                    end += 2
                name = body[name_at:end].decode("utf-16-le")
            else:
                end = body.index(b"\0", name_at)
                name = body[name_at:end].decode("shift_jis", errors="replace")
        out.entries.append(Entry(name, fid, bytes(body[data_at : data_at + csize]), flags, usize))
    return out


def _path_hash32(name: str) -> int:
    h = 0
    text = name.strip().replace("\\", "/").lower()
    if not text.startswith("/"):
        text = "/" + text
    for c in text:
        h = (h * 37 + ord(c)) & 0xFFFFFFFF
    return h


def _is_prime(n: int) -> bool:
    return n >= 2 and all(n % d for d in range(2, int(n**0.5) + 1))


def _hash_table(entries: list[Entry], at: int) -> bytes:
    groups = next(p for p in range(len(entries) // 7, 100001) if _is_prime(p))
    buckets: list[list[tuple[int, int]]] = [[] for _ in range(groups)]
    for i, e in enumerate(entries):
        h = _path_hash32(e.name or "")
        buckets[h % groups].append((h, i))
    table = bytearray(struct.pack("<qiBBBB", at + 16 + groups * 8, groups, 0x10, 8, 8, 0))
    start = 0
    for b in buckets:
        table += struct.pack("<ii", len(b), start)
        start += len(b)
    for b in buckets:
        for h, i in sorted(b):
            table += struct.pack("<Ii", h, i)
    return bytes(table)


def _align(n: int, a: int) -> int:
    return (n + a - 1) // a * a


def write_bnd4(b: Bnd4) -> bytes:
    fmt = b.format
    size = _entry_size(fmt)
    n = len(b.entries)
    names = bytearray()
    name_at = []
    names_start = 0x40 + n * size
    for e in b.entries:
        name_at.append(names_start + len(names))
        if fmt & (NAMES1 | NAMES2):
            names += (
                (e.name or "").encode("utf-16-le") + b"\0\0"
                if b.unicode
                else (e.name or "").encode("shift_jis") + b"\0"
            )
    headers_end = names_start + len(names)
    table = b""
    table_at = 0
    if b.extended == 4:
        table_at = _align(headers_end, 8)
        table = _hash_table(b.entries, table_at)
        headers_end = table_at + len(table)
    out = bytearray(b.header)
    struct.pack_into("<i", out, 0x0C, n)
    struct.pack_into("<q", out, 0x28, headers_end)
    struct.pack_into("<q", out, 0x38, table_at)
    data_at = []
    pos = headers_end
    for e in b.entries:
        if e.data:
            pos = _align(pos, 0x10)
        data_at.append(pos)
        pos += len(e.data)
    for i, e in enumerate(b.entries):
        row = bytearray(struct.pack("<B3xi", e.flags, -1))
        row += struct.pack("<q", len(e.data))
        if fmt & COMPRESSION:
            row += struct.pack("<q", e.uncompressed if e.uncompressed >= 0 else len(e.data))
        row += struct.pack("<q", data_at[i]) if fmt & LONG_OFFSETS else struct.pack("<I", data_at[i])
        if fmt & IDS:
            row += struct.pack("<i", e.id)
        if fmt & (NAMES1 | NAMES2):
            row += struct.pack("<I", name_at[i])
        if fmt == NAMES1:
            row += struct.pack("<ii", e.id, 0)
        out += row
    out += names
    if table:
        out += b"\0" * (table_at - len(out))
        out += table
    for i, e in enumerate(b.entries):
        out += b"\0" * (data_at[i] - len(out))
        out += e.data
    return bytes(out)


# ----------------------------------------------------------------------------- FMG (version 2: Elden Ring)
@dataclass
class Fmg:
    header: bytes  # the first 0x28 bytes as read
    entries: dict[int, str | None]  # text ID -> text (None: an ID listed without text)


def is_fmg(body: bytes) -> bool:
    return len(body) >= 0x28 and body[0] == 0 and body[2] == 2 and struct.unpack_from("<i", body, 0x04)[0] == len(body)


def read_fmg(body: bytes) -> Fmg:
    if body[2] != 2:
        raise FormatError("only version 2 text tables (Elden Ring) are supported")
    groups = struct.unpack_from("<i", body, 0x0C)[0]
    offsets_at = struct.unpack_from("<q", body, 0x18)[0]
    entries: dict[int, str | None] = {}
    for g in range(groups):
        index, first, last, _pad = struct.unpack_from("<iiii", body, 0x28 + g * 16)
        for k, text_id in enumerate(range(first, last + 1)):
            at = struct.unpack_from("<q", body, offsets_at + (index + k) * 8)[0]
            if at > 0:
                end = at
                while body[end : end + 2] != b"\0\0":
                    end += 2
                entries[text_id] = body[at:end].decode("utf-16-le")
            else:
                entries[text_id] = None
    return Fmg(bytes(body[:0x28]), entries)


def write_fmg(f: Fmg) -> bytes:
    ids = sorted(f.entries)
    groups = []
    i = 0
    while i < len(ids):
        start = i
        while i + 1 < len(ids) and ids[i + 1] == ids[i] + 1:
            i += 1
        groups.append((start, ids[start], ids[i]))
        i += 1
    head = bytearray(f.header)
    struct.pack_into("<ii", head, 0x0C, len(groups), len(ids))
    out = head + b"".join(struct.pack("<iiii", s, a, b, 0) for s, a, b in groups)
    offsets_at = len(out)
    struct.pack_into("<q", out, 0x18, offsets_at)
    strings = bytearray()
    strings_at = offsets_at + 8 * len(ids)
    offsets = []
    for text_id in ids:
        text = f.entries[text_id]
        if text is None:
            offsets.append(0)
        else:
            offsets.append(strings_at + len(strings))
            strings += text.encode("utf-16-le") + b"\0\0"
    out += b"".join(struct.pack("<q", o) for o in offsets) + strings
    out += b"\0" * (-len(out) % 4)  # the game's own tables end on a multiple of 4
    struct.pack_into("<i", out, 0x04, len(out))
    return bytes(out)
