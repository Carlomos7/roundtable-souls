# Overhaul configs (for mod authors)

An overhaul is a mod that must load after the others and ships merged copies of game files other mods also change
(Nightreign Revive, for example). The launcher describes each one in a config: one TOML file saying how to recognise
the mod and, optionally, how the launcher can build it itself instead of running the mod's installer. Nothing about a
particular overhaul is in the launcher's code.

The shipped configs are in `src/roundtable_souls/data/overhauls/*.toml`. To change one or add your own, put a file in
the `overhauls` folder of the launcher's data folder: a file with the same `id` as a shipped config replaces it, and
one with a new `id` adds an overhaul. A file that does not read, or does not fit the format, is left out and the
others still load. Editors can check a file against `src/roundtable_souls/data/schemas/overhaul.schema.json`.

```toml
overhaul = 1                     # the version of this format
id = "my-overhaul"
label = "My Overhaul"
short_label = "Mine"             # where space is short (the Play page's summary)
game = "eldenring"               # the game's key: eldenring, nightreign, ...

[recognise]
folder = "MyOverhaul"            # its own folder beside the me3 profile (or in the game folder)
manifest = "installation.json"   # its installer's manifest in that folder
mod_ids = ["my-overhaul", "myoverhaul.dll"]  # profile entries meaning a setup includes it
profile_marks = ["myoverhaul"]   # text marking its profile entries (case aside)

[[builds]]                       # one per edition the launcher builds itself; none is fine
id = "my-overhaul-lite"          # written into the build's manifest as "recipe"

[builds.match]
files = ["edition.json", "tools/merge.exe"]
json = [{ file = "edition.json", key = "edition", equals = "LITE" }]
version = { file = "edition.json", key = "version" }
versions = ["1.2.0"]

[builds.tool]
path = "tools/merge.exe"
env = { GAME_DIR = "{game_dir}" }
timeout = 900

[builds.output]
mod = "mod"
report = "merge-report.txt"
manifest = "installation.json"

[[builds.steps]]
do = "copy_tree"
from = "payload/ui"
to = "ui"
```

## Recognising it

The Play page offers each installation it finds (`folder`/`manifest` beside the me3 profiles, or in the game folder) as
a setup of its own, launched as its installer set it up. It says a setup includes the overhaul when the setup was
started from its manifest, its folder is beside the profile, or the profile has one of `mod_ids`. An offline launch
with **Skip Revive too** turns off the profile entries containing one of `profile_marks`.

## Builds: the launcher builds it itself

For a mod whose installer keeps its download in a setup folder, the launcher can do the installer's merge itself when
the player turns on **Build Nightreign Revive in the launcher** on Settings.

`match` recognises the download (files that must be there, values in its JSON files) and the versions the build was
written for; another version runs the mod's own installer. The output is the folder holding the package's `mod`
folder. Steps, in order:

| `do` | What it does |
|---|---|
| `copy_tree`, `copy` | Files of the download (`from`) into the output (`to`) as they are. |
| `config` | A settings file of the player's: kept when it is there, with only the keys a newer default adds; else the default. |
| `merge` | One file merged by the launcher: the last package before it that ships `file`, then the mod's copy (`patch`), against the game's copy (archives file by file, text entry by entry); with no package shipping it, the mod's copy as it is. |
| `text` | A text archive: the mod's strings (`texts`, a JSON object of text ID to string, by `each` folder, `*` for the rest) set in its `table` of the game's copy (or `vanilla` from the download), then merged like `merge`. |
| `params` | `regulation.bin`: the launcher's row-by-row combine of that package's copy and the mod's (`patch`) against the game's. |
| `tool` | One file merged by the mod's tool, where the launcher cannot merge it itself yet: `{source}` is `file` from the last enabled package before it that ships it, else what `missing` says (`game`, `copy_patch`, or a path in the download). Also `{patch}`, `{out}`, `{setup}`, `{text}` (from a `text` map by `each`, `*` for the rest). `each = { folders_in, except }` repeats it per folder. |
| `script_append` | The packages' own `folder` (for example `action/script`) copied in load order, then `append` added to `entry` (or to `base` up to `base_until` when no package has one); `refuse` lists text that means a package already contains it. |
| `remove` | Leftovers of the tool, a `glob` below the output's `mod` folder. |

The build runs in a staging folder beside the output and replaces it by renaming; the build it replaced is kept in
`.roundtable-build/previous` for Undo rebuild. The manifest is written as the mod's installer writes it, with each
source's path and sha256, so the launcher's checks and the mod's installer keep working. The inputs are only read
and the profile is never written. A build is accepted when its output matches the mod's own installer's for the same
inputs, file for file.
