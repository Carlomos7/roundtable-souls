# system

Facts about this machine and the play session.

| Module | Role |
| --- | --- |
| `common.py` | Where Steam, the game, the saves and me3 are on Windows (registry) and Linux (Steam folders, Proton prefix, XDG paths), what is running (tasklist or /proc), opening folders, and the Settings > Locations overrides. Every game-specific answer is for the active game (`GAME`, set with `set_game`); the per-game facts come from `games.py`. |
| `session.py` | Start Steam if needed, launch through me3, wait for the game to exit, repair the saves it touched, clear leftovers. |
| `processes.py` | Dead shells of the active game's exe (zero threads) that keep overlays thinking the game runs; removed with one elevation prompt. Windows only. |
| `me3_info.py` | `me3 --version`, `me3 info` directories and the latest GitHub release. |
| `logging.py` | `logging` configuration: a fresh `last_run.log` per job plus a sink the window attaches. |

Nothing here writes to disk except the run log. A real game instance uses gigabytes; anything under 100 MB with that image name is a leftover shell, not the game.
