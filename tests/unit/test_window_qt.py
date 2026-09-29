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

    assert list(launcher._game_actions) == [g.key for g in games.GAMES]
    assert launcher.game_btn.text() == "Elden Ring"
    launcher._on_game_tab("nightreign")
    for _ in range(10):
        app.processEvents()
    assert launcher.game is games.NIGHTREIGN and common.GAME is games.NIGHTREIGN
    assert launcher.game_btn.text() == "Nightreign"
    assert launcher.windowTitle().endswith("Nightreign")
    assert launcher.shortcut_fields["Launch options"].text().endswith("--game nightreign --play")
    assert launcher.repair_row.isVisibleTo(launcher.tools_page)  # Nightreign re-signs encrypted sections after play

    launcher._on_game_tab("darksouls3")
    for _ in range(10):
        app.processEvents()
    assert launcher.stackedWidget.currentWidget() is launcher.placeholder_page
    assert not launcher.navigationInterface.widget(launcher.play_page.objectName()).isEnabled()
    assert not launcher.repair_row.isVisibleTo(launcher.tools_page)
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
    assert not launcher.game_btn.isEnabled()
    launcher._on_game_tab("nightreign")
    assert launcher.game.key == "eldenring"
    launcher.set_busy(False, "done")
    assert launcher.game_btn.isEnabled()


def test_switcher_remembers_the_last_page_per_game(launcher, app):
    launcher.switchTo(launcher.mods_page)  # leave Elden Ring on Mods
    launcher._on_game_tab("nightreign")
    for _ in range(10):
        app.processEvents()
    assert launcher.stackedWidget.currentWidget() is launcher.play_page  # Nightreign, first visit, opens on Play
    launcher.switchTo(launcher.saves_page)  # leave Nightreign on Saves
    launcher._on_game_tab("eldenring")
    for _ in range(10):
        app.processEvents()
    assert launcher.stackedWidget.currentWidget() is launcher.mods_page  # Elden Ring returns to Mods
    launcher._on_game_tab("nightreign")
    for _ in range(10):
        app.processEvents()
    assert launcher.stackedWidget.currentWidget() is launcher.saves_page  # Nightreign returns to Saves


def test_switcher_menu_opens_under_the_button_and_picks_a_game(launcher, app):
    from PySide6.QtCore import QPoint

    from roundtable_souls import games

    btn, menu = launcher.game_btn, launcher._game_menu_view
    QTest.mouseClick(btn, Qt.LeftButton)  # the real click path: button -> _showMenu -> menu.exec with its animation
    for _ in range(40):
        app.processEvents()
    assert menu.isVisible()
    list_left = menu.view.mapToGlobal(QPoint(0, 0)).x()
    assert list_left == btn.mapToGlobal(QPoint(0, 0)).x()  # flush with the button's left edge, not centred
    assert [a.isChecked() for a in launcher._game_actions.values()] == [g is launcher.game for g in games.GAMES]

    def click_row(key):
        item = launcher._game_actions[key].property("item")
        QTest.mouseClick(menu.view.viewport(), Qt.LeftButton, pos=menu.view.visualItemRect(item).center())
        for _ in range(20):
            app.processEvents()

    click_row("eldenring")  # the current game: nothing switches and its check stays on
    assert launcher.game is games.ELDEN_RING and launcher._game_actions["eldenring"].isChecked()
    QTest.mouseClick(btn, Qt.LeftButton)
    for _ in range(40):
        app.processEvents()
    click_row("nightreign")
    assert launcher.game is games.NIGHTREIGN
    assert [k for k, a in launcher._game_actions.items() if a.isChecked()] == ["nightreign"]
    assert launcher.launched == []


def test_ctrl_tab_cycles_games(launcher, app):
    from roundtable_souls import games

    launcher._cycle_game(1)
    for _ in range(5):
        app.processEvents()
    assert launcher.game is games.NIGHTREIGN
    launcher._cycle_game(-1)
    for _ in range(5):
        app.processEvents()
    assert launcher.game is games.ELDEN_RING
