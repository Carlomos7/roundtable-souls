"""Animation events (TAE): changes animation by animation, matched by animation ID; the file header is one more part.

What each mod added, changed or left out is found against the game's file and applied in load order, as for the
inner files of an archive. An animation is taken whole (its header, file name, events in their stored order and
event groups): two mods changing the same animation differently is a clash, and the later mod's animation is used.
Events inside one animation are not merged. The file header (ID, event bank, flags, skeleton and sib names) is
merged the same way, as one part.

Animations are compared exactly (formats.tae.animation_key), event parameters byte for byte with their padding:
a copy whose events differ from the game's only in trailing zero bytes counts as changed, because without the event
type's parameter size padding cannot be told from parameters that are zero. Copies a tool rewrote store an empty file
name where the game's files store none; both mean no name, and are the same here.

A copy the format code cannot read, or a merged file that does not read back exactly to what was merged (every
animation's parameter bytes included), is not merged: the later mod's copy is used whole, with the reason recorded.
"""

from __future__ import annotations

from roundtable_souls import formats
from roundtable_souls.formats import tae as fmt
from roundtable_souls.merging.changes import REMOVED, Result

LISTED = 12  # animation IDs named in a note before the rest are counted


def is_tae(body: bytes) -> bool:
    return fmt.is_tae(body)


def merge(base: bytes, bodies: list[tuple[str, bytes]], where: str = "") -> Result:
    """Merge the mods' copies of one TAE (in load order) against the game's."""
    path = where or "/"
    changed = [(label, body) for label, body in bodies if body != base]
    if not changed:
        return Result(base)
    try:
        return _merge(base, bodies, path)
    except formats.FormatError as e:
        out = Result(changed[-1][1], merged=False)
        out.changed[path] = [label for label, _ in changed]
        if len({body for _, body in changed}) > 1:
            out.clashes[path] = [label for label, _ in changed]
        out.notes[path] = [f"not merged: {e}; {changed[-1][0]}'s copy is used whole"]
        return out


def _merge(base: bytes, bodies: list[tuple[str, bytes]], path: str) -> Result:
    game = fmt.read_tae(base)
    game_anims = {a.id: a for a in game.animations}
    game_keys = {a.id: fmt.animation_key(a) for a in game.animations}
    order = [a.id for a in game.animations]
    who: dict[int, list[tuple[str, object]]] = {}
    headers: list[tuple[str, fmt.TAE]] = []
    notes: list[str] = []
    changers: list[str] = []
    for label, body in bodies:
        mod = fmt.read_tae(body)
        header_changed = fmt.header_key(mod) != fmt.header_key(game)
        if header_changed:
            headers.append((label, mod))
        seen = {a.id for a in mod.animations}
        changed, added = [], []
        for a in mod.animations:
            key = fmt.animation_key(a)
            if game_keys.get(a.id) != key:
                who.setdefault(a.id, []).append((label, a))
                (changed if a.id in game_keys else added).append(a.id)
                if a.id not in game_keys and a.id not in order:
                    order.append(a.id)
        left_out = [i for i in game_keys if i not in seen]
        for i in left_out:
            who.setdefault(i, []).append((label, REMOVED))
        what = [
            f"{text} {_ids(ids)}"
            for text, ids in (("changed", changed), ("added", added), ("left out", left_out))
            if ids
        ]
        if header_changed:
            what.append(f"file header ({_header_change(game, mod)})")
        if what:
            changers.append(label)
            notes.append(f"{label}: " + "; ".join(what))

    if not who and not headers:
        return Result(base)
    out = Result(b"")
    result = dict(game_anims)
    for anim_id, changes in who.items():
        part = f"{path}#{anim_id}"
        if len({fmt.animation_key(a) if a is not REMOVED else None for _, a in changes}) > 1:
            out.clashes[part] = [label for label, _ in changes]
        last = changes[-1][1]
        if last is REMOVED:
            result.pop(anim_id, None)
            if anim_id in game_anims:
                out.removed[part] = [label for label, a in changes if a is REMOVED]
        else:
            result[anim_id] = last  # type: ignore[assignment]
    header = game
    if headers:
        if len({fmt.header_key(t) for _, t in headers}) > 1:
            out.clashes[f"{path}#header"] = [label for label, _ in headers]
        header = headers[-1][1]
    ids = [i for i in order if i in result]
    if [a.id for a in game.animations] == sorted(game_anims):
        ids.sort()  # the game's files keep animations by ID; added ones go in their place
    merged = fmt.TAE(
        header.id, header.event_bank, header.flags, header.skeleton_name, header.sib_name, [result[i] for i in ids]
    )
    data = fmt.write_tae(merged)
    back = fmt.read_tae(data)
    if fmt.header_key(back) != fmt.header_key(merged) or [fmt.animation_key(a) for a in back.animations] != [
        fmt.animation_key(a) for a in merged.animations
    ]:
        raise formats.FormatError("the merged file does not read back to what was merged")
    out.data = data
    out.changed[path] = changers
    out.notes[path] = notes
    return out


def _ids(ids: list[int]) -> str:
    shown = ", ".join(str(i) for i in ids[:LISTED])
    more = len(ids) - LISTED
    return f"{len(ids)} ({shown}{f' and {more} more' if more > 0 else ''})"


def _header_change(game: fmt.TAE, mod: fmt.TAE) -> str:
    names = ("ID", "event bank", "flags", "skeleton name", "sib name")
    parts = []
    for name, old, new in zip(names, fmt.header_key(game), fmt.header_key(mod), strict=True):
        if old != new:
            show = (lambda v: v.hex(" ")) if isinstance(old, bytes) else repr
            parts.append(f"{name} {show(old)} -> {show(new)}")
    return ", ".join(parts)
