"""`RoundtableSouls --update`: Update now without the window."""

from __future__ import annotations

from roundtable_souls import __version__
from roundtable_souls.platform import instance
from roundtable_souls.updates import apply, feed


def update_headless(restart_args: list[str], log=None, start_log=None) -> int:
    """`RoundtableSouls --update [args...]`: Update now without the window (a terminal, a Steam shortcut in Gaming
    Mode). Checks GitHub now, verifies and downloads like Update now, keeps this version for a rollback, then hands
    over to Velopack and exits; the launcher restarts with args (none: the window; --game er --play: Play).

    Exit codes: 0 updating or already up to date, 1 failed (nothing changed), 3 the newest release is blocked here."""
    from roundtable_souls.game import catalog
    from roundtable_souls.platform import logging as run_logging

    log = log or run_logging.log
    if start_log is not None:
        start_log("launcher: update (no window)")
    else:
        run_logging.start_log("launcher: update (no window)", catalog.DEFAULT.key)
    if instance.held(instance.WINDOW):
        log("error: Roundtable Souls is open; use Update now there, or close it first")
        return 1
    why = apply.busy_reason()
    if why:
        log(f"error: {why}")
        return 1
    check = feed.check_launcher_update(force=True)
    if check.failed:
        log(f"error: could not check for updates: {check.reason}")
        return 1
    if check.blocked:
        log(f"{check.blocked} failed to start here and was undone; it is not installed again")
        return 3
    if not check.offer:
        log(f"Roundtable Souls {__version__} is the latest release")
        return 0
    if not apply.can_self_update(check.offer):
        log(f"error: {check.offer['version']} cannot be installed by this copy; get it from {feed.RELEASES_URL}")
        return 1
    try:
        log(f"downloading and checking {check.offer['version']}")
        prepared = apply.download_update(check.offer)
        log("checked: signed feed and " + ("delta" if prepared.delta else "full") + " package")
        prepared.rollback = apply.stage_rollback()
        log(f"kept this version ({__version__}) to put back if the new one does not start")
        apply.apply_update(prepared, restart_args=restart_args)
    except feed.UpdateError as e:
        log(f"error: {e}")
        return 1
    log(f"installing {prepared.version}; the launcher restarts when it is done")
    return 0
