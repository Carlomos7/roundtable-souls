# system

Facts about this machine and the play session.

| Module | Role |
| --- | --- |
| `common.py` | Where Steam, the game, the saves and me3 are on Windows (registry) and Linux (Steam folders, Proton prefix, XDG paths), what is running (tasklist or /proc), opening folders, and the Settings > Locations overrides. Every game-specific answer is for the active game (`GAME`, set with `set_game`); the per-game facts come from `games.py`. |
| `session.py` | Start Steam if needed, launch through me3, wait for the game to exit, repair the saves it touched, clear leftovers. |
| `processes.py` | Dead shells of the active game's exe (zero threads) that keep overlays thinking the game runs; removed with one elevation prompt. Windows only. |
| `me3_info.py` | `me3 --version`, `me3 info` directories and the latest GitHub release. |
| `instance.py` | One window at a time per data folder: named mutexes (Windows) or lock files (Linux) for the window and a Play from a Steam shortcut, and the local socket a second start uses to bring the window forward or hand it a Play. |
| `steam_shortcuts.py` | Steam's binary shortcuts.vdf, read and written back byte for byte; points shortcuts that start an old copy at this one (only while Steam is closed, with a backup). |
| `filelock.py` | An exclusive lock file shared by every launcher process, around read-change-write of the settings file. |
| `logging.py` | `logging` configuration: a fresh `last_run.log` per job plus a sink the window attaches. |

Nothing here writes to disk except the run log and lock files (beside the settings file, and in the runtime or temp folder on Linux). A real game instance uses gigabytes; anything under 100 MB with that image name is a leftover shell, not the game.
