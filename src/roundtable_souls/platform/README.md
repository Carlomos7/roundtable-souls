# platform

Facts about this machine and the play session.

| Module | Role |
| --- | --- |
| `paths.py` | The primitives for where a game, its saves and me3 are on Windows and Linux (Steam libraries, Proton prefix, XDG paths) and whether a game's exe runs. Each takes what it looks for; a game's own answers, with the Settings > Locations overrides, are `game/locate.py`'s `Locations`. |
| `steam.py` | Steam: where it is installed (registry on Windows; the usual folders, Flatpak included, on Linux), its libraries, whether it runs and is signed in, how to start it. |
| `proc.py` | Processes running under a name (tasklist, or /proc where Wine and Proton processes are matched by their exe), and the flag that keeps child consoles hidden. |
| `data_folder.py` | The launcher's own data folder: its root (set once at startup, `app.use_data_folder`), the temp folder installs unpack into, the deleted-profiles folder. |
| `files.py` | Atomic writes, and merging one folder's contents into another (each file's .json note moves with it). |
| `desktop.py` | Opening a folder, file or URL with the desktop's default handler. |
| `session.py` | Start Steam if needed, launch through me3, wait for the game to exit, clear leftovers. |
| `processes.py` | Dead shells of a game's exe (zero threads) that keep overlays thinking the game runs; removed with one elevation prompt. Windows only. From the command line: `scripts/clear_dead_shells.py`. |
| `me3_info.py` | `me3 --version`, `me3 info` directories and the latest GitHub release. |
| `instance.py` | One window at a time per data folder (the scope is set once at startup): named mutexes (Windows) or lock files (Linux) for the window and a Play from a Steam shortcut, and the local socket a second start uses to bring the window forward or hand it a Play. |
| `steam_shortcuts.py` | Steam's binary shortcuts.vdf, read and written back byte for byte; points shortcuts that start an old copy at this one (only while Steam is closed, with a backup). |
| `filelock.py` | An exclusive lock file shared by every launcher process, around read-change-write of the settings file. |
| `logging.py` | `logging` configuration: a log per job, the jobs index the Activity page reads, a sink the window attaches, and `log` / `fail` for one line. |

Nothing here writes to disk except the run log and lock files (beside the settings file, and in the runtime or temp folder on Linux). A real game instance uses gigabytes; anything under 100 MB with that image name is a leftover shell, not the game.
