"""FMG: the game's text tables (version 2, Elden Ring). Text IDs in ranges, and UTF-16 strings."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from roundtable_souls.formats import FormatError
from roundtable_souls.formats.bnd4 import _utf16z


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


def fmg_entries(blob: bytes) -> dict[int, str]:
    """Text ID -> text for an FMG table (version 2). Empty entries are skipped."""
    groups = struct.unpack_from("<i", blob, 0x0C)[0]
    offsets_at = struct.unpack_from("<q", blob, 0x18)[0]
    out = {}
    for g in range(groups):
        index, first, last, _pad = struct.unpack_from("<iiii", blob, 0x28 + g * 16)
        for k, text_id in enumerate(range(first, last + 1)):
            at = struct.unpack_from("<q", blob, offsets_at + (index + k) * 8)[0]
            if at > 0:
                text = _utf16z(blob, at).strip()
                if text:
                    out[text_id] = text
    return out
