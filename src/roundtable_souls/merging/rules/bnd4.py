"""Archives (BND4): changes inner file by inner file, matched by name (case and slashes aside), else by ID."""

from __future__ import annotations

from roundtable_souls import formats
from roundtable_souls.merging.changes import REMOVED, Result


def merge(base: bytes, bodies: list[tuple[str, bytes]], where: str) -> Result:
    """Inner file by inner file: what each mod changed, added or left out against the game's archive, applied in
    load order; an inner file several mods changed is merged inside when it is itself an archive or a text table."""
    from roundtable_souls.merging.merger import _inner, _merge_body, mergeable  # they dispatch back here

    van = formats.bnd4.read_bnd4(base)
    _unique(van, "the game's")
    vmap = {e.key: e for e in van.entries}
    order = [e.key for e in van.entries]
    touched: dict[str, list[tuple[str, object]]] = {}
    for label, body in bodies:
        b = formats.bnd4.read_bnd4(body)
        _unique(b, f"{label}'s")
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
                out.removed.update(sub.removed)
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
            if key in vmap:
                out.removed[path] = [label for label, e in changes if e is REMOVED]
        else:
            result[key] = last
    van.entries = [result[k] for k in order if k in result]
    out.data = formats.bnd4.write_bnd4(van)
    return out


def _unique(b: formats.bnd4.Bnd4, whose: str) -> None:
    """Inner files are matched by name, case and slashes aside: two that differ only so cannot be told apart, and one
    would be lost. The game's own archives have none."""
    seen: dict[str, str] = {}
    for e in b.entries:
        other = seen.get(e.key)
        if other is not None:
            raise formats.FormatError(
                f"{whose} copy has two inner files that differ only in capital letters or slashes: {other} and {e.name}"
            )
        seen[e.key] = e.name or f"#{e.id}"
