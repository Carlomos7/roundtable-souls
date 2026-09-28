# mods

me3 profiles (`.me3`, TOML, schema v1) and the mods they list.

| Module | Role |
| --- | --- |
| `profile.py` | Top-level profile settings (`savefile`, `start_online`, `disable_arxan`, `mem_patch`, ...), package rows, effective load order and the later-wins conflict scan. |
| `item_names.py` | Names for items the game does not define, read at runtime from the installed mods: Seamless Co-op's language file and other mods' item text tables. |
| `manage.py` | Install from a `.zip`, `.7z`, `.rar` or folder, per-mod options, remove, and profile create / delete. |
| `service.py` | The Mods page's view: enable / disable rows, install plans (validated against `models.ModPlan`), me3 facts and profile settings. |

## Rules

- A folder with game asset folders (`parts`, `chr`, `msg`, ...) or `regulation.bin` is a package; a folder with DLLs and no assets is a native; a `.me3` inside means a whole profile. Loose game files at an archive root are sorted into the folder the game serves them from.
- Profile edits are text-level so comments, order and line endings survive. New blocks go at the end, options rewrite only the keys inside one block, and inline-array profiles are converted to blocks first.
- A mod already inside the profile folder is registered in place, never copied over itself. A path already listed is not added twice.
