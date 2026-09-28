"""Read-only save checks: duplicate inventory entries, items the game does not define, and torn writes.

Never writes. The item check compares every held, stored and leftover item against the items the game defines: the
bundled list (data/known_item_ids.txt) plus every item in the installed game's own regulation.bin, which also covers
official content the list lacks, such as the Tarnished Edition pack. Anything outside both came from a mod; its name
comes from the mod's own files when they can be read (mods/item_names.py).
"""

from __future__ import annotations

import struct
from collections import Counter
from dataclasses import dataclass, field

from roundtable_souls import gamefiles
from roundtable_souls.resources import DATA_DIR

WEAPON, ARMOUR, TALISMAN, GOODS, ASH = 0x0, 0x1, 0x2, 0x4, 0x8
KIND_NAMES = {WEAPON: "Weapon", ARMOUR: "Armour", TALISMAN: "Talisman", GOODS: "Item", ASH: "Ash of War"}
EQUIPMENT = frozenset((WEAPON, ARMOUR, TALISMAN))
UNLISTED = "Not in the game"

# Rows the game itself writes for empty slots and built-in skills; never foreign.
UNARMED_WEAPON = 110000
NAKED_ARMOR = frozenset((10000, 10100, 10200, 10300))
EMPTY_IDS = frozenset((0, 0xFFFFFFFF))

TARNISHED_FLAG_BYTE = 3  # in the per-character DLC block

_KNOWN_IDS: set[int] | None = None
_GAME_IDS: tuple[tuple, frozenset[int]] | None = None


def known_item_ids() -> set[int]:
    """Every item ID the game defines (base game and Shadow of the Erdtree), loaded once."""
    global _KNOWN_IDS
    if _KNOWN_IDS is None:
        path = DATA_DIR / "known_item_ids.txt"
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        _KNOWN_IDS = {int(line) for line in text.split() if line.isdigit()}
    return _KNOWN_IDS


def game_item_ids() -> frozenset[int]:
    """Every item the installed game's regulation.bin defines (empty when the game or the file cannot be read).
    Read once per version of the file."""
    global _GAME_IDS
    from roundtable_souls.system import common

    path = common.regulation_bin()
    if path is None:
        return frozenset()
    try:
        stamp = (str(path), path.stat().st_mtime_ns, path.stat().st_size)
    except OSError:
        return frozenset()
    if _GAME_IDS and _GAME_IDS[0] == stamp:
        return _GAME_IDS[1]
    try:
        ids = gamefiles.regulation_item_ids(path.read_bytes())
    except OSError, gamefiles.FormatError, ValueError, IndexError:
        ids = frozenset()
    _GAME_IDS = (stamp, ids)
    return ids


def kind_of(item_id: int) -> int:
    return (item_id >> 28) & 0xF


def direct_item_id(handle: int) -> int | None:
    """Goods and talismans are stored by ID in the inventory handle itself; other kinds point at a gaItem row."""
    kind = handle >> 28
    if kind == 0xB:
        return (GOODS << 28) | (handle & 0x00FFFFFF)
    if kind == 0xA:
        return (TALISMAN << 28) | (handle & 0x00FFFFFF)
    return None


def tarnished_flag(parsed: dict) -> bool:
    """True when any active character has the Tarnished Edition pack enabled."""
    for _i, slot in active_slots(parsed):
        dlc = slot.get("dlc") or b""
        if len(dlc) > TARNISHED_FLAG_BYTE and dlc[TARNISHED_FLAG_BYTE]:
            return True
    return False


@dataclass(frozen=True)
class Catalog:
    """Decides whether an item ID belongs to the game for one save."""

    known: frozenset[int] = field(default_factory=frozenset)
    pack: bool = False  # the save has the Tarnished Edition pack enabled
    game: frozenset[int] = field(default_factory=frozenset)  # items the installed game's regulation defines

    @classmethod
    def for_save(cls, parsed: dict | None = None, game: frozenset[int] | None = None) -> Catalog:
        return cls(frozenset(known_item_ids()), tarnished_flag(parsed or {}), game_item_ids() if game is None else game)

    @property
    def available(self) -> bool:
        return bool(self.known)

    def _listed(self, item_id: int) -> bool:
        return item_id in self.known or item_id in self.game

    def is_game_item(self, item_id: int) -> bool:
        if item_id in EMPTY_IDS or self._listed(item_id):
            return True
        kind, raw = kind_of(item_id), item_id & 0x0FFFFFFF
        if kind == WEAPON:
            # base row + affinity * 100 + upgrade: compare the base row, and the base row at this upgrade level
            if raw == UNARMED_WEAPON:
                return True
            base = raw // 10000 * 10000
            if self._listed(base) or self._listed(base + raw % 100):
                return True
        elif kind == ARMOUR and raw in NAKED_ARMOR:
            return True
        elif kind == ASH and raw == 0:
            return True
        # Without the game's own item tables (the game is not on this PC), fall back to assuming a save with the
        # pack enabled got its unlisted equipment from the pack.
        return not self.game and self.pack and kind in EQUIPMENT


