"""Rebuild src/roundtable_souls/data/known_item_ids.txt: every item ID the game defines, one per line.

Source: the item ID tables of Elden-Ring-Save-Editor (Apache-2.0), src/db/{item,weapon,armor,accessory,aow}_name.rs.
Only the numeric IDs are taken, never names. IDs carry the category in the high nibble (weapon 0x0, armour 0x1,
talisman 0x2, goods 0x4, ash of war 0x8). Weapons get every upgrade level 0..25 on top of the base row, spirit ashes
+0..+10; affinity rows are handled at lookup time.

    uv run python scripts/build_item_list.py [path/to/Elden-Ring-Save-Editor]

Without an argument the editor is looked for next to this repo, or in ER_SAVE_EDITOR.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "roundtable_souls" / "data" / "known_item_ids.txt"
WEAPON, ARMOR, TALISMAN, GOODS, AOW = 0x00000000, 0x10000000, 0x20000000, 0x40000000, 0x80000000
TABLES = {"item_name": GOODS, "weapon_name": WEAPON, "armor_name": ARMOR, "accessory_name": TALISMAN, "aow_name": AOW}
MAX_UPGRADE = 25
MAX_SPIRIT_ASH = 10
ROW = re.compile(r"^\s*\((\d+)\s*,", re.M)


def is_spirit_ash(goods_id: int) -> bool:
    return 200000 <= goods_id < 300000 or 2200000 <= goods_id < 2300000


def ids_from(db: Path) -> set[int]:
    known: set[int] = set()
    for table, category in TABLES.items():
        for m in ROW.finditer((db / f"{table}.rs").read_text(encoding="utf-8")):
            raw = int(m.group(1))
            if category == WEAPON:
                base = raw // 100 * 100
                known.update(WEAPON | (base + level) for level in range(MAX_UPGRADE + 1))
            elif category == GOODS and is_spirit_ash(raw):
                known.update(GOODS | (raw + level) for level in range(MAX_SPIRIT_ASH + 1))
            else:
                known.add(category | raw)
    return known


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ER_SAVE_EDITOR")
    editor = Path(arg) if arg else ROOT.parent / "Elden-Ring-Save-Editor"
    db = editor / "src" / "db"
    if not db.is_dir():
        print(f"not found: {db}", file=sys.stderr)
        return 1
    known = ids_from(db)
    OUT.write_text("\n".join(str(i) for i in sorted(known)) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(known):,} IDs -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
