# Evidence ledger

What has been shown to work, what failed, and what is still open, for the plan in
[technical-specification.md](technical-specification.md) (v1.1). A check that has not been done stays **pending**; it is
never reported as passing. Newest entries are added at the end of each section.

Status words: **accepted** (shown to work where stated), **failed**, **pending** (not done yet), **unknown** (looked
into, not resolved).

## 1. Current state (Phase 0 inventory, 2026-09-30, release 3.13.1, commit ac14414; regulation writer as of 3.13.2)

**What the launcher writes today (Elden Ring, Windows)**

| Output | Written by | Layout |
|---|---|---|
| Merged archives and text (files two mods ship) | `mods/filemerge.py` via `mods/backends/builtin.py` (Combine) | DCX KRAK, Oodle level 6, header byte 6 (6/6), from the game's own Oodle DLL |
| Nightreign Revive build (preview setting) | `mods/engine.py` with the recipe `data/recipes/nightreign-revive-lite.json` | as above; the grace menu (ESD) still comes from Revive's Assets.exe |
| Combined parameters | `mods/param_merge.py` + `mods/paramfile.py` | regulation.bin: BND4 in DCX ZSTD (64 KB window, no content size: E-011), AES-encrypted |

**Format code and its callers**

| Module | Reads / writes | Called from |
|---|---|---|
| `gamefiles.py` | DCX decompression (KRAK with the game's Oodle, DFLT, ZSTD), regulation decryption | `mods/formats.py`, `mods/paramfile.py`, `mods/item_names.py` |
| `mods/formats.py` | DCX write, BND4 (general), FMG | `mods/filemerge.py`, `mods/backends/builtin.py`, `mods/engine.py` |
| `mods/paramfile.py` | PARAM, the regulation's binder rules and read/write (its own BND4 copy removed in Phase 1, E-012) | `mods/param_merge.py` |
| `mods/gamearchive.py` | the game's BHD5/BDT archives (RSA-decrypted indexes, cached) | `mods/backends/builtin.py`, `mods/engine.py` |
| `mods/filemerge.py` | three-way merge of archives and text | `mods/backends/builtin.py`, `mods/engine.py` |
| `mods/param_merge.py` | three-way merge of parameters, 4-byte chunks | `mods/backends/builtin.py`, `mods/engine.py` |
| `mods/profile.py` `effective_order` | predicted load order | `mods/merge.py`, `mods/manage.py`, `mods/stay_last.py` |

**Platform capability**

- Windows: KRAK read and write (the game's `oo2core_*_win64.dll`), DFLT and ZSTD read and write.
- Linux (native Python): no Oodle, so KRAK files can be neither read nor written; DFLT and ZSTD work. Whether a DFLT
  file can stand in for a KRAK one is experiment E-006.
- Steam Deck: nothing tested (no Deck available). Every Deck check below is **pending: needs a Deck**.

**Workflows**: `test.yml` (push and pull request to `main`/`dev`: ruff, pyright, pytest on Windows and Ubuntu),
`release.yml` (tags: verify, Windows and Linux builds, publish).

**Real-data checks**: `scripts/verify/` (see its README). Earlier one-off checks were run from a scratch folder; their
results are recorded below as E-001 to E-004.

## 2. Evidence

### E-001 Launcher-written 6/6 files load in game (Windows): withdrawn (not the launcher's files)

2026-09-30, Windows, Elden Ring regulation 11711000, me3 0.13.0. The owner played 15:13 to 15:19 from the hotfix build
(branch hotfix-3.13.1, commit 377e49f) after its "Rebuild combined parameters" job. Checked afterwards (that build's
`dist/logs/launcher.log`, the Revive folder's `installation.json` and `merge-report.txt`, the files' headers): the
job ran **Revive's own rebuild tool** (0.1.33-rc3, through the `manifest_refresh` backend), not the launcher's engine.
Every file played was that tool's: regulation.bin in its editor shape (zero IV, 64 KB zstd window), the high-detail
player animations and the common effects as **DFLT level 9**, menu text and the grace menu as KRAK 6. No
launcher-written file was in that session, so this entry shows nothing about the launcher's writers. The launcher's
engine and its Combine had never run on the owner's setup before 2026-09-30 (no log line, no record).

What the session does show: Revive's tool's output loads and plays (save loads, animations, grace menu, map markers,
common effects normal), including DFLT 9 archives for animations and effects on Windows, which bears on E-006.
Rain, co-op revive animations and the Deck stay **pending** as before.

The launcher's own files in game are E-005, E-006 and E-011.

### E-002 Independent reading of that output: accepted, with stated limits

Soulstruct (its own DCX, BND4 and FMG readers) opened every launcher-written file after the 6/6 change, with 0
validation failures: inner files, IDs, flags and contents equal a result worked out from the inputs; the 58 removals
are absent and the 4 additions present; the menu text table equals the reference tool's in all 15 languages (the 166
map-mod changes and 27 new strings were checked in English only); all 194 parameter tables equal the reference tool's
after decryption.

Limits: Soulstruct decompresses with Oodle too, so decompression is not independently checked. The parameter result
matches the reference tool; it was not worked out independently. The removal rule shares the reference tool's
unvalidated assumption (E-007).

### E-003 Header byte 4: a checker limitation, not a game result

Before 3.13.1, files over 16 MB were written at Oodle level 4 with byte 4 in the header. Soulstruct refused them; with
only that byte set to 6 it opened them and their contents were correct. This shows Soulstruct does not recognise that
header. It does not show whether the game accepts it; that is experiment E-005.

### E-004 Compression time at 6/6

A full engine build of Revive took 267 s at 6/6 (about 90 s before, when large files used level 4); the effects
archive alone took 150 s and the high-detail player animations 9 s. Level 4 and level 6 are different settings, so
this is not an equal-settings benchmark of two writers.

### E-005 DCX layouts 4/4, 4/6, 6/6 in game (Windows): accepted

Packages are made by `scripts/verify/ingame_package.py --layout 6/6|4/4|4/6`: two marker mods merged by the
launcher's own Combine, then stored in the layout under test, played on a separate save.

2026-09-30 (evening), Windows, Elden Ring 1.17.1 / regulation 11711000, me3 0.13.0, packages rebuilt after E-011's
fix. The owner ran each package's `launch.cmd`:

| Layout | Menu text (KRAK) | Player animations (KRAK) | Parameters | Windows | Deck |
|---|---|---|---|---|---|
| 6/6 | both tags shown | loads (no crash) | both classes' values shown | **accepted** | pending: needs a Deck |
| 4/4 | both tags shown | loads (no crash) | both classes' values shown | **accepted** | pending: needs a Deck |
| 4/6 | both tags shown | loads (no crash) | both classes' values shown | **accepted** | pending: needs a Deck |

What each check demonstrates, and what it does not:

- **Menu text.** The title menu read "NEW GAME [RS <layout> A]" and "SYSTEM [RS <layout> B]". Each mod changed one
  entry, so this shows the game read the launcher-merged `menu_dlc02.msgbnd.dcx` in that layout and that both mods'
  entries survived the merge. It does not show the other 14 languages in game.
- **Parameters.** Class selection showed Vagabond Vigor 20 / Mind 5 and Warrior Vigor 16 / Mind 7 (one mod changed
  each class). This shows the game read the launcher-combined regulation.bin and applied both mods' rows of
  CharaInitParam. It does not exercise any other table in game.
- **Player animations.** The game reached the title screen and class selection, where the player model is shown,
  without a crash, with the launcher-merged `c0000_a00_hi.anibnd.dcx` (one unused clip added) in the package. This
  shows the archive in that layout did not stop the game from loading. It does not show that any clip plays or that
  a change applies: no visible change was in the package, and the optional movement step's result was not reported.

Before play (same day, earlier): each stored file reads back to the merged content. `verify_output.py` with
Soulstruct 2.6.0: 6/6 and 4/6 have 0 validation failures (inner files, IDs, flags, contents; both mods' menu text
changes merged entry by entry; exactly the 2 changed parameter rows); dflt the same, with its different layout noted;
4/4 not opened by Soulstruct (E-003), so its contents were checked only by the read-back.

Only 6/6 is written by the launcher. The others are experiments; 3.13.1's header regression tests keep the writer
at 6/6. Header byte 4 (E-003) is accepted by the game: 4/4 loaded. That 4/4 and 4/6 are accepted and faster to write
is recorded as a separate performance decision, not adopted: `docs/decisions/0002-kraken-layout-speed.md`.

An earlier run of these packages (afternoon) crashed at start in every layout; the cause was the regulation writer
(E-011), not the layouts: the 6/6 text file alone loaded, the regulation alone crashed.

### E-006 DFLT in place of KRAK (Windows): accepted

Same packages with `--layout dflt` (zlib level 9 in the same header). 2026-09-30 (evening), Windows: the dflt package
loaded with both text tags and both classes' parameter values shown, and the player animation archive loaded
(`ingame_package.py --layout dflt`, same session as E-005). Independently, Revive's tool writes the high-detail
player animations and the common effects as DFLT 9 and the owner has played those (E-001). Deck: pending: needs a
Deck. This is only about output: reading the game's own KRAK files on Linux still needs Oodle, whatever the result.

### E-007 The 58 animations the Sekiro animation mod leaves out: unknown

The mod's `c0000_a00_hi.anibnd.dcx` (dated 2022-08-20) replaces 1,132 of the game's 1,192 clips and lacks 58, all
`a000_*`, from `a000_017180` to `a000_910200`. The merger (like the reference tool) treats a missing part as removed,
so those 58 are left out. Whether the author meant that, or the mod predates them, is not known, and no gameplay
symptom has been observed or ruled out. Decided with the owner (2026-09-30): this is the worked example for the
omission policy (proposal, not approved) and is investigated with Phase 4, not in Phase 0. `verify_output.py` lists
every such removal as a note.

### E-008 Parameter rows keep duplicate IDs in order: accepted

2026-09-30, `scripts/verify/param_rows.py` on the game's regulation 11711000 (194 tables, 179,358 rows). One table
has rows sharing an ID: RandomAppearParam, 26 IDs used twice (52 rows). For every table: writing it back gives the
same bytes; the merger's row keys (ID plus occurrence) cover every row once; combining with an unchanged copy keeps
the rows and their order. A pack changing only the second row with ID 1202020 changed that row alone. Soulstruct's
parameter writer loses those 26 rows, so it is not used as a writer or as the duplicate-row oracle.

### E-009 Reader calibration on the game's own files: accepted

2026-09-30, `scripts/verify/calibrate.py`: the launcher's reader and Soulstruct both open the game's own menu text,
menu layout, low and high player animations and common effects archives (all KRAK, header byte 6), with the same
inner file counts (50, 47, 34, 1,192 and 14,997). pyooz was not installed for this run.

### E-010 Load order prediction differs from me3: known issue, fixed in Phase 3

The launcher's `effective_order` (repeated moves) is not me3's `sort_dependencies`. Reported fuzz: 475 of 2,000
acyclic profiles (seed 1) order differently against a Python port; smallest case A B C D with D after A: the port
gives A D B C, the launcher A B C D. Both satisfy the constraints but pick different later-wins providers, so a
predicted file winner can be wrong. Phase 3 ports `sort_dependencies` from me3 `9b1e080bcf691608021e7bd8a4447198a2dcb94c`
with a pinned Rust harness for parity. Installed me3 here: 0.13.0.

### E-011 regulation.bin written by the launcher crashed the game; fixed (64 KB zstd window): accepted

2026-09-30, Windows, Elden Ring 1.17.1 / regulation 11711000, me3 0.13.0. Every package with a launcher-written
regulation.bin crashed at start (`0xc0000005` in eldenring.exe at offset `0x1ebb809`), including the game's own
regulation read and written back **with no change**. The 6/6 menu text alone loaded, so the layouts were not the
cause. Single-file tests (one package each, separate save), run by the owner:

| Test | regulation.bin | Result |
|---|---|---|
| 6 | the game's decrypted bytes, untouched, re-encrypted with a random IV | title screen |
| 7 | launcher writer (zstd level 9, default 128 KB blocks, content size in the frame), zero IV | crash |
| 8 | as 7, content size left out, 4 MB window | crash |
| 9 | as 8 at level 21 with a 64 MB window (the game's own frame header, byte for byte) | crash |
| 11 | 64 MB window, level 21, a block flushed every 64 KB of input (the game's own block layout) | crash |
| 10 | 64 KB window (`window_log` 16), content size left out, level 9 | title screen |
| 4 | the fixed writer, unchanged parameters, random IV | title screen |
| 5 | the fixed writer, balanced marker edit | class selection shows the edit |

Offline controls: encrypting the game's plaintext with a zero IV reproduces its file byte for byte; `write_bnd4`
reproduces its decompressed body byte for byte; the DCX headers differ only in the two size fields. So the AES step
and the archive were right and the zstd frame was wrong. Reading: the game's decoder keeps 64 KB of history whatever
the frame header declares (the game's own file declares 64 MB but, by its block count, was compressed in 64 KB
pieces; test 11 shows a real 64 MB window crashes). Every file known to load has a 64 KB window: the game's own
(in effect), Revive's tool's, and map-for-goblins' editor output.

The same two settings are what every community writer uses, and they were a fix there too: SoulsFormatsNEXT commit
f10e60a8 "DCX ZSTD fix?" (2024-08-17) changed its zstd writer from library defaults to `ZSTD_c_contentSizeFlag = 0`,
`ZSTD_c_windowLog = 16`, and WitchyBND shipped ZSTD writing that day; TKGP's SoulsFormats (2024-11, ZstdSharp level
21) and Soulstruct 2.6.0 (`_compress_dcx_zstd`, level 15) use the identical overrides.

Decision record: `docs/decisions/0001-regulation-zstd-window.md`. Fix: `mods/paramfile.py` `compress_regulation_body` (level 9, no content size, `ZSTD_WINDOW_LOG = 16`); the unit test
`test_the_zstd_frame_is_shaped_as_the_game_requires` parses the written frame and pins the shape (no content size,
window at most 64 KB, one block per 64 KB of input). Files come out about 1% larger than the game's own (2,058,144
against 2,045,728 bytes for the unchanged regulation) and compress in well under a second.

Releases: v3.6.0 to v3.13.1 shipped the same compressor settings (zstd library defaults; the source of
`write_regulation` at every one of those tags was inspected, 2026-10-01). The crash was demonstrated with the current
pre-fix writer on Elden Ring 1.17.1 (tests 4, 7, 8, 9 and 11 above); the historical releases were inspected, not run
in game, and a game version other than 1.17.1 was not tested. The writer is reached by Combine (two packages that both
ship a regulation.bin) and by the engine's `params` step (the nightreign-revive-lite recipe). Neither had run on the
owner's setup (E-001). Fixed in 3.13.2 (released 2026-10-01).

### E-012 One BND4 implementation serves archives and the regulation (Phase 1): accepted

2026-10-01, Elden Ring 1.17.1 / regulation 11711000, Windows. The regulation's own BND4 reader and writer were
removed; it reads and writes its binder with the shared code in `mods/formats.py`, through `paramfile.read_binder`
(refuses any layout but 36-byte entries, Unicode names, stored format 0x74) and `paramfile.binder_bytes` (each
table's stored size taken from its data, as the removed writer did). Compression and removal behaviour unchanged.

Before the change (`scripts/verify` probe on the game's own files): the shared writer reproduced the regulation
binder and all ten archives below byte for byte; the regulation's own writer reproduced the binder and two archives,
and differed on eight (the header's data-start field, empty-entry alignment, stored sizes).

After (`scripts/verify/bnd4_roundtrip.py`, commit with this entry):

| Check | Result |
|---|---|
| Ten game archives (menu text English and Japanese, item text, menu layout, low and high player animations, player animations, behaviour, common effects, talk scripts; 14,997 entries in the largest), unwrapped, read and written back | all byte-identical |
| The game's regulation binder (54,111,776 bytes), read and written back | byte-identical (also through the general writer alone) |
| Its 194 tables against an independent reader and the stored entry headers | same names, IDs, flags, contents, order |
| Their 179,358 rows: ID and occurrence, row bytes, name; table header, type and names area | unchanged by reading and writing; IDs in order match an independent reader |
| Duplicate IDs | RandomAppearParam, 26 IDs (52 rows), kept in order; the merger's keys cover every row once |
| Same inputs, old code against new: the unchanged regulation, and the 6/6 package's combined regulation (two marker mods, two edited rows) | binders byte-identical |
| Same inputs, old code against new: every merged text and animation file of the 6/6 package | byte-identical |
| `param_rows.py` (duplicate rows through write-back, combine and a one-row edit) | 0 problems |

The encrypted files differ on every write (random IV) and were not compared. Not re-tested in game: the outputs are
byte-identical to the ones accepted in E-005 and E-011 once decrypted and decompressed.

### E-013 Editing an entry in place leaves its old stored size: open

Found 2026-10-01 while consolidating. The general writer keeps each entry's stored uncompressed size as read. Where
code replaces an entry's data in place, the header then carries the old size: the engine's text step
(`filemerge.add_text`, the preview Nightreign Revive build) and the marker mods `ingame_package.py` writes (shown:
GR_MenuText.fmg stored as 92,668 bytes, 92,712 or 92,752 actual). The merged files the launcher writes when two mods
change an entry are not affected (the size is set), and the files played in E-005 had correct sizes. Whether the game
tolerates a stale size is untested. Not changed in Phase 1 (no behaviour change); the regulation always writes sizes
from the data (E-012). To decide: set the size from the data for entries stored uncompressed, with a test.

## 3. Open checks

- Phase 0 is not complete: the three checks below marked (Phase 0) stay open.
- (Phase 0) A controlled animation change seen in game (see the last item).
- (Phase 0) Every Deck check.
- (Phase 0, moved to Phase 4) E-007: the intent behind the 58 omissions, with the omission policy.
- E-010: me3 ordering parity (Phase 3).
- E-013: stale stored sizes after an in-place entry edit (decision and test).
- E-001 (Revive's tool's output): rain; co-op revive animations.
- E-005 and E-006: every layout on the Deck (pending: needs a Deck). Windows is done.
- E-011: a Linux-written regulation in game (same writer, no Oodle involved; expected to match Windows).
- Linux: KRAK input decoding (a separate prerequisite from any DFLT output result).
- A controlled animation change seen in game (`ingame_package.py --anim-swap CLIP=SOURCE`), once a clip pair with an
  obvious difference is identified; until then the animation archive shows it loads, not that a change applies.
