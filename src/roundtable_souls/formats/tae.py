# Adapted from SoulsFormatsNEXT (https://github.com/soulsmods/SoulsFormatsNEXT), SoulsFormats/Formats/TAE/TAE.cs,
# Animation.cs, Event.cs and EventGroup.cs at commit ee1dd61958f60bdc51ce3da548e9a90a8ab39905 (the TAE folder last
# changed in d0caa7ab7749e1a575fb3056b9b65020e81de826, 2026-01-21). SoulsFormats is by TKGP and the SoulsFormatsNEXT
# contributors; its TAE code was originally sourced from SoulsAssetPipeline by Meowmartius. Licensed under the GNU
# General Public License v3.0, as is Roundtable Souls (the same license text is in LICENSE).
#
# Modified for Roundtable Souls, 2026-10-05:
#   - translated from C# to Python; one layout only, Elden Ring's (version 0x1000D, 64-bit, little-endian); the
#     other games' layouts (Demon's Souls, Dark Souls 1 to 3, Bloodborne, Sekiro) are refused;
#   - event parameters are kept as raw bytes (with their padding): event templates (Template.cs) and the parameter
#     container were not taken;
#   - an event's parameters run to the next structure in the file (the reference reads up to the next event's data,
#     the group headers or the next animation's data);
#   - kept as stored, where the reference normalized: an event's end time (the reference read float.MaxValue as 100
#     and wrote anything from 100 up as float.MaxValue), the order of each event group's members (the reference
#     rewrote it in event order), and the difference between no animation file name stored (the game's own files)
#     and an empty one ("\0\0", as SoulsFormats writes it; the reference read both as "" and wrote the second);
#   - the file-level animation groups are read and must be the runs of consecutive animation IDs the writer makes
#     (the reference skipped them); two animations with one ID, a second animation count other than the first, an
#     event in two groups, a group member that is not one of the animation's events, and an event whose parameters
#     do not follow it (Sekiro's event type 943) are refused;
#   - the reference's name-detection heuristics (the probes for 1 and for a float) were replaced: a stored name is
#     one whose offset is not where another structure starts. Every TAE file in the game's character animation
#     archives (906 in 37 archives, the player's 642 among them) and the copies of the player's two mods ship are
#     written back byte for byte (scripts/verify/tae_roundtrip.py).

"""Elden Ring TAE files (animation events: what happens when during each animation), read and written structurally.

A TAE has a file header (an ID, the event bank, flags, the skeleton and sib file names) and animations by ID. Each
animation has a header (a standard one, with flags and the ID of an animation whose motion data it uses, or one that
imports another animation's motion and events whole), a file name, its events in stored order (start and end time, a
type and raw parameter bytes) and event groups (a type and the events in it). Writing lays the file out as the game's
own files are, so those come back byte for byte.

An event's parameters are kept with the zero padding that follows them (their size is set by the event type, which
this code does not know). Where an event's data starts decides how much padding there is, so an edit that moves it
(adding or removing an event before it) can change the padding: comparisons (animation_key) leave trailing zero bytes
of the parameters out.
"""

from __future__ import annotations

__all__ = ["TAE", "Animation", "Event", "EventGroup", "animation_key", "header_key", "is_tae", "read_tae", "write_tae"]

import bisect
import struct
from dataclasses import dataclass, field

from roundtable_souls.formats import FormatError

MAGIC = b"TAE "
VERSION = 0x1000D
HEADER_SIZE = 0xD0

# 64-bit values the header always has in this layout: offset -> value
_HEADER_CONSTANTS = {
    0x10: 0x40,
    0x18: 1,
    0x20: 0x50,
    0x28: 0x80,
    0x38: 0,
    0x68: 0xA0,
    0x80: 1,
    0x88: 0x90,
    0x98: 0x50,
    0xA0: 0,
    0xA8: 0xB0,
    0xC0: 0,
    0xC8: 0,
}
STANDARD = 0  # an animation header with flags and the animation whose motion data (HKX) it uses
IMPORT = 1  # an animation header that imports another animation's motion data and events whole


@dataclass
class Event:
    start: float
    end: float
    type: int
    unk04: int
    params: bytes  # raw, with the zero padding that follows them


@dataclass
class EventGroup:
    type: int
    members: list[int]  # indices into the animation's events, in stored order


