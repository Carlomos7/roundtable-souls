"""Merging what several mods ship into one result, against the game's own files.

merger: one entry point that picks the rule for a file's format. rules: what a mod changed and how changes
combine, per format (bnd4: archives, fmg: text tables, param: parameter tables, esd: talk scripts). build:
staging, checking and activating a build. record: what a build was made from. changes: what a merge reports."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from roundtable_souls.merging import (
        build,
        changes,
        merger,
        record,
        rules,
    )

__all__ = [
    "build",
    "changes",
    "merger",
    "record",
    "rules",
]
