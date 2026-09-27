"""Restore vanilla: strip non-vanilla items from a character so the save passes the "looks vanilla"
check, then clear the known quest soft-locks and re-sign. Layer 3, named and backed up.

What it changes, and only this:
  * inventory / chest entries whose item is outside the vanilla+DLC list: the (handle, qty, index)
    triple is zeroed in place and the list's item count goes down by one. The game itself leaves
    holes in these arrays, so nothing is shifted.
  * the gaItem row behind a stripped weapon, armour piece or ash of war is turned into the row the
    game keeps for an empty slot, same length, handle kept: weapons become "Unarmed" (110000),
    armour becomes the "Head" placeholder (10000), 8-byte rows become empty (0, 0xFFFFFFFF).
    Rows are variable length (21 / 16 / 8 bytes), so replacing in place is the only edit that does
    not move the rest of the slot.
  * quick-item and pouch slots that point at a stripped good are emptied (0, 0xFFFFFFFF), along
    with the mirror in equipped_items.
  * leftover non-vanilla rows nothing references are neutralised the same way.
  * quest soft-lock flags, via save_fix.

What it refuses (reported as blocked, everything else still runs):
  * a non-vanilla weapon, armour piece or talisman that is currently worn. Equip slots hold indexes
    whose layout is not documented, so take it off in-game first.
  * a vanilla weapon carrying a non-vanilla ash of war. Remove the ash in-game first.

Every write goes through save_fix._commit: verify the new bytes parse with matching MD5s, back the
original up into save-fix-backups, then replace it.
"""

from __future__ import annotations

import struct
from pathlib import Path

from roundtable_souls.saves import analyze as A
from roundtable_souls.saves import fix as F
from roundtable_souls.saves import layout as L

EMPTY_ROW8 = struct.pack("<II", 0, 0xFFFFFFFF)
UNARMED_ROW_TAIL = struct.pack("<iiIB", 0, 0, 0, 0)  # unk2, unk3, aow, unk5 of every real Unarmed row
NAKED_ROW_TAIL = struct.pack("<ii", 0, 0)
INV_ENTRY = 12
INV_COMMON_LEN, INV_KEY_LEN = 0xA80, 0x180
STO_COMMON_LEN, STO_KEY_LEN = 0x780, 0x80
QUICK_N, POUCH_N = 10, 6
EQUIPPED_QUICK_AT, EQUIPPED_POUCH_AT = 22, 32  # equipped_items mirrors quick[i] at 22+i and pouch[i] at 32+i


def row_size(item_id: int) -> int:
    cat = item_id & 0xF0000000
    if item_id and cat == 0:
        return 21
    if item_id and cat == 0x10000000:
        return 16
    return 8


def _inventory_offsets(slot: dict, box: str) -> dict:
    """Absolute offsets of the count fields and entry arrays of the held or chest inventory."""
    base = slot["inv_pos"] if box == "inventory" else slot["storage_pos"]
    l1, l2 = (INV_COMMON_LEN, INV_KEY_LEN) if box == "inventory" else (STO_COMMON_LEN, STO_KEY_LEN)
    common_count = base
    common = base + 4
    key_count = common + l1 * INV_ENTRY
    key = key_count + 4
    return {"common_count": common_count, "common": common, "key_count": key_count, "key": key}


def _neutral_row(item_id: int) -> bytes:
    """Replacement bytes (after the 4-byte handle) for a stripped row, same length as the original."""
    cat = item_id & 0xF0000000
    if item_id and cat == 0:
        return struct.pack("<I", A.UNARMED_WEAPON) + UNARMED_ROW_TAIL
    if item_id and cat == 0x10000000:
        return struct.pack("<I", 0x10000000 | 10000) + NAKED_ROW_TAIL
    return b""


