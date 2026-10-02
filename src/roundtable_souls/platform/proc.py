"""Processes on this machine: the ones running under a program name (tasklist on Windows; /proc on Linux, where a
Wine or Proton process is matched by the Windows exe its command line names), and the flag that keeps child consoles
hidden."""

import re
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
# Child consoles must never pop up (the window has no console of its own).
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _windows_processes(name):
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV"],
            capture_output=True,
            text=True,
            creationflags=NO_WINDOW,
        ).stdout
    except OSError:
        return []
    found = []
    for line in out.splitlines()[1:]:
        cols = [c.strip('"') for c in line.split('","')]
        if len(cols) >= 5 and cols[0].lower() == name.lower():
            digits = "".join(ch for ch in cols[4] if ch.isdigit())
            found.append((int(cols[1]), int(digits) if digits else 0))
    return found


def _linux_processes(name, proc_root=Path("/proc")):
    """Match the program name, or for Wine / Proton processes the Windows exe named in the command line."""
    wanted = name.lower()
    found = []
    for entry in proc_root.iterdir() if proc_root.is_dir() else ():
        if not entry.name.isdigit():
            continue
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
            comm = (entry / "comm").read_text(errors="ignore").strip()
            status = (entry / "status").read_text(errors="ignore")
        except OSError:
            continue
        first = argv[0].decode(errors="ignore").replace("\\", "/").rsplit("/", 1)[-1].lower() if argv else ""
        if wanted not in (first, comm.lower()):
            continue
        rss = re.search(r"^VmRSS:\s+(\d+)\s+kB", status, re.M)
        found.append((int(entry.name), int(rss.group(1)) if rss else 0))
    return found


def processes(name):
    """(pid, resident memory in KB) for every process with this program name."""
    if IS_WINDOWS:
        return _windows_processes(name)
    if IS_LINUX:
        return _linux_processes(name)
    return []
