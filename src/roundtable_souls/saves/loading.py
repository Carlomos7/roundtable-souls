"""Fix loading: save states that leave Elden Ring stuck on the loading screen, each with a small in-place repair.

Every check is a `LoadCheck`: a title, the action shown to the user, a detector and a repair. The detectors only
read the parsed slot; the repairs only touch the bytes of that slot and are verified by re-running the detector on
the re-parsed result before anything is written. Writes go through fix._commit (verify, back up, replace).

The torn-write check at the bottom is detection only.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from roundtable_souls.saves import fix as F
from roundtable_souls.saves import layout as L

# Game facts used below.
TORRENT_SUMMONED, TORRENT_DEAD = 13, 3  # RideGameData state values
ROUNDTABLE_HOLD = bytes([0, 0, 10, 11])  # map ID bytes, area in the last byte
ROUNDTABLE_POSITION = (-331.0, -22.0, -305.8)
DLC_AREAS = frozenset(range(20, 30)) | {61}  # Land of Shadow overworld (61) and DLC legacy dungeons
GAME_AREAS = frozenset(range(10, 20)) | frozenset(range(30, 61)) | DLC_AREAS
DLC_ENTERED_BYTE = 1  # in the per-character DLC block
HORSE_STATE_OFFSET = 36  # xyz(12) map(4) angle(16) hp(4), then the state
MAX_COORD = 1e7


@dataclass(frozen=True)
class Context:
    dlc_installed: bool  # Shadow of the Erdtree data is present for whoever loads this save


@dataclass(frozen=True)
class LoadCheck:
    key: str
    title: str
    action: str
    detect: Callable[[dict, Context], bool]
    repair: Callable[[bytearray, dict], None]


def slot_start(index: int) -> int:
    """File offset of a slot's data (after its 16-byte checksum)."""
    return L.HEADER + index * F.SLOT_STRIDE + 0x10


def dlc_installed(game_dir) -> bool | None:
    """Shadow of the Erdtree is installed when DLC.bdt sits next to the game; None when the game folder is unknown."""
    if not game_dir:
        return None
    try:
        return (Path(game_dir) / "DLC.bdt").is_file()
    except OSError:
        return None


# ----------------------------------------------------------------------------- detectors


def _area(slot: dict) -> int:
    return slot["map_id"][3]


def _position_invalid(slot: dict) -> bool:
    values = [*(slot.get("coords") or ()), *(slot.get("coords2") or ())]
    return _area(slot) not in GAME_AREAS or any(math.isnan(v) or math.isinf(v) or abs(v) > MAX_COORD for v in values)


def _torrent_stuck(slot: dict, _ctx: Context) -> bool:
    hp, state = slot.get("horse") or (None, None)
    return hp == 0 and state == TORRENT_SUMMONED


def _in_dlc_without_dlc(slot: dict, ctx: Context) -> bool:
    return not ctx.dlc_installed and _area(slot) in DLC_AREAS


def _dlc_entered_without_dlc(slot: dict, ctx: Context) -> bool:
    dlc = slot.get("dlc") or b""
    return not ctx.dlc_installed and len(dlc) > DLC_ENTERED_BYTE and bool(dlc[DLC_ENTERED_BYTE])


# ----------------------------------------------------------------------------- repairs


def _move_to_roundtable(data: bytearray, slot: dict) -> None:
    map_pos = slot["ga_items_pos"] - 0x1C
    data[map_pos : map_pos + 4] = ROUNDTABLE_HOLD
    xyz = struct.pack("<fff", *ROUNDTABLE_POSITION)
    for key in ("coords_pos", "coords2_pos"):
        data[slot[key] : slot[key] + 12] = xyz
    struct.pack_into("<H", data, slot["weather_pos"], ROUNDTABLE_HOLD[3])


def _clear_dlc_entered(data: bytearray, slot: dict) -> None:
    data[slot["dlc_pos"] + DLC_ENTERED_BYTE] = 0


def _dismiss_torrent(data: bytearray, slot: dict) -> None:
    struct.pack_into("<I", data, slot["horse_pos"] + HORSE_STATE_OFFSET, TORRENT_DEAD)


def _leave_dlc(data: bytearray, slot: dict) -> None:
    _move_to_roundtable(data, slot)
    _clear_dlc_entered(data, slot)


