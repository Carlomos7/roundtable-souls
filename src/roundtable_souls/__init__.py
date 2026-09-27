"""Roundtable Souls: a launcher and save toolkit for modded Elden Ring."""

__version__ = "3.0.0"


def main() -> int:
    """Console entry point: the window, or --check / --shots without one."""
    import sys

    from roundtable_souls.system.logging import setup_logging

    setup_logging()
    if "--check" in sys.argv:
        from roundtable_souls import core

        core.check()
        return 0
    from roundtable_souls.ui.window import main as window_main

    return int(window_main() or 0)
