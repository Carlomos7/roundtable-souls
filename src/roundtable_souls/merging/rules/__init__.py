"""How the changes of several mods to one file combine, one module per format: bnd4, fmg, param, esd."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from roundtable_souls.merging.rules import (
        bnd4,
        esd,
        fmg,
        param,
    )

__all__ = [
    "bnd4",
    "esd",
    "fmg",
    "param",
]
