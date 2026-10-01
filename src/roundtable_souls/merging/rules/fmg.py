"""Text tables (FMG): changes entry by entry, matched by text ID."""

from __future__ import annotations

from roundtable_souls import formats
from roundtable_souls.merging.changes import REMOVED, Result


def merge(base: bytes, bodies: list[tuple[str, bytes]], where: str) -> Result:
    """Entry by entry: what each mod changed, added or left out against the game's table, applied in load order."""
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
            if tid in van.entries:
                out.removed[path] = [label for label, t in changes if t is REMOVED]
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
