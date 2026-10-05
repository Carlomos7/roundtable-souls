"""Self-update: the release feed (feed), downloading, verifying, applying and rolling back with Velopack
(apply), signatures (signing), --update without the window (headless), and the move from the old Inno
Setup install (inno; delete once no 3.13.2-or-older installs remain)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from roundtable_souls.updates import (
        apply,
        feed,
        headless,
        inno,
        signing,
    )

__all__ = [
    "apply",
    "feed",
    "headless",
    "inno",
    "signing",
]
