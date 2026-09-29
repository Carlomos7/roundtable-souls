"""Roundtable Souls: a launcher and save toolkit for modded FromSoftware games (Elden Ring and Nightreign)."""

__version__ = "3.5.0"


def main() -> int:
    """Console entry point: the window, or --check / --shots without one."""
    import sys

    from roundtable_souls.system.logging import setup_logging

    setup_logging()
    if getattr(sys, "frozen", False):
        from pathlib import Path

        from roundtable_souls.updates import remove_parked_exe

        remove_parked_exe(Path(sys.executable))  # the exe an Update now replaced; ignored while it is still exiting
    if "--play" in sys.argv or "--check" in sys.argv or any(a.startswith("--game") for a in sys.argv):
        from roundtable_souls import core, games

        game = core.game_from_args(sys.argv)
        if game is None:
            print(f"Unknown game. --game takes one of: {games.names_help()}", file=sys.stderr)
            return 2
        if "--play" in sys.argv:
            return core.play_headless(game)
        if "--check" in sys.argv:
            core.check(game)
            return 0
        core.STARTUP_GAME = game  # the window opens on this tab, this run only
    from roundtable_souls.ui.window import main as window_main

    return int(window_main() or 0)
