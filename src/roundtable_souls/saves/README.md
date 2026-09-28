# saves

Parsing, read-only checks and named repairs for Elden Ring PC saves (`ER0000.sl2`, `ER0000.co2`).

| Module | Role |
| --- | --- |
| `layout.py` | Save parser. Version aware and tolerant: a slot that does not parse is reported, the others still load. |
| `analyze.py` | Findings (ok / info / warn / error): duplicate entries, items the game does not define, torn writes. `Catalog` decides what counts as a game item for one save. Never writes. |
| `fix.py` | Checksum repair, and the commit step every repair uses: `backup` (with a JSON note of what changed) and `_commit` (verify, back up, replace). |
| `loading.py` | States that hang the loading screen, as a table of `LoadCheck`s, each with a detector and an in-place repair. |
| `vanilla.py` | Remove mod items per character, opt-in and per item. Rows are neutralised in place so nothing shifts. |
| `regulation.py` | Rebuild the regulation block me3 leaves dirty, from the game's `regulation.bin`. |
| `service.py` | What the window sees: `save_info` (validated against `models.SaveInfo`), backups, copies between standard and co-op saves, and the repair behind each button, all gated on the game being closed. |

## Format facts the code relies on

- Header 0x300, then 10 slots of 0x280000 bytes, each preceded by its 16-byte MD5. USER_DATA_10 holds the profile summary, USER_DATA_11 the regulation block.
- gaItem rows are 21 (weapon), 16 (armour) or 8 (other) bytes. Slot versions up to 81 hold 0x13FE rows; later versions hold more, and tail fields shift by 4 bytes from version 65 and 1 more from 66.
- Inventory arrays are sparse: holes inside the count are normal and live entries can sit past it. Removing an entry zeroes it and lowers the count.
- Handles: goods `0xB0000000 | id`, talismans `0xA0000000 | id`, weapons `0x8...`, armour `0x9...`, ashes of war `0xC...`. An empty quick or pouch slot is `(0, 0xFFFFFFFF)`; `equipped_items[22 + i]` mirrors quick slot `i` and `[32 + i]` pouch slot `i`.
- The per-character DLC block sits 0x20 bytes after the Steam ID: byte 1 marks having entered the Land of Shadow, byte 3 the Tarnished Edition pack.
- What counts as a game item: `../data/known_item_ids.txt` (rebuilt by `scripts/build_item_list.py`) plus every row of the item tables in the installed game's own `regulation.bin`, read at runtime by `gamefiles.py`. The second covers official items the list lacks, such as the Tarnished Edition pack. Without the game on the PC, a save with the pack flag falls back to treating unlisted equipment as pack gear.
- Names for foreign items come from the mods themselves (`mods/item_names.py`): Seamless Co-op's language file, and other mods' `msg/engus/item*.msgbnd.dcx` text tables.

Every write path refuses while the game runs and goes through `fix._commit`.
