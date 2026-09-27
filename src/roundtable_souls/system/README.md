# system

Facts about this machine and the play session.

| Module | Role |
| --- | --- |
| `common.py` | Where Steam, the game, the saves and me3 are (registry, library folders, defaults), what is running, and the Tools > Locations overrides. |
| `session.py` | Start Steam if needed, launch through me3, wait for the game to exit, repair the saves it touched, clear leftovers. |
| `processes.py` | Dead `eldenring.exe` shells (zero threads) that keep overlays thinking the game runs; removed with one elevation prompt. |
| `me3_info.py` | `me3 --version`, `me3 info` directories and the latest GitHub release. |
| `logging.py` | `logging` configuration: a fresh `last_run.log` per job plus a sink the window attaches. |

Nothing here writes to disk except the run log. A real game instance uses gigabytes; anything under 100 MB with that image name is a leftover shell, not the game.
