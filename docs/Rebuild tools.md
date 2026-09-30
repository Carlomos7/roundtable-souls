# Rebuild tools (for mod authors)

me3 uses one `regulation.bin`: the one in the last enabled package, in load order, that has one. An overhaul that must
stay last can still take other packs' parameters into account, but only with a tool of its own that combines their
files into its copy. Roundtable Souls can run such a tool, tell players when its result is out of date, and check it
afterwards. It never merges files itself.

To let it, ship a `rebuild.json` in your package folder, or in the folder that holds it:

```json
{
  "rebuild": 1,
  "name": "Example Overhaul's rebuild tool",
  "command": ["{here}/tools/combine.exe", "--profile", "{profile}", "--out", "{package}"],
  "cwd": "{here}",
  "merges": ["regulation.bin", "script/talk/m00_00_00_00.talkesdbnd.dcx"],
  "merges_from": ["{here}/payload"],
  "sources": "{package}/rebuild-sources.json",
  "timeout_minutes": 30
}
```

| Key | Meaning |
|---|---|
| `rebuild` | Always `1` (the version of this format). |
| `name` | What players see. Defaults to "the rebuild tool of \<package id\>". |
| `command` | The program and its arguments. Run without a shell. |
| `cwd` | Folder to run it in. Defaults to `{here}`. |
| `merges` | Files, relative to your package, that the tool combines from the packages before it. |
| `merges_from` | Folders whose files (relative to each folder) also count as combined. Optional. |
| `sources` | A JSON file your tool writes after every run (see below). |
| `timeout_minutes` | Optional, default 30. |

Placeholders: `{here}` (the folder holding `rebuild.json`), `{package}` (the package your tool writes into),
`{profile}` (the player's `.me3`), `{profile_dir}`, `{game_dir}`, `{game_exe}`, `{me3}`. A relative program path,
`cwd`, `sources` or `merges_from` entry is taken from `{here}`.

## What your tool must do

1. Read the profile. For each file it combines, take the copy from the **last enabled package before yours** that
   has that file (in me3's load order, `load_after` / `load_before` included), or the game's own copy when none does.
2. Write the combined files into `{package}`. Exit with code 0 on success and anything else on failure. Print
   progress to standard output; players see it in the launcher's log.
3. Write the `sources` file:

```json
{
  "sources": [
    {"path": "C:/.../profiles/my-setup/mod/some-pack/regulation.bin", "sha256": "…"},
    {"path": "C:/.../ELDEN RING/Game/regulation.bin", "sha256": "…"}
  ]
}
```

One entry per input file your tool read, with its sha256. The launcher compares these against the packages as they
are now: a different package, changed bytes, a removed or disabled pack, or a game update marks the result out of
date, and a run whose list does not match is reported as failed. Without a `sources` file a result is never shown
as up to date.

Your tool may rewrite the profile. When the rewritten profile still loads the same things, the launcher puts the
player's own text (comments, layout) back and keeps only your entries' `load_after` / `load_before` changes.

## Safety

A rebuild tool is a program from a mod. The launcher shows the command and asks the player once before it first
runs, and again whenever `rebuild.json` (or the tool it names) changes.

## Tools without a rebuild.json

Players can turn on **Parameter overlay** in your package's Options and pick a `rebuild.json` they wrote for your
tool. Tools that keep an `installation.json` with a `refreshProtocol` and a source list beside their package, and
their installer in a setup folder of the profile, are recognised without one.

The player's choice is kept in `roundtable.json` next to their profile (relative paths), so it travels with the profile
folder. Whatever the tool, the launcher keeps your package's `load_after` naming every other package, and your DLL's
naming every other DLL (not `load_early` ones), each optional, so it stays last however mods are added. It changes only
those lists, never the player's other entries.

## Recipes: the launcher builds it itself

For a mod whose installer keeps its download in a setup folder, the launcher can do the installer's merge itself from
a recipe (`src/roundtable_souls/data/recipes/*.json`), when the player turns on **Build Nightreign Revive in the
launcher** on Settings. The recipe is data; nothing about a particular mod is in the launcher's code.

```json
{ "recipe": 1, "id": "my-overhaul", "label": "My Overhaul",
  "match": { "files": ["edition.json", "tools/merge.exe"],
             "json": [{ "file": "edition.json", "key": "edition", "equals": "LITE" }],
             "version": { "file": "edition.json", "key": "version" }, "versions": ["1.2.0"] },
  "tool": { "path": "tools/merge.exe", "env": { "GAME_DIR": "{game_dir}" }, "timeout": 900 },
  "output": { "mod": "mod", "report": "merge-report.txt", "manifest": "installation.json" },
  "steps": [ ... ] }
```

`match` recognises the download (files that must be there, values in its JSON files) and the versions the recipe was
written for; another version runs the mod's own installer. The output is the folder holding the package's `mod`
folder. Steps, in order:

| `do` | What it does |
|---|---|
| `copy_tree`, `copy` | Files of the download (`from`) into the output (`to`) as they are. |
| `config` | A settings file of the player's: kept when it is there, with only the keys a newer default adds; else the default. |
| `merge` | One file merged by the launcher: the last package before it that ships `file`, then the mod's copy (`patch`), against the game's copy (archives file by file, text entry by entry); with no package shipping it, the mod's copy as it is. |
| `text` | A text archive: the mod's strings (`texts`, a JSON object of text ID to string, by `each` folder, `*` for the rest) set in its `table` of the game's copy (or `vanilla` from the download), then merged like `merge`. |
| `params` | `regulation.bin`: the launcher's row-by-row combine of that package's copy and the mod's (`patch`) against the game's. |
| `tool` | One file merged by the mod's tool, where the launcher cannot merge it itself yet: `{source}` is `file` from the last enabled package before it that ships it, else what `missing` says (`game`, `copy_patch`, or a path in the download). Also `{patch}`, `{out}`, `{setup}`, `{text}` (from a `text` map by `each`, `*` for the rest). `each: {folders_in, except}` repeats it per folder. |
| `script_append` | The packages' own `folder` (for example `action/script`) copied in load order, then `append` added to `entry` (or to `base` up to `base_until` when no package has one); `refuse` lists text that means a package already contains it. |
| `remove` | Leftovers of the tool, a `glob` below the output's `mod` folder. |

The build runs in a staging folder beside the output and replaces it by renaming; the build it replaced is kept in
`.roundtable-build/previous` for Undo rebuild. The manifest is written as the mod's installer writes it, with each
source's path and sha256, so the launcher's checks and the mod's installer keep working. The inputs are only read
and the profile is never written. A recipe is accepted when its output matches the mod's own installer's for the same
inputs, file for file.
