"""The window's pages, in the order the navigation rail shows them. Each page has a view (ui/pages/<page>/view.py):
its widgets and handlers, a mixin class the window (ui/shell.Launcher) inherits. Presenters (plain Python, no Qt)
join them page by page."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from roundtable_souls.ui.pages import coop, tools

PAGES = ("coop", "tools")  # the page views the window is made of

__all__ = ["PAGES", "coop", "tools"]
