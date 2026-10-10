"""The light theme hooks into two internals of PySide6-Fluent-Widgets (written against 1.11.3): the style-sheet renderer
every widget's sheet goes through, and the navigation row's paint and state. If a library update renames them, these
tests fail loudly instead of the light theme quietly going back to black text or the sidebar breaking."""

import os

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"  # always, whatever the shell sets: no real windows
pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtWidgets import QApplication  # noqa: E402

from roundtable_souls.ui import theme  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_the_style_sheet_renderer_is_still_where_the_theme_hooks_in(app):
    from qfluentwidgets.common import style_sheet

    assert callable(getattr(style_sheet, "renderQss", None))
    theme.use_theme_text()
    theme.use_theme_text()  # installing twice wraps it once
    assert getattr(style_sheet.renderQss, "theme_text", False)


def test_light_sheets_get_the_theme_text_colour_and_other_blacks_stay(app, monkeypatch):
    from qfluentwidgets.common import style_sheet

    monkeypatch.setattr(theme, "isDarkTheme", lambda: False)
    theme.use_theme_text()
    out = style_sheet.renderQss("QLabel{color: black; background-color: black; selection-color: #000000}")
    assert (
        f"color: {theme.TEXT_LIGHT}" in out and "background-color: black" in out and "selection-color: #000000" in out
    )


def test_the_navigation_row_still_has_what_the_sidebar_paint_uses(app):
    from qfluentwidgets import FluentIcon, NavigationPushButton

    row = NavigationPushButton(FluentIcon.HOME, "Play", True)
    for name in ("_margins", "_canDrawIndicator", "indicatorRect"):
        assert callable(getattr(row, name, None)), name
    for name in ("isPressed", "isEnter", "isAboutSelected", "isCompacted", "_icon"):
        assert hasattr(row, name), name