@dataclass
class Animation:
    id: int
    header_type: int  # STANDARD or IMPORT
    header: bytes | None  # its 8 bytes of settings; None when the animation has no header data
    file_name: str | None  # None: no name stored; "": an empty name stored
    events: list[Event] = field(default_factory=list)
    groups: list[EventGroup] = field(default_factory=list)

    @property
    def source_id(self) -> int | None:
        """The animation whose data this one uses: the motion data of a standard header that imports it, or the
        animation an import header takes whole. None when it uses its own."""
        if self.header is None:
            return None
        if self.header_type == IMPORT:
            return struct.unpack_from("<i", self.header, 0)[0]
        if self.header[1]:
            return struct.unpack_from("<i", self.header, 4)[0]
        return None


@dataclass
class TAE:
    id: int
    event_bank: int
    flags: bytes  # 8 bytes
    skeleton_name: str | None
    sib_name: str | None
    animations: list[Animation] = field(default_factory=list)


def is_tae(body: bytes) -> bool:
    """An Elden Ring TAE (version 0x1000D, 64-bit, little-endian); other games' TAE layouts are not."""
    return (
        len(body) >= HEADER_SIZE
        and body[:4] == MAGIC
        and body[4:8] == b"\0\0\0\xff"
        and struct.unpack_from("<i", body, 8)[0] == VERSION
    )


def header_key(t: TAE) -> tuple:
    """The file header's values, for comparing two files' headers."""
    return (t.id, t.event_bank, bytes(t.flags), t.skeleton_name, t.sib_name)


def animation_key(a: Animation) -> tuple:
    """Everything an animation is, for comparing two copies of it. An empty file name and none stored are the same
    (the game's files store none; tools that rewrite a TAE store an empty one); times are compared bit for bit, and
    parameters without their trailing zero bytes (the padding)."""
    return (
        a.id,
        a.header_type,
        a.header,
        a.file_name or "",
        tuple((_f32(e.start), _f32(e.end), e.type, e.unk04, e.params.rstrip(b"\0")) for e in a.events),
        tuple((g.type, tuple(g.members)) for g in a.groups),
    )


# ----------------------------------------------------------------------------- reading
def read_tae(data: bytes) -> TAE:
    data = bytes(data)
    if not is_tae(data):
        raise FormatError("not an Elden Ring TAE (version 0x1000D, 64-bit)")
    r = _Reader(data)
    for off, want in _HEADER_CONSTANTS.items():
        r.expect(off, want, "header")
    if data[0x48:0x50] != b"\x01\0\0\0\0\0\0\0":
        raise FormatError("unexpected TAE header bytes at 0x48")
    tae_id, count = r.i32(0x50), r.i32(0x54)
    if r.i32(0x90) != tae_id or r.i32(0x94) != tae_id:
        raise FormatError("the TAE's ID is not repeated in its header")
    if r.q(0x70) != count:
        raise FormatError("the TAE's two animation counts differ")
    anims_off, groups_off, first_body = r.q(0x58), r.q(0x60), r.q(0x78)
    skel_off, sib_off = r.q(0xB0), r.q(0xB8)

    ids = [r.q(anims_off + 16 * i) for i in range(count)]
    if len(set(ids)) != len(ids):
        raise FormatError("the TAE has two animations with the same ID")
    bodies = [r.q(anims_off + 16 * i + 8) for i in range(count)]
    group_count, group_ptr = r.q(groups_off), r.q(groups_off + 8)
    groups = [
        (r.i32(group_ptr + 16 * k), r.i32(group_ptr + 16 * k + 4), r.q(group_ptr + 16 * k + 8))
        for k in range(group_count)
    ]
    if groups != _id_runs(ids, anims_off):
        raise FormatError("the TAE's animation groups are not the runs of consecutive animation IDs")

    bounds = {HEADER_SIZE, len(data), anims_off, groups_off, group_ptr, first_body, skel_off, sib_off}
    raw = []
    for body in bodies:
        ev, gr, tm, fo = r.q(body), r.q(body + 8), r.q(body + 16), r.q(body + 24)
        ec, gc = r.i32(body + 32), r.i32(body + 36)
        r.expect32(body + 44, 0, "animation")
        data_offs = [r.q(ev + 24 * j + 16) for j in range(ec)]
        group_heads = [(r.q(gr + 32 * k), r.q(gr + 32 * k + 8), r.q(gr + 32 * k + 16)) for k in range(gc)]
        bounds.update((body, ev, gr, tm, fo, *data_offs))
        bounds.update(x for _, vo, to in group_heads for x in (vo, to))
        raw.append((ev, gr, tm, fo, ec, data_offs, group_heads))
    bounds.discard(0)
    ordered = sorted(bounds)

    def next_bound(at: int) -> int:
        return ordered[bisect.bisect_left(ordered, at)]

    animations = []
    for anim_id, (ev, gr, _tm, fo, ec, data_offs, group_heads) in zip(ids, raw, strict=True):
        events = []
        for j in range(ec):
            h = ev + 24 * j
            d = data_offs[j]
            if r.q(d + 8) != d + 16:
                raise FormatError(f"animation {anim_id}: event {j}'s parameters do not follow it")
            start = d + 16
            end = next_bound(start)
            events.append(Event(r.f32(r.q(h)), r.f32(r.q(h + 8)), r.i32(d), r.i32(d + 4), data[start:end]))
        headers = [ev + 24 * j for j in range(ec)]
        index = {off: j for j, off in enumerate(headers)}
        groups_ = []
        seen: set[int] = set()
        for k, (n, vo, to) in enumerate(group_heads):
            r.expect(gr + 32 * k + 24, 0, f"animation {anim_id} group {k}")
            r.expect32(to + 4, 0, f"animation {anim_id} group {k}")
            r.expect(to + 8, 0, f"animation {anim_id} group {k}")
            members = []
            for x in range(n):
                j = index.get(r.i32(vo + 4 * x))
                if j is None:
                    raise FormatError(f"animation {anim_id}: group {k} has a member that is not one of its events")
                if j in seen:
                    raise FormatError(f"animation {anim_id}: an event is in more than one group")
                seen.add(j)
                members.append(j)
            groups_.append(EventGroup(r.i32(to), members))
        header_type = r.i32(fo)
        r.expect32(fo + 4, 0, f"animation {anim_id}")
        ptr = r.q(fo + 8)
        if ptr == 0:
            header, name = None, None
        elif ptr == fo + 16:
            name_off = r.q(fo + 16)
            header = data[fo + 24 : fo + 32]
            r.expect(fo + 32, 0, f"animation {anim_id}")
            r.expect(fo + 40, 0, f"animation {anim_id}")
            if name_off != fo + 48:
                raise FormatError(f"animation {anim_id}: its file name is not where the format puts it")
            name = None if name_off in bounds else r.utf16(name_off)
        else:
            raise FormatError(f"animation {anim_id}: its header is not where the format puts it")
        if header_type not in (STANDARD, IMPORT):
            raise FormatError(f"animation {anim_id}: unknown header type {header_type}")
        animations.append(Animation(anim_id, header_type, header, name, events, groups_))

    return TAE(
        tae_id,
        r.q(0x30),
        data[0x40:0x48],
        r.utf16(skel_off) if skel_off else None,
        r.utf16(sib_off) if sib_off else None,
        animations,
    )


