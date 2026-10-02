"""The command line: `roundtable-souls` opens the window; --play, --check and --update run without one, and --game
picks the game. Each mode imports only what it needs, so a Play from a Steam shortcut never loads the window."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from roundtable_souls.game.catalog import Game


def main() -> int:
    """Console entry point: the window; or without one --play, --check, --update (see headless.update_headless)."""
    from roundtable_souls.platform import logging as run_logging

    run_logging.setup_logging()

    def crashed(exc_type, exc, tb):  # the window replaces this with one that also shows a message
        run_logging.log_crash(exc_type, exc, tb, "command line")
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = crashed
    if getattr(sys, "frozen", False):
        from roundtable_souls.updates import apply as updates
        from roundtable_souls.updates import headless

        updates.velopack_startup()  # Velopack's install/update/uninstall hooks exit here
    if "--update" in sys.argv:
        from roundtable_souls.updates import apply as updates
        from roundtable_souls.updates import headless

        return headless.update_headless([a for a in sys.argv[1:] if a != "--update"])
    if "--play" in sys.argv or "--check" in sys.argv or any(a.startswith("--game") for a in sys.argv):
        from roundtable_souls.game import catalog as games
        from roundtable_souls.services import play as core

        game = core.game_from_args(sys.argv)
        if game is None:
            print(f"Unknown game. --game takes one of: {games.names_help()}", file=sys.stderr)
            return 2
        if "--play" in sys.argv:
            return play_from_shortcut(game)
        if "--check" in sys.argv:
            core.check(game)
            return 0
        core.STARTUP_GAME = game  # the window opens on this tab, this run only
    from roundtable_souls.ui.window import main as window_main

    return int(window_main() or 0)


def play_from_shortcut(game) -> int:
    """--play: when the window is open, it runs Play itself (one launcher manages the session); otherwise Play runs
    here, holding the PLAY name so a second shortcut start, or a silent update, waits for it to end."""
    from roundtable_souls.platform import instance
    from roundtable_souls.services import play as core
    from roundtable_souls.updates import apply as updates

    updates.mark_ready("play")  # this version starts and runs: an update's watchdog can stand down
    if instance.held(instance.WINDOW) and instance.send(f"play {game.key}"):
        core.common.start_log("launcher: play (no window)")
        core.run_logging.log("Roundtable Souls is open: Play was handed to its window")
        return 0
    hold = instance.acquire(instance.PLAY)
    if hold is None:
        core.common.start_log("launcher: play (no window)")
        core.run_logging.log("error: a Play from a Steam shortcut is already running")
        return 1
    try:
        return core.play_headless(game, notice=not_started_notice)
    finally:
        hold.release()


def not_started_notice(game: Game, why: str) -> None:
    """--play without the window, when the game was not started: a small window saying why, with a way to open the
    launcher (a Steam shortcut or Gaming Mode has nowhere else to show it). Nothing happens without a display."""
    from roundtable_souls.services import play as core

    try:
        import subprocess

        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv[:1])
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(core.TITLE)
        box.setText(f"{game.name} was not started: your mods need a rebuild")
        box.setInformativeText(
            f"{why}\n\nThe game does not start with merged mods that no longer match your mods, so it cannot run "
            "with a removed or changed mod still inside them."
        )
        open_btn = box.addButton("Open Roundtable Souls", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        del app
        if box.clickedButton() is open_btn:
            command = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "roundtable_souls"]
            subprocess.Popen([*command, "--game", game.key], close_fds=True)
    except Exception as e:  # no display (a console, a test): the log says it
        core.run_logging.log(f"the notice could not be shown: {e}")