CHECKS: tuple[LoadCheck, ...] = (
    LoadCheck(
        "torrent",
        "Torrent stuck at 0 HP",
        "Mark Torrent as fallen so the game stops waiting for him; he comes back at the next grace.",
        _torrent_stuck,
        _dismiss_torrent,
    ),
    LoadCheck(
        "position",
        "Position is not on any map",
        "Move the character to Roundtable Hold.",
        lambda slot, _ctx: _position_invalid(slot),
        _move_to_roundtable,
    ),
    LoadCheck(
        "dlc_area",
        "In the Land of Shadow without the DLC installed",
        "Move the character to Roundtable Hold and clear the DLC entry mark.",
        _in_dlc_without_dlc,
        _leave_dlc,
    ),
    LoadCheck(
        "dlc_flag",
        "DLC entry mark set without the DLC installed",
        "Clear the DLC entry mark.",
        _dlc_entered_without_dlc,
        _clear_dlc_entered,
    ),
)
BY_KEY = {c.key: c for c in CHECKS}
FIX_TEXT = {c.key: (c.title, c.action) for c in CHECKS}


def detect_slot(slot: dict, dlc_owned: bool | None) -> list[str]:
    ctx = Context(dlc_installed=True if dlc_owned is None else dlc_owned)
    found = [c.key for c in CHECKS if c.detect(slot, ctx)]
    if "dlc_area" in found:  # leaving the DLC moves the character and clears the mark
        found = [k for k in found if k not in ("position", "dlc_flag")]
    return found


def plan_loading_fixes(parsed: dict, dlc_owned: bool | None = None) -> list[dict]:
    from roundtable_souls.saves.analyze import active_slots, character_name

    plan = []
    for i, slot in active_slots(parsed):
        issues = detect_slot(slot, dlc_owned)
        if issues:
            plan.append(
                {
                    "slot": i,
                    "name": character_name(slot),
                    "issues": issues,
                    "labels": [BY_KEY[k].title for k in issues],
                    "actions": [BY_KEY[k].action for k in issues],
                }
            )
    return plan


def torn_write_check(data: bytes, parsed: dict) -> list[dict]:
    """Active slots whose Steam ID is not where the layout put it: bytes shifted mid-slot."""
    from roundtable_souls.saves.analyze import active_slots, character_name

    steam_id = (parsed.get("ud10") or {}).get("steam_id")
    if not steam_id:
        return []
    needle = struct.pack("<Q", steam_id)
    out = []
    for i, slot in active_slots(parsed):
        if slot.get("steam_id") == steam_id:
            continue
        start = slot_start(i)
        found = data.rfind(needle, start, start + L.SLOT_SIZE)
        out.append(
            {"slot": i, "name": character_name(slot), "shift": found - slot["steam_id_pos"] if found >= 0 else None}
        )
    return out


def apply_loading_fixes(
    save: Path, slots: list[int] | None = None, dlc_owned: bool | None = None, log=None, selection: dict | None = None
) -> dict:
    """Repair the detected states (all, the given slots, or selection = {slot: [keys]}). Nothing is written when
    there is nothing to do, or when a repair does not clear its own check."""
    save = Path(save)
    say = log or (lambda *_: None)
    data = bytearray(save.read_bytes())
    parsed = L.parse(str(save))
    plan = [p for p in plan_loading_fixes(parsed, dlc_owned) if slots is None or p["slot"] in slots]
    if selection is not None:
        plan = [{**p, "issues": [k for k in p["issues"] if k in selection.get(p["slot"], [])]} for p in plan]
        plan = [p for p in plan if p["issues"] and p["slot"] in selection]
    if not plan:
        say("  nothing to fix")
        return {"fixed": [], "backup": None}
    changes = []
    for p in plan:
        slot = parsed["slots"][p["slot"]]
        who = p["name"] or f"slot {p['slot'] + 1}"
        for key in p["issues"]:
            BY_KEY[key].repair(data, slot)
            say(f"  {who}: {BY_KEY[key].action}")
            changes.append(f"{who}: {BY_KEY[key].title}")
        F._sign_slot(data, p["slot"])
    probe = save.with_name(save.name + ".roundtable.verify")
    probe.write_bytes(data)
    try:
        after = L.parse(str(probe))
        for p in plan:
            left = set(detect_slot(after["slots"][p["slot"]], dlc_owned)) & set(p["issues"])
            if left:
                raise F.FixError(f"slot {p['slot'] + 1}: {', '.join(sorted(left))} still detected; not writing")
    finally:
        probe.unlink(missing_ok=True)
    touched = [p["slot"] for p in plan]
    bak = F._commit(
        save, bytes(data), touched, parsed["ud10_md5_ok"], {"action": "Before fixing loading", "changes": changes}
    )
    say(f"  backup: {bak}")
    return {"fixed": [{"slot": p["slot"], "name": p["name"], "issues": p["issues"]} for p in plan], "backup": bak}