# ----------------------------------------------------------------------------- plan (read-only)
def plan_restore(parsed: dict, tarnished: str | None = None, dlc_owned: bool | None = None) -> list[dict]:
    """Per active character: what Remove mod items would strip, clear, fix, and what it refuses.
    tarnished: None reads the pack flag from the save; 'yes' / 'no' force it. dlc_owned False drops DLC items from vanilla."""
    plan = []
    active = (parsed.get("ud10") or {}).get("active") or []
    quest = {p["slot"]: p for p in F.plan_quest_fixes(parsed)}
    known = A.effective_known(parsed, tarnished, dlc_owned=dlc_owned)
    for i, slot in enumerate(parsed.get("slots") or []):
        if i < len(active) and not active[i]:
            continue
        scan = A.scan_mod_items(slot, known)
        rows = slot.get("ga_items") or []
        strip, blocked = [], []
        for e in scan["held"]:
            if e["worn"] and (e["row"] is not None or (e["item_id"] & 0xF0000000) == 0x20000000):
                blocked.append({**e, "why": "worn"})
            else:
                strip.append(e)
        # a vanilla weapon whose ash of war row is non-vanilla
        mod_aow_rows = {
            g["gaitem_handle"]
            for g in rows
            if g.get("gaitem_handle")
            and (g["item_id"] & 0xF0000000) == 0x80000000
            and not A._item_known(g["item_id"], known)
        }
        for g in rows:
            if (
                g.get("gaitem_handle")
                and (g["item_id"] & 0xF0000000) == 0
                and g["item_id"]
                and g.get("aow") in mod_aow_rows
                and A._item_known(g["item_id"], known)
            ):
                name, src = A.item_label(next(r["item_id"] for r in rows if r["gaitem_handle"] == g["aow"]))
                blocked.append(
                    {"item_id": g["item_id"], "name": f"ash {name} on a vanilla weapon", "source": src, "why": "ash"}
                )
        # never neutralise an ash row that a kept (blocked) weapon still points at
        keep_aow = {
            g.get("aow")
            for g in rows
            if g.get("gaitem_handle")
            and (g["item_id"] & 0xF0000000) == 0
            and g["item_id"]
            and A._item_known(g["item_id"], known)
        }
        orphans = [o for o in scan["orphans"] if o["handle"] not in keep_aow]
        strip = [e for e in strip if e["handle"] not in keep_aow]
        q = quest.get(i)
        if not (strip or orphans or blocked or q):
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
                "strip": strip,
                "orphans": orphans,
                "blocked": blocked,
                "quest": (q or {}).get("issues") or [],
                "quest_labels": (q or {}).get("labels") or [],
            }
        )
    return plan


def restore_needed(plan: list[dict]) -> bool:
    return any(p["strip"] or p["orphans"] or p["quest"] for p in plan)


def describe(plan: list[dict]) -> list[str]:
    """Plain lines for a confirm dialog."""
    lines = []
    for p in plan:
        who = p["name"] or f"slot {p['slot'] + 1}"
        if p["strip"]:
            names = []
            for e in p["strip"]:
                lab = e["name"] + (f" x{e['qty']}" if e["qty"] > 1 else "")
                if lab not in names:
                    names.append(lab)
            lines.append(
                f"{who}: remove {len(names)} item(s): "
                + ", ".join(names[:8])
                + (f", +{len(names) - 8} more" if len(names) > 8 else "")
            )
        if p["orphans"]:
            lines.append(f"{who}: clear {len(p['orphans'])} leftover item row(s) nothing holds")
        for lab in p["quest_labels"]:
            lines.append(f"{who}: {lab}")
        for b in p["blocked"]:
            if b.get("why") == "worn":
                lines.append(f"{who}: KEPT (worn) {b['name']} - take it off in-game first")
            else:
                lines.append(f"{who}: KEPT {b['name']} - remove it in-game first")
    return lines


# ----------------------------------------------------------------------------- apply
def select_plan(plan: list[dict], selection: dict | None) -> list[dict]:
    """Narrow a plan to a selection: {slot: {"items": set(handles) | None, "orphans": bool, "quest": [keys] | None}}.
    Slots missing from the selection are left alone. None means "everything" for that part."""
    if selection is None:
        return plan
    out = []
    for p in plan:
        sel = selection.get(p["slot"])
        if sel is None:
            continue
        items = sel.get("items")
        quest = sel.get("quest")
        q = p["quest"] if quest is None else [k for k in p["quest"] if k in quest]
        out.append(
            {
                **p,
                "strip": p["strip"] if items is None else [e for e in p["strip"] if e["handle"] in items],
                "orphans": p["orphans"] if sel.get("orphans", True) else [],
                "quest": q,
                "quest_labels": [A._FLAG_ISSUE_TITLES.get(k, (k, ""))[0] for k in q],
            }
        )
    return out


