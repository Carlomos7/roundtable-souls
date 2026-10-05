"""Self-update for the window and the command line: the modules of the updates package (feed, apply, headless,
inno), passed through as modules so a test that stands in for one of their functions reaches every caller."""

from roundtable_souls.updates import apply, feed, headless, inno
from roundtable_souls.updates.feed import RELEASES_URL

__all__ = ["RELEASES_URL", "apply", "feed", "headless", "inno"]