class _Reader:
    def __init__(self, data: bytes):
        self.data = data

    def _at(self, fmt: str, off: int):
        try:
            return struct.unpack_from(fmt, self.data, off)[0]
        except struct.error as e:
            raise FormatError(f"the TAE ends early (at {off:#x})") from e

    def q(self, off: int) -> int:
        return self._at("<q", off)

    def i32(self, off: int) -> int:
        return self._at("<i", off)

    def f32(self, off: int) -> float:
        return self._at("<f", off)

    def expect(self, off: int, want: int, where: str) -> None:
        if self.q(off) != want:
            raise FormatError(f"unexpected value in the TAE's {where} at {off:#x}")

    def expect32(self, off: int, want: int, where: str) -> None:
        if self.i32(off) != want:
            raise FormatError(f"unexpected value in the TAE's {where} at {off:#x}")

    def utf16(self, off: int) -> str:
        end = off
        while True:
            end = self.data.find(b"\0\0", end)
            if end < 0:
                raise FormatError(f"an unterminated name at {off:#x}")
            if (end - off) % 2 == 0:
                break
            end += 1
        try:
            return self.data[off:end].decode("utf-16-le")
        except UnicodeDecodeError as e:
            raise FormatError(f"a name that is not UTF-16 at {off:#x}") from e


