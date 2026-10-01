"""Read and write Elden Ring's regulation.bin: AES-256-CBC around a DCX (ZSTD) around a BND4 archive of PARAM tables.

Writing keeps every structure the game's own file has and only recomputes what changes (row counts, offsets, sizes,
the archive's hash table), so rebuilding an unchanged regulation gives back the same archive bytes. The archive (BND4)
is the shared one in formats.py. Nothing here
knows what a field means: a row is its ID, its bytes and its (editor-only) name.
"""

from __future__ import annotations

import os
import struct
from compression import zstd
from dataclasses import dataclass, replace

from roundtable_souls.gamefiles import (
    DCX_DATA_OFFSET,
    REGULATION_KEY,
    FormatError,
    dcx_decompress,
    decrypt_regulation,
)
from roundtable_souls.mods.formats import COMPRESSION, IDS, NAMES1, NAMES2, Bnd4, read_bnd4, write_bnd4

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


# ----------------------------------------------------------------------------- the binder
# The regulation's binder is a BND4 archive read and written by the shared code in formats.py. What is particular to
# it is checked and kept here: its layout, and each table's stored size taken from its data on write.
REGULATION_FORMAT = IDS | NAMES1 | NAMES2 | COMPRESSION  # 0x74 as stored: 36-byte entries with IDs and Unicode names
REGULATION_ENTRY = 36


def read_binder(body: bytes) -> Bnd4:
    """The regulation's binder. Refuses another layout rather than guess at it."""
    b = read_bnd4(body)
    if b.format != REGULATION_FORMAT or not b.unicode or struct.unpack_from("<q", body, 0x20)[0] != REGULATION_ENTRY:
        raise FormatError("unsupported BND4 layout")
    return b


def binder_bytes(b: Bnd4) -> bytes:
    """The binder as the game's regulation stores it. Every table's uncompressed size is its length (tables are not
    compressed inside the binder), so a table that was edited never keeps the size it was read with."""
    return write_bnd4(replace(b, entries=[replace(e, uncompressed=-1) for e in b.entries]))


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
    return Regulation(bytes(dec[:DCX_DATA_OFFSET]), read_binder(dcx_decompress(dec, oodle)))


ZSTD_WINDOW_LOG = 16  # 64 KB window: every zstd block then holds at most 64 KB, which the game requires (below)


def compress_regulation_body(body: bytes, level: int = 9) -> bytes:
    """The zstd frame the game accepts.

    The game crashes at start (access violation) on a frame whose blocks hold more than 64 KB of data, which is what
    zstd writes by default (128 KB). Its own regulation and every editor's output (SoulsFormats, Soulstruct) keep
    blocks at 64 KB by capping the window at 64 KB, and leave the content size out of the frame header. Checked in
    game on Elden Ring 1.17.1 (2026-09-30): the game's own bytes re-encrypted load; the same content recompressed
    with default blocks crashes, whatever the IV, level or window.
    """
    P = zstd.CompressionParameter
    return zstd.compress(
        body, options={P.compression_level: level, P.content_size_flag: 0, P.window_log: ZSTD_WINDOW_LOG}
    )


def write_regulation(reg: Regulation, level: int = 9) -> bytes:
    """The encrypted file. Always ZSTD (what the game's own regulation uses)."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    body = binder_bytes(reg.bnd)
    payload = compress_regulation_body(body, level)
    header = bytearray(reg.dcx_header)
    if header[0x28:0x2C] != b"ZSTD":
        raise FormatError("the base regulation is not ZSTD-compressed; rebuild from the game's own file")
    struct.pack_into(">II", header, 0x1C, len(body), len(payload))
    plain = bytes(header) + payload
    plain += b"\0" * (-len(plain) % 16)
    iv = os.urandom(16)
    enc = Cipher(algorithms.AES(REGULATION_KEY), modes.CBC(iv)).encryptor()
    return iv + enc.update(plain) + enc.finalize()
