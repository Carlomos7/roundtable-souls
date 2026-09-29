"""Read and write Elden Ring's regulation.bin: AES-256-CBC around a DCX (ZSTD) around a BND4 archive of PARAM tables.

Writing keeps every structure the game's own file has and only recomputes what changes (row counts, offsets, sizes,
the archive's hash table), so rebuilding an unchanged regulation gives back the same archive bytes. Nothing here
knows what a field means: a row is its ID, its bytes and its (editor-only) name.
"""

from __future__ import annotations

import os
import struct
from compression import zstd
from dataclasses import dataclass, field

from roundtable_souls.gamefiles import (
    DCX_DATA_OFFSET,
    REGULATION_KEY,
    FormatError,
    dcx_decompress,
    decrypt_regulation,
)

NO_NAME = -1  # Param.shared_name when every row's name offset is 0
ROW_HEADER = 24  # u32 id, u32 pad, i64 data offset, i64 name offset (the 64-bit layout the game uses)
PARAM_HEADER = 0x40


# ----------------------------------------------------------------------------- PARAM
@dataclass
class Row:
    id: int
    data: bytes
    name: str = ""


@dataclass
class Param:
    """One PARAM table. header is the 0x40 header as read; tail is everything after the row data (the type string and
    the names area); shared_name is the offset, within tail, of the one empty name every nameless row points at."""

    header: bytes
    rows: list[Row]
    stride: int
    tail: bytes
    shared_name: int | None
    unicode_names: bool
    data_end: int = 0  # where the row data ended in the bytes it was read from
    source: bytes = b""  # the bytes it was read from

    @property
    def type_name(self) -> str:
        return self.tail.split(b"\0", 1)[0].decode("ascii", "replace")


def _name(blob: bytes, at: int, unicode: bool) -> str:
    if at <= 0 or at >= len(blob):
        return ""
    if unicode:
        end = at
        while end + 1 < len(blob) and blob[end : end + 2] != b"\0\0":
            end += 2
        return blob[at:end].decode("utf-16-le", "replace")
    end = blob.find(b"\0", at)
    return blob[at : end if end >= 0 else len(blob)].decode("shift_jis", "replace")


def read_param(blob: bytes) -> Param:
    if len(blob) < PARAM_HEADER:
        raise FormatError("PARAM too short")
    header = bytes(blob[:PARAM_HEADER])
    if header[0x2C] != 0:
        raise FormatError("big-endian PARAM")
    unicode = bool(header[0x2E] & 1)
    count = struct.unpack_from("<H", blob, 0x0A)[0]
    raw = [struct.unpack_from("<IIqq", blob, PARAM_HEADER + i * ROW_HEADER) for i in range(count)]
    table_end = PARAM_HEADER + count * ROW_HEADER
    type_at = struct.unpack_from("<q", blob, 0x10)[0]
    if count == 0:
        stride, data_end = 0, table_end
    elif count == 1:
        stride = (type_at if table_end <= type_at <= len(blob) else len(blob)) - raw[0][2]
        data_end = raw[0][2] + stride
    else:
        stride = raw[1][2] - raw[0][2]
        data_end = raw[-1][2] + stride
        if any(raw[i + 1][2] - raw[i][2] != stride for i in range(count - 1)):
            raise FormatError("PARAM rows are not evenly spaced")
    if stride < 0 or data_end > len(blob):
        raise FormatError("PARAM row data runs past the file")
    names = {r[3] for r in raw}
    shared = None  # rows with names of their own
    if names == {0}:
        shared = NO_NAME  # no row has a name at all (offset 0)
    elif len(names) == 1 and raw[0][3] >= data_end:
        shared = raw[0][3] - data_end  # every row points at one empty name after the type string
    rows = [
        Row(r[0], bytes(blob[r[2] : r[2] + stride]), "" if shared is not None else _name(blob, r[3], unicode))
        for r in raw
    ]
    tail = bytes(blob[data_end:])
    if shared is None:  # names of their own: keep the type string, names are written again
        end = tail.find(b"\0")
        tail = tail[: end + 1] if end >= 0 else tail
    return Param(header, rows, stride, tail, shared, unicode, data_end, bytes(blob))