# ----------------------------------------------------------------------------- writing
def write_tae(t: TAE) -> bytes:
    if len(t.flags) != 8:
        raise ValueError("a TAE's flags are 8 bytes")
    out = bytearray(HEADER_SIZE)
    anims = t.animations
    ids = [a.id for a in anims]
    if len(set(ids)) != len(ids):
        raise ValueError("two animations with the same ID")

    def name(s: str | None) -> int:
        if s is None:
            return 0
        at = len(out)
        out.extend(s.encode("utf-16-le") + b"\0\0")
        _pad(out)
        return at

    skel_off, sib_off = name(t.skeleton_name), name(t.sib_name)
    anims_off = len(out) if anims else 0
    for a in anims:
        out.extend(struct.pack("<qq", a.id, 0))
    groups_off = len(out)
    runs = _id_runs(ids, anims_off)
    out.extend(struct.pack("<qq", len(runs), groups_off + 16 if runs else 0))
    for first, last, at in runs:
        out.extend(struct.pack("<iiq", first, last, at))
    first_body = len(out) if anims else 0
    bodies = []
    for i in range(len(anims)):
        bodies.append(len(out))
        struct.pack_into("<q", out, anims_off + 16 * i + 8, len(out))
        out.extend(bytes(48))
    for a, body in zip(anims, bodies, strict=True):
        _write_animation(out, a, body)
    struct.pack_into("<4sBBBBii", out, 0, MAGIC, 0, 0, 0, 0xFF, VERSION, len(out))
    for off, value in _HEADER_CONSTANTS.items():
        struct.pack_into("<q", out, off, value)
    struct.pack_into("<q", out, 0x30, t.event_bank)
    out[0x40:0x48] = t.flags
    out[0x48:0x50] = b"\x01\0\0\0\0\0\0\0"
    struct.pack_into("<iiqq", out, 0x50, t.id, len(anims), anims_off, groups_off)
    struct.pack_into("<qq", out, 0x70, len(anims), first_body)
    struct.pack_into("<ii", out, 0x90, t.id, t.id)
    struct.pack_into("<qq", out, 0xB0, skel_off, sib_off)
    return bytes(out)


def _write_animation(out: bytearray, a: Animation, body: int) -> None:
    if a.header_type not in (STANDARD, IMPORT):
        raise ValueError(f"animation {a.id}: unknown header type {a.header_type}")
    fo = len(out)
    if a.header is None:
        if a.file_name is not None:
            raise ValueError(f"animation {a.id}: a file name needs a header")
        out.extend(struct.pack("<iiq", a.header_type, 0, 0))
    else:
        if len(a.header) != 8:
            raise ValueError(f"animation {a.id}: a header is 8 bytes")
        out.extend(struct.pack("<iiqq", a.header_type, 0, fo + 16, fo + 48))
        out.extend(a.header + bytes(16))
        if a.file_name:
            out.extend(a.file_name.encode("utf-16-le") + b"\0\0")
            _pad(out)
        elif a.file_name == "":
            out.extend(b"\0\0")
    times = sorted({_f32(x) for e in a.events for x in (e.start, e.end)}, key=lambda b: (_float(b), b))
    tm = len(out) if times else 0
    where = {}
    for bits in times:
        where[bits] = len(out)
        out.extend(bits)
    _pad(out)
    ev = len(out) if a.events else 0
    data_slots = []
    for e in a.events:
        out.extend(struct.pack("<qq", where[_f32(e.start)], where[_f32(e.end)]))
        data_slots.append(len(out))
        out.extend(bytes(8))
    for e, slot in zip(a.events, data_slots, strict=True):
        d = len(out)
        struct.pack_into("<q", out, slot, d)
        out.extend(struct.pack("<iiq", e.type, e.unk04, d + 16))
        out.extend(e.params)
        _pad(out)
    member_of: dict[int, int] = {}
    for k, g in enumerate(a.groups):
        for j in g.members:
            if not 0 <= j < len(a.events):
                raise ValueError(f"animation {a.id}: group {k} has a member that is not one of its events")
            if j in member_of:
                raise ValueError(f"animation {a.id}: event {j} is in more than one group")
            member_of[j] = k
    gr = len(out) if a.groups else 0
    for g in a.groups:
        out.extend(struct.pack("<qqqq", len(g.members), 0, 0, 0))
    for k, g in enumerate(a.groups):
        to = len(out)
        out.extend(struct.pack("<iiq", g.type, 0, 0))
        vo = len(out)
        for j in g.members:
            out.extend(struct.pack("<i", ev + 24 * j))
        _pad(out)
        struct.pack_into("<qq", out, gr + 32 * k + 8, vo, to)
    struct.pack_into("<qqqqiiii", out, body, ev, gr, tm, fo, len(a.events), len(a.groups), len(times), 0)


def _id_runs(ids: list[int], anims_off: int) -> list[tuple[int, int, int]]:
    """Runs of consecutive animation IDs: (first ID, last ID, offset of the first one's entry)."""
    runs = []
    i = 0
    while i < len(ids):
        j = i
        while j < len(ids) - 1 and ids[j + 1] == ids[j] + 1:
            j += 1
        runs.append((ids[i], ids[j], anims_off + 16 * i))
        i = j + 1
    return runs


def _pad(out: bytearray, to: int = 16) -> None:
    out.extend(bytes(-len(out) % to))


def _f32(x: float) -> bytes:
    return struct.pack("<f", x)


def _float(bits: bytes) -> float:
    return struct.unpack("<f", bits)[0]
