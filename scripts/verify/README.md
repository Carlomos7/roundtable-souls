# Real-data checks

Checks run on a real game install, by hand, before a change that affects what the launcher writes is released. They
are not part of the automated tests (those use small made-up files only). Results go into
[docs/evidence-ledger.md](../../docs/evidence-ledger.md).

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
| `verify_output.py --package DIR` | A combined package matches a result worked out from its inputs: inner files, IDs, flags, contents, text entry by entry, parameters byte by byte. Removals (a part missing from a mod's copy) are listed separately. |
| `param_rows.py` | The parameter code keeps every row: duplicate IDs in order, write-back unchanged, merge keys, a change to one duplicate row. |
| `ingame_package.py --layout 6/6` | Builds a package to play: two marker mods merged by the launcher's Combine, stored in a DCX layout (6/6, 4/4, 4/6 or dflt), a me3 profile on a separate save, `launch.cmd` and `CHECK.txt`. |
| `bnd4_roundtrip.py` | The shared BND4 code writes the game's own archives and regulation binder back byte for byte; every regulation table keeps its rows (IDs and their order, duplicates, bytes, names) and metadata. `--compare A B` compares two regulation.bin files' binders. |

Independent readers are optional and not dependencies of the launcher. With Soulstruct (GPL-3.0):

```
uv run --with soulstruct python scripts/verify/verify_output.py --package D:/rs-verify/ingame-6-6/mods/combined-parameters
```

The in-game checklist is [ingame_checklist.md](ingame_checklist.md).
