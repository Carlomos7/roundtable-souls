"""BND4: the game's archive format. Named entries with IDs and flags, a hash table of their paths, and the data.

read_bnd4/write_bnd4 keep every structure as read (format bits, entry order, names, IDs, flags, alignment, the hash
table), so an unchanged archive is written back byte for byte. bnd4_files is a small reader of names and data only."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from roundtable_souls.formats import FormatError

IDS, NAMES1, NAMES2, LONG_OFFSETS, COMPRESSION = 0x02, 0x04, 0x08, 0x10, 0x20
ENTRY_COMPRESSED = 0x01  # an entry's flag: its data is compressed inside the archive


@dataclass
class Entry:
    name: str | None
    id: int
    data: bytes  # as stored (a file compressed inside the archive stays compressed)
    flags: int = 0x40
    uncompressed: int = -1  # its size decompressed; only used for a compressed entry (see write_bnd4)

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

    def get(self, short: str) -> Entry | None:
        """The first entry whose file name (the last part of its path) is `short`, ignoring case."""
        low = short.lower()
        return next(
            (e for e in self.entries if (e.name or "").replace("\\", "/").rsplit("/", 1)[-1].lower() == low), None
        )


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


def path_hash(name: str) -> int:
    """The archive's hash of a stored path (the whole path, drive included)."""
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
        h = path_hash(e.name or "")
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


def _uncompressed_size(e: Entry) -> int:
    """The entry header's second size: the entry decompressed. An entry stored as it is (every entry of the game's own
    archives checked) is its own length, whatever size it was read with, so an entry whose data was replaced is never
    stored with its old size. Only for a compressed entry is the size the caller set used, since it cannot be known
    here without decompressing."""
    if e.flags & ENTRY_COMPRESSED and e.uncompressed >= 0:
        return e.uncompressed
    return len(e.data)


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
            row += struct.pack("<q", _uncompressed_size(e))
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


def _utf16z(data: bytes, offset: int) -> str:
    end = offset
    while data[end : end + 2] != b"\0\0":
        end += 2
    return data[offset:end].decode("utf-16-le")


def bnd4_files(body: bytes) -> list[tuple[str, bytes]]:
    """(file name without folders, bytes) for every file in a BND4 archive of the kind the game uses (format 0x74)."""
    if body[:4] != b"BND4":
        raise FormatError("not a BND4 archive")
    count = struct.unpack_from("<i", body, 0x0C)[0]
    header_size = struct.unpack_from("<q", body, 0x20)[0]
    if not body[0x30] or header_size < 36:
        raise FormatError("unsupported BND4 layout")
    files = []
    for i in range(count):
        o = 0x40 + i * header_size
        size = struct.unpack_from("<q", body, o + 8)[0]
        data_offset, _id, name_offset = struct.unpack_from("<III", body, o + 24)
        name = _utf16z(body, name_offset).replace("\\", "/").rsplit("/", 1)[-1]
        files.append((name, body[data_offset : data_offset + size]))
    return files
