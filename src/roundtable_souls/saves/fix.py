"""Named, backed-up repairs for Elden Ring PC saves: quest-flag soft-locks and
slot / profile checksums. Layer 3 of the plan (parse -> analyze -> repair).

Every write here:
  1. builds the new bytes in memory,
  2. re-parses them and checks every MD5,
  3. backs the save up into save-fix-backups next to it, then replaces it.

Nothing is written when the plan is empty. Callers refuse while the game runs.

Flag edits mirror er-save-manager's CorruptionFixer, so the result matches
what that editor would produce for the same issue.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

from roundtable_souls.saves import analyze as A
from roundtable_souls.saves import layout as L

BACKUP_DIR = "save-fix-backups"
SLOT_STRIDE = 0x10 + L.SLOT_SIZE

RANNI_FLAGS_TO_ENABLE = [
    1034509410,
    1034509412,
    1034500732,
    1034500736,
    1034505015,
    1034509361,
    1034500715,
    1034500710,
    1034500700,
    1034490701,
    1034490700,
    1034509413,
    1034509418,
    1034509355,
    1034509357,
    1034509358,
    1034509205,
    1045379208,
    1034509305,
    1034509306,
    1034509417,
    1034500734,
    1034509416,
    1034500739,
    1034500733,
    1034502610,
    1034505002,
    1034505003,
    1034505004,
    1034500716,
    1034503600,
]
RADAHN_MAP_MARKER = 9417
SEALING_TREE_RESTED_AFTER = 20010500
SEALING_TREE_CUTSCENE = 20010196


class FixError(Exception):
    pass


# ----------------------------------------------------------------------------- flag bits
def set_flag(event_flags: bytearray, event_id: int, state: bool) -> None:
    """Same layout as save_analyze.get_flag. Raises FixError when the flag block is unknown."""
    if len(event_flags) != A.EVENT_FLAGS_SIZE:
        raise FixError(f"event flags are {len(event_flags)} bytes, expected {A.EVENT_FLAGS_SIZE}")
    bst = A._bst_map()
    block = event_id // A.FLAG_DIVISOR
    if block not in bst:
        raise FixError(f"flag {event_id}: block {block} is not in the bundled BST")
    index = event_id - block * A.FLAG_DIVISOR
    byte_index = index // 8
    bit = 7 - (index - byte_index * 8)
    pos = bst[block] * A.BLOCK_SIZE + byte_index
    if pos >= len(event_flags):
        raise FixError(f"flag {event_id}: offset {pos:#x} past the end of the flag table")
    if state:
        event_flags[pos] |= 1 << bit
    else:
        event_flags[pos] &= ~(1 << bit) & 0xFF


def _fix_ranni(f):
    set_flag(f, A.RANNI_BLOCKING, False)
    for fid in RANNI_FLAGS_TO_ENABLE:
        try:
            set_flag(f, fid, True)
        except FixError:
            pass  # not every progression flag block is in the BST


def _fix_radahn_alive(f):
    set_flag(f, A.METEORITE_GREEN, False)
    set_flag(f, RADAHN_MAP_MARKER, False)


def _fix_radahn_dead(f):
    set_flag(f, A.GRACE_RADAHN, True)


def _fix_morgott(f):
    set_flag(f, A.MORGOTT_THORNS, True)
    set_flag(f, A.MORGOTT_FOG, True)


def _fix_radagon(f):
    set_flag(f, A.GRACE_FRACTURED, True)


def _fix_sealing_tree(f):
    set_flag(f, A.GRACE_ENIR_ILIM, True)
    set_flag(f, SEALING_TREE_RESTED_AFTER, True)


def _fix_romina(f):
    set_flag(f, A.SPIRIT_TREE_BURNING, False)
    set_flag(f, SEALING_TREE_CUTSCENE, False)


def _fix_unte_golem(f):
    set_flag(f, A.GOLEM_DESTROYED, True)


def _fix_erdtree_pre_giant(f):
    for fid in (A.WORLD_TREE_BURNING, A.WORLD_TREE_SPARKS, A.WORLD_TREE_SMALL_FLAME):
        set_flag(f, fid, False)


FIXERS = {
    "ranni_softlock": _fix_ranni,
    "radahn_alive_warp": _fix_radahn_alive,
    "radahn_dead_warp": _fix_radahn_dead,
    "morgott_warp": _fix_morgott,
    "radagon_warp": _fix_radagon,
    "sealing_tree_warp": _fix_sealing_tree,
    "romina_missing": _fix_romina,
    "unte_golem_stuck": _fix_unte_golem,
    "erdtree_pre_giant": _fix_erdtree_pre_giant,
}


# ----------------------------------------------------------------------------- plans (read-only)
def plan_quest_fixes(parsed: dict) -> list[dict]:
    """Per active character: the soft-lock issues a fix would clear. Empty when nothing to do."""
    plan = []
    active = (parsed.get("ud10") or {}).get("active") or []
    for i, slot in enumerate(parsed.get("slots") or []):
        if i < len(active) and not active[i]:
            continue
        flags = slot.get("event_flags")
        if not isinstance(flags, (bytes, bytearray)) or len(flags) != A.EVENT_FLAGS_SIZE:
            continue
        issues = [k for k in A.detect_flag_issues(bytes(flags)) if k in FIXERS]
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
                "labels": [A._FLAG_ISSUE_TITLES.get(k, (k, ""))[0] for k in issues],
                "actions": [A.FLAG_FIX_TEXT.get(k, k) for k in issues],
            }
        )
    return plan


def plan_checksum_fixes(parsed: dict) -> dict:
    """Which MD5s are stale: {'slots': [active slot indexes], 'ud10': bool}."""
    active = (parsed.get("ud10") or {}).get("active") or []
    bad = [i for i, ok in enumerate(parsed.get("slot_md5_ok") or []) if not ok and i < len(active) and active[i]]
    return {"slots": bad, "ud10": not parsed.get("ud10_md5_ok", True)}


# ----------------------------------------------------------------------------- writing
def backup(save: Path, manifest: dict | None = None) -> Path:
    """Copy the save into save-fix-backups. A manifest (action + change lines) is written next to it as
    <backup>.json so the Backups list can say what each copy was taken before."""
    folder = save.parent / BACKUP_DIR
    folder.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = folder / f"{save.name}.{stamp}.bak"
    n = 1
    while dest.exists():
        n += 1
        dest = folder / f"{save.name}.{stamp}-{n}.bak"
    shutil.copy2(save, dest)
    write_manifest(dest, manifest or {"action": "Backup"}, save)
    return dest


def write_manifest(bak: Path, manifest: dict, save: Path | None = None) -> None:
    doc = {
        "action": manifest.get("action", "Backup"),
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "save": str(save) if save else "",
        "changes": list(manifest.get("changes") or []),
    }
    try:
        Path(str(bak) + ".json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    except OSError:
        pass


def read_manifest(bak: Path) -> dict | None:
    p = Path(str(bak) + ".json")
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None


def _sign_slot(data: bytearray, i: int) -> None:
    off = L.HEADER + i * SLOT_STRIDE
    data[off : off + 0x10] = hashlib.md5(data[off + 0x10 : off + SLOT_STRIDE]).digest()


def _sign_ud10(data: bytearray, ud10_pos: int) -> None:
    data[ud10_pos : ud10_pos + 0x10] = hashlib.md5(data[ud10_pos + 0x10 : ud10_pos + 0x60010]).digest()


def _commit(
    save: Path, data: bytes, touched_slots: list[int], expect_ud10_ok: bool, manifest: dict | None = None
) -> Path:
    """Verify the new bytes parse with matching MD5s, back the original up, then replace it."""
    tmp = save.with_name(save.name + ".roundtable.tmp")
    tmp.write_bytes(data)
    try:
        r = L.parse(str(tmp))
        for i in touched_slots:
            if not r["slot_md5_ok"][i]:
                raise FixError(f"slot {i + 1} checksum did not verify after the write")
        if expect_ud10_ok and not r["ud10_md5_ok"]:
            raise FixError("profile summary checksum did not verify after the write")
        bak = backup(save, manifest)
        tmp.replace(save)
        return bak
    finally:
        if tmp.exists():
            tmp.unlink()


def apply_quest_fixes(save: Path, slots: list[int] | None = None, log=None, selection: dict | None = None) -> dict:
    """Clear the detected soft-locks on the given (or every active) character. Re-signs each touched slot.

    Returns {'fixed': [{'slot', 'name', 'issues'}], 'backup': Path | None}. Nothing is written when
    there is nothing to fix.
    """
    save = Path(save)
    say = log or (lambda *_: None)
    data = bytearray(save.read_bytes())
    r = L.parse(str(save))
    plan = [p for p in plan_quest_fixes(r) if slots is None or p["slot"] in slots]
    if selection is not None:  # {slot: [issue keys]}; slots missing from it are left alone
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
        pos = slot["event_flags_pos"]
        flags = bytearray(data[pos : pos + A.EVENT_FLAGS_SIZE])
        for key in p["issues"]:
            FIXERS[key](flags)
            say(f"  slot {i + 1} ({p['name']}): {A.FLAG_FIX_TEXT.get(key, key)}")
            changes.append(f"{p['name'] or 'slot ' + str(i + 1)}: {A._FLAG_ISSUE_TITLES.get(key, (key, ''))[0]}")
        still = [k for k in A.detect_flag_issues(bytes(flags)) if k in p["issues"]]
        if still:
            raise FixError(f"slot {i + 1}: {', '.join(still)} still detected after the fix; not writing")
        data[pos : pos + A.EVENT_FLAGS_SIZE] = flags
        _sign_slot(data, i)
        touched.append(i)
    bak = _commit(save, bytes(data), touched, r["ud10_md5_ok"], {"action": "Fix quest flags", "changes": changes})
    say(f"  backup: {bak}")
    return {"fixed": [{"slot": p["slot"], "name": p["name"], "issues": p["issues"]} for p in plan], "backup": bak}


def repair_checksums(save: Path, log=None) -> dict:
    """Recompute stale slot and profile-summary MD5s. Returns {'slots': [...], 'ud10': bool, 'backup': Path | None}."""
    save = Path(save)
    say = log or (lambda *_: None)
    data = bytearray(save.read_bytes())
    r = L.parse(str(save))
    plan = plan_checksum_fixes(r)
    if not plan["slots"] and not plan["ud10"]:
        say("  checksums already match")
        return {"slots": [], "ud10": False, "backup": None}
    for i in plan["slots"]:
        _sign_slot(data, i)
        say(f"  slot {i + 1}: checksum recomputed")
    if plan["ud10"]:
        _sign_ud10(data, r["ud10_pos"])
        say("  profile summary: checksum recomputed")
    changes = [f"slot {i + 1}: checksum recomputed" for i in plan["slots"]] + (
        ["profile summary: checksum recomputed"] if plan["ud10"] else []
    )
    bak = _commit(save, bytes(data), plan["slots"], True, {"action": "Fix checksums", "changes": changes})
    say(f"  backup: {bak}")
    return {"slots": plan["slots"], "ud10": plan["ud10"], "backup": bak}