def item_label(item_id: int) -> tuple[str, str]:
    """(display name, source) for an item the game does not define: the mod's own name when its files can be read,
    otherwise the kind and ID."""
    from roundtable_souls.mods.item_names import item_names

    named = item_names().get(item_id)
    if named:
        return named
    kind, raw = kind_of(item_id), item_id & 0x0FFFFFFF
    label = KIND_NAMES.get(kind, "Item")
    if kind == WEAPON and raw % 100:
        return f"{label} {raw - raw % 100} +{raw % 100}", UNLISTED
    return f"{label} {raw}", UNLISTED


def active_slots(parsed: dict):
    """(index, slot) for every slot marked active in the profile summary."""
    active = (parsed.get("ud10") or {}).get("active") or []
    for i, slot in enumerate(parsed.get("slots") or []):
        if i < len(active) and active[i]:
            yield i, slot


def character_name(slot: dict) -> str:
    return str((slot.get("pgd") or {}).get("name") or "")


def slot_tag(index: int, name: str) -> str:
    return f"slot {index + 1}" + (f" ({name})" if name else "")


# ----------------------------------------------------------------------------- duplicates


def _duplicate_goods(entries: list[tuple], label: str) -> list[dict]:
    """(handle, quantity, index) triples: a goods handle listed twice is what editors refuse to write."""
    counts = Counter(h for h, _q, _i in entries if h and (h >> 24) == 0xB0)
    repeated = [h for h, n in counts.items() if n > 1]
    if not repeated:
        return []
    return [
        {
            "level": "warn",
            "code": "duplicate_inventory",
            "title": f"Duplicate inventory entries ({label})",
            "detail": f"{len(repeated)} item(s) listed twice, e.g. {repeated[0]:#010x}. "
            "Save editors refuse to write this; the game may still load it.",
        }
    ]


def _duplicate_ids(pairs: list[tuple], label: str) -> list[dict]:
    counts = Counter(iid for iid, _ in pairs if iid)
    repeated = [i for i, n in counts.items() if n > 1]
    if not repeated:
        return []
    return [
        {
            "level": "warn",
            "code": "duplicate_inventory",
            "title": f"Duplicate {label} entries",
            "detail": f"{len(repeated)} item(s) appear more than once (e.g. {repeated[0]:#x}).",
        }
    ]


# ----------------------------------------------------------------------------- foreign items


def _worn_ids(slot: dict) -> set[int]:
    """IDs on the character: chr_asm holds raw IDs, equipped_items full IDs (gear, talismans, quick, pouch)."""
    return {v for v in (slot.get("chr_asm") or []) if v} | {v for v in (slot.get("equipped_items") or []) if v}


