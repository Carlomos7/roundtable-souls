"""Moving progress between saves: compare two files, copy a whole file, or copy one character into a slot.

A .co2 and a .sl2 hold the same format, so all of this works between co-op and standard saves, between two files of
the same kind, and within one file (a character copied to another slot).

Copying one character (Elden Ring) moves four things and signs them again:
  the slot's 0x280000 bytes, then the Steam ID inside it set to the target file's account,
  the character's profile summary entry (name, level, playtime, look),
  the target's active flag for that slot,
  the slot and profile-summary MD5s.
The result is parsed back before anything is replaced, and the target keeps a backup (the launcher's backups) for Undo.
"""

from __future__ import annotations

import struct
from pathlib import Path

from roundtable_souls.game import catalog as games
from roundtable_souls.saves import fix as save_fix
from roundtable_souls.saves import layout as L
from roundtable_souls.saves import library


class TransferError(Exception):
    pass


# ----------------------------------------------------------------------------- compare
def compare(a: Path, b: Path, game: games.Game | None = None) -> list[dict]:
    """Slot by slot: {slot, a, b, change}, a and b being {name, level, seconds} or None. change is one of
    same / a only / b only / ahead in a / ahead in b / different (a different character in that slot)."""
    game = game or games.for_save(a) or games.ELDEN_RING
    left = {c["slot"]: c for c in library.characters(a, game)}
    right = {c["slot"]: c for c in library.characters(b, game)}
    rows = []
    for slot in sorted(set(left) | set(right)):
        x, y = left.get(slot), right.get(slot)
        if x and not y:
            change = "a only"
        elif y and not x:
            change = "b only"
        elif x["name"] != y["name"]:
            change = "different"
        elif (x["level"], x["seconds"]) == (y["level"], y["seconds"]):
            change = "same"
        else:
            change = "ahead in a" if (x["seconds"], x["level"]) > (y["seconds"], y["level"]) else "ahead in b"
        rows.append({"slot": slot, "a": x, "b": y, "change": change})
    return rows


def hours(seconds: int) -> str:
    h = seconds / 3600
    return f"{h:.1f} h" if h < 10 else f"{h:.0f} h"


# ----------------------------------------------------------------------------- whole files
def copy_file(source: Path, target: Path, game: games.Game, keep_as: str | None = None) -> dict:
    """Write source's bytes over target. An existing target goes into the library first under keep_as (a default
    name when None), and a backup is kept for Undo. Returns {kept, backup}."""
    source, target = Path(source), Path(target)
    if source.resolve() == target.resolve():
        raise TransferError("That is the same file.")
    data = source.read_bytes()
    library.check_whole(data, game)
    kept = bak = None
    if target.exists():
        kept = library.add(
            target.parent, target, keep_as or library.default_name(target, game), game, action="replaced"
        )
        bak = save_fix.backup(target, {"action": f"Before copying {source.name} over it", "changes": [source.name]})
    tmp = target.with_name(target.name + ".roundtable.tmp")
    tmp.write_bytes(data)
    tmp.replace(target)
    if target.read_bytes() != data:
        raise TransferError(f"{target.name} did not read back the same; restore it from Backups.")
    return {"kept": kept, "backup": bak}


# ----------------------------------------------------------------------------- one character
def _slot_body(i: int) -> int:
    return L.HEADER + i * save_fix.SLOT_STRIDE + 0x10


def plan_character_copy(source: Path, src_slot: int, target: Path, dst_slot: int) -> dict:
    """What copying one character would do, read-only. Slots are 1-based. Raises TransferError when it cannot."""
    source, target = Path(source), Path(target)
    if not 1 <= src_slot <= 10 or not 1 <= dst_slot <= 10:
        raise TransferError("Slots run from 1 to 10.")
    try:
        rs = L.parse(str(source))
        rt = rs if source.resolve() == target.resolve() else L.parse(str(target))
    except (L.ParseError, EOFError, OSError) as e:
        raise TransferError(f"Could not read the saves: {e}") from e
    si, di = src_slot - 1, dst_slot - 1
    if not rs["ud10"]["active"][si]:
        raise TransferError(f"Slot {src_slot} of {source.name} has no character.")
    if si in rs["unreadable"]:
        raise TransferError(f"Slot {src_slot} of {source.name} is in a layout this launcher cannot read.")
    if source.resolve() == target.resolve() and si == di:
        raise TransferError("A character cannot be copied onto itself.")
    src_chars = {c["slot"]: c for c in library.characters(source)}
    dst_chars = {c["slot"]: c for c in library.characters(target)}
    return {
        "character": src_chars.get(src_slot),
        "replaces": dst_chars.get(dst_slot),
        "steam_id_changes": rs["ud10"]["steam_id"] != rt["ud10"]["steam_id"],
        "source_steam_id": rs["ud10"]["steam_id"],
        "target_steam_id": rt["ud10"]["steam_id"],
        "free_slots": [i + 1 for i, on in enumerate(rt["ud10"]["active_raw"]) if not on],
    }


def copy_character(source: Path, src_slot: int, target: Path, dst_slot: int) -> dict:
    """Copy one Elden Ring character (1-based slots) into the target file, replacing whatever is in that slot.
    Verified by parsing the result before the target is replaced; the target is backed up first. Returns the plan
    plus {backup}."""
    source, target = Path(source), Path(target)
    plan = plan_character_copy(source, src_slot, target, dst_slot)
    src = source.read_bytes()
    dst = bytearray(target.read_bytes())
    rs, rt = L.parse(str(source)), L.parse(str(target))
    si, di = src_slot - 1, dst_slot - 1

    s0, d0 = _slot_body(si), _slot_body(di)
    dst[d0 : d0 + L.SLOT_SIZE] = src[s0 : s0 + L.SLOT_SIZE]
    steam_rel = rs["slots"][si]["steam_id_pos"] - s0
    struct.pack_into("<Q", dst, d0 + steam_rel, rt["ud10"]["steam_id"])

    s_sum = rs["ud10"]["active_pos"] + 10 + si * library.SUMMARY_STRIDE
    d_sum = rt["ud10"]["active_pos"] + 10 + di * library.SUMMARY_STRIDE
    dst[d_sum : d_sum + library.SUMMARY_STRIDE] = src[s_sum : s_sum + library.SUMMARY_STRIDE]
    dst[rt["ud10"]["active_pos"] + di] = 1

    save_fix._sign_slot(dst, di)
    save_fix._sign_ud10(dst, rt["ud10_pos"])

    who = plan["character"] or {"name": "?", "level": 0}
    changes = [f"slot {dst_slot}: {who['name']} (level {who['level']}) copied from {source.name} slot {src_slot}"]
    if plan["replaces"]:
        changes.append(f"slot {dst_slot} held {plan['replaces']['name']} (level {plan['replaces']['level']})")
    bak = save_fix._commit(
        target, bytes(dst), [di], True, {"action": "Before copying a character in", "changes": changes}
    )

    after = L.parse(str(target))
    got = after["slots"][di]
    if (
        not after["ud10"]["active"][di]
        or got["pgd"]["name"] != rs["slots"][si]["pgd"]["name"]
        or got["pgd"]["level"] != rs["slots"][si]["pgd"]["level"]
        or got["steam_id"] != rt["ud10"]["steam_id"]
    ):
        raise TransferError(f"Slot {dst_slot} did not read back as expected; restore {target.name} from Backups.")
    return {**plan, "backup": bak}