def write_param(p: Param) -> bytes:
    rows = p.rows  # in the order given: the game's own tables are not all sorted, and some repeat an ID
    n = len(rows)
    table_end = PARAM_HEADER + n * ROW_HEADER
    data_end = table_end + n * p.stride
    tail = bytearray(p.tail)
    named = [r for r in rows if r.name]
    offsets: list[int] = []
    if p.shared_name == NO_NAME and not named:
        name_at = [0] * n
    elif p.shared_name is not None and not named:
        name_at = [data_end + p.shared_name] * n
    else:
        tail = bytearray(p.tail.split(b"\0", 1)[0] + b"\0")  # the type string; the names follow it
        base = len(tail)
        if p.unicode_names and (data_end + base) % 2:
            tail += b"\0"
        empty = None
        for r in rows:
            enc = (
                r.name.encode("utf-16-le") + b"\0\0"
                if p.unicode_names
                else r.name.encode("shift_jis", "replace") + b"\0"
            )
            if not r.name and empty is not None:
                offsets.append(empty)
                continue
            offsets.append(data_end + len(tail))
            if not r.name:
                empty = offsets[-1]
            tail += enc
        name_at = offsets
    header = bytearray(p.header)
    struct.pack_into("<H", header, 0x0A, n)
    type_at_old = struct.unpack_from("<q", p.header, 0x10)[0]
    shift = data_end - p.data_end
    struct.pack_into("<q", header, 0x10, type_at_old + shift)
    strings_old = struct.unpack_from("<I", p.header, 0x00)[0]
    struct.pack_into("<I", header, 0x00, max(0, strings_old + shift))
    struct.pack_into("<q", header, 0x30, table_end)
    out = bytearray(header)
    for i, r in enumerate(rows):
        out += struct.pack("<IIqq", r.id, 0, table_end + i * p.stride, name_at[i])
    for r in rows:
        if len(r.data) != p.stride:
            raise FormatError(f"row {r.id} is {len(r.data)} bytes, the table's rows are {p.stride}")
        out += r.data
    out += tail
    return bytes(out)


# ----------------------------------------------------------------------------- BND4
@dataclass
class BndFile:
    name: str  # the full path as stored (N:\GR\data\Param\param\GameParam\...)
    data: bytes
    id: int = 0
    flags: int = 0x40


@dataclass
class Bnd4:
    header: bytes  # the 0x40 header as read
    files: list[BndFile] = field(default_factory=list)

    def get(self, short: str) -> BndFile | None:
        low = short.lower()
        return next((f for f in self.files if f.name.replace("\\", "/").rsplit("/", 1)[-1].lower() == low), None)


def read_bnd4(body: bytes) -> Bnd4:
    if body[:4] != b"BND4":
        raise FormatError("not a BND4 archive")
    count = struct.unpack_from("<i", body, 0x0C)[0]
    header_size = struct.unpack_from("<q", body, 0x20)[0]
    if header_size != 36 or body[0x30] != 1 or body[0x31] != 0x74:
        raise FormatError("unsupported BND4 layout")
    files = []
    for i in range(count):
        o = 0x40 + i * header_size
        flags = body[o]
        size = struct.unpack_from("<q", body, o + 8)[0]
        data_at, fid, name_at = struct.unpack_from("<IiI", body, o + 24)
        end = name_at
        while body[end : end + 2] != b"\0\0":
            end += 2
        files.append(BndFile(body[name_at:end].decode("utf-16-le"), bytes(body[data_at : data_at + size]), fid, flags))
    return Bnd4(bytes(body[:0x40]), files)


def path_hash(name: str) -> int:
    h = 0
    text = name.strip().replace("\\", "/").lower()
    if not text.startswith("/"):
        text = "/" + text
    for c in text:
        h = (h * 37 + ord(c)) & 0xFFFFFFFF
    return h


