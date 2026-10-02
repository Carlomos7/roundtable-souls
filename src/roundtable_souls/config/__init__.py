"""The launcher's own configuration: its settings file (settings) and the build's identity (identity: app ID,
release feed and signing key, overridden for isolated test builds)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from roundtable_souls.config import (
        identity,
        settings,
    )

__all__ = [
    "identity",
    "settings",
]
