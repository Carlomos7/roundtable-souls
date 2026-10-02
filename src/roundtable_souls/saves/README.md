# saves

Parsing, read-only checks and named repairs for Elden Ring PC saves (`ER0000.sl2`, `ER0000.co2`).

| Module | Role |
| --- | --- |
| `container.py` | Structure check for a BND4 save: the header, the section count the game writes, and every section and name inside the file. |
| `nightreign.py` | Nightreign decrypt / MD5 / re-sign (original IV), and restore of entry 12 from a healthy sibling when me3 left it unreadable. |
| `layout.py` | Elden Ring save parser. Version aware and tolerant: a slot that does not parse is reported, the others still load. `active_slots` and `character_name` read the parsed result. |
| `analyze.py` | Findings (ok / info / warn / error): duplicate entries, items the game does not define, torn writes. `Catalog` decides what counts as a game item for one save. Never writes. |
| `item_names.py` | Names for items the game does not define, read at runtime from the installed mods: Seamless Co-op's language file and other mods' item text tables. |
| `fix.py` | Checksum repair, and the commit step every repair uses: `backup` (with a JSON note of what changed) and `_commit` (verify, back up, replace). |
| `loading.py` | States that hang the loading screen, as a table of `LoadCheck`s, each with a detector and an in-place repair. |
| `vanilla.py` | Remove mod items per character, opt-in and per item. Rows are neutralised in place so nothing shifts. |
| `regulation.py` | Rebuild the regulation block me3 leaves dirty, from the game's `regulation.bin`. |
| `repair.py` | After play: wait until the game has let go of its saves, then repair every save of the active game (Elden Ring: `regulation.py`; Nightreign: `nightreign.py`). |
| `backups.py` | Where a save's backups and library copies live in the data folder, the note beside each backup, retention (`KEEP_NEWEST`, `KEEP_DAYS`), and moving older tools' folders in. |
| `models.py` | The shapes save info and findings are validated against before the window sees them. |

## Format facts the code relies on

- Header 0x300, then 10 slots of 0x280000 bytes, each preceded by its 16-byte MD5. USER_DATA_10 holds the profile summary, USER_DATA_11 the regulation block.
- gaItem rows are 21 (weapon), 16 (armour) or 8 (other) bytes. Slot versions up to 81 hold 0x13FE rows; later versions hold more, and tail fields shift by 4 bytes from version 65 and 1 more from 66.
- Inventory arrays are sparse: holes inside the count are normal and live entries can sit past it. Removing an entry zeroes it and lowers the count.
- Handles: goods `0xB0000000 | id`, talismans `0xA0000000 | id`, weapons `0x8...`, armour `0x9...`, ashes of war `0xC...`. An empty quick or pouch slot is `(0, 0xFFFFFFFF)`; `equipped_items[22 + i]` mirrors quick slot `i` and `[32 + i]` pouch slot `i`.
- The per-character DLC block sits 0x20 bytes after the Steam ID: byte 1 marks having entered the Land of Shadow, byte 3 the Tarnished Edition pack.
- What counts as a game item: `../data/known_item_ids.txt` (rebuilt by `scripts/build_item_list.py`) plus every row of the item tables in the installed game's own `regulation.bin`, read at runtime by `formats/regulation.py`. The second covers official items the list lacks, such as the Tarnished Edition pack. Without the game on the PC, a save with the pack flag falls back to treating unlisted equipment as pack gear.
- Names for foreign items come from the mods themselves (`item_names.py`): Seamless Co-op's language file, and other mods' `msg/engus/item*.msgbnd.dcx` text tables.

Every write path refuses while the game runs and goes through `fix._commit`.

What the window calls (save info, backups, the repair behind each button, all gated on the game being closed) is `services/saves.py`.
