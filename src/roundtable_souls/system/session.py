"""The play session's steps on this machine: make sure Steam is running and signed in, launch the game through me3,
wait for it to exit, and clear leftover game processes. core.job_play runs them in order and then repairs the saves
(saves/repair.py)."""

import subprocess
import time
from pathlib import Path

from roundtable_souls.system import common
from roundtable_souls.system import processes as clear_dead_game_shells
from roundtable_souls.system.common import fail, log


def _start_steam():
    cmd = common.steam_launch_command()
    if not cmd:
        fail("steam is not running and could not be found; start Steam and try again")
    log(f"steam: starting {' '.join(cmd)}")
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=common.NO_WINDOW)


def ensure_steam(timeout):
    if common.steam_running() and common.steam_logged_in():
        log("steam: running and signed in")
        return
    if not common.steam_running():
        _start_steam()
    else:
        log("steam: running, waiting for sign-in")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if common.steam_running() and common.steam_logged_in():
            time.sleep(5)  # let the client finish loading before me3 pokes it
            log("steam: signed in")
            return
        time.sleep(2)
    fail(f"steam did not sign in within {timeout}s; sign in and try again")


def ensure_steam_running(timeout=60):
    """Offline play: Steam must be running (in Offline Mode), but we do not wait for a sign-in."""
    if not common.steam_running():
        _start_steam()
        deadline = time.time() + timeout
        while time.time() < deadline and not common.steam_running():
            time.sleep(2)
    time.sleep(5)
    log(
        "steam: running"
        + (
            " and signed in"
            if common.steam_logged_in()
            else ", NOT signed in (offline play: choose 'Start in Offline Mode' in Steam if it asks)"
        )
    )


def clear_dead_shells(when):
    """The game leaves a dead copy of itself behind on exit, which makes
    name-based checks report it as still running. Clearing needs admin, so
    this raises one UAC prompt only when there is something to clear."""
    found, remaining = clear_dead_game_shells.clear()
    if remaining:
        log(
            f"{when}: {len(remaining)} dead shell(s) could not be removed; Discord/overlays may still show the game as running"
        )


def me3_log_path():
    """Where me3's own output goes: an attachment of the running job, else logs/me3-launch.log."""
    from roundtable_souls.system import logging as run_logging

    return run_logging.attachment("me3") or run_logging.log_dir() / "me3-launch.log"


def launch(game, profile, me3=None, exe=None, extra_args=()):
    """Run me3 and return once both me3 and the game are gone.

    me3: path of the me3.exe to use (default: the one on PATH / in its default folder).
    exe: path of eldenring.exe to launch with `--exe` instead of `--game` (Nightreign Revive's
    Launch.cmd does this with the me3 runtime it bundles, for setups without a me3 install).

    me3 0.13 stays attached and streams its log for as long as the game runs,
    so its exit normally means the game has already closed. Older or future
    versions may hand off and return at once, so the game is tracked through
    the process list as well: whichever happens, this returns only when no
    real eldenring.exe is left. Returns True if the game was seen running.
    """
    me3 = Path(me3) if me3 else common.me3_exe()
    if not me3 or not Path(me3).exists():
        fail("me3 was not found on PATH or in its default install folder; install it or use --no-launch")
    cmd = (
        [str(me3), "launch"]
        + (["--exe", str(exe)] if exe else ["--game", game])
        + ["--profile", profile]
        + list(extra_args)
    )
    log("launching: " + " ".join(cmd))
    me3_log = me3_log_path()
    me3_log.parent.mkdir(parents=True, exist_ok=True)
    log(f"me3 output goes to {me3_log.name}")

    seen_running = False
    with open(me3_log, "w", encoding="utf-8", errors="backslashreplace") as out:
        proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, creationflags=common.NO_WINDOW)
        try:
            while proc.poll() is None:
                if not seen_running and common.game_running():
                    seen_running = True
                    log("game running, waiting for it to close (this window can stay minimised)")
                time.sleep(2)
        except KeyboardInterrupt:
            log("interrupted: leaving the game running; run the Repair shortcut after you quit")
            raise SystemExit(130) from None
    log(f"me3 exited with code {proc.returncode}")

    if not seen_running:
        # me3 returned without the game ever showing up. Give it a short
        # grace period in case it launched asynchronously, then move on.
        seen_running = wait_for_game(appear_timeout=20, quiet=True)
        if not seen_running:
            log("warning: the game never appeared; me3's own output (in this job's log files) says why")
            return False
    while common.game_running():
        time.sleep(3)
    log("game closed")
    return True


def wait_for_game(appear_timeout, quiet=False):
    """Wait for a real game process to appear, then to go away."""
    deadline = time.time() + appear_timeout
    while not common.game_running():
        if time.time() > deadline:
            if not quiet:
                log("game never appeared; nothing to wait for")
            return False
        time.sleep(2)
    log("game running, waiting for it to close")
    while common.game_running():
        time.sleep(3)
    log("game closed")
    return True
