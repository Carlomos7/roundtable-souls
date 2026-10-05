"""The window's widgets, by kind: cards (cards and form rows), layout (page grounds, headers, wrapping rows),
menus (the switcher and pick-one menus), labels (path tags, eliding labels), log (the Bus and the log pane), hero (the
Play hero banner), panels (the action bar, the editor panel) and notices (notices, the drop overlay, the status
pill)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from roundtable_souls.ui.widgets import (
        cards,
        hero,
        labels,
        layout,
        log,
        menus,
        notices,
        panels,
    )

__all__ = [
    "cards",
    "hero",
    "labels",
    "layout",
    "log",
    "menus",
    "notices",
    "panels",
]
