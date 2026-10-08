# mods

me3 profiles (`.me3`, TOML, schema v1) and the mods they list.

| Module | Role |
| --- | --- |
| `profile.py` | Top-level profile settings (`savefile`, `start_online`, `disable_arxan`, `mem_patch`, ...), package rows, effective load order and the later-wins conflict scan. |
| `profile_edit.py` | Editing a profile's text in place: entries, per-mod options, profile create / delete. |
| `profile_writer.py` | The one writer every profile change goes through: read once, edited in memory, planned under the rules (plug-ins of one interface: unchanged since read, history copy and `.bak`, the mod that must stay last, shared dependencies, what me3 refuses, declared dependencies, paths), written once or as a step of an operation's journal. |
| `install.py` | What a download or folder contains, the install plan, copying a mod in and adding its entries, adding mods already on disk. |
| `extract.py` | Unpacking `.zip`, `.7z` and `.rar` downloads (or using a folder where it is) into a staging folder. |
| `checks.py` | What a profile's mod folders hold (the package tree, folders and DLLs no entry loads) and the entry problems me3 would refuse. |
| `remove.py` | Taking a mod's entry out of a profile, its folder optionally to the Recycle Bin, with what undo needs to put both back. |
| `models.py` | The install plan's shape, validated before the window sees it. |
| `locations.py` | The game's `Locations` the rebuild code, its backends and the conflicts overview read, set by the app context (until Phase 6 hands them Locations call by call). |

## Rules

- A folder with game asset folders (`parts`, `chr`, `msg`, ...) or `regulation.bin` is a package; a folder with DLLs and no assets is a native; a `.me3` inside means a whole profile. Loose game files at an archive root are sorted into the folder the game serves them from.
- Profile edits are text-level so comments, order and line endings survive. New blocks go at the end, options rewrite only the keys inside one block, and inline-array profiles are converted to blocks first.
- Nothing writes a profile but `profile_writer.ProfileWriter` (the journal's byte restores in `operations.py` carry its check). A profile that changed on disk since it was read is never overwritten: the write is refused with "the profile changed outside the launcher; reload and try again".
- A mod already inside the profile folder is registered in place, never copied over itself. A path already listed is not added twice.

The Mods page's view (rows, install plans, me3 facts, profile settings) is `services/mods.py`.
