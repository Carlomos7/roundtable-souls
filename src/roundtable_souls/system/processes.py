"""Remove dead eldenring.exe shells.

When Elden Ring exits it spawns a second copy of itself that dies at once,
and on some machines that corpse stays in the process list: zero threads,
zero handles, no memory. Steam ignores it, but Discord, overlays and other
"is the game running?" checks go by name and keep reporting the game as
running until the next reboot.

Killing the corpse needs administrator rights, so this asks for elevation
(one UAC prompt) and terminates only processes that are provably dead: named
eldenring.exe with no threads. A running game always has hundreds.

Usage:
  clear_dead_game_shells.py [--dry-run]
"""
import argparse
import subprocess
import sys

from roundtable_souls.system import common
from roundtable_souls.system.common import log

PS = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]


def dead_shells():
    """PIDs of eldenring.exe processes with zero threads."""
    if sys.platform != "win32":
        return []
    script = ("Get-Process eldenring -ErrorAction SilentlyContinue | "
              "Where-Object { $_.Threads.Count -eq 0 } | ForEach-Object { $_.Id }")
    try:
        out = subprocess.run(PS + [script], capture_output=True, text=True, timeout=30, creationflags=common.NO_WINDOW).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [int(x) for x in out.split() if x.isdigit()]


def kill_elevated(pids):
    """Stop the given PIDs from an elevated PowerShell. Returns the PIDs still
    present afterwards."""
    ids = ",".join(str(p) for p in pids)
    inner = f"Stop-Process -Id {ids} -Force -ErrorAction SilentlyContinue"
    launcher = (f"$p = Start-Process powershell.exe -ArgumentList '-NoProfile','-NonInteractive','-Command',"
                f"\"{inner}\" -Verb RunAs -Wait -PassThru; exit $p.ExitCode")
    try:
        subprocess.run(PS + [launcher], capture_output=True, text=True, timeout=120, creationflags=common.NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as err:
        log(f"could not run the elevated kill: {err}")
    return [p for p in dead_shells() if p in pids]


def clear(dry_run=False):
    """Find and remove dead shells. Returns (found, remaining)."""
    found = dead_shells()
    if not found:
        log("no dead eldenring.exe shells")
        return [], []
    log(f"dead eldenring.exe shell(s): {', '.join(map(str, found))}")
    if dry_run:
        return found, found
    log("asking for administrator rights to remove them (UAC prompt)")
    remaining = kill_elevated(found)
    if remaining:
        log(f"still present (UAC declined, or held by a driver): {', '.join(map(str, remaining))}")
    else:
        log("cleared")
    return found, remaining


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="only report, do not kill")
    a = ap.parse_args()
    common.start_log("clear_dead_game_shells")
    if common.game_running():
        log("note: a real game instance is running; it will not be touched")
    found, remaining = clear(a.dry_run)
    sys.exit(1 if remaining and not a.dry_run else 0)


if __name__ == "__main__":
    main()