def scan_mod_items(slot: dict, catalog: Catalog | None = None) -> dict:
    """Items on one character that the game does not define.

    held:    inventory and chest entries, each with its gaItem row (weapons, armour, ashes) or direct handle
             (goods, talismans), the quick / pouch slots pointing at it, and whether it is worn.
    orphans: gaItem rows with a foreign ID that no inventory entry references.
    """
    catalog = catalog or Catalog.for_save()
    rows = {}
    for index, row in enumerate(slot.get("ga_items") or []):
        handle = row.get("gaitem_handle") or 0
        if handle and (row.get("item_id") or 0) not in EMPTY_IDS:
            rows[handle] = (index, row)
    worn = _worn_ids(slot)
    quick = slot.get("quick") or []
    pouch = slot.get("pouch") or []
    held, seen = [], set()
    for box in ("inventory", "storage"):
        lists = slot.get(box) or {}
        for part in ("common", "key"):
            for pos, (handle, qty, _index) in enumerate(lists.get(part) or []):
                if not handle:
                    continue
                item_id, row = direct_item_id(handle), None
                if item_id is None:
                    if handle not in rows:
                        continue
                    row, item_id = rows[handle][0], rows[handle][1]["item_id"]
                if catalog.is_game_item(item_id):
                    continue
                name, source = item_label(item_id)
                raw = item_id & 0x0FFFFFFF
                held.append(
                    {
                        "box": box,
                        "list": part,
                        "pos": pos,
                        "handle": handle,
                        "item_id": item_id,
                        "qty": qty,
                        "row": row,
                        "name": name,
                        "source": source,
                        # worn gear and talismans stay; goods in a quick or pouch slot can go (the slot is emptied)
                        "worn": (item_id in worn or raw in worn) and (row is not None or kind_of(item_id) == TALISMAN),
                        "quick": [i for i, (h, _) in enumerate(quick) if h == handle],
                        "pouch": [i for i, (h, _) in enumerate(pouch) if h == handle],
                    }
                )
                seen.add(handle)
    orphans = []
    for handle, (index, row) in rows.items():
        item_id = row["item_id"]
        if handle in seen or catalog.is_game_item(item_id) or item_id in worn or (item_id & 0x0FFFFFFF) in worn:
            continue
        name, source = item_label(item_id)
        orphans.append({"row": index, "handle": handle, "item_id": item_id, "name": name, "source": source})
    return {"held": held, "orphans": orphans}


def _name_list(entries: list[dict], limit: int = 5) -> str:
    """'Seamless Co-op: Tiny Great Pot, Effigy of Malenia (+3 more); Not in the game: Armour 742000'"""
    by: dict[str, list[str]] = {}
    for e in entries:
        label = e["name"] + (" (worn)" if e.get("worn") else "")
        names = by.setdefault(e.get("source") or UNLISTED, [])
        if label not in names:
            names.append(label)
    parts = []
    for source, names in by.items():
        more = f" (+{len(names) - limit} more)" if len(names) > limit else ""
        parts.append(f"{source}: {', '.join(names[:limit])}{more}")
    return "; ".join(parts)


def analyze_slot(slot: dict, index: int, name: str, catalog: Catalog) -> list[dict]:
    findings = []
    tag = slot_tag(index, name)
    inv, chest = slot.get("inventory") or {}, slot.get("storage") or {}
    findings += _duplicate_goods((inv.get("common") or [])[: int(inv.get("common_count") or 0)], f"{tag} held")
    findings += _duplicate_goods((chest.get("common") or [])[: int(chest.get("common_count") or 0)], f"{tag} chest")
    findings += _duplicate_ids(slot.get("quick") or [], f"{tag} quick slot")
    findings += _duplicate_ids(slot.get("pouch") or [], f"{tag} pouch")
    if not catalog.available:
        return findings
    scan = scan_mod_items(slot, catalog)
    if scan["held"]:
        count = len({e["item_id"] for e in scan["held"]})
        worn = any(e["worn"] for e in scan["held"])
        findings.append(
            {
                "level": "warn",
                "code": "unknown_item",
                "title": f"Mod items held ({tag})",
                "detail": f"{count} item(s) the game does not define: {_name_list(scan['held'])}. "
                + ("Worn pieces have to come off in-game before they can be removed. " if worn else "")
                + "Fine in co-op; a standard save should not carry them.",
            }
        )
    if scan["orphans"]:
        findings.append(
            {
                "level": "info",
                "code": "orphan_item",
                "title": f"Leftover mod item entries ({tag})",
                "detail": f"{len(scan['orphans'])} item record(s) nothing holds or wears: "
                f"{_name_list(scan['orphans'], 4)}. Invisible in play; Review & fix can clear them.",
            }
        )
    return findings


# ----------------------------------------------------------------------------- whole save


