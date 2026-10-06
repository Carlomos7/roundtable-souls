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
files = ["edition.json", "payload/my-overhaul.dll"]
json = [{ file = "edition.json", key = "edition", equals = "LITE" }]
version = { file = "edition.json", key = "version" }
versions = ["1.2.0"]

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
the player turns on **Build Nightreign Revive in the launcher** on Settings. Nothing from the download runs: every
merge is the launcher's.

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
| `script_append` | The packages' own `folder` (for example `action/script`) copied in load order, then `append` added to `entry` (or to `base` up to `base_until` when no package has one); `refuse` lists text that means a package already contains it. A compiled entry script (Lua bytecode) is refused; packages shipping different entry scripts are a clash, recorded in the report. |
| `remove` | Leftovers, a `glob` below the output's `mod` folder. |

`merge`, `text` and `params` take `each = { folders_in, except }` to repeat per folder (`{each}` in their paths).
As the mod's own installer does, only the **last** enabled package before it that ships a file is merged with the
mod's copy. Files no format rule covers (behaviour and animation data, `.hkx`) are taken whole, three-way: changed
by one side, its copy; changed differently by both, the mod's copy and a clash. Clashes and the rules' notes are
written to the build's report (`merge-report.txt`).

The build runs in a staging folder beside the output and replaces it by renaming; the build it replaced is kept in
`.roundtable-build/previous` for Undo rebuild. The manifest is written as the mod's installer writes it, with each
source's path and sha256, so the launcher's checks and the mod's installer keep working. The inputs are only read
and the profile is never written. A build is accepted when its output matches the mod's own installer's for the same
inputs, file for file.

## Installing it into a profile

A build may also say what installing that edition does to the player's me3 profile (`[builds.install]`). The
launcher works the changes out from it without writing anything (`overhauls/install_plan.py`); applying them is a
later step, through the launcher's journaled install and its profile writer. Editions the mod's installer knows but
the launcher does not install are listed with the reason in `install_unsupported` (edition -> why) at the top.

```toml
[builds.install]
profile_settings = { profileVersion = "v1", start_online = false }  # top-level keys set
owned_package_ids = ["my-overhaul"]          # an earlier install's packages, removed first
owned_dlls = ["myoverhaul.dll"]              # an earlier install's DLLs (file names, lower-case), removed first
required_files = ["MyOverhaul.dll", "mod/regulation.bin"]   # in its folder: the check after an install
required_folders = ["ui"]                    # in its folder, not empty

[builds.install.seamless]                    # Seamless Co-op must be switched on
dll = "ersc.dll"
candidates = ["{profile_dir}/SeamlessCoop/ersc.dll", "{game_dir}/SeamlessCoop/ersc.dll"]

[[builds.install.set_initializers]]          # other mods' DLLs that get an initializer when they have none
name_prefix = "companionmod"
function = "CompanionInitialize"

[[builds.install.natives]]                   # its DLLs, added after the profile's own, in this order
file = "MyOverhaul.dll"                      # in its own folder
load_early = true                            # optional
initializer = { function = "MyInitialize" }  # optional
after_enabled_natives = true                 # load_after every enabled DLL already there, each optional

[builds.install.package]                     # its package, added after the profile's own
id = "my-overhaul"
folder = "mod"
after_enabled_packages = true                # load_after every enabled package already there, each optional
```

The plan removes an earlier install's own entries, sets the settings that differ, switches Seamless Co-op on (an
entry switched off is switched on and pointed at the Seamless found; with none, the first candidate that exists is
added; with no Seamless at all the install stops), gives the matching DLLs their initializer, and adds the
overhaul's DLLs and package last with the load settings written here. The player's other entries are left as they
are. It stops for a profile me3 cannot use (two enabled packages with one id, a circle of `load_after`), an enabled
package whose folder is missing, or an unreadable profile. Nightreign Revive's LITE description is the one its own
installer (0.1.33-rc3) applies; the plan gives the same profile as that installer on the profiles compared.
