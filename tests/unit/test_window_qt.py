"""The real window, offscreen: keyboard safety at start, page shortcuts, and layouts that fit a narrow window."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtTest = pytest.importorskip("PySide6.QtTest")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from roundtable_souls.ui import window  # noqa: E402

QTest = QtTest.QTest


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def launcher(app, monkeypatch):
    launched = []
    monkeypatch.setattr(window, "launcher_update", lambda *a, **k: None)
    monkeypatch.setattr(window, "me3_facts", lambda setup: {"version": None, "info": {}, "latest": None})
    monkeypatch.setattr(window.Launcher, "launch", lambda self: launched.append("play"))
    monkeypatch.setattr(window.Launcher, "launch_offline", lambda self: launched.append("offline"))
    w = window.Launcher()
    w.resize(1080, 760)
    w.show()
    for _ in range(20):
        app.processEvents()
    w.launched = launched
    yield w
    w.hide()
    w.deleteLater()
    app.processEvents()


def test_nothing_can_press_play_by_accident_at_start(launcher, app):
    assert app.focusWidget() is not launcher.play_btn
    for key in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
        QTest.keyClick(launcher, key)
        app.processEvents()
    assert launcher.launched == []


def test_ctrl_number_switches_pages(launcher, app):
    pages = [launcher.play_page, launcher.coop_page, launcher.mods_page, launcher.saves_page, launcher.tools_page]
    for n, page in enumerate(pages, start=1):
        QTest.keyClick(launcher, getattr(Qt, f"Key_{n}"), Qt.ControlModifier)
        app.processEvents()
        assert launcher.stackedWidget.currentWidget() is page


def test_pages_fit_a_narrow_window(launcher, app):
    launcher.resize(740, 640)
    for _ in range(20):
        app.processEvents()
    for page in (launcher.play_page, launcher.mods_page, launcher.saves_page, launcher.tools_page):
        launcher.switchTo(page)
        for _ in range(10):
            app.processEvents()
        inner = page.widget()
        assert inner.width() <= page.viewport().width() + 1, page.objectName()


def test_game_tabs_switch_every_page(launcher, app):
    from roundtable_souls import games
    from roundtable_souls.system import common

    assert list(launcher.game_tabs.items) == [g.key for g in games.GAMES]
    launcher._on_game_tab("nightreign")
    for _ in range(10):
        app.processEvents()
    assert launcher.game is games.NIGHTREIGN and common.GAME is games.NIGHTREIGN
    assert launcher.windowTitle().endswith("Nightreign")
    assert launcher.shortcut_fields["Launch options"].text().endswith("--game nightreign --play")
    assert not launcher.repair_row.isVisibleTo(launcher.tools_page)  # the regulation repair is Elden Ring's

    launcher._on_game_tab("darksouls3")
    for _ in range(10):
        app.processEvents()
    assert launcher.stackedWidget.currentWidget() is launcher.placeholder_page
    assert not launcher.navigationInterface.widget(launcher.play_page.objectName()).isEnabled()
    QTest.keyClick(launcher, Qt.Key_1, Qt.ControlModifier)  # Ctrl+1 cannot open Play for a placeholder game
    app.processEvents()
    assert launcher.stackedWidget.currentWidget() is launcher.placeholder_page
    assert launcher.launched == []

    launcher._on_game_tab("eldenring")
    for _ in range(10):
        app.processEvents()
    assert launcher.stackedWidget.currentWidget() is launcher.play_page
    assert launcher.navigationInterface.widget(launcher.play_page.objectName()).isEnabled()


def test_game_tabs_are_locked_while_a_job_runs(launcher, app):
    launcher.set_busy(True, "Working...")
    assert not launcher.game_tabs.isEnabled()
    launcher._on_game_tab("nightreign")
    assert launcher.game.key == "eldenring"
    launcher.set_busy(False, "done")
    assert launcher.game_tabs.isEnabled()
