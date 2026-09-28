"""Roundtable Souls: a launcher and save toolkit for modded Elden Ring."""

__version__ = "3.2.0"


def main() -> int:
    """Console entry point: the window, or --check / --shots without one."""
    import sys

    from roundtable_souls.system.logging import setup_logging

    setup_logging()
    if getattr(sys, "frozen", False):
        from pathlib import Path

        from roundtable_souls.updates import remove_parked_exe

        remove_parked_exe(Path(sys.executable))  # the exe an Update now replaced; ignored while it is still exiting
    if "--play" in sys.argv:
        from roundtable_souls import core

        return core.play_headless()
    if "--check" in sys.argv:
        from roundtable_souls import core

        core.check()
        return 0
    from roundtable_souls.ui.window import main as window_main

    return int(window_main() or 0)
