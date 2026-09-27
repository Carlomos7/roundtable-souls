"""Fix loading: the handful of save states that make Elden Ring hang on the loading screen, and their
fixes. Ported from er-save-manager (torrent, teleport, dlc, weather fixes) onto this package's parser.

Detected per active character (plan_loading_fixes):
  torrent      Torrent at 0 HP but state ACTIVE (13); the game waits for a horse that never comes.
               Fix: state DEAD (3), which is what the game writes itself.
  position     NaN / infinite coordinates, or a map prefix the game does not have.
               Fix: move to Roundtable Hold (map 11 10 0 0, the spot the game uses).
  dlc_area     Standing in the Land of Shadow or a DLC dungeon while DLC.bdt is not installed.
               Fix: move to Roundtable Hold and clear the DLC entry flag.
  dlc_flag     DLC entry flag set while DLC.bdt is not installed. Fix: clear it.
  dlc_junk     Non-zero bytes in the unused part of the DLC block (bytes 4..49). Fix: zero them.
  weather      Weather area does not match the map prefix. Fix: set it to the map prefix.

Detect only (reported by save_analyze, never written here):
  torn write   The character's Steam ID is not where the layout says, or the slot no longer parses.
               Bytes were inserted or lost mid-slot; er-save-manager's deep scan is the tool for that.

Every write goes through save_fix._commit (verify, back up into save-fix-backups, replace).
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

from roundtable_souls.saves import fix as F
from roundtable_souls.saves import layout as L

HORSE_ACTIVE, HORSE_DEAD = 13, 3
ROUNDTABLE_MAP = bytes([0, 0, 10, 11])
ROUNDTABLE_XYZ = (-331.0, -22.0, -305.8)
DLC_PREFIXES = set(range(20, 30)) | {61}
VALID_PREFIXES = set(range(10, 20)) | DLC_PREFIXES | set(range(30, 60)) | {60}

FIX_TEXT = {
    "torrent": (
        "Torrent stuck at 0 HP",
        "Mark Torrent dead so the game stops waiting for him. He returns at the next grace.",
    ),
    "position": ("Position is not on any map", "Move the character to Roundtable Hold."),
    "dlc_area": (
        "In the Land of Shadow without the DLC installed",
        "Move the character to Roundtable Hold and clear the DLC entry flag.",
    ),
    "dlc_flag": ("DLC entry flag set without the DLC installed", "Clear the DLC entry flag."),
    "dlc_junk": ("Junk in the DLC block", "Zero the unused bytes of the DLC block."),
    "weather": ("Weather out of sync with the map", "Set the weather area to the current map."),
}


def dlc_installed(game_dir) -> bool | None:
    """True/False from DLC.bdt in the game folder; None when the game folder is unknown (then assume installed)."""
    if not game_dir:
        return None
    try:
        return (Path(game_dir) / "DLC.bdt").is_file()
    except OSError:
        return None


def _bad_float(v: float) -> bool:
    return math.isnan(v) or math.isinf(v) or abs(v) > 1e7


def detect_slot(slot: dict, dlc_owned: bool | None) -> list[str]:
    issues = []
    hp, state = slot.get("horse") or (None, None)
    if hp == 0 and state == HORSE_ACTIVE:
        issues.append("torrent")
    prefix = slot["map_id"][3]
    coords = list(slot.get("coords") or ()) + list(slot.get("coords2") or ())
    if any(_bad_float(v) for v in coords) or prefix not in VALID_PREFIXES:
        issues.append("position")
    owned = True if dlc_owned is None else dlc_owned
    if prefix in DLC_PREFIXES and not owned:
        issues.append("dlc_area")
    dlc = slot.get("dlc") or b""
    if len(dlc) >= 50:
        if dlc[1] and not owned and "dlc_area" not in issues:
            issues.append("dlc_flag")
        if any(dlc[4:50]):
            issues.append("dlc_junk")
    weather = slot.get("weather")
    if weather and prefix in VALID_PREFIXES and weather[0] != prefix:
        issues.append("weather")
    return issues


def plan_loading_fixes(parsed: dict, dlc_owned: bool | None = None) -> list[dict]:
    plan = []
    active = (parsed.get("ud10") or {}).get("active") or []
    for i, slot in enumerate(parsed.get("slots") or []):
        if i < len(active) and not active[i]:
            continue
        issues = detect_slot(slot, dlc_owned)
        if not issues:
            continue
        name = ""
        try:
            name = slot["pgd"]["name"]
        except Exception:
            pass
        plan.append(
            {
                "slot": i,
                "name": name,
                "issues": issues,
                "labels": [FIX_TEXT[k][0] for k in issues],
                "actions": [FIX_TEXT[k][1] for k in issues],
            }
        )
    return plan


def torn_write_check(data: bytes, parsed: dict) -> list[dict]:
    """Slots whose Steam ID is not where the layout put it: bytes shifted mid-slot."""
    out = []
    ud_sid = (parsed.get("ud10") or {}).get("steam_id")
    if not ud_sid:
        return out
    needle = struct.pack("<Q", ud_sid)
    active = (parsed.get("ud10") or {}).get("active") or []
    for i, slot in enumerate(parsed.get("slots") or []):
        if i < len(active) and not active[i]:
            continue
        if slot.get("steam_id") == ud_sid:
            continue
        start = L.HEADER + i * F.SLOT_STRIDE + 0x10
        found = data.rfind(needle, start, start + L.SLOT_SIZE)
        shift = (found - slot["steam_id_pos"]) if found >= 0 else None
        out.append({"slot": i, "name": (slot.get("pgd") or {}).get("name", ""), "shift": shift})
    return out


# ----------------------------------------------------------------------------- apply
def _teleport_roundtable(data: bytearray, slot: dict) -> None:
    map_pos = slot["ga_items_pos"] - 0x1C
    data[map_pos : map_pos + 4] = ROUNDTABLE_MAP
    xyz = struct.pack("<fff", *ROUNDTABLE_XYZ)
    data[slot["coords_pos"] : slot["coords_pos"] + 12] = xyz
    data[slot["coords2_pos"] : slot["coords2_pos"] + 12] = xyz
    struct.pack_into("<H", data, slot["weather_pos"], ROUNDTABLE_MAP[3])


def apply_loading_fixes(
    save: Path, slots: list[int] | None = None, dlc_owned: bool | None = None, log=None, selection: dict | None = None
) -> dict:
    """selection = {slot: [issue keys]} narrows the plan; slots missing from it are left alone."""
    save = Path(save)
    say = log or (lambda *_: None)
    data = bytearray(save.read_bytes())
    r = L.parse(str(save))
    plan = [p for p in plan_loading_fixes(r, dlc_owned) if slots is None or p["slot"] in slots]
    if selection is not None:
        plan = [
            {**p, "issues": [k for k in p["issues"] if k in selection.get(p["slot"], [])]}
            for p in plan
            if p["slot"] in selection
        ]
        plan = [p for p in plan if p["issues"]]
    if not plan:
        say("  nothing to fix")
        return {"fixed": [], "backup": None}
    touched = []
    changes = []
    for p in plan:
        i = p["slot"]
        slot = r["slots"][i]
        who = p["name"] or f"slot {i + 1}"
        moved = "position" in p["issues"] or "dlc_area" in p["issues"]  # the teleport already syncs the weather
        for key in p["issues"]:
            if key == "weather" and moved:
                continue
            if key == "torrent":
                struct.pack_into("<I", data, slot["horse_pos"] + 36, HORSE_DEAD)
            elif key in ("position", "dlc_area"):
                _teleport_roundtable(data, slot)
                if key == "dlc_area":
                    data[slot["dlc_pos"] + 1] = 0
            elif key == "dlc_flag":
                data[slot["dlc_pos"] + 1] = 0
            elif key == "dlc_junk":
                data[slot["dlc_pos"] + 4 : slot["dlc_pos"] + 50] = bytes(46)
            elif key == "weather":
                struct.pack_into("<H", data, slot["weather_pos"], slot["map_id"][3])
            say(f"  {who}: {FIX_TEXT[key][1]}")
            changes.append(f"{who}: {FIX_TEXT[key][0]}")
        F._sign_slot(data, i)
        touched.append(i)
    tmp = save.with_name(save.name + ".roundtable.verify")
    tmp.write_bytes(data)
    try:
        r2 = L.parse(str(tmp))
        for p in plan:
            still = [k for k in detect_slot(r2["slots"][p["slot"]], dlc_owned) if k in p["issues"]]
            if still:
                raise F.FixError(f"slot {p['slot'] + 1}: {', '.join(still)} still detected after the fix; not writing")
    finally:
        if tmp.exists():
            tmp.unlink()
    bak = F._commit(save, bytes(data), touched, r["ud10_md5_ok"], {"action": "Fix loading", "changes": changes})
    say(f"  backup: {bak}")
    return {"fixed": [{"slot": p["slot"], "name": p["name"], "issues": p["issues"]} for p in plan], "backup": bak}