def _is_prime(n: int) -> bool:
    if n < 2:
        return False
    return all(n % d for d in range(2, int(n**0.5) + 1))


def _hash_table(files: list[BndFile], at: int) -> bytes:
    groups = next(p for p in range(len(files) // 7, 100001) if _is_prime(p))
    buckets: list[list[tuple[int, int]]] = [[] for _ in range(groups)]
    for i, f in enumerate(files):
        h = path_hash(f.name)  # the whole stored path, drive included
        buckets[h % groups].append((h, i))
    table = bytearray()
    hashes_at = at + 16 + groups * 8
    table += struct.pack("<qiBBBB", hashes_at, groups, 0x10, 8, 8, 0)
    start = 0
    for b in buckets:
        table += struct.pack("<ii", len(b), start)
        start += len(b)
    for b in buckets:
        for h, i in sorted(b):  # by hash within each group, as the game's own files have them
            table += struct.pack("<Ii", h, i)
    return bytes(table)


def _align(n: int, a: int) -> int:
    return (n + a - 1) // a * a


def write_bnd4(b: Bnd4) -> bytes:
    n = len(b.files)
    names = bytearray()
    name_at = []
    names_start = 0x40 + n * 36
    for f in b.files:
        name_at.append(names_start + len(names))
        names += f.name.encode("utf-16-le") + b"\0\0"
    hash_at = _align(names_start + len(names), 8)
    table = _hash_table(b.files, hash_at)
    data_start = _align(hash_at + len(table), 16)
    out = bytearray(b.header)
    struct.pack_into("<i", out, 0x0C, n)
    struct.pack_into("<q", out, 0x28, data_start)
    struct.pack_into("<q", out, 0x38, hash_at)
    data_at = []
    pos = data_start
    for f in b.files:
        pos = _align(pos, 16)
        data_at.append(pos)
        pos += len(f.data)
    for i, f in enumerate(b.files):
        out += struct.pack(
            "<B7sqqIiI", f.flags, b"\0\0\0\xff\xff\xff\xff", len(f.data), len(f.data), data_at[i], f.id, name_at[i]
        )
    out += names
    out += b"\0" * (hash_at - len(out))
    out += table
    out += b"\0" * (data_start - len(out))
    for i, f in enumerate(b.files):
        out += b"\0" * (data_at[i] - len(out))
        out += f.data
    return bytes(out)


# ----------------------------------------------------------------------------- DCX and encryption
@dataclass
class Regulation:
    dcx_header: bytes  # the 0x4C DCX header as read
    bnd: Bnd4

    @property
    def version(self) -> str:
        """The regulation version the archive names (e.g. 11711000)."""
        return self.bnd.header[0x18:0x20].decode("ascii", "replace").strip("\0")


def read_regulation(raw: bytes, oodle=None) -> Regulation:
    dec = decrypt_regulation(raw)
    if dec[:4] != b"DCX\0":
        raise FormatError("not a DCX file")
    return Regulation(bytes(dec[:DCX_DATA_OFFSET]), read_bnd4(dcx_decompress(dec, oodle)))


def write_regulation(reg: Regulation, level: int = 9) -> bytes:
    """The encrypted file. Always ZSTD (what the game's own regulation uses)."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    body = write_bnd4(reg.bnd)
    payload = zstd.compress(body, level)
    header = bytearray(reg.dcx_header)
    if header[0x28:0x2C] != b"ZSTD":
        raise FormatError("the base regulation is not ZSTD-compressed; rebuild from the game's own file")
    struct.pack_into(">II", header, 0x1C, len(body), len(payload))
    plain = bytes(header) + payload
    plain += b"\0" * (-len(plain) % 16)
    iv = os.urandom(16)
    enc = Cipher(algorithms.AES(REGULATION_KEY), modes.CBC(iv)).encryptor()
    return iv + enc.update(plain) + enc.finalize()
