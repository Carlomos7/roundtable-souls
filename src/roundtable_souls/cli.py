"""The command line: `roundtable-souls` opens the window; --play, --check and --update run without one, and --game
picks the game. --play --allow-without-backup starts the game even when 'back up saves before Play' fails.
--check-storage opens (creating or upgrading) the launcher's database in the data folder and prints what it found:
a check for builds, which reads nothing else. Each mode imports only what it needs, so a Play from a Steam shortcut never loads the window."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from roundtable_souls.game.catalog import Game


def main() -> int:
    """Console entry point: the window; or without one --play, --check, --update (see headless.update_headless)."""
    from roundtable_souls.app import use_data_folder
    from roundtable_souls.platform import logging as run_logging

    use_data_folder()  # before anything logs: the platform layer is told where the data folder is
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
    if "--check-storage" in sys.argv:
        return check_storage()
    game = None  # --game without --play/--check: the tab the window opens on, this run only
    if "--play" in sys.argv or "--check" in sys.argv or any(a.startswith("--game") for a in sys.argv):
        from roundtable_souls.game import catalog as games
        from roundtable_souls.services import play as core

        game = core.game_from_args(sys.argv)
        if game is None:
            print(f"Unknown game. --game takes one of: {games.names_help()}", file=sys.stderr)
            return 2
        if "--play" in sys.argv:
            return play_from_shortcut(game, allow_without_backup="--allow-without-backup" in sys.argv)
        if "--check" in sys.argv:
            from roundtable_souls.app import create_app
            from roundtable_souls.storage.db import MigrationFailed

            try:
                ctx = create_app(game)
            except MigrationFailed as e:
                return storage_failed(e, window=False)
            core.check(ctx.settings, ctx.locations, ctx.data_dir)
            return 0
    from roundtable_souls.app import create_app
    from roundtable_souls.storage.db import MigrationFailed
    from roundtable_souls.ui.shell import main as window_main

    try:
        ctx = create_app(game)
    except MigrationFailed as e:  # no window, so no ready report: an update's watchdog rolls back
        return storage_failed(e, window=True)
    return int(window_main(ctx) or 0)


def check_storage() -> int:
    """--check-storage: open the database in the data folder (creating or upgrading it) and print the facts; exit 0
    only when it is open at the current schema. Used on builds, to prove the migrations were packaged."""
    import sqlite3

    from roundtable_souls.app import use_data_folder
    from roundtable_souls.config import identity
    from roundtable_souls.platform import data_folder
    from roundtable_souls.resources import MIGRATIONS_DIR
    from roundtable_souls.storage import db as storage_db

    use_data_folder()
    root = data_folder.data_root()
    report: list[str] = []

    def say(line: str) -> None:
        report.append(line)
        print(line)

    scripts = sorted(p.name for p in (MIGRATIONS_DIR / "versions").glob("*.py"))
    say(f"identity: {identity.get().pack_id}")
    say(f"data folder: {root}")
    say(f"sqlite: {sqlite3.sqlite_version} (minimum {'.'.join(map(str, storage_db.MIN_SQLITE))})")
    say(f"migrations: {MIGRATIONS_DIR} ({len(scripts)} scripts: {', '.join(scripts) or 'none'})")
    ok = False
    try:
        db = storage_db.open_database(root, log=lambda line: say(f"  {line}"))
    except storage_db.StorageError as e:
        say(f"FAILED: {e}")
    else:
        try:
            head = storage_db.head_revision()
            say(f"database: {db.path} at {db.revision} (head {head}), journal {db.journal_mode}")
            ok = db.revision == head
        finally:
            db.close()
        say("OK" if ok else "FAILED: not at the current schema")
    try:  # a windowed build has no console: the report is also a file in the data folder
        (root / "storage-check.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    except OSError:
        pass
    return 0 if ok else 1


def storage_failed(error: Exception, window: bool) -> int:
    """The database upgrade failed: say so (the log, the console, and a small window when there is a display);
    this version does not report itself ready."""
    from roundtable_souls.platform import logging as run_logging

    run_logging.log(f"error: Roundtable Souls could not start: {error}")
    print(f"Roundtable Souls could not start: {error}", file=sys.stderr)
    if window:
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance() or QApplication(sys.argv[:1])
            QMessageBox.critical(None, "Roundtable Souls", f"Roundtable Souls could not start.\n\n{error}")
            del app
        except Exception as e:  # no display: the log and the console say it
            run_logging.log(f"the message could not be shown: {e}")
    return 1


def play_from_shortcut(game, allow_without_backup: bool = False) -> int:
    """--play: when the window is open, it runs Play itself (one launcher manages the session); otherwise Play runs
    here, holding the PLAY name so a second shortcut start, or a silent update, waits for it to end.
    allow_without_backup (--allow-without-backup): start even when 'back up saves before Play' fails."""
    from roundtable_souls.app import create_app
    from roundtable_souls.platform import instance
    from roundtable_souls.platform import logging as run_logging
    from roundtable_souls.services import play as core
    from roundtable_souls.updates import apply as updates

    message = f"play {game.key}" + (" allow-without-backup" if allow_without_backup else "")
    if instance.held(instance.WINDOW) and instance.send(message):
        updates.mark_ready("play")  # this version started and handed Play to its window
        run_logging.start_log("launcher: play (no window)", game.key)
        run_logging.log("Roundtable Souls is open: Play was handed to its window")
        return 0
    hold = instance.acquire(instance.PLAY)
    if hold is None:
        run_logging.start_log("launcher: play (no window)", game.key)
        run_logging.log("error: a Play from a Steam shortcut is already running")
        return 1
    try:
        from roundtable_souls.storage.db import MigrationFailed

        try:
            ctx = create_app(game)
        except MigrationFailed as e:  # not ready: an update's watchdog rolls back
            return storage_failed(e, window=False)
        updates.mark_ready("play")  # this version starts and runs: an update's watchdog can stand down
        if allow_without_backup:
            return core.play_headless(ctx.settings, ctx.locations, notice=not_started_notice, allow_without_backup=True)
        return core.play_headless(ctx.settings, ctx.locations, notice=not_started_notice)
    finally:
        hold.release()


def not_started_notice(game: Game, why: str, headline: str | None = None) -> None:
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
        if headline:  # another reason than the merged mods (a failed backup before Play)
            box.setText(headline)
            box.setInformativeText(why)
        else:
            box.setText(f"{game.name} was not started: your mods need a rebuild")
            box.setInformativeText(
                f"{why}\n\nThe game does not start with merged mods that no longer match your mods, so it cannot "
                "run with a removed or changed mod still inside them."
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
