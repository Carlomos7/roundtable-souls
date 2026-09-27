"""Read-only save analyzers: duplicate inventory, unknown
item IDs (against a bundled vanilla+DLC list), and known quest-flag soft-locks.

Never writes. Callers that convert .co2 -> .sl2 must refuse when findings are
not clean (see findings_are_clean).
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from roundtable_souls.resources import DATA_DIR

_KNOWN_IDS: set[int] | None = None
_MOD_NAMES: dict[int, tuple[str, str]] | None = None
_DLC_NAMES: dict[int, str] | None = None
DLC_SOURCE = "Shadow of the Erdtree (not installed)"
_BST: dict[int, int] | None = None


def _data_dir() -> Path | None:
    return DATA_DIR if (DATA_DIR / "known_item_ids.txt").is_file() else None


# Inventory handle prefixes (er-save-manager inventory_ops): weapons/armour/ashes of war point at a gaItem
# row; talismans (0xA) and goods (0xB) carry the item ID directly.
def direct_item_id(handle: int) -> int | None:
    pre = handle >> 28
    if pre == 0xB:
        return 0x40000000 | (handle & 0x00FFFFFF)
    if pre == 0xA:
        return 0x20000000 | (handle & 0x00FFFFFF)
    return None


FLAG_DIVISOR = 1000
BLOCK_SIZE = 125
EVENT_FLAGS_SIZE = 0x1BF99F

# Soft-lock / warp-sickness flag IDs (from er-save-manager CorruptionDetector).
RANNI_BLOCKING = 1034500738
METEORITE_GREEN = 310
DEFEATED_RADAHN = 9130
GRACE_RADAHN = 76422
GRACE_WAR_DEAD = 73016
MORGOTT_DEFEATED = 11000800
MORGOTT_THORNS = 11000500
MORGOTT_FOG = 11000501
DEFEATED_RADAGON = 9123
ENDING_CUTSCENE = 121
GRACE_FRACTURED = 71900
SPIRIT_TREE_BURNING = 330
DEFEATED_DANCING_LION = 9140
GRACE_ENIR_ILIM = 72012
DEFEATED_ROMINA = 9160
GOLEM_DESTROYED = 2050460300
GOLEM_DEFEATED = 2250460309
WORLD_TREE_BURNING = 300
WORLD_TREE_SPARKS = 301
WORLD_TREE_SMALL_FLAME = 302
DEFEATED_MALIKETH = 9116
USED_CAULDRON = 110

_FLAG_ISSUE_TITLES = {
    "ranni_softlock": ("Ranni tower soft-lock flag", "Blocking flag 1034500738 is on. Ranni's quest can stick until an editor clears it."),
    "radahn_alive_warp": ("Radahn warp sickness (alive)", "Meteorite flag is on but Radahn is not marked defeated. Map warp can break."),
    "radahn_dead_warp": ("Radahn warp sickness (dead)", "Meteorite and defeat are set, but neither Radahn grace is. Map warp can break."),
    "morgott_warp": ("Morgott warp sickness", "Morgott is defeated but thorns/fog flags are incomplete."),
    "radagon_warp": ("Radagon warp sickness", "Radagon is defeated without the ending or Fractured Marika grace."),
    "sealing_tree_warp": ("Sealing Tree warp sickness", "Spirit tree burning without Dancing Lion defeat or Enir-Ilim grace."),
    "romina_missing": ("Romina missing after Sealing Tree", "Spirit tree burning without Romina defeat."),
    "unte_golem_stuck": ("Ruins of Unte golem stuck", "Golem defeat set without the destroy flag (common after Seamless)."),
    "erdtree_pre_giant": ("Erdtree flags too early", "Erdtree burn visuals are set before the Forge of the Giants."),
}

# What "Fix quest flags" writes for each issue (mirrors er-save-manager CorruptionFixer).
FLAG_FIX_TEXT = {
    "ranni_softlock": "Clear the blocking flag and set Ranni's progression flags.",
    "radahn_alive_warp": "Close the crater and remove the Radahn map marker.",
    "radahn_dead_warp": "Grant the Starscourge Radahn grace.",
    "morgott_warp": "Mark Morgott's thorns touched and drop his fog wall.",
    "radagon_warp": "Grant the Fractured Marika grace.",
    "sealing_tree_warp": "Grant the Enir-Ilim grace and mark the Sealing Tree rest.",
    "romina_missing": "Reset the Sealing Tree so Romina spawns.",
    "unte_golem_stuck": "Set the golem-destroyed flag so the event finishes.",
    "erdtree_pre_giant": "Clear the Erdtree burn flags.",
}

# gaItem entries the game keeps for empty slots; never mod items.
UNARMED_WEAPON = 110000
NAKED_ARMOR = frozenset((10000, 10100, 10200, 10300))


def known_item_ids() -> set[int]:
    global _KNOWN_IDS
    if _KNOWN_IDS is not None:
        return _KNOWN_IDS
    d = _data_dir()
    path = (d / "known_item_ids.txt") if d else None
    ids: set[int] = set()
    if path and path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try: ids.add(int(line))
                except ValueError: pass
    _KNOWN_IDS = ids
    return ids


def mod_item_names() -> dict[int, tuple[str, str]]:
    """Full item ID -> (mod name, item name) for items known mods add (bundled mod_item_names.txt)."""
    global _MOD_NAMES
    if _MOD_NAMES is not None:
        return _MOD_NAMES
    d = _data_dir()
    path = (d / "mod_item_names.txt") if d else None
    m: dict[int, tuple[str, str]] = {}
    if path and path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.rstrip("\n").split(",", 2)
            if len(parts) != 3: continue
            try: m[int(parts[0])] = (SOURCE_NAMES.get(parts[1], parts[1]), parts[2])
            except ValueError: pass
    _MOD_NAMES = m
    return m


# The Tarnished Edition pack is paid official content. Its items are listed with the mods only because the
# reference CSVs keep them there; when the pack is owned they count as vanilla.
TARNISHED = "Tarnished Edition"
SOURCE_NAMES = {"Tarnished Pack": TARNISHED}
_TARNISHED_IDS: set[int] | None = None


def tarnished_ids() -> set[int]:
    global _TARNISHED_IDS
    if _TARNISHED_IDS is None:
        _TARNISHED_IDS = {i for i, (src, _n) in mod_item_names().items() if src == TARNISHED}
    return _TARNISHED_IDS


def tarnished_flag(parsed: dict) -> bool:
    """True when any active character carries the Tarnished pack entry flag (byte 3 of the DLC block)."""
    active = (parsed.get("ud10") or {}).get("active") or []
    for i, slot in enumerate(parsed.get("slots") or []):
        if i < len(active) and not active[i]:
            continue
        dlc = slot.get("dlc") or b""
        if len(dlc) > 3 and dlc[3]:
            return True
    return False


def tarnished_owned(parsed: dict, override: str | None = None) -> bool:
    """'yes' / 'no' force it; anything else reads the flag from the save."""
    if override == "yes": return True
    if override == "no": return False
    return tarnished_flag(parsed)


def effective_known(parsed: dict | None = None, override: str | None = None, owned: bool | None = None,
                    dlc_owned: bool | None = None) -> set[int]:
    """The vanilla list for this save: base game, plus Shadow of the Erdtree unless it is known to be missing
    (dlc_owned False), plus Tarnished Edition gear when the pack is owned."""
    base = known_item_ids()
    if not base:
        return base
    if owned is None:
        owned = tarnished_owned(parsed or {}, override)
    known = set(base)
    if dlc_owned is False:
        known -= set(dlc_item_names())
    if owned:
        known |= tarnished_ids()
    return known


def count_pack_items(slot: dict) -> int:
    """Tarnished Edition pieces the character holds, chest included (informational)."""
    ids = tarnished_ids()
    if not ids: return 0
    rows = {g["gaitem_handle"]: g["item_id"] for g in slot.get("ga_items") or [] if g.get("gaitem_handle")}
    n = 0
    for box in ("inventory", "storage"):
        for lst in ("common", "key"):
            for h, _q, _i in (slot.get(box) or {}).get(lst) or []:
                if not h: continue
                iid = direct_item_id(h)
                if iid is None: iid = rows.get(h)
                if iid is not None and _item_known(iid, ids):
                    n += 1
    return n


def dlc_item_names() -> dict[int, str]:
    """Full item ID -> name for Shadow of the Erdtree items (bundled dlc_item_names.txt)."""
    global _DLC_NAMES
    if _DLC_NAMES is not None:
        return _DLC_NAMES
    d = _data_dir()
    path = (d / "dlc_item_names.txt") if d else None
    m: dict[int, str] = {}
    if path and path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.rstrip("\n").split(",", 1)
            if len(parts) != 2: continue
            try: m[int(parts[0])] = parts[1]
            except ValueError: pass
    _DLC_NAMES = m
    return m


def _dlc_label(item_id: int) -> str | None:
    names = dlc_item_names()
    if item_id in names:
        return names[item_id]
    cat = item_id & 0xF0000000; raw = item_id & 0x0FFFFFFF
    if cat == 0:
        hit = names.get(raw // 10000 * 10000)
        if hit:
            up = raw % 100
            return f"{hit} +{up}" if up else hit
    elif cat == 0x40000000:
        return names.get(raw // 10 * 10) or names.get(raw // 1000 * 1000)
    return None


def item_label(item_id: int) -> tuple[str, str]:
    """(display name, mod source) for a non-vanilla ID; source is "" when no bundled list names it.
    A DLC item only reaches here when the DLC is not installed, so it is named as such."""
    dlc = _dlc_label(item_id)
    if dlc:
        return dlc, DLC_SOURCE
    mods = mod_item_names()
    cat = item_id & 0xF0000000
    raw = item_id & 0x0FFFFFFF
    if cat == 0:                                   # weapons: name the base row, show the upgrade level
        hit = mods.get(raw // 10000 * 10000) or mods.get(item_id)
        if hit:
            up = raw % 100
            return (f"{hit[1]} +{up}" if up else hit[1]), hit[0]
    hit = mods.get(item_id)
    if hit:
        return hit[1], hit[0]
    elif cat == 0x40000000:
        hit = mods.get(raw // 10 * 10) or mods.get(raw // 1000 * 1000)
        if hit:
            return hit[1], hit[0]
    return f"{item_id:#x}", ""


def _bst_map() -> dict[int, int]:
    global _BST
    if _BST is not None:
        return _BST
    d = _data_dir()
    path = (d / "eventflag_bst.txt") if d else None
    m: dict[int, int] = {}
    if path and path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line: continue
            parts = line.split(",")
            if len(parts) != 2: continue
            try: m[int(parts[0])] = int(parts[1])
            except ValueError: pass
    _BST = m
    return m


def get_flag(event_flags: bytes, event_id: int) -> bool | None:
    if len(event_flags) != EVENT_FLAGS_SIZE:
        return None
    bst = _bst_map()
    if not bst:
        return None
    block = event_id // FLAG_DIVISOR
    index = event_id - block * FLAG_DIVISOR
    if block not in bst:
        return None
    offset = bst[block] * BLOCK_SIZE
    byte_index = index // 8
    bit_index = 7 - (index - byte_index * 8)
    byte_pos = offset + byte_index
    if byte_pos >= len(event_flags):
        return None
    return ((event_flags[byte_pos] >> bit_index) & 1) == 1


def _flag(event_flags: bytes, eid: int) -> bool:
    v = get_flag(event_flags, eid)
    return bool(v)


def detect_flag_issues(event_flags: bytes) -> list[str]:
    issues = []
    if get_flag(event_flags, RANNI_BLOCKING) is None and not _bst_map():
        return []
    try:
        if _flag(event_flags, RANNI_BLOCKING):
            issues.append("ranni_softlock")
        if _flag(event_flags, METEORITE_GREEN) and not _flag(event_flags, DEFEATED_RADAHN):
            issues.append("radahn_alive_warp")
        if (_flag(event_flags, METEORITE_GREEN) and _flag(event_flags, DEFEATED_RADAHN)
                and not (_flag(event_flags, GRACE_RADAHN) or _flag(event_flags, GRACE_WAR_DEAD))):
            issues.append("radahn_dead_warp")
        if _flag(event_flags, MORGOTT_DEFEATED) and not (_flag(event_flags, MORGOTT_THORNS) and _flag(event_flags, MORGOTT_FOG)):
            issues.append("morgott_warp")
        if _flag(event_flags, DEFEATED_RADAGON) and not (_flag(event_flags, ENDING_CUTSCENE) or _flag(event_flags, GRACE_FRACTURED)):
            issues.append("radagon_warp")
        if (_flag(event_flags, SPIRIT_TREE_BURNING) and not _flag(event_flags, DEFEATED_DANCING_LION)
                and not _flag(event_flags, GRACE_ENIR_ILIM)):
            issues.append("sealing_tree_warp")
        if _flag(event_flags, SPIRIT_TREE_BURNING) and not _flag(event_flags, DEFEATED_ROMINA):
            issues.append("romina_missing")
        if _flag(event_flags, GOLEM_DEFEATED) and not _flag(event_flags, GOLEM_DESTROYED):
            issues.append("unte_golem_stuck")
        used = _flag(event_flags, USED_CAULDRON)
        maliketh = _flag(event_flags, DEFEATED_MALIKETH)
        if not used and not maliketh:
            burning = _flag(event_flags, WORLD_TREE_BURNING)
            sparks = _flag(event_flags, WORLD_TREE_SPARKS)
            flame = _flag(event_flags, WORLD_TREE_SMALL_FLAME)
            if burning or sparks or flame:
                issues.append("erdtree_pre_giant")
    except Exception:
        return issues
    return issues


def _dup_handles(items: list[tuple], label: str) -> list[dict]:
    """items are (ga_item_handle, quantity, inventory_index). Match Rust: goods (high byte 0xB0)."""
    findings = []
    seen: set[int] = set()
    dups = []
    for handle, _qty, _idx in items:
        if handle == 0:
            continue
        # Rust validator only flags goods handles (0xB0......).
        if (handle >> 24) != 0xB0:
            continue
        if handle in seen:
            dups.append(handle)
        else:
            seen.add(handle)
    if dups:
        findings.append({
            "level": "warn", "code": "duplicate_inventory",
            "title": f"Duplicate inventory handles ({label})",
            "detail": f"{len(set(dups))} repeated goods handle(s), e.g. {dups[0]:#010x}. Editors refuse to write this; the game may still load.",
        })
    return findings


def _dup_equip_ids(pairs: list[tuple], label: str) -> list[dict]:
    """pairs are (item_id, equipment_index)."""
    ids = [iid for iid, _ in pairs if iid]
    counts = Counter(ids)
    dups = [i for i, n in counts.items() if n > 1]
    if not dups:
        return []
    return [{
        "level": "warn", "code": "duplicate_inventory",
        "title": f"Duplicate {label} item IDs",
        "detail": f"{len(dups)} ID(s) appear more than once (e.g. {dups[0]:#x}).",
    }]


def _item_known(item_id: int, known: set[int]) -> bool:
    """True when the ID is vanilla/DLC or one of the game's own placeholders.

    Weapon IDs are base + affinity * 100 + upgrade (Heavy Uchigatana +14 is
    9000914); the bundled list holds base rows with upgrade levels but not
    affinity rows, so strip the low four digits before the lookup.
    """
    if item_id == 0 or item_id == 0xFFFFFFFF:
        return True
    if item_id in known:
        return True
    cat = item_id & 0xF0000000
    raw = item_id & 0x0FFFFFFF
    if cat == 0:  # weapon
        if raw == UNARMED_WEAPON:
            return True
        base = raw // 10000 * 10000
        if base in known or (base | (raw % 100)) in known:
            return True
    elif cat == 0x10000000 and raw in NAKED_ARMOR:  # empty armour slot
        return True
    elif cat == 0x80000000 and raw == 0:            # ash-of-war row the game itself makes for a weapon's own skill
        return True
    return False


def _referenced_handles(slot: dict) -> set[int]:
    """gaItem handles the character actually holds, stores or wears. The inventory arrays are sparse
    (the game leaves holes and places items past the count), so every non-zero entry counts."""
    refs: set[int] = set()
    for key in ("inventory", "storage"):
        box = slot.get(key) or {}
        for lst in ("common", "key"):
            for h, _q, _i in (box.get(lst) or []):
                if h:
                    refs.add(h)
    for key in ("equip_data", "chr_asm", "chr_asm2", "equipped_items"):
        refs.update(v for v in (slot.get(key) or []) if v)
    for key in ("quick", "pouch"):
        refs.update(v for v, _ in (slot.get(key) or []) if v)
    return refs


def _worn_ids(slot: dict) -> set[int]:
    """Item IDs on the character: chr_asm holds raw IDs, equipped_items full IDs (weapons, armour, talismans, quick, pouch)."""
    return {v for v in (slot.get("chr_asm") or []) if v} | {v for v in (slot.get("equipped_items") or []) if v}


def scan_mod_items(slot: dict, known: set[int] | None = None) -> dict:
    """Non-vanilla items on one character, for the Saves page and for Remove mod items.

    held:    entries in the held/chest arrays whose ID is outside the vanilla+DLC list, each with the
             gaItem row (weapons, armour, ashes of war) or the direct handle (goods, talismans), the
             quick/pouch slots that point at it, and whether it is worn.
    orphans: gaItem rows with a non-vanilla ID that no inventory entry references.
    """
    known = known if known is not None else known_item_ids()
    rows_by_handle = {}
    for ri, g in enumerate(slot.get("ga_items") or []):
        h = g.get("gaitem_handle") or 0
        if h and (g.get("item_id") or 0) not in (0, 0xFFFFFFFF):
            rows_by_handle[h] = (ri, g)
    worn = _worn_ids(slot)
    quick = slot.get("quick") or []
    pouch = slot.get("pouch") or []
    held = []
    seen_handles: set[int] = set()
    for box in ("inventory", "storage"):
        b = slot.get(box) or {}
        for lst in ("common", "key"):
            for pos, (h, q, _ix) in enumerate(b.get(lst) or []):
                if not h:
                    continue
                iid = direct_item_id(h)
                row = None
                if iid is None:
                    hit = rows_by_handle.get(h)
                    if not hit:
                        continue
                    row = hit[0]; iid = hit[1]["item_id"]
                if _item_known(iid, known):
                    continue
                name, source = item_label(iid)
                raw = iid & 0x0FFFFFFF
                held.append({
                    "box": box, "list": lst, "pos": pos, "handle": h, "item_id": iid, "qty": q,
                    "row": row, "name": name, "source": source,
                    # goods in a quick/pouch slot can be stripped (the slot is emptied); worn gear and talismans cannot
                    "worn": (iid in worn or raw in worn) and (row is not None or (iid & 0xF0000000) == 0x20000000),
                    "quick": [i for i, (a, _) in enumerate(quick) if a == h],
                    "pouch": [i for i, (a, _) in enumerate(pouch) if a == h],
                })
                seen_handles.add(h)
    orphans = []
    for h, (ri, g) in rows_by_handle.items():
        if h in seen_handles:
            continue
        iid = g["item_id"]
        if _item_known(iid, known) or iid in worn or (iid & 0x0FFFFFFF) in worn:
            continue
        name, source = item_label(iid)
        orphans.append({"row": ri, "handle": h, "item_id": iid, "name": name, "source": source})
    return {"held": held, "orphans": orphans}


def _group_names(entries: list[dict], limit: int = 5) -> str:
    """'Seamless Co-op: Tiny Great Pot, Effigy of Malenia (+3 more); Tarnished Pack: ...'"""
    by: dict[str, list[str]] = {}
    for e in entries:
        label = e["name"] + (" (worn)" if e.get("worn") else "")
        lst = by.setdefault(e["source"] or "Unknown mod", [])
        if label not in lst:
            lst.append(label)
    bits = []
    for src, names in by.items():
        more = f" (+{len(names) - limit} more)" if len(names) > limit else ""
        bits.append(f"{src}: {', '.join(names[:limit])}{more}")
    return "; ".join(bits)


def analyze_slot(slot: dict, slot_index: int, name: str, known: set[int] | None = None) -> list[dict]:
    findings = []
    tag = f"slot {slot_index + 1}" + (f" ({name})" if name else "")

    inv = slot.get("inventory") or {}
    stor = slot.get("storage") or {}
    # Only the live prefix counts; the rest of the fixed array is unused slots.
    inv_common = (inv.get("common") or [])[: int(inv.get("common_count") or 0)]
    stor_common = (stor.get("common") or [])[: int(stor.get("common_count") or 0)]
    findings.extend(_dup_handles(inv_common, f"{tag} held"))
    findings.extend(_dup_handles(stor_common, f"{tag} chest"))
    findings.extend(_dup_equip_ids(slot.get("quick") or [], f"{tag} quick slot"))
    findings.extend(_dup_equip_ids(slot.get("pouch") or [], f"{tag} pouch"))

    known = known if known is not None else known_item_ids()
    if known:
        scan = scan_mod_items(slot, known)
        if scan["held"]:
            n = len({e["item_id"] for e in scan["held"]})
            worn = sum(1 for e in scan["held"] if e["worn"])
            findings.append({
                "level": "warn", "code": "unknown_item",
                "title": f"Mod items held ({tag})",
                "detail": f"{n} item(s) outside the vanilla+DLC list. {_group_names(scan['held'])}. "
                          + ("Worn pieces must come off in-game before Remove mod items can strip them. " if worn else "")
                          + "Fine in co-op; a vanilla .sl2 should not carry them.",
            })
        if scan["orphans"]:
            findings.append({
                "level": "info", "code": "orphan_item",
                "title": f"Leftover mod item entries ({tag})",
                "detail": f"{len(scan['orphans'])} gaItem row(s) outside the vanilla+DLC list that nothing holds or wears: "
                          f"{_group_names(scan['orphans'], 4)}. Invisible in play; Review & fix can clear them.",
            })
    else:
        findings.append({
            "level": "ok", "code": "unknown_item",
            "title": "Item ID check skipped",
            "detail": "Bundled item list missing from this build.",
        })

    flags = slot.get("event_flags")
    if isinstance(flags, (bytes, bytearray)) and len(flags) == EVENT_FLAGS_SIZE:
        for key in detect_flag_issues(bytes(flags)):
            title, detail = _FLAG_ISSUE_TITLES.get(key, (key, "Known quest-flag inconsistency."))
            findings.append({
                "level": "warn", "code": "quest_flags",
                "title": f"{title} ({tag})",
                "detail": detail,
            })

    return findings


def analyze_parsed(parsed: dict, *, dlc_owned: bool | None = None, raw: bytes | None = None, tarnished: str | None = None) -> list[dict]:
    """Extra findings from a save_layout_check.parse result (active slots only). tarnished: None (read the save), 'yes', 'no'."""
    from roundtable_souls.saves import loading as save_loading
    findings = []
    owned = tarnished_owned(parsed, tarnished)
    known = effective_known(parsed, owned=owned, dlc_owned=dlc_owned)
    if dlc_owned is False and dlc_item_names():
        findings.append({"level": "info", "code": "dlc", "title": "Shadow of the Erdtree is not installed here",
                         "detail": "Its items count as outside the game on this PC and are listed under Remove mod items if a character holds any."})
    if tarnished_ids():
        if owned:
            findings.append({"level": "ok", "code": "tarnished", "title": "Tarnished Edition gear counts as vanilla",
                             "detail": "Forced on in Tools." if tarnished == "yes" else "The pack flag is set on this save, so its items are official content here."})
        elif tarnished_flag(parsed) and tarnished == "no":
            findings.append({"level": "info", "code": "tarnished", "title": "Tarnished Edition gear treated as mod items",
                             "detail": "Forced off in Tools, although the pack flag is set on this save."})
    for p in save_loading.plan_loading_fixes(parsed, dlc_owned):
        tag = f"slot {p['slot'] + 1}" + (f" ({p['name']})" if p["name"] else "")
        for key, label, action in zip(p["issues"], p["labels"], p["actions"]):
            findings.append({"level": "warn", "code": "loading", "key": key,
                             "title": f"{label} ({tag})", "detail": f"Can hang the loading screen. Fix loading: {action}"})
    if raw is not None:
        for i, why in sorted((parsed.get("unreadable") or {}).items()):
            if not (parsed.get("ud10") or {}).get("active_raw", [False] * 10)[i] or 0 < why.get("ver", 0) <= 81:
                continue                                     # old layouts are reported by save_info, not as damage
            name = ""
            try: name = (parsed["ud10"]["profiles"][i] or ("", 0))[0]
            except Exception: pass
            tag = f"slot {i + 1}" + (f" ({name})" if name else "")
            ud_sid = (parsed.get("ud10") or {}).get("steam_id")
            start = save_loading.L.HEADER + i * save_loading.F.SLOT_STRIDE + 0x10
            found = raw.rfind(__import__("struct").pack("<Q", ud_sid), start, start + save_loading.L.SLOT_SIZE) if ud_sid else -1
            where = f"its Steam ID sits {found - start:#x} bytes into the slot" if found >= 0 else "its Steam ID is not in the slot at all"
            findings.append({"level": "error", "code": "layout", "title": f"Torn write ({tag})",
                             "detail": f"The character is stamped with the current save version ({why.get('ver')}) but its layout does not parse ({why.get('error')}); {where}. "
                                       f"Bytes were inserted or lost mid-slot, usually by a crash while saving. Roundtable Souls does not repair this; er-save-manager's deep scan can."})
        for t in save_loading.torn_write_check(raw, parsed):
            tag = f"slot {t['slot'] + 1}" + (f" ({t['name']})" if t["name"] else "")
            where = f"found {t['shift']:+d} bytes from where the layout expects it" if t["shift"] is not None else "not found in the slot at all"
            findings.append({"level": "error", "code": "layout",
                             "title": f"Torn write ({tag})",
                             "detail": f"The character's Steam ID is {where}. Bytes were inserted or lost mid-slot, usually by a crash "
                                       f"while saving. Roundtable Souls does not repair this; er-save-manager's deep scan can."})
    active = (parsed.get("ud10") or {}).get("active") or []
    for i, slot in enumerate(parsed.get("slots") or []):
        if i < len(active) and not active[i]:
            continue
        name = ""
        try: name = slot["pgd"]["name"]
        except Exception: pass
        findings.extend(analyze_slot(slot, i, name, known))
    if not any(f["code"] == "duplicate_inventory" for f in findings):
        findings.append({
            "level": "ok", "code": "duplicate_inventory",
            "title": "No duplicate inventory handles",
            "detail": "Held and chest goods handles are unique on active characters.",
        })
    if known_item_ids() and not any(f["code"] == "unknown_item" and f["level"] == "warn" for f in findings):
        findings.append({
            "level": "ok", "code": "unknown_item",
            "title": "Item IDs look vanilla",
            "detail": "Active characters' gaItem IDs are in the bundled vanilla+DLC list.",
        })
    if _bst_map() and not any(f["code"] == "quest_flags" for f in findings):
        findings.append({
            "level": "ok", "code": "quest_flags",
            "title": "No known quest-flag soft-locks",
            "detail": "Checked Ranni, Radahn/Morgott/Radagon warp, Sealing Tree, Unte golem, early Erdtree.",
        })
    return findings


def findings_are_clean(findings: list[dict], *, allow_warn: bool = False) -> bool:
    """True when nothing blocks a .co2 -> .sl2 copy. Regulation must be OK; layout OK; no warn/error unless allow_warn."""
    for f in findings:
        if f.get("level") == "info":
            continue
        if f.get("level") == "error":
            return False
        if f.get("level") == "warn" and not allow_warn:
            return False
        if f.get("code") == "regulation" and f.get("level") != "ok":
            return False
        if f.get("code") == "layout" and f.get("level") != "ok":
            return False
    return True


def format_health_report(info: dict) -> str:
    """Plain-text health report suitable for clipboard."""
    lines = [
        "Roundtable Souls save health report",
        f"File: {info.get('name', '?')}  ({info.get('kind', '?')})",
        f"Path: {info.get('path', '?')}",
        f"Modified: {info.get('modified', '?')}",
        f"Regulation block: {info.get('block', '?')}",
        "",
    ]
    chars = info.get("characters") or []
    if chars:
        lines.append("Characters:")
        for ch in chars:
            ok = "checksum OK" if ch.get("ok") else "checksum MISMATCH"
            lines.append(f"  slot {ch['slot']}: {ch['name']}  Lv {ch['level']}  {ch['body']}  HP {ch['hp']:,}  runes {ch['runes']:,}  ({ok})")
        lines.append("")
    lines.append("Findings:")
    for f in info.get("findings") or []:
        mark = {"ok": "OK", "info": "INFO", "warn": "WARN", "error": "ERROR"}.get(f.get("level"), "?")
        lines.append(f"  [{mark}] {f.get('title', '')}")
        detail = (f.get("detail") or "").strip()
        if detail:
            lines.append(f"         {detail}")
    if info.get("error") and not info.get("findings"):
        lines.append(f"  ERROR: {info['error']}")
    lines.append("")
    clean = findings_are_clean(info.get("findings") or [])
    lines.append("Convert .co2 → .sl2: " + ("allowed (findings clean)" if clean else "blocked until warnings/errors are cleared or repaired"))
    return "\n".join(lines)
