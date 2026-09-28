"""Read-only structure check for BND4 saves (Nightreign uses this, then decrypts each section separately).

A FromSoftware PC save is a BND4 container: a header, one 32-byte entry per section (USER_DATA000, 001, ...), the
section names in UTF-16, then the sections themselves. The check here is the magic, the section count, and that every
section and name lies inside the file. That is enough to tell a whole save from a torn or truncated one, and to refuse
restoring something that is not a save at all.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

HEADER_SIZE = 0x40
ENTRY_SIZE = 0x20


class ContainerError(ValueError):
    """The file is not a whole save container."""


@dataclass(frozen=True)
class Section:
    name: str
    offset: int
    size: int


def sections(data: bytes) -> list[Section]:
    """Every section of a BND4 save, in file order. Raises ContainerError for anything that is not a whole one."""
    if len(data) < HEADER_SIZE or data[:4] != b"BND4":
        raise ContainerError("not a save container (no BND4 header)")
    count = struct.unpack_from("<i", data, 0x0C)[0]
    entry_size = struct.unpack_from("<q", data, 0x20)[0]
    if not 0 < count <= 64:
        raise ContainerError(f"implausible section count {count}")
    if entry_size != ENTRY_SIZE:
        raise ContainerError(f"unexpected entry size {entry_size:#x}")
    if HEADER_SIZE + count * ENTRY_SIZE > len(data):
        raise ContainerError("the section table runs past the end of the file")
    out = []
    for i in range(count):
        e = HEADER_SIZE + i * ENTRY_SIZE
        size = struct.unpack_from("<q", data, e + 0x08)[0]
        offset, name_offset = struct.unpack_from("<II", data, e + 0x10)
        if size < 0 or offset + size > len(data):
            raise ContainerError(f"section {i} runs past the end of the file (truncated save?)")
        end = data.find(b"\0\0", name_offset)
        while end >= 0 and (end - name_offset) % 2:
            end = data.find(b"\0\0", end + 1)
        if name_offset >= len(data) or end < 0:
            raise ContainerError(f"section {i} has no readable name")
        name = data[name_offset:end].decode("utf-16-le", errors="replace")
        out.append(Section(name, offset, size))
    return out


def check(data: bytes, expected_sections: int | None = None) -> list[Section]:
    """sections(), plus the section count the game is known to write. Raises ContainerError."""
    found = sections(data)
    if expected_sections is not None and len(found) != expected_sections:
        raise ContainerError(f"{len(found)} sections where the game writes {expected_sections}")
    return found
