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

## Overhaul configs: the launcher builds it itself

For a mod whose installer keeps its download in a setup folder, the launcher can do the installer's merge itself from
the mod's overhaul config (`src/roundtable_souls/data/overhauls/*.toml`), when the player turns on **Build Nightreign
Revive in the launcher** on Settings. The config is data; nothing about a particular mod is in the launcher's code.
[Overhaul configs](Overhaul%20configs.md) describes the format and its build steps.
