"""Rebuilds the bundled item lists from the two reference repos (read-only):

  known_item_ids.txt    vanilla + Shadow of the Erdtree full IDs (category in the high nibble:
                        weapon 0x0, armour 0x1, talisman 0x2, goods 0x4, ash of war 0x8)
  mod_item_names.txt    "fullid,source,name" for items that known mods add (Seamless Co-op,
                        Tarnished Pack, Convergence) so the Saves page can name what it strips
  dlc_item_names.txt    "fullid,name" for Shadow of the Erdtree items (from the DLC csv folder), so a save on
                        a PC without the DLC installed can show them as DLC items rather than vanilla

Sources:
  Elden-Ring-Save-Editor/src/db/*_name.rs      Paramdex name tables = every param row the game has
  Elden-Ring-Save-Editor/src/db/{items,weapons,armors,talismans,aows}.rs
  er-save-manager/src/er_save_manager/data/items/**.csv   (vanilla, DLC and the mod folders)

Weapons: base + affinity*100 + upgrade; the table lists bases, so upgrade 0..25 is appended and the
analyzer strips affinity. Spirit ashes get +0..+10. Run:  uv run python scripts/build_known_ids.py
"""
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "src" / "roundtable_souls" / "data"
REPOS = Path(os.environ.get("ER_REPOS", Path(__file__).resolve().parents[2]))   # er-save-manager and Elden-Ring-Save-Editor checked out here
ERSM = REPOS / "er-save-manager" / "src" / "er_save_manager" / "data" / "items"
RUST = REPOS / "Elden-Ring-Save-Editor" / "src" / "db"

WEAPON, ARMOR, TALISMAN, GOODS, AOW = 0x00000000, 0x10000000, 0x20000000, 0x40000000, 0x80000000
MAX_UPGRADE = 25
MAX_ASH = 10
NAME_TABLES = {"item_name": GOODS, "weapon_name": WEAPON, "armor_name": ARMOR, "accessory_name": TALISMAN, "aow_name": AOW}
ENTRY = re.compile(r'^\s*\((\d+)\s*,\s*"((?:[^"\\]|\\.)*)"\s*\)', re.M)


def csv_rows(path: Path):
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines()[1:]:
        parts = line.split(",")
        cell = parts[0].strip()
        try:
            v = int(cell)
        except ValueError:
            continue
        if v >= 0:
            rows.append((v, parts[1].strip() if len(parts) > 1 else ""))
    return rows


def category_for(rel: str):
    r = "/" + rel.replace("\\", "/")
    if r.endswith("armor_slot_types.csv"):
        return None, None
    source = "Seamless Co-op" if r.endswith("SeamlessCoop.csv") else "Tarnished Pack" if "/TarnishedPack/" in r \
        else "Convergence" if "/Convergence/" in r else None
    if "/Weapons/" in r or "/DLCWeapons/" in r or "Weapons.csv" in r or r.endswith(("Ammo.csv", "Shields.csv", "SpellTools.csv")):
        cat = "weapon"
    elif r.endswith("Armor.csv"):
        cat = "armor"
    elif r.endswith("Talismans.csv"):
        cat = "talisman"
    elif r.endswith("Gems.csv"):
        cat = "aow"
    elif r.endswith("Ashes.csv"):
        cat = "ashes"
    elif "/Goods/" in r or "/DLCGoods/" in r or r.endswith(("Magic.csv", "Goods.csv", "Spelltools/ConvergenceSpellTools.csv")):
        cat = "goods"
    else:
        raise SystemExit(f"unclassified csv: {rel}")
    return cat, source


def expand(cat: str, i: int):
    if cat == "weapon":
        return {WEAPON | (i + u) for u in range(MAX_UPGRADE + 1)}
    if cat == "armor":
        return {ARMOR | i}
    if cat == "talisman":
        return {TALISMAN | i}
    if cat == "aow":
        return {AOW | i}
    if cat == "ashes":
        return {GOODS | (i + u) for u in range(MAX_ASH + 1)}
    return {GOODS | i}


