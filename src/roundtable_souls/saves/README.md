# saves

Parsing, read-only analysis and named repairs for Elden Ring PC saves (`ER0000.sl2`, `ER0000.co2`).

| Module | Role |
| --- | --- |
| `layout.py` | BND4 container and per-slot parser. Version aware and tolerant: a slot that does not parse is reported, the others still load. |
| `analyze.py` | Findings (ok / info / warn / error): checksums, duplicates, unknown items, quest soft-locks, torn writes. Never writes. |
| `fix.py` | Quest-flag repairs and checksum re-signing. Owns `backup` (with a JSON manifest) and `_commit` (verify, back up, replace). |
| `loading.py` | The save states that hang the loading screen (Torrent, position, DLC area or flag, weather) and their fixes. |
| `vanilla.py` | Remove mod items per character, opt-in and per item. Rows are neutralised in place so nothing shifts. |
| `regulation.py` | Rebuild the regulation block me3 leaves dirty, from the game's `regulation.bin`. |

## Format facts the code relies on

- Header 0x300, then 10 slots of 0x280000 bytes, each preceded by its 16-byte MD5. USER_DATA_10 holds the profile summary, USER_DATA_11 the regulation block.
- gaItem rows are 21 (weapon), 16 (armour) or 8 (other) bytes. Slot versions up to 81 hold 0x13FE rows; later versions hold more, and tail fields shift by 4 bytes from version 65 and 1 more from 66.
- Inventory arrays are sparse: holes inside the count are normal and live entries can sit past it. Stripping an entry zeroes it and lowers the count.
- Handles: goods `0xB0000000 | id`, talismans `0xA0000000 | id`, weapons `0x8...`, armour `0x9...`, ashes of war `0xC...`. An empty quick or pouch slot is `(0, 0xFFFFFFFF)`; `equipped_items[22 + i]` mirrors quick slot `i` and `[32 + i]` pouch slot `i`.
- The DLC block sits 0x20 bytes after the Steam ID: byte 1 is "entered the Land of Shadow", byte 3 is the Tarnished Edition pack flag.
- Bundled item lists live in `../data/` and are rebuilt by `scripts/build_known_ids.py`.

Every write path refuses while the game runs and goes through `fix._commit`.
