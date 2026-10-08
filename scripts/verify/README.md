# Real-data checks

Checks run on a real game install, by hand, before a change that affects what the launcher writes is released. They
are not part of the automated tests (those use small made-up files only). Record what a check showed with the change
it supports (its pull request or release notes); decisions that follow from one go in [docs/decisions](../../docs/decisions/).

Rules: real files (the game, me3 profiles, saves, mods) are only read. Each check writes to an output folder of its
own (`--out`, or `out` in `local.toml`; default `%TEMP%\rs-verify`), and refuses a folder inside the game, me3's
profiles, a save folder or this repository. The launcher's code runs with its data folder inside that output folder.

## Settings

Pass `--game` and `--out`, or put them in `scripts/verify/local.toml` (ignored by git):

```toml
game = 'C:/Program Files (x86)/Steam/steamapps/common/ELDEN RING/Game'
out = 'D:/rs-verify'
```

Without either, the game is found through Steam, as the launcher finds it.

## The checks

| Script | What it shows |
|---|---|
| `calibrate.py` | Each reader (the launcher's, Soulstruct, pyooz) opens the game's own files. Run it before trusting a reader's verdict on the launcher's output. |
| `verify_output.py --package DIR` | A combined package matches a result worked out from its inputs: inner files, IDs, flags, contents, text entry by entry, animation events (TAE) animation by animation, parameters byte by byte. Removals (a part missing from a mod's copy) are listed separately. The TAE part uses our own reader whatever reader the rest uses; it is not independently validated (the report says so). |
| `param_rows.py` | The parameter code keeps every row: duplicate IDs in order, write-back unchanged, merge keys, a change to one duplicate row. |
| `ingame_package.py --layout 6/6` | Builds a package to play: two marker mods merged by the launcher's Combine, stored in a DCX layout (6/6, 4/4, 4/6 or dflt), a me3 profile on a separate save, `launch.cmd` and `CHECK.txt`. |
| `bnd4_roundtrip.py` | The shared BND4 code writes the game's own archives and regulation binder back byte for byte; every regulation table keeps its rows (IDs and their order, duplicates, bytes, names) and metadata. `--compare A B` compares two regulation.bin files' binders. |
| `esd_roundtrip.py [--file TALKESDBND]` | The ESD code reads every talk script in the game's talk archives (and any given) and writes it back: the same structure (machines, states, conditions in order with their targets inside their own machine, nested conditions, commands, every test and argument byte for byte), and the game's own scripts byte for byte. With Soulstruct installed it is also compared with Soulstruct's reading. |
| `ingame_esd_package.py [--mod DIR]` | Builds a package to play: a mod's grace and menu talk scripts (or the game's own) written back by the ESD code with nothing changed, a me3 profile on a separate save, `launch.cmd` and `CHECK.txt` (the menus have to behave exactly as with the original file). |
| `tae_roundtrip.py [--chr cNNNN] [--all-chr] [--file ANIBND]` | The TAE code reads every animation-event file in the player's animation archive (and any other character's or archive given) and writes it back byte for byte, or else to the same structure (file header; per animation its header, file name, events in stored order with their parameter bytes, and event groups); an edited copy of one file per archive reads back as edited (padding added after an event's parameters, where an edit moved its data, is listed separately). Uses our own reader; not independently validated. |
| `tae_merge.py --input NAME=PATH ... [--compare FILE] [--package]` | Merges the player's animation archive (`chr/c0000.anibnd.dcx`) of several mods as Combine does and says, animation by animation, what each mod changed, added or left out and where changes met. `--compare` checks the result against another tool's merge of the same mods: each TAE animation by animation, parameter bytes exactly (our own reader on both sides; not independently validated), every other inner file byte for byte. `--package` builds a package to play (the profile's asset mods, the merged archive last, a separate save) with `CHECK.txt`. |
| `clash_corpus.py [--profile ME3]` | Merges every game file that two or more enabled packages of a profile ship, in me3's load order, without touching the profile or the mods: parts each mod changed, where changes met (the later mod wins), what a mod's copy leaves out, and files that cannot be merged. Writes the merged files and `result.json`. |
| `native_parity.py [--profile ME3] [--setup DIR]` | The launcher's own build of the profile's overhaul (Nightreign Revive), from a copy of the profile pointing its package into the output folder, compared with the mod's own installed build from the same inputs (which must be the installer's output, its recorded inputs unchanged): archives part by part (talk scripts by meaning, animation events animation by animation, text entry by entry), the regulation row by row, every other file by hash. Every difference goes to `report.md` and `result.json`, to be explained or fixed before the build is accepted (Phase 6, S3c). |
| `esd_merge.py --input NAME=PATH ... [--compare FILE] [--package]` | Merges talk archives of several mods with the launcher's ESD rule (as Combine does) and says, state by state, what it did: additions, a mod's own version of a state, new states renumbered, or why a script was not merged. `--compare` checks the result by meaning against another tool's merge of the same mods; `--package` builds a package to play (the profile's asset mods, the merged archive last, a separate save) with `CHECK.txt` naming the menu entries to look for. |

Independent readers are optional and not dependencies of the launcher. With Soulstruct (GPL-3.0):

```
uv run --with soulstruct python scripts/verify/verify_output.py --package D:/rs-verify/ingame-6-6/mods/combined-parameters
```

The in-game checklist is [ingame_checklist.md](ingame_checklist.md).