def main():
    if not ERSM.is_dir() or not RUST.is_dir():
        raise SystemExit(f"reference repos not found under {REPOS} (set ER_REPOS)")
    known: set[int] = set()
    mods: dict[int, tuple[str, str]] = {}
    dlc: dict[int, str] = {}
    per = {}

    # 1. Paramdex name tables: the authoritative vanilla + DLC row list.
    for name, cat_bits in NAME_TABLES.items():
        text = (RUST / f"{name}.rs").read_text(encoding="utf-8")
        n = 0
        for m in ENTRY.finditer(text):
            v = int(m.group(1)); n += 1
            if cat_bits == WEAPON:
                base = v // 100 * 100
                known.update(WEAPON | (base + u) for u in range(MAX_UPGRADE + 1))
            elif cat_bits == GOODS and 200000 <= v < 300000 or 2200000 <= v < 2300000:
                known.update(GOODS | (v + u) for u in range(MAX_ASH + 1))   # spirit ash upgrade levels
            else:
                known.add(cat_bits | v)
        per[f"rust {name}.rs"] = n

    # 2. The Rust editor's curated lists (full IDs with category bits).
    for name in ("items", "weapons", "armors", "talismans", "aows"):
        text = (RUST / f"{name}.rs").read_text(encoding="utf-8")
        n = 0
        for m in re.finditer(r"0x([0-9A-Fa-f]{8})", text):
            v = int(m.group(1), 16); n += 1
            if v == 0xFFFFFFFF:
                continue
            if (v & 0xF0000000) == WEAPON:
                base = (v & 0x0FFFFFFF) // 100 * 100
                known.update(base + u for u in range(MAX_UPGRADE + 1))
            else:
                known.add(v)
        per[f"rust {name}.rs"] = n

    # 3. er-save-manager CSVs: vanilla/DLC folders add to known; mod folders go to the mod table.
    for p in sorted(ERSM.rglob("*.csv")):
        rel = str(p.relative_to(ERSM))
        cat, source = category_for(rel)
        if cat is None:
            continue
        rows = csv_rows(p)
        per[rel] = len(rows)
        for v, label in rows:
            ids = expand(cat, v)
            if source:
                for i in ids:
                    mods.setdefault(i, (source, label))
                if source == "Tarnished Pack" and cat == "armor":
                    mods.setdefault(ARMOR | (v + 1000), (source, label + " (altered)"))   # altered variants sit at +1000
            else:
                known.update(ids)
                if "/DLC/" in ("/" + rel.replace("\\", "/")):
                    for i in ids:
                        dlc.setdefault(i, label)

    for i in list(mods):
        if i in known:
            del mods[i]            # a mod list re-listing a vanilla item is still vanilla
    known.add(0xFFFFFFFF)
    (HERE / "known_item_ids.txt").write_text("\n".join(str(i) for i in sorted(known)) + "\n", encoding="utf-8")
    (HERE / "mod_item_names.txt").write_text(
        "".join(f"{i},{src},{label}\n" for i, (src, label) in sorted(mods.items())), encoding="utf-8")
    (HERE / "dlc_item_names.txt").write_text("".join(f"{i},{label}\n" for i, label in sorted(dlc.items())), encoding="utf-8")
    print(f"dlc items: {len(dlc)}")
    cats = {}
    for i in known:
        cats[hex(i & 0xF0000000)] = cats.get(hex(i & 0xF0000000), 0) + 1
    print(f"known: {len(known)} ids  by category {cats}")
    srcs = {}
    for src, _ in mods.values():
        srcs[src] = srcs.get(src, 0) + 1
    print(f"mod items: {len(mods)}  {srcs}")
    for rel, n in per.items():
        print(f"  {n:5d}  {rel}")


if __name__ == "__main__":
    main()