def apply_restore(
    save: Path,
    slots: list[int] | None = None,
    log=None,
    selection: dict | None = None,
    tarnished: str | None = None,
    dlc_owned: bool | None = None,
) -> dict:
    """Run the plan (or the selected part of it) on the given (or every active) character.
    Returns {'done': [...], 'blocked': [...], 'backup': Path|None}."""
    save = Path(save)
    say = log or (lambda *_: None)
    data = bytearray(save.read_bytes())
    r = L.parse(str(save))
    plan = [p for p in plan_restore(r, tarnished, dlc_owned) if slots is None or p["slot"] in slots]
    plan = select_plan(plan, selection)
    work = [p for p in plan if p["strip"] or p["orphans"] or p["quest"]]
    if not work:
        say("  nothing to restore")
        return {"done": [], "blocked": [b for p in plan for b in p["blocked"]], "backup": None}
    touched = []
    done = []
    changes = []
    for p in work:
        i = p["slot"]
        slot = r["slots"][i]
        rows = slot["ga_items"]
        who = p["name"] or f"slot {i + 1}"
        cleared_rows: set[int] = set()

        def neutralise(row_index: int):  # called within this iteration only
            if row_index in cleared_rows:  # noqa: B023
                return
            g = rows[row_index]  # noqa: B023
            size = row_size(g["item_id"])
            new = _neutral_row(g["item_id"])
            if new:
                data[g["pos"] + 4 : g["pos"] + size] = new
            else:
                data[g["pos"] : g["pos"] + 8] = EMPTY_ROW8
            cleared_rows.add(row_index)  # noqa: B023

        counts_dec: dict[int, int] = {}
        for e in p["strip"]:
            off = _inventory_offsets(slot, e["box"])
            entry = off[e["list"]] + e["pos"] * INV_ENTRY
            assert struct.unpack_from("<I", data, entry)[0] == e["handle"], "inventory entry moved"
            data[entry : entry + INV_ENTRY] = bytes(INV_ENTRY)
            cpos = off[e["list"] + "_count"]
            counts_dec[cpos] = counts_dec.get(cpos, 0) + 1
            if e["row"] is not None:
                neutralise(e["row"])
            for qi in e["quick"]:
                data[slot["quick_pos"] + qi * 8 : slot["quick_pos"] + qi * 8 + 8] = EMPTY_ROW8
                ep = slot["equipped_items_pos"] + (EQUIPPED_QUICK_AT + qi) * 4
                data[ep : ep + 4] = b"\xff\xff\xff\xff"
            for pi in e["pouch"]:
                data[slot["pouch_pos"] + pi * 8 : slot["pouch_pos"] + pi * 8 + 8] = EMPTY_ROW8
                ep = slot["equipped_items_pos"] + (EQUIPPED_POUCH_AT + pi) * 4
                data[ep : ep + 4] = b"\xff\xff\xff\xff"
            say(
                f"  {who}: removed {e['name']}"
                + (f" x{e['qty']}" if e["qty"] > 1 else "")
                + (f" ({e['source']})" if e["source"] else "")
            )
            changes.append(f"{who}: removed {e['name']}" + (f" ({e['source']})" if e["source"] else ""))
        for cpos, n in counts_dec.items():
            cur = struct.unpack_from("<I", data, cpos)[0]
            struct.pack_into("<I", data, cpos, max(0, cur - n))
        for o in p["orphans"]:
            neutralise(o["row"])
        if p["orphans"]:
            say(f"  {who}: cleared {len(p['orphans'])} leftover row(s)")
            changes.append(f"{who}: cleared {len(p['orphans'])} leftover item row(s)")
        if p["quest"]:
            pos = slot["event_flags_pos"]
            flags = bytearray(data[pos : pos + A.EVENT_FLAGS_SIZE])
            for key in p["quest"]:
                F.FIXERS[key](flags)
                say(f"  {who}: {A.FLAG_FIX_TEXT.get(key, key)}")
                changes.append(f"{who}: {A._FLAG_ISSUE_TITLES.get(key, (key, ''))[0]}")
            data[pos : pos + A.EVENT_FLAGS_SIZE] = flags
        F._sign_slot(data, i)
        touched.append(i)
        done.append(
            {
                "slot": i,
                "name": p["name"],
                "removed": len(p["strip"]),
                "orphans": len(p["orphans"]),
                "quest": p["quest"],
            }
        )
        for b in p["blocked"]:
            say(f"  {who}: kept {b['name']} ({b.get('why')})")

    # verify: the new bytes must parse, every chosen entry must be gone, every chosen row neutral, every chosen flag fixed
    tmp = save.with_name(save.name + ".roundtable.verify")
    tmp.write_bytes(data)
    try:
        r2 = L.parse(str(tmp))
        known = A.effective_known(r2, tarnished, dlc_owned=dlc_owned)
        for p in work:
            s2 = r2["slots"][p["slot"]]
            for e in p["strip"]:
                if s2[e["box"]][e["list"]][e["pos"]][0] != 0:
                    raise F.FixError(
                        f"slot {p['slot'] + 1}: {e['name']} is still in the inventory after the restore; not writing"
                    )
                if e["row"] is not None and not A._item_known(s2["ga_items"][e["row"]]["item_id"], known):
                    raise F.FixError(f"slot {p['slot'] + 1}: row for {e['name']} still non-vanilla; not writing")
            for o in p["orphans"]:
                if not A._item_known(s2["ga_items"][o["row"]]["item_id"], known):
                    raise F.FixError(f"slot {p['slot'] + 1}: leftover row {o['name']} still non-vanilla; not writing")
            still = [k for k in A.detect_flag_issues(bytes(s2["event_flags"])) if k in p["quest"]]
            if still:
                raise F.FixError(f"slot {p['slot'] + 1}: {', '.join(still)} still detected after the fix; not writing")
    finally:
        if tmp.exists():
            tmp.unlink()
    bak = F._commit(save, bytes(data), touched, r["ud10_md5_ok"], {"action": "Remove mod items", "changes": changes})
    say(f"  backup: {bak}")
    return {"done": done, "blocked": [b for p in plan for b in p["blocked"]], "backup": bak}
