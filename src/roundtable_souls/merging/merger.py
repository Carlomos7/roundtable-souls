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

from roundtable_souls import formats
from roundtable_souls.merging.changes import Result
from roundtable_souls.merging.rules import bnd4 as bnd4_rule
from roundtable_souls.merging.rules import esd as esd_rule
from roundtable_souls.merging.rules import fmg as fmg_rule

# Talk scripts (ESD) are merged by merging.rules.esd (on since a merged grace menu was checked in game, 2026-10-02).
# False: they are handled as any other file (the later mod's copy, a clash when several changed it).
ESD_MERGING = True


def mergeable(body: bytes) -> bool:
    return formats.bnd4.is_bnd4(body) or formats.fmg.is_fmg(body) or ESD_MERGING and esd_rule.is_esd(body)


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
        return Result(layers[-1][1], result.changed, result.clashes, False, result.removed, result.notes)
    result.data = formats.dcx.pack(result.data, how, compressor, dflt_fallback) if result.data != base else vanilla
    return result


def _merge_body(base: bytes, bodies: list[tuple[str, bytes]], where: str) -> Result:
    if formats.bnd4.is_bnd4(base) and all(formats.bnd4.is_bnd4(b) for _, b in bodies):
        return bnd4_rule.merge(base, bodies, where)
    if formats.fmg.is_fmg(base) and all(formats.fmg.is_fmg(b) for _, b in bodies):
        return fmg_rule.merge(base, bodies, where)
    if ESD_MERGING and esd_rule.is_esd(base) and all(esd_rule.is_esd(b) for _, b in bodies):
        return esd_rule.merge(base, bodies, where)
    changed = [(label, b) for label, b in bodies if b != base]
    out = Result(changed[-1][1] if changed else base, merged=False)
    if changed:
        out.changed[where or "/"] = [label for label, _ in changed]
        if len({b for _, b in changed}) > 1:
            out.clashes[where or "/"] = [label for label, _ in changed]
    return out


def _inner(data: bytes) -> tuple[bytes, formats.dcx.Dcx | None]:
    return formats.dcx.unpack(data) if data[:4] == b"DCX\0" and data[0x28:0x2C] != b"KRAK" else (data, None)
