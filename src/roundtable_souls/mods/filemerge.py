"""Merging one file that several mods ship, against the game's own copy of it.

Each mod's copy is the game's file with that mod's changes. For an archive (BND4) the merger finds, inner file by
inner file, what each mod changed, added or left out (removed) compared with the game's copy, and applies all of
them in load order into one archive. For a text table (FMG) it does the same entry by entry. Where two mods changed
the same inner file, and that file is itself an archive or a text table, it is merged the same way inside; otherwise
the later mod's version is used and the merge reports it as a clash. Any other file is not merged: the later mod's
copy is used whole (a clash when several changed it).

The result keeps the game's layout (the archive's format, the file's compression), so it differs from the game's
copy only where the mods did.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

from roundtable_souls import formats

REMOVED = object()


@dataclass
class Result:
    data: bytes
    changed: dict[str, list[str]] = field(default_factory=dict)  # inner path -> the mods that changed it
    clashes: dict[str, list[str]] = field(default_factory=dict)  # inner path -> mods whose changes met; the last won
    merged: bool = True  # False: the file could not be merged and the last mod's copy is used whole

    def summary(self) -> str:
        n = len(self.changed)
        text = f"{n} part{'s' if n != 1 else ''} changed"
        if self.clashes:
            text += f", {len(self.clashes)} changed by more than one mod (the later one's used)"
        return text


def mergeable(body: bytes) -> bool:
    return formats.bnd4.is_bnd4(body) or formats.fmg.is_fmg(body)


def merge(
    vanilla: bytes | None, layers: list[tuple[str, bytes]], oodle=None, compressor=None, dflt_fallback: bool = False
) -> Result:
    """Merge the mods' copies of one file (as stored: DCX-compressed or not), in load order, against the game's own
    copy (None when the game has no such file: the first mod's copy is then the base)."""
    if not layers:
        raise ValueError("nothing to merge")
    if vanilla is None:
        vanilla, layers = layers[0][1], layers
    damaged = (struct.error, ValueError, IndexError, UnicodeDecodeError, zlib.error)
    try:
        base, how = formats.dcx.unpack(vanilla, oodle)
    except damaged as e:
        raise formats.FormatError(f"the game's own copy could not be read ({e})") from e
    bodies = []
    for label, raw in layers:
        try:
            bodies.append((label, formats.dcx.unpack(raw, oodle)[0]))
        except damaged as e:
            raise formats.FormatError(f"{label}'s copy is damaged or not in the format it claims ({e})") from e
    try:
        result = _merge_body(base, bodies, "")
    except formats.FormatError:
        raise
    except damaged as e:
        raise formats.FormatError(f"a copy is damaged or not in the format it claims ({e})") from e
    if not result.merged:
        return Result(layers[-1][1], result.changed, result.clashes, merged=False)
    result.data = formats.dcx.pack(result.data, how, compressor, dflt_fallback) if result.data != base else vanilla
    return result


def _merge_body(base: bytes, bodies: list[tuple[str, bytes]], where: str) -> Result:
    if formats.bnd4.is_bnd4(base) and all(formats.bnd4.is_bnd4(b) for _, b in bodies):
        return _merge_bnd(base, bodies, where)
    if formats.fmg.is_fmg(base) and all(formats.fmg.is_fmg(b) for _, b in bodies):
        return _merge_fmg(base, bodies, where)
    changed = [(label, b) for label, b in bodies if b != base]
    out = Result(changed[-1][1] if changed else base, merged=False)
    if changed:
        out.changed[where or "/"] = [label for label, _ in changed]
        if len({b for _, b in changed}) > 1:
            out.clashes[where or "/"] = [label for label, _ in changed]
    return out


def _inner(data: bytes) -> tuple[bytes, formats.dcx.Dcx | None]:
    return formats.dcx.unpack(data) if data[:4] == b"DCX\0" and data[0x28:0x2C] != b"KRAK" else (data, None)


def _merge_bnd(base: bytes, bodies: list[tuple[str, bytes]], where: str) -> Result:
    van = formats.bnd4.read_bnd4(base)
    vmap = {e.key: e for e in van.entries}
    order = [e.key for e in van.entries]
    touched: dict[str, list[tuple[str, object]]] = {}
    for label, body in bodies:
        b = formats.bnd4.read_bnd4(body)
        lmap = {e.key: e for e in b.entries}
        for key, e in lmap.items():
            v = vmap.get(key)
            if v is None or v.data != e.data:
                touched.setdefault(key, []).append((label, e))
                if key not in vmap and key not in order:
                    order.append(key)
        for key in vmap:
            if key not in lmap:
                touched.setdefault(key, []).append((label, REMOVED))
    out = Result(b"")
    result = dict(vmap)
    for key, changes in touched.items():
        path = f"{where}/{key}" if where else key
        out.changed[path] = [label for label, _ in changes]
        kept = [(label, e) for label, e in changes if e is not REMOVED]
        distinct = {e.data if e is not REMOVED else None for _, e in changes}
        if len(distinct) == 1 or len(changes) == 1:
            last = changes[-1][1]
        elif key in vmap and len(kept) == len(changes):  # all changed it: merge inside when it is a container
            inner_base, how = _inner(vmap[key].data)
            inner = [(label, _inner(e.data)[0]) for label, e in kept]
            if mergeable(inner_base):
                sub = _merge_body(inner_base, inner, path)
                out.changed.update(sub.changed)
                out.clashes.update(sub.clashes)
                data = formats.dcx.pack(sub.data, how) if how is not None and sub.data != inner_base else sub.data
                if sub.data == inner_base:
                    data = vmap[key].data
                last = formats.bnd4.Entry(kept[-1][1].name, kept[-1][1].id, data, kept[-1][1].flags, len(sub.data))
            else:
                out.clashes[path] = [label for label, _ in changes]
                last = changes[-1][1]
        else:
            out.clashes[path] = [label for label, _ in changes]
            last = changes[-1][1]
        if last is REMOVED:
            result.pop(key, None)
        else:
            result[key] = last
    van.entries = [result[k] for k in order if k in result]
    out.data = formats.bnd4.write_bnd4(van)
    return out


def _merge_fmg(base: bytes, bodies: list[tuple[str, bytes]], where: str) -> Result:
    van = formats.fmg.read_fmg(base)
    entries = dict(van.entries)
    who: dict[int, list[tuple[str, object]]] = {}
    for label, body in bodies:
        f = formats.fmg.read_fmg(body)
        for tid, text in f.entries.items():
            if tid not in van.entries or van.entries[tid] != text:
                who.setdefault(tid, []).append((label, text))
        for tid in van.entries:
            if tid not in f.entries:
                who.setdefault(tid, []).append((label, REMOVED))
    out = Result(b"")
    for tid, changes in who.items():
        path = f"{where}#{tid}"
        if len({(t if t is not REMOVED else "\0removed") for _, t in changes}) > 1:
            out.clashes[path] = [label for label, _ in changes]
        last = changes[-1][1]
        if last is REMOVED:
            entries.pop(tid, None)
        else:
            entries[tid] = last
    if who:
        labels = sorted({label for changes in who.values() for label, _ in changes})
        out.changed[where or "/"] = labels
    out.data = formats.fmg.write_fmg(formats.fmg.Fmg(van.header, entries)) if who else base
    return out


def add_text(body: bytes, table: str, texts: dict[int, str]) -> bytes:
    """A text archive (a msgbnd, not compressed) with entries set in one of its tables: how a mod that ships its text
    as a list (Nightreign Revive's JSON) becomes a layer like any other."""
    b = formats.bnd4.read_bnd4(body)
    want = table.lower()
    for e in b.entries:
        if (e.name or "").replace("\\", "/").rsplit("/", 1)[-1].lower() == want:
            f = formats.fmg.read_fmg(e.data)
            f.entries.update(texts)
            e.data = formats.fmg.write_fmg(f)
            return formats.bnd4.write_bnd4(b)
    raise formats.FormatError(f"the text archive has no table named {table}")
