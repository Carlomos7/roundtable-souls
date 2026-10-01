"""PARAM: one parameter table of the regulation. A row is its ID, its bytes and its (editor-only) name; nothing here
knows what a field means. Reading and writing keeps every row (repeated IDs included, in order), names and the
table's metadata, so an unchanged table is written back byte for byte."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from roundtable_souls.formats import FormatError

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


def param_row_ids(blob: bytes) -> list[int]:
    """Row IDs of a PARAM table (the 64-bit layout the game uses)."""
    count = struct.unpack_from("<H", blob, 0x0A)[0]
    return [struct.unpack_from("<I", blob, 0x40 + i * 24)[0] for i in range(count)]