def _torn_findings(parsed: dict, raw: bytes) -> list[dict]:
    from roundtable_souls.saves import loading as save_loading

    findings = []
    ud10 = parsed.get("ud10") or {}
    for i, why in sorted((parsed.get("unreadable") or {}).items()):
        if not ud10.get("active_raw", [False] * 10)[i] or 0 < why.get("ver", 0) <= 81:
            continue  # old layouts are reported by save_info, not as damage
        profiles = ud10.get("profiles") or []
        name = (profiles[i] or ("", 0))[0] if i < len(profiles) else ""
        steam_id = ud10.get("steam_id")
        start = save_loading.slot_start(i)
        found = raw.rfind(struct.pack("<Q", steam_id), start, start + save_loading.L.SLOT_SIZE) if steam_id else -1
        where = f"its Steam ID sits {found - start:#x} bytes in" if found >= 0 else "its Steam ID is missing"
        findings.append(
            {
                "level": "error",
                "code": "layout",
                "title": f"Torn write ({slot_tag(i, name)})",
                "detail": f"Stamped with the current save version ({why.get('ver')}) but the layout does not parse "
                f"({why.get('error')}); {where}. Bytes were inserted or lost mid-slot, usually by a crash while saving. "
                "Restore a backup from before the crash.",
            }
        )
    for t in save_loading.torn_write_check(raw, parsed):
        where = f"{t['shift']:+d} bytes from where it belongs" if t["shift"] is not None else "missing from the slot"
        findings.append(
            {
                "level": "error",
                "code": "layout",
                "title": f"Torn write ({slot_tag(t['slot'], t['name'])})",
                "detail": f"The character's Steam ID is {where}. Bytes were inserted or lost mid-slot, usually by a "
                "crash while saving. Restore a backup from before the crash.",
            }
        )
    return findings


def analyze_parsed(parsed: dict, *, dlc_owned: bool | None = None, raw: bytes | None = None) -> list[dict]:
    """Findings for a parsed save (active characters only)."""
    from roundtable_souls.saves import loading as save_loading

    findings = []
    catalog = Catalog.for_save(parsed)
    if catalog.pack:
        findings.append(
            {
                "level": "ok",
                "code": "tarnished",
                "title": "Tarnished Edition pack enabled",
                "detail": "Its gear is official content and is never treated as a mod item."
                if catalog.game
                else "The game's own item tables could not be read here, so unlisted equipment is taken to be pack gear.",
            }
        )
    for plan in save_loading.plan_loading_fixes(parsed, dlc_owned):
        for key, label, action in zip(plan["issues"], plan["labels"], plan["actions"]):
            findings.append(
                {
                    "level": "warn",
                    "code": "loading",
                    "key": key,
                    "title": f"{label} ({slot_tag(plan['slot'], plan['name'])})",
                    "detail": f"Can hang the loading screen. Fix loading: {action}",
                }
            )
    if raw is not None:
        findings += _torn_findings(parsed, raw)
    for i, slot in active_slots(parsed):
        findings += analyze_slot(slot, i, character_name(slot), catalog)
    if not any(f["code"] == "duplicate_inventory" for f in findings):
        findings.append(
            {
                "level": "ok",
                "code": "duplicate_inventory",
                "title": "No duplicate inventory entries",
                "detail": "Held and chest items are each listed once.",
            }
        )
    if catalog.available and not any(f["code"] == "unknown_item" for f in findings):
        findings.append(
            {
                "level": "ok",
                "code": "unknown_item",
                "title": "Only game items",
                "detail": "Every item on the active characters is one the game defines.",
            }
        )
    return findings


def findings_are_clean(findings: list[dict], *, allow_warn: bool = False) -> bool:
    """True when nothing blocks a .co2 -> .sl2 copy: no errors, no warnings (unless allowed), regulation and layout OK."""
    for f in findings:
        level, code = f.get("level"), f.get("code")
        if level == "info":
            continue
        if level == "error" or (level == "warn" and not allow_warn):
            return False
        if code in ("regulation", "layout") and level != "ok":
            return False
    return True


def format_health_report(info: dict) -> str:
    """Plain-text report for the clipboard."""
    lines = [
        "Roundtable Souls save report",
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
            lines.append(
                f"  slot {ch['slot']}: {ch['name']}  Lv {ch['level']}  {ch['body']}  HP {ch['hp']:,}  "
                f"runes {ch['runes']:,}  ({ok})"
            )
        lines.append("")
    lines.append("Findings:")
    marks = {"ok": "OK", "info": "INFO", "warn": "WARN", "error": "ERROR"}
    for f in info.get("findings") or []:
        lines.append(f"  [{marks.get(f.get('level'), '?')}] {f.get('title', '')}")
        detail = (f.get("detail") or "").strip()
        if detail:
            lines.append(f"         {detail}")
    if info.get("error") and not info.get("findings"):
        lines.append(f"  ERROR: {info['error']}")
    lines.append("")
    clean = findings_are_clean(info.get("findings") or [])
    lines.append("Copy to standard save: " + ("ready" if clean else "notes above are still open"))
    return "\n".join(lines)
