"""Save files: parsing (layout, container, nightreign), read-only checks (analyze, item_names), named repairs
(fix, loading, vanilla, regulation, repair), copies (transfer, library), backups and their retention
(backups), and the report's shapes (models)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from roundtable_souls.saves import (
        analyze,
        backups,
        container,
        fix,
        item_names,
        layout,
        library,
        loading,
        models,
        nightreign,
        regulation,
        repair,
        transfer,
        vanilla,
    )

__all__ = [
    "analyze",
    "backups",
    "container",
    "fix",
    "item_names",
    "layout",
    "library",
    "loading",
    "models",
    "nightreign",
    "regulation",
    "repair",
    "transfer",
    "vanilla",
]
