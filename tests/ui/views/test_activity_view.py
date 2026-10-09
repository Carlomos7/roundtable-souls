"""The Activity page in its own window, off-screen: it loads with no QML warning in every theme at the narrow and
wide sizes, follows the theme's tokens, opens a job's log on a click, and Undo asks first and runs as a job."""

import pytest
from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from roundtable_souls.ui import theme_tokens
from roundtable_souls.ui.page_window import PageWindow

THEMES = ("dark", "tarnished", "light")
WIDTHS = (740, 1100)


def settle(ms: int = 60) -> None:
    """Let the event loop run (animations, bindings) without holding the GIL like QTest.qWait."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    QApplication.processEvents()


def opened(entry, host, theme="dark", width=1100) -> PageWindow:
    w = PageWindow(entry, host, theme)
    assert w.build(), w.warnings
    win = w.window
    assert win is not None
    win.resize(width, 760)
    win.show()
    settle(250)
    return w


def closed(w: PageWindow) -> None:
    """Free the window; any QML warning it reported on the way fails the test."""
    warnings = list(w.warnings)
    w.dispose()
    settle()
    assert warnings == []


def click(w: PageWindow, item) -> None:
    """A real left click on the item's centre, through the window."""
    win = w.window
    assert win is not None
    QTest.mouseClick(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre(item))


def centre(item) -> QPoint:
    p = item.mapToScene(item.boundingRect().center())
    return QPoint(round(p.x()), round(p.y()))


def find(w: PageWindow, name: str):
    """An item by objectName in the window's visual tree (Repeater delegates are not QObject children)."""
    win = w.window
    assert win is not None
    todo = [win.contentItem()]
    while todo:
        item = todo.pop()
        if item.objectName() == name:
            return item
        todo.extend(item.childItems())
    raise AssertionError(f"no item named {name}")


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("theme", THEMES)
def test_the_page_renders_in_every_theme_at_both_sizes(qt_app, activity_entry, host, shots, theme, width):
    w = opened(activity_entry, host, theme, width)
    try:
        win = w.window
        assert win is not None
        img = win.grabWindow()
        assert img.width() == width
        img.save(str(shots / f"activity-{theme}-{width}.png"))
        assert w.warnings == []
        page = w.page_item()
        assert page is not None and round(page.property("width")) == width
        # the empty page area below the last card is the theme's page surface
        roles = theme_tokens.THEMES[theme]
        assert img.pixelColor(width // 2, 740).name().upper() == QColor(str(roles["surfacePage"])).name().upper()
        state = w.adapter.state()
        assert [d.label for d in state.days] == ["Today", "Yesterday"]
    finally:
        closed(w)


def test_a_click_on_a_job_opens_its_log_and_a_second_closes_it(qt_app, activity_entry, host, monkeypatch):
    from roundtable_souls.platform import logging as run_logging

    entries = [{"time": "11:00:02.000", "level": "info", "source": "me3", "text": "game exited (0)"}]
    monkeypatch.setattr(run_logging, "read_job_log", lambda name: {"entries": entries, "cut": False, "missing": False})
    w = opened(activity_entry, host)
    try:
        row = find(w, "job_p2")
        click(w, row)
        settle(300)
        assert w.adapter.openJob == "p2"
        assert "game exited (0)" in w.adapter.logText
        assert row.height() > 60  # the log opened inside the row
        click(w, find(w, "job_i1"))
        settle(300)
        assert w.adapter.openJob == "i1"
    finally:
        closed(w)


def test_undo_asks_first_and_then_runs_as_a_job(qt_app, activity_entry, host):
    w = opened(activity_entry, host)
    try:
        asked = []
        w.notifier.confirmRequested.connect(lambda token, title, *rest: asked.append((token, title)))
        click(w, find(w, "undo_i1"))
        settle(200)
        assert [t for _, t in asked] == ["Undo the install of Grand Merchant"]
        assert host.jobs == []  # nothing runs until the user applies it
        w.notifier.answer(asked[0][0], True)
        assert host.jobs == ["Restoring Grand Merchant..."]
    finally:
        closed(w)


def test_undo_while_a_job_runs_says_so_in_a_toast(qt_app, activity_entry, host):
    w = opened(activity_entry, host)
    try:
        toasts = []
        w.notifier.toastRequested.connect(lambda text, error: toasts.append((text, error)))
        host.busy = True
        click(w, find(w, "undo_i1"))
        settle(200)
        assert toasts == [("Wait for the current job. Undo runs as a job of its own.", True)]
        assert host.jobs == []
    finally:
        closed(w)


def test_filters_narrow_the_list(qt_app, activity_entry, host):
    w = opened(activity_entry, host)
    try:
        w.adapter.setFailedOnly(True)
        settle()
        assert [j.id for d in w.adapter.state().days for j in d.jobs] == ["r1"]
        assert w.warnings == []
    finally:
        closed(w)


def test_opening_the_page_counts_as_looking_at_activity(qt_app, activity_entry, host):
    w = opened(activity_entry, host)
    try:
        assert host.seen == 1
    finally:
        closed(w)
