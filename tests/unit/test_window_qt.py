"""The real window, offscreen: keyboard safety at start, page shortcuts, and layouts that fit a narrow window."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtTest = pytest.importorskip("PySide6.QtTest")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from roundtable_souls.platform import paths as _common  # noqa: E402
from roundtable_souls.ui import window  # noqa: E402

REAL_SAVE_FILES = _common.save_files
REAL_LAUNCH = window.Launcher.launch

QTest = QtTest.QTest


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def launcher(app, monkeypatch):
    launched = []
    monkeypatch.setattr(window.feed, "check_launcher_update", lambda *a, **k: window.feed.UpdateCheck("off"))
    monkeypatch.setattr(window.feed, "check_advisory", lambda *a, **k: None)
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
    pages = [
        launcher.play_page,
        launcher.coop_page,
        launcher.mods_page,
        launcher.saves_page,
        launcher.activity_page,
        launcher.tools_page,
    ]
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
    from roundtable_souls.game import catalog as games
    from roundtable_souls.platform import paths as common

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

    from roundtable_souls.game import catalog as games

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
    from roundtable_souls.game import catalog as games

    launcher._cycle_game(1)
    for _ in range(5):
        app.processEvents()
    assert launcher.game is games.NIGHTREIGN
    launcher._cycle_game(-1)
    for _ in range(5):
        app.processEvents()
    assert launcher.game is games.ELDEN_RING


SANDBOX_PROFILE = (
    'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n\n'
    "[[natives]]\npath = 'natives/SeamlessCoop/ersc.dll'\nload_early = true\n"
)
SANDBOX_INI = "[PASSWORD]\ncooppassword = start\n[SCALING]\nenemy_health_scaling = 35\n"


@pytest.fixture
def sandbox(app, monkeypatch, tmp_path):
    """The real window pointed at a temp me3 profile and co-op ini, with no saves, so tests can type and save."""
    from roundtable_souls.platform import paths as common

    profiles = tmp_path / "profiles"
    seamless = profiles / "natives" / "SeamlessCoop"
    seamless.mkdir(parents=True)
    (seamless / "ersc.dll").write_bytes(b"d")
    (seamless / "ersc_settings.ini").write_text(SANDBOX_INI, encoding="utf-8")
    (profiles / "sandbox.me3").write_text(SANDBOX_PROFILE, encoding="utf-8")
    monkeypatch.setattr(common, "me3_profiles_dir", lambda: profiles)
    monkeypatch.setattr(common, "save_files", lambda game=None: [])
    monkeypatch.setattr(window.feed, "check_launcher_update", lambda *a, **k: window.feed.UpdateCheck("off"))
    monkeypatch.setattr(window.feed, "check_advisory", lambda *a, **k: None)
    monkeypatch.setattr(window, "me3_facts", lambda setup: {"version": None, "info": {}, "latest": None})
    monkeypatch.setattr(window.Launcher, "launch", lambda self: None)
    monkeypatch.setattr(window.Launcher, "_watch_game", lambda self: None)
    w = window.Launcher()
    w.resize(1080, 760)
    w.show()
    QTest.qWait(300)
    w.profiles = profiles
    yield w
    w.hide()
    w.deleteLater()
    app.processEvents()


def test_save_rows_use_one_button_size(sandbox):
    w = sandbox
    pairs = [
        (w.save_bar.primary, w.save_bar.secondary),
        (w.profile_panel.bar.primary, w.profile_panel.bar.secondary),
        (w.share_panel.bar.primary, w.share_panel.bar.secondary),
    ]
    heights = {b.height() for pair in pairs for b in pair if b.isVisible()}
    heights |= {b.minimumHeight() for pair in pairs for b in pair}
    assert heights == {36}, heights  # primary and secondary alike, in every save row


def test_profile_editor_saves_and_discards_in_its_own_footer(sandbox):
    w = sandbox
    panel, path = w.profile_panel, w.profiles / "sandbox.me3"
    assert not panel.dirty and not panel.bar.primary.isEnabled()
    panel.edit.setPlainText(panel.text() + "# note\n")
    assert panel.dirty and panel.bar.primary.isEnabled() and "Not saved" in panel.bar.note.text()
    QTest.mouseClick(panel.bar.secondary, Qt.LeftButton)  # Discard reads the file again
    assert not panel.dirty and "# note" not in panel.text()
    panel.edit.setPlainText(panel.text() + "# kept\n")
    QTest.mouseClick(panel.bar.primary, Qt.LeftButton)
    QTest.qWait(50)
    assert "# kept" in path.read_text(encoding="utf-8") and not panel.dirty


def test_closing_with_unsaved_edits_asks_save_discard_or_cancel(sandbox, monkeypatch):
    w = sandbox
    ini = w.profiles / "natives" / "SeamlessCoop" / "ersc_settings.ini"
    w._do_page_fill(w._page_fill_token)
    w.pw.setText("changed")
    asked = []
    monkeypatch.setattr(window, "ask_unsaved", lambda parent, what, action: asked.append(what) or None)
    w.close()
    assert w.isVisible() and asked and "Password" in asked[0][0]  # Cancel keeps the window open
    monkeypatch.setattr(window, "ask_unsaved", lambda parent, what, action: "discard")
    w.close()
    assert not w.isVisible() and "cooppassword = start" in ini.read_text(encoding="utf-8")  # nothing written


def test_update_notice_fits_a_narrow_window(sandbox, monkeypatch):
    w = sandbox
    monkeypatch.setattr(window, "FROZEN", True)
    monkeypatch.setattr(window.updates, "can_self_update", lambda *a, **k: True)
    w.resize(740, 640)
    QTest.qWait(100)
    notes = "## Changes\n- one\n- two"
    offer = {"version": "9.9.9", "url": "https://example.invalid", "notes": notes, "assets": {}}
    w._on_update({"check": window.feed.UpdateCheck("fresh", offer=offer), "advisory": None, "force": False})
    QTest.qWait(400)
    from qfluentwidgets import InfoBar

    bars = [b for b in w.findChildren(InfoBar) if b.isVisible()]
    assert bars and all(b.width() <= w.width() for b in bars)


def test_saves_page_names_the_file_play_uses_and_lists_the_library(sandbox, monkeypatch, tmp_path):
    from PySide6.QtCore import QEventLoop, QTimer

    from roundtable_souls.game import catalog as games
    from roundtable_souls.platform import paths as common
    from roundtable_souls.saves import library, regulation

    acct = tmp_path / "EldenRing" / "7656"
    acct.mkdir(parents=True)
    data = bytearray(regulation.FILE_SIZE)
    data[:4] = b"BND4"
    (acct / "ER0000.sl2").write_bytes(bytes(data))
    monkeypatch.setattr(common, "save_roots", lambda game=None: [tmp_path / "EldenRing"])
    monkeypatch.setattr(common, "save_files", REAL_SAVE_FILES)  # the sandbox hides saves; this test brings its own
    library.add(acct, acct / "ER0000.sl2", "first run", games.ELDEN_RING)
    w = sandbox
    w._on_setup()  # the sandbox setup loads Seamless Co-op, so Play uses the co-op save
    assert w._saves_in_use["active"] == "ER0000.co2" and w._save_role("ER0000.co2") == "Play uses this"
    assert w._save_role("ER0000.sl2") == "Play offline uses this"
    w.refresh_saves()
    loop = QEventLoop()
    for _ in range(100):  # the read runs on a worker thread
        if w.saves:
            break
        QTimer.singleShot(50, loop.quit)
        loop.exec()
    assert [s["name"] for s in w.saves] == ["ER0000.sl2"]
    targets = [t.name for _label, t in w._save_targets(acct)]
    assert targets == ["ER0000.sl2", "ER0000.co2"]  # the co-op file does not exist yet but can be swapped into
    assert "1 saved copy" in w.library_note.text() and w.library_rows.count() == 1


def test_folder_of_mods_entry_shows_as_its_folder_and_can_be_removed(sandbox, monkeypatch):
    from roundtable_souls.mods import profile_edit as manage

    w = sandbox
    prof = w.profiles / "sandbox.me3"
    (w.profiles / "mod" / "hud" / "menu").mkdir(parents=True)
    (w.profiles / "mod" / "skin" / "parts").mkdir(parents=True)
    prof.write_text(
        prof.read_text(encoding="utf-8")
        + "\n[[packages]]\nid = \"all\"\npath = 'mod'\n\n[[packages]]\nid = \"hud\"\npath = 'mod/hud'\n",
        encoding="utf-8",
    )
    w.switchTo(w.mods_page)
    w._fill_mods()
    QTest.qWait(100)
    assert w.pack_exp.card.contentLabel.text() == "1 loaded"  # the folder entry is not counted as a mod
    labels = [lab.full_text() for lab in w.pack_exp.findChildren(window.ElideLabel)]
    assert "all" not in labels and "hud" in labels and "mod" in labels  # shown as the folder it is
    from PySide6.QtWidgets import QAbstractButton

    buttons = [b for b in w.pack_exp.findChildren(QAbstractButton) if b.isVisible()]
    assert any(b.text() == "Not loaded (1)" for b in buttons)
    remove = next(b for b in buttons if b.toolTip().startswith("Remove 'all'"))  # the trash in the delete column
    monkeypatch.setattr(window, "confirm", lambda *a, **k: True)
    QTest.mouseClick(remove, Qt.LeftButton)
    QTest.qWait(100)
    assert [e["name"] for e in manage.entries(prof) if e["kind"] == "package"] == ["hud"]
    assert (w.profiles / "mod" / "skin").is_dir()  # folders stay


def test_mod_actions_follow_the_file_when_it_changed_outside_the_window(sandbox, monkeypatch):
    from roundtable_souls.mods import profile_edit as manage

    w = sandbox
    prof = w.profiles / "sandbox.me3"
    (w.profiles / "natives" / "a.dll").write_bytes(b"a")
    prof.write_text(prof.read_text(encoding="utf-8") + "\n[[natives]]\npath = 'natives/a.dll'\n", encoding="utf-8")
    w.switchTo(w.mods_page)
    w._fill_mods()
    shown = {e["name"]: e for e in manage.entries(prof)}
    text = prof.read_text(encoding="utf-8")  # someone adds an entry above both, outside the window
    (w.profiles / "natives" / "b.dll").write_bytes(b"b")
    prof.write_text(
        text.replace("[[natives]]", "[[natives]]\npath = 'natives/b.dll'\n\n[[natives]]", 1), encoding="utf-8"
    )
    w._toggle_mod(shown["a.dll"], False)  # the row still holds the old position
    now = {e["name"]: e["enabled"] for e in manage.entries(prof)}
    assert now == {"b.dll": True, "ersc.dll": True, "a.dll": False}  # the right entry changed, by name not position


def test_saving_the_editor_over_outside_changes_asks_first(sandbox, monkeypatch):
    w = sandbox
    prof = w.profiles / "sandbox.me3"
    w._load_profile_editor(force=True)
    w.profile_panel.edit.setPlainText(w.profile_panel.text() + "# mine\n")
    prof.write_text(prof.read_text(encoding="utf-8") + "# theirs\n", encoding="utf-8")
    asked = []
    monkeypatch.setattr(window, "confirm", lambda *a, **k: asked.append(a[1]) or False)
    assert w._save_profile() is False and asked and "changed on disk" in asked[0]
    assert "# theirs" in prof.read_text(encoding="utf-8") and "# mine" not in prof.read_text(encoding="utf-8")
    QTest.mouseClick(w.profile_panel.bar.secondary, Qt.LeftButton)  # Discard reads the file again
    assert "# theirs" in w.profile_panel.text()


def test_right_aligned_rows_end_at_the_right_edge_and_wrap(app):
    from PySide6.QtWidgets import QPushButton

    from roundtable_souls.ui.widgets import action_row

    w, flow = action_row("right")
    buttons = [QPushButton(t) for t in ("One", "Two", "Three")]
    for b in buttons:
        b.setFixedSize(100, 30)
        flow.addWidget(b)
    w.resize(400, 80)
    w.show()
    QTest.qWait(50)
    assert buttons[-1].geometry().right() == w.width() - 1 and buttons[0].x() > 0  # one line, pushed right
    w.resize(230, 120)
    QTest.qWait(50)
    assert buttons[2].y() > buttons[0].y() and buttons[2].geometry().right() == w.width() - 1  # wraps, still right
    w.hide()


def test_seamless_settings_button_opens_the_coop_page(sandbox, monkeypatch):
    w = sandbox
    w.switchTo(w.mods_page)
    w._fill_mods()
    ersc = next(e for e in window.profile_entries(w.setup.profile) if e["name"] == "ersc.dll")
    opened = []
    monkeypatch.setattr(window.ConfigFilesDialog, "exec", lambda self: opened.append(self))
    w._native_settings(ersc)
    assert w.stackedWidget.currentWidget() is w.coop_page and opened == []  # its ini belongs to the Co-op page
    (w.profiles / "natives" / "SeamlessCoop" / "ersc.dll").with_name("extra_settings.ini").write_text("a = 1\n")
    w._native_settings(ersc)
    assert opened and [f["path"].name for f in opened[0].files] == ["extra_settings.ini"]
    assert opened[0].tie_btn.text() == "Attach a file..." and opened[0].untie_btn.text() == "Detach"


def _drag(target, paths, kind="enter"):
    """Send a real drag enter or drop event carrying local files to a widget."""
    from PySide6.QtCore import QMimeData, QPointF, QUrl
    from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent

    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    point = target.rect().center()
    events = [QDragEnterEvent(point, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)]
    if kind == "drop":  # Qt only delivers a drop to a widget the drag entered and moved over
        events += [
            QDragMoveEvent(point, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier),
            QDropEvent(QPointF(point), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier),
        ]
    for e in events:
        QApplication.sendEvent(target, e)
    return events[-1], md  # the mime data must outlive the events


def test_dropping_mods_on_the_mods_page_installs_each_in_turn(sandbox, monkeypatch, tmp_path):
    from PySide6.QtCore import QEventLoop, QTimer

    from roundtable_souls.mods import profile_edit as manage
    from roundtable_souls.platform import logging as run_logging
    from roundtable_souls.platform import paths as common

    monkeypatch.setattr(common, "start_log", lambda *a, **k: None)  # the job's log stays out of the real logs folder
    monkeypatch.setattr(run_logging, "log", lambda *a, **k: None)
    asked = []

    def answer(dlg):
        asked.append(dlg.plan["name"])
        return dlg.validate()

    monkeypatch.setattr(window.InstallDialog, "exec", answer)
    toasts = []
    monkeypatch.setattr(window.Launcher, "_toast", lambda self, title, msg, **k: toasts.append(title))
    w = sandbox
    dl = tmp_path / "downloads"
    for name in ("Armor", "Hud"):
        (dl / name / "parts").mkdir(parents=True)
        (dl / name / "parts" / "x.partsbnd.dcx").write_bytes(b"p")
    (dl / "notes.pdf").write_bytes(b"n")
    w.switchTo(w.mods_page)
    QTest.qWait(50)
    paths = [dl / "Armor", dl / "Hud", dl / "notes.pdf"]
    held = _drag(w.mods_page.viewport(), paths)
    assert held[0].isAccepted() and w.mods_drop.isVisible()
    assert w.mods_drop._usable == paths[:2] and w.mods_drop._refused == paths[2:]
    held = _drag(w.mods_drop, paths, "drop")
    loop = QEventLoop()
    prof = w.profiles / "sandbox.me3"
    for _ in range(200):  # each install runs on a worker thread, then the next one starts
        if not w.busy and {"armor", "hud"} <= {e["name"] for e in manage.entries(prof)}:
            break
        QTimer.singleShot(50, loop.quit)
        loop.exec()
    assert asked == ["armor", "hud"] and "Skipped" in toasts, toasts
    assert (w.profiles / "mod" / "hud" / "parts" / "x.partsbnd.dcx").is_file()
    for _ in range(20):  # the overlay fades out
        QTimer.singleShot(50, loop.quit)
        loop.exec()
    assert not w.mods_drop.isVisible()


def test_install_dialog_offers_a_rebuild_only_before_the_merger(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from test_mod_merge import World, _pack_source

    from roundtable_souls.mods import install

    world = World(tmp_path, monkeypatch)
    plan = install.plan_install(world.profile, _pack_source(tmp_path / "dl"))
    parent = QWidget()
    parent.resize(1000, 800)
    dlg = window.InstallDialog(parent, plan, lambda *a: plan, world.profile)
    assert not dlg.rebuild.isHidden() and dlg.rebuild.isChecked()
    assert dlg.validate() and plan["merge"] is True and plan["insert_before"] == "last"
    dlg.rebuild.setChecked(False)
    assert "will not apply" in dlg.reg_effect.text()
    dlg.validate()
    assert plan["merge"] is False
    dlg.rebuild.setChecked(True)
    dlg.reg_place.setCurrentIndex(1)  # Last: nothing to rebuild, the merger's own parameters are lost
    assert dlg.rebuild.isHidden() and "last's parameters will not apply" in dlg.reg_effect.text()
    dlg.validate()
    assert plan["merge"] is False and plan["insert_before"] is None
    dlg.reg_place.setCurrentIndex(0)
    dlg.boxes["regulation.bin"].setChecked(False)  # left out: no parameters, no rebuild
    assert dlg.rebuild.isHidden()
    dlg.validate()
    assert plan["merge"] is False
    parent.deleteLater()


def test_merge_health_is_a_pill_and_prompts_when_it_goes_stale(sandbox, monkeypatch):
    w = sandbox
    shown = []
    monkeypatch.setattr(
        window, "notice", lambda *a, **k: shown.append(a[2]) or type("B", (), {"close": lambda s: None})()
    )
    prof = str(w.profiles / "sandbox.me3")
    base = {"profile": prof, "packs": ["p", "last"], "winner": "last", "backend": "the rebuild tool of last"}
    w.switchTo(w.mods_page)
    w.load_exp.setExpand(False)
    w._on_merge({**base, "state": "current", "text": "Combined parameters are up to date", "reasons": []})
    assert not w.merge_pill.isHidden() and (w.merge_pill.text(), w.merge_pill.level()) == ("Parameters OK", "ok")
    # up to date, and still rebuildable (turning on the launcher's own build, say, changes nothing out of date)
    assert not w.merge_btn.isHidden() and w.merge_btn.text() == "Rebuild" and not w.load_exp.isExpand
    stale = {
        **base,
        "state": "stale",
        "text": "Combined parameters are out of date",
        "reasons": ["regulation.bin: p changed"],
    }
    w._on_merge(stale)
    assert (w.merge_pill.text(), w.merge_pill.level()) == ("Parameters out of date", "bad")
    assert (
        not w.merge_btn.isHidden() and "p changed" in w.merge_reasons.text() and "p changed" in w.merge_pill.toolTip()
    )
    assert "Play updates them first" in w.merge_text.text()
    assert w.load_exp.isExpand  # opened once, when it turned red
    assert shown == ["Combined parameters are out of date"]  # prompted once, on the change
    w.load_exp.setExpand(False)
    w._on_merge(stale)
    assert len(shown) == 1 and not w.load_exp.isExpand  # still red: left as the user set it
    w._on_merge(
        {**base, "state": "stacked", "text": "Several packages ship parameters", "reasons": [], "can_combine": True}
    )
    assert w.merge_pill.text() == "Parameters: 1 of 2 apply" and w.merge_btn.text() == "Combine"
    w._on_merge({**base, "packs": ["p"], "state": "single", "text": "", "reasons": [], "backend": None})
    assert (w.merge_pill.text(), w.merge_pill.level()) == ("Parameters OK", "ok")  # one pack: green
    w._on_merge({**base, "packs": [], "state": "single", "text": "", "reasons": [], "backend": None})
    assert w.merge_pill.isHidden() and w.merge_row.isHidden()  # nothing ships parameters: no pill at all
    QTest.mouseClick(w.merge_pill, Qt.LeftButton)  # hidden: nothing happens


def test_an_install_that_asked_for_it_rebuilds_afterwards(sandbox, monkeypatch, tmp_path):
    from PySide6.QtCore import QEventLoop, QTimer

    from roundtable_souls.platform import logging as run_logging
    from roundtable_souls.platform import paths as common

    monkeypatch.setattr(common, "start_log", lambda *a, **k: None)
    monkeypatch.setattr(run_logging, "log", lambda *a, **k: None)
    rebuilt = []
    tool = type("T", (), {"label": "a tool", "package": {"name": "last"}, "problem": lambda self: None})()
    monkeypatch.setattr(window.core.mod_merge, "find_backend", lambda p: tool)
    monkeypatch.setattr(window.core.mod_merge, "approved", lambda t: True)
    monkeypatch.setattr(
        window.core.mod_merge, "rebuild", lambda p, log, **k: rebuilt.append(p) or {"backend": "m", "profile_note": ""}
    )

    def answer(dlg):
        ok = dlg.validate()
        dlg.plan["merge"] = True  # as if the rebuild box was ticked
        return ok

    monkeypatch.setattr(window.InstallDialog, "exec", answer)
    w = sandbox
    src = tmp_path / "dl" / "Armor"
    (src / "parts").mkdir(parents=True)
    (src / "parts" / "x.partsbnd.dcx").write_bytes(b"p")
    w._install_paths([src])
    loop = QEventLoop()
    for _ in range(200):
        if rebuilt and not w.busy:
            break
        QTimer.singleShot(50, loop.quit)
        loop.exec()
    assert [p.name for p in rebuilt] == ["sandbox.me3"]


def test_options_offer_the_parameter_overlay_switch_for_packages_only(app):
    from PySide6.QtWidgets import QWidget

    from roundtable_souls.ui.dialogs import ModOptionsDialog

    parent = QWidget()
    parent.resize(1000, 800)
    pkg = {"kind": "package", "name": "last", "id": "last", "path": "Merger/mod", "enabled": True}
    dlg = ModOptionsDialog(pkg, [], parent, overlay=False)
    assert dlg.overlay is not None and not dlg.overlay.isChecked()
    nat = {"kind": "native", "name": "x.dll", "path": "natives/x.dll", "enabled": True}
    assert ModOptionsDialog(nat, [], parent).overlay is None
    parent.deleteLater()


def test_a_rebuild_tool_runs_only_after_it_is_allowed_once(sandbox, monkeypatch, tmp_path):
    from test_mod_merge import _declared

    from roundtable_souls.mods import rebuild as merge

    prof = _declared(tmp_path, monkeypatch)
    asked, started = [], []
    monkeypatch.setattr(window, "confirm", lambda *a, **k: asked.append(k.get("detail", "")) or False)
    monkeypatch.setattr(window.Launcher, "start", lambda self, job, status, **k: started.append(status))
    w = sandbox
    w._rebuild_merge(prof)
    assert len(asked) == 1 and "combine.py" in asked[0] and started == []  # declined: nothing runs
    monkeypatch.setattr(window, "confirm", lambda *a, **k: asked.append("again") or True)
    w._rebuild_merge(prof)
    assert started == ["Rebuilding combined parameters..."] and merge.approved(merge.find_backend(prof))
    w._rebuild_merge(prof)
    assert asked.count("again") == 1 and len(started) == 2  # allowed once, not asked again


def test_stacked_packs_offer_combine_on_the_mods_page(sandbox, monkeypatch):
    w = sandbox
    started = []
    monkeypatch.setattr(window.Launcher, "start", lambda self, job, status, **k: started.append(status))
    monkeypatch.setattr(window.core.mod_merge, "health", lambda p: {"state": "stacked", "can_combine": True})
    prof = str(w.profiles / "sandbox.me3")
    w.switchTo(w.mods_page)
    w._on_merge(
        {"profile": prof, "state": "stacked", "text": "Several packages ship parameters", "winner": "b",
         "reasons": [], "backend": None, "can_combine": True}
    )  # fmt: skip
    assert not w.merge_btn.isHidden() and w.merge_btn.text() == "Combine"
    QTest.mouseClick(w.merge_btn, Qt.LeftButton)
    assert started == ["Combining parameters..."]


def test_install_dialog_names_a_combine_when_there_is_no_tool(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from test_mod_merge import World, _pack_source

    from roundtable_souls.mods import install

    world = World(tmp_path, monkeypatch)
    (world.base / "Merger" / "installation.json").unlink()
    world.pack("a")
    plan = install.plan_install(world.profile, _pack_source(tmp_path / "dl"))
    parent = QWidget()
    parent.resize(1000, 800)
    dlg = window.InstallDialog(parent, plan, lambda *a: plan, world.profile)
    assert not dlg.rebuild.isHidden() and dlg.rebuild.text() == "Combine parameters with the other packs after install"
    dlg.reg_place.setCurrentIndex(dlg.reg_place.count() - 1)  # Last: still combined, placement only orders overlaps
    assert not dlg.rebuild.isHidden() and "combined with the other packs" in dlg.reg_effect.text()
    dlg.validate()
    assert plan["merge"] is True
    parent.deleteLater()


def test_the_log_pane_wraps_its_buttons_and_opens_the_logs_folder(sandbox, monkeypatch):
    w = sandbox
    opened = []
    monkeypatch.setattr(window.desktop, "open_path", lambda p: opened.append(p))
    w.switchTo(w.play_page) if hasattr(w, "play_page") else None
    w.log_exp.setExpand(True)
    pane = w.log_pane
    assert pane.folder_btn is not None and pane.folder_btn.text() == "Logs folder"
    QTest.mouseClick(pane.folder_btn, Qt.LeftButton)
    assert opened and opened[0].endswith("logs")
    w.resize(560, 700)  # narrow: the row wraps instead of pushing buttons out of view
    QTest.qWait(200)
    for b in (pane.copy_btn, pane.clear_btn, pane.folder_btn):
        assert b.geometry().right() <= pane.width() + 1, b.text()


def test_a_jobs_lines_reach_the_pane_with_their_level(sandbox, monkeypatch):
    from PySide6.QtCore import QEventLoop, QTimer

    w = sandbox
    seen = []
    real_add = w.log_pane.add
    monkeypatch.setattr(w.log_pane, "add", lambda msg, kind=None: (seen.append((msg, kind)), real_add(msg, kind)))

    def job(_setup):
        window.run_logging.log("working")
        window.run_logging.log("warning: something to know")

    w.start(job, "Testing...", need_setup=False)
    loop = QEventLoop()
    for _ in range(100):
        if not w.busy:
            break
        QTimer.singleShot(50, loop.quit)
        loop.exec()
    assert ("working", "info") in seen and ("warning: something to know", "warning") in seen
    rec = window.core.run_logging.read_jobs()[0]
    assert rec["title"] == "Testing" and rec["outcome"] == "warnings"


def test_changes_made_in_the_window_are_kept_in_the_logs(sandbox):
    from roundtable_souls.platform import logging as rl

    rl.setup_logging(console=False)
    sandbox._log("profile: mem_patch = On")
    rl.shutdown()
    assert "profile: mem_patch = On" in (rl.log_dir() / rl.APP_LOG).read_text(encoding="utf-8")


def _wait_idle(w, loops=100):
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    for _ in range(loops):
        if not w.busy:
            break
        QTimer.singleShot(50, loop.quit)
        loop.exec()


def test_a_failed_job_shows_on_activity_with_a_badge_until_looked_at(sandbox, monkeypatch):
    w = sandbox
    buttons = []
    real_notice = window.notice

    def spy(parent, kind, title, content="", actions=(), **k):
        buttons.extend(b.text() for b in actions)
        return real_notice(parent, kind, title, content, actions=actions, **k)

    monkeypatch.setattr(window, "notice", spy)

    def job(_setup):
        window.run_logging.log("error: the save is locked")
        raise SystemExit(1)

    w.switchTo(w.play_page)
    w.start(job, "Repairing...", need_setup=False)
    _wait_idle(w)
    assert "View in Activity" in buttons
    assert w._activity_badge is not None and w._activity_badge.text() == "1"
    QTest.keyClick(w, Qt.Key_5, Qt.ControlModifier)  # Ctrl+5: Activity
    QTest.qWait(50)
    assert w.stackedWidget.currentWidget() is w.activity_page
    assert w._activity_badge is None  # looked at: the count goes
    rows = w.activity.rows_shown()
    assert rows and rows[0].title.full_text() == "Repairing" and rows[0].pill.text() == "Failed"
    assert rows[0].summary.full_text() == "the save is locked"


def test_activity_entries_fit_a_narrow_window(sandbox):
    from roundtable_souls.platform import logging as rl

    job = rl.begin_job("install mod a very long mod name that would never fit on a narrow window at all")
    window.run_logging.log("done: " + "installed and combined with several other packs " * 3)
    rl.end_job(job)
    w = sandbox
    w.switchTo(w.activity_page)
    w.resize(560, 700)
    QTest.qWait(200)
    row = w.activity.rows_shown()[0]
    row.flip()
    QTest.qWait(100)
    for widget in (row.pill, row.title, row.meta, row.toggle, row.details.copy_btn, row.details.open_btn):
        assert widget.mapTo(row, widget.rect().topRight()).x() <= row.width(), widget
    assert row.title.text().endswith("…") and row.summary.text().endswith("…")  # shortened, full text on hover


def test_the_play_pages_log_links_to_activity(sandbox):
    w = sandbox
    w.switchTo(w.play_page)
    w.log_exp.setExpand(True)
    QTest.mouseClick(w.log_pane.activity_btn, Qt.LeftButton)
    assert w.stackedWidget.currentWidget() is w.activity_page


def test_the_load_order_card_shows_outcomes_from_one_scan(sandbox, tmp_path):
    from roundtable_souls.mods import conflicts as overview

    w = sandbox
    prof = w.profiles / "sandbox.me3"
    for name in ("a", "b"):
        (w.profiles / "mod" / name / "parts").mkdir(parents=True)
        (w.profiles / "mod" / name / "parts" / "am_m_1000.partsbnd.dcx").write_bytes(name.encode())
    prof.write_text(
        prof.read_text(encoding="utf-8")
        + "\n[[packages]]\nid = \"a\"\npath = 'mod/a'\n\n[[packages]]\nid = \"b\"\npath = 'mod/b'\n",
        encoding="utf-8",
    )
    w.switchTo(w.mods_page)
    w._fill_conflicts(overview.overview(prof))
    assert "1 shipped by more than one" in w.conf_note.text() and "1 replaced" in w.conf_note.text()
    assert "a: 1 replaced" in w.conf_packages.text() and "b: used 1" in w.conf_packages.text()
    assert "1 replaced" in w.load_exp.card.contentLabel.text()
    labels = [lab.text() for lab in w.load_exp.findChildren(window.CaptionLabel)]
    assert any("b is used; a replaced" in t for t in labels)
    assert w.problems_head.isHidden()
    w._fill_conflicts({"profile": str(prof), "error": "disk on fire"})
    assert "Could not scan: disk on fire" in w.conf_note.text()


def test_clicking_the_pill_opens_the_load_order(sandbox):
    w = sandbox
    w.switchTo(w.mods_page)
    w.load_exp.setExpand(False)
    prof = str(w.profiles / "sandbox.me3")
    w._on_merge({"profile": prof, "packs": ["p"], "state": "single", "text": "", "reasons": [], "backend": None})
    QTest.mouseClick(w.merge_pill, Qt.LeftButton)
    assert w.load_exp.isExpand
    w.load_exp.setExpand(False)
    w.merge_pill.setFocus()
    QTest.keyClick(w.merge_pill, Qt.Key_Space)  # reachable without a mouse
    assert w.load_exp.isExpand


def _notices(monkeypatch):
    """Capture window notices: [(title, [(button text, button)])]."""
    got = []
    real = window.notice

    def spy(parent, kind, title, content="", actions=(), **k):
        got.append((title, [(b.text(), b) for b in actions]))
        return real(parent, kind, title, content, actions=actions, **k)

    monkeypatch.setattr(window, "notice", spy)
    return got


def test_turning_a_mod_off_offers_undo_and_undo_restores_the_file(sandbox, monkeypatch):
    w = sandbox
    got = _notices(monkeypatch)
    prof = w.profiles / "sandbox.me3"
    before = prof.read_text(encoding="utf-8")
    entry = next(e for e in window.profile_entries(prof) if e["kind"] == "native")
    w._toggle_mod(entry, False)
    assert "enabled = false" in prof.read_text(encoding="utf-8")
    title, buttons = next(n for n in got if "turned off" in n[0])
    undo = dict(buttons)["Undo"]
    QTest.mouseClick(undo, Qt.LeftButton)
    assert prof.read_text(encoding="utf-8") == before
    assert any(t == "Earlier version restored" for t, _ in got)


def test_versions_lists_earlier_copies_and_restores_one(sandbox, monkeypatch):
    w = sandbox
    prof = w.profiles / "sandbox.me3"
    original = prof.read_text(encoding="utf-8")
    entry = next(e for e in window.profile_entries(prof) if e["kind"] == "native")
    monkeypatch.setattr(window, "notice", lambda *a, **k: type("B", (), {"close": lambda s: None})())
    w._toggle_mod(entry, False)
    chosen = []

    def pick(dlg):
        labels = [dlg.list.item(i).text() for i in range(dlg.list.count())]
        chosen.append(labels)
        dlg.list.setCurrentRow(0)
        return True

    monkeypatch.setattr(window.VersionsDialog, "exec", pick)
    w._show_versions()
    assert chosen and "before turning ersc.dll off" in chosen[0][0] and "1 line differs from now" in chosen[0][0]
    assert prof.read_text(encoding="utf-8") == original


def test_removing_a_mod_is_a_job_that_activity_can_restore(sandbox, monkeypatch):
    from roundtable_souls.mods import profile_edit as manage

    w = sandbox
    prof = w.profiles / "sandbox.me3"
    original = prof.read_text(encoding="utf-8")
    monkeypatch.setattr(window, "notice", lambda *a, **k: type("B", (), {"close": lambda s: None})())
    shown = []

    def accept(dlg):
        shown.append((dlg.yesButton.text(), dlg.secondButton.text() if dlg.secondButton else None))
        dlg.choice = "apply"
        return True

    monkeypatch.setattr(window.ConfirmDialog, "exec", accept)
    entry = next(e for e in window.profile_entries(prof) if e["kind"] == "native")
    w._remove_mod(entry)
    _wait_idle(w)
    assert shown[0] == ("Remove", None)  # not inside any combined result: one way to go ahead
    assert not [e for e in manage.entries(prof) if e["kind"] == "native"]
    w.switchTo(w.activity_page)
    row = w.activity.rows_shown()[0]
    assert row.title.full_text() == "Remove ersc.dll" and row.undo_btn is not None and row.undo_btn.text() == "Restore"
    QTest.mouseClick(row.undo_btn, Qt.LeftButton)
    _wait_idle(w)
    assert prof.read_text(encoding="utf-8") == original  # back where it was, comments and all
    assert w.activity.rows_shown()[0].title.full_text() == "Restore ersc.dll"


def test_removing_a_merged_package_says_play_rebuilds_first(sandbox, monkeypatch):
    w = sandbox
    prof = w.profiles / "sandbox.me3"
    (w.profiles / "mod" / "near" / "parts").mkdir(parents=True)
    prof.write_text(
        prof.read_text(encoding="utf-8") + "\n[[packages]]\nid = \"near\"\npath = 'mod/near'\n", encoding="utf-8"
    )
    monkeypatch.setattr(window.Launcher, "_merged_from", lambda self, p, e: ["regulation.bin"])
    monkeypatch.setattr(window, "notice", lambda *a, **k: type("B", (), {"close": lambda s: None})())
    rebuilt, shown = [], []
    monkeypatch.setattr(window.core.mod_merge, "rebuild", lambda p, log, **k: rebuilt.append(p) or {"backend": "t"})
    monkeypatch.setattr(window.core.mod_merge, "find_backend", lambda p: None)

    def accept(dlg):
        shown.append((dlg.yesButton.text(), dlg.secondButton.text() if dlg.secondButton else None))
        dlg.choice = "apply"
        return True

    monkeypatch.setattr(window.ConfirmDialog, "exec", accept)
    entry = next(e for e in window.profile_entries(prof) if e["name"] == "near")
    w._remove_mod(entry)
    _wait_idle(w)
    assert shown[0] == ("Remove", None) and rebuilt == []  # one button; Play (or Rebuild) brings it up to date
    w.game_running = True  # while playing: the same one button
    prof.write_text(
        prof.read_text(encoding="utf-8") + "\n[[packages]]\nid = \"near\"\npath = 'mod/near'\n", encoding="utf-8"
    )
    entry = next(e for e in window.profile_entries(prof) if e["name"] == "near")
    w._remove_mod(entry)
    _wait_idle(w)
    assert shown[1] == ("Remove", None) and rebuilt == []
    w.game_running = False


def test_undo_rebuild_and_redo_from_activity(sandbox, monkeypatch):
    from roundtable_souls.platform import logging as rl

    w = sandbox
    prof = w.profiles / "sandbox.me3"
    kept = w.profiles / "kept.me3"
    kept.write_text("# before the rebuild\n", encoding="utf-8")
    ran = []

    def fake_run(u, log):
        ran.append(bool(u.get("redo")))
        return "undid the rebuild: the profile back as before" if not u.get("redo") else "redid the rebuild"

    monkeypatch.setattr(window.mod_undo, "run", fake_run)
    monkeypatch.setattr(window.mod_undo, "available", lambda u: bool(u))
    monkeypatch.setattr(window, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(window, "notice", lambda *a, **k: type("B", (), {"close": lambda s: None})())
    job = rl.begin_job("rebuild combined parameters")
    rl.set_undo({"type": "rebuild", "profile": str(prof), "profile_before": str(kept)})
    rl.end_job(job)
    w.switchTo(w.activity_page)
    row = w.activity.rows_shown()[0]
    assert row.undo_btn is not None and row.undo_btn.text() == "Undo rebuild"
    QTest.mouseClick(row.undo_btn, Qt.LeftButton)
    _wait_idle(w)
    rows = w.activity.rows_shown()
    assert ran == [False] and rows[0].title.full_text() == "Undo the rebuild"
    assert rows[0].undo_btn is not None and rows[0].undo_btn.text() == "Redo rebuild"
    assert rows[1].undo_btn is None  # the undone rebuild no longer offers it
    QTest.mouseClick(rows[0].undo_btn, Qt.LeftButton)
    _wait_idle(w)
    assert ran == [False, True] and w.activity.rows_shown()[0].title.full_text() == "Redo the rebuild"


def test_install_dialog_places_a_mod_before_the_one_that_must_stay_last(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from test_mod_merge import World, _pack_source

    from roundtable_souls.mods import install

    world = World(tmp_path, monkeypatch)
    plan = install.plan_install(world.profile, _pack_source(tmp_path / "dl"))
    parent = QWidget()
    parent.resize(1000, 800)
    dlg = window.InstallDialog(parent, plan, lambda *a: plan, world.profile)
    assert "Placed before last" in dlg.last_note.text() and not dlg.after_last.isHidden()
    assert dlg.reg_place.isHidden()  # no load order choice to make
    dlg.validate()
    assert plan["insert_before"] == "last" and plan["after_overlay"] is False
    dlg.after_last.setChecked(True)  # the advanced exception
    assert "Loads after last" in dlg.last_note.text() and "last's parameters will not apply" in dlg.reg_effect.text()
    dlg.validate()
    assert plan["after_overlay"] is True and plan["insert_before"] is None
    parent.deleteLater()


def test_the_load_order_card_says_what_loads_after_the_mod_that_must_stay_last(sandbox, monkeypatch):
    w = sandbox
    w.switchTo(w.mods_page)
    w.load_exp.setExpand(False)
    fixed, kept = [], []
    monkeypatch.setattr(window.mod_stay_last, "fix", lambda p: fixed.append(p))
    monkeypatch.setattr(window.mod_stay_last, "keep_after", lambda p, names, keep=True: kept.append((names, keep)))
    st = {"name": "revive", "late": ["hand"], "kept": [], "kept_setting": [], "can_fix": True, "problem": None}
    assert w._fill_stay_last(st) == ["hand"]
    assert "hand loads after revive and replaces its files" in w.last_text.text()
    assert not w.fix_order_btn.isHidden() and not w.keep_after_btn.isHidden() and w.put_before_btn.isHidden()
    assert w.load_exp.isExpand  # opened once for it
    w.fix_order_btn.click()
    assert len(fixed) == 1
    w._fill_stay_last(st)
    w.keep_after_btn.click()
    assert kept[-1] == (["hand"], True)
    w._fill_stay_last({**st, "late": [], "kept": ["hand"], "kept_setting": ["hand"]})
    assert (
        "loads after every other mod" in w.last_text.text() and "Kept after it on purpose: hand" in w.last_text.text()
    )
    assert w.fix_order_btn.isHidden() and not w.put_before_btn.isHidden()
    w.put_before_btn.click()
    assert kept[-1] == (["hand"], False)
    w._fill_stay_last(None)
    assert w.last_row.isHidden()


def _stale_merge(monkeypatch, fail=False):
    """Play sees an out-of-date merge; the update itself is faked (recorded, or failing)."""
    ran = []
    h = {"state": "stale", "text": "Combined parameters are out of date", "reasons": ["p changed"], "backend": "t"}
    h.update(packs=["p", "last"], winner="last")
    monkeypatch.setattr(window.core.mod_merge, "play_check", lambda p: {**h, "blocked": None})

    def update(p, log):
        ran.append(p)
        if fail:
            window.core.mod_merge.note_run(p, False, "the tool refused a file")
            raise window.core.mod_merge.MergeError("the tool refused a file")
        return {"backend": "t", "profile_note": "kept", "undo": None}

    monkeypatch.setattr(window.core.mod_merge, "update_before_play", update)
    return ran


def test_play_updates_the_merged_mods_first_then_starts(sandbox, monkeypatch):
    w = sandbox
    ran = _stale_merge(monkeypatch)
    resumed = []
    assert w._update_first(lambda: resumed.append(1)) is True
    _wait_idle(w)
    for _ in range(5):
        QApplication.processEvents()
    assert len(ran) == 1 and resumed == [1]
    monkeypatch.setattr(window.core.mod_merge, "play_check", lambda p: None)
    assert w._update_first(lambda: resumed.append(2)) is False  # up to date: Play goes straight on


def test_cancel_play_lets_the_update_finish_but_does_not_start(sandbox, monkeypatch):
    w = sandbox
    _stale_merge(monkeypatch)
    resumed = []
    w._update_first(lambda: resumed.append(1))
    w._cancel_update()
    _wait_idle(w)
    for _ in range(5):
        QApplication.processEvents()
    assert resumed == []


def test_a_failed_update_offers_play_anyway_once(sandbox, monkeypatch):
    w = sandbox
    _stale_merge(monkeypatch, fail=True)
    asked = []

    class Answer:
        def __init__(self, title, parent, **k):
            asked.append((title, k.get("apply_text"), k.get("second_text"), k.get("changes")))
            self.choice = "apply"

        def exec(self):
            return True

    monkeypatch.setattr(window, "ConfirmDialog", Answer)
    resumed = []
    w._update_first(lambda: resumed.append(1))
    _wait_idle(w)
    for _ in range(5):
        QApplication.processEvents()
    assert asked and asked[0][1:3] == ("Play anyway", "View details") and "refused" in asked[0][3][0]
    assert resumed == [1]
    assert w._update_first(lambda: None) is False  # Play anyway: this Play starts as it is
    asked.clear()
    # Not tried again with the same inputs this session, but never started silently either: it asks again.
    assert w._update_first(lambda: resumed.append(2)) is True and not w.busy
    for _ in range(5):
        QApplication.processEvents()
    assert asked and asked[0][1:3] == ("Play anyway", "View details") and resumed == [1, 2]


class _Answer:
    """A ConfirmDialog stand-in that records what was asked and answers with `choice`."""

    asked: list = []
    choice = "apply"

    def __init__(self, title, parent, **k):
        _Answer.asked.append((title, k.get("apply_text"), k.get("second_text"), k.get("changes")))
        self.choice = _Answer.choice

    def exec(self):
        return self.choice is not None


def _fresh_play(w):
    """The window is shared between tests: no Play anyway armed, no failed update remembered."""
    w._skip_update_once = False
    w._update_failed = {}


def _answer(monkeypatch, choice):
    _Answer.asked, _Answer.choice = [], choice
    monkeypatch.setattr(window, "ConfirmDialog", _Answer)
    return _Answer.asked


def test_with_automatic_rebuilds_off_play_asks_and_never_starts_silently(sandbox, monkeypatch):
    w = sandbox
    _fresh_play(w)
    ran = _stale_merge(monkeypatch)
    w.settings.play_update_merge = False
    assert not w.play_rows["play_update_merge"].isHidden() or w.game is not window.games.ELDEN_RING
    asked = _answer(monkeypatch, None)  # closed: nothing happens
    resumed = []
    assert w._update_first(lambda: resumed.append(1)) is True and not w.busy and ran == []
    assert asked[0][1:3] == ("Rebuild and play", "Play anyway")
    _answer(monkeypatch, "second")  # Play anyway: this once, with the previous result
    # Play comes back through resume and uses up the "Play anyway" (here: resume asks _update_first, as Play does).
    assert w._update_first(lambda: resumed.append(2 if w._update_first(lambda: None) is False else 0)) is True
    assert ran == []
    for _ in range(5):
        QApplication.processEvents()
    assert resumed == [2]
    _answer(monkeypatch, "apply")  # Rebuild and play
    assert w._update_first(lambda: resumed.append(3)) is True
    _wait_idle(w)
    for _ in range(5):
        QApplication.processEvents()
    assert len(ran) == 1 and resumed == [2, 3]


def test_play_asks_when_the_merged_mods_cannot_be_rebuilt(sandbox, monkeypatch):
    w = sandbox
    _fresh_play(w)
    ran = _stale_merge(monkeypatch)
    h = window.core.mod_merge.play_check(None)
    monkeypatch.setattr(window.core.mod_merge, "play_check", lambda p: {**h, "blocked": "the last package is missing"})
    asked = _answer(monkeypatch, None)
    assert w._update_first(lambda: None) is True and ran == [] and not w.busy
    assert asked[0][1:3] == ("Play anyway", "View details") and "missing" in asked[0][3][1]


def test_play_asks_when_the_rebuild_tool_was_not_allowed(sandbox, monkeypatch):
    w = sandbox
    _fresh_play(w)
    ran = _stale_merge(monkeypatch)
    monkeypatch.setattr(w, "_tool_ready", lambda prof: False)
    asked = _answer(monkeypatch, None)
    assert w._update_first(lambda: None) is True and ran == []
    assert asked[0][1:3] == ("Play anyway", "View details")


def test_play_asks_for_the_update_before_anything_else(sandbox, monkeypatch):
    w = sandbox
    asked = []
    monkeypatch.setattr(w, "_update_first", lambda resume: asked.append(resume) or True)
    started = []
    monkeypatch.setattr(w, "start", lambda *a, **k: started.append(a))
    REAL_LAUNCH(w)
    assert asked and not started  # the update runs first; Play itself comes back through resume


def test_install_mod_opens_one_picker_and_cancel_means_cancel(launcher, monkeypatch):
    w = launcher
    opened, menus, installed = [], [], []
    monkeypatch.setattr(window.QFileDialog, "getOpenFileName", lambda *a, **k: opened.append("file") or ("", ""))
    monkeypatch.setattr(window.QFileDialog, "getExistingDirectory", lambda *a, **k: opened.append("folder") or "")
    monkeypatch.setattr(window.RoundMenu, "exec", lambda self, *a, **k: menus.append(self))
    monkeypatch.setattr(w, "_mods_locked", lambda: False)
    monkeypatch.setattr(w, "_install_paths", lambda paths: installed.append(paths))
    w._install_mod()
    assert not opened and len(menus) == 1  # the click only asks which kind of mod
    file_choice, folder_choice = menus[0].actions()
    file_choice.trigger()
    assert opened == ["file"] and not installed  # cancelled: no second picker, nothing installed
    folder_choice.trigger()
    assert opened == ["file", "folder"] and not installed


def test_an_unapproved_rebuild_tool_is_offered_once_on_the_mods_page(sandbox, monkeypatch):
    w = sandbox
    w._approval_offered = set()
    tool = type(
        "Tool", (), {"label": "the rebuild tool of revive", "package": {"name": "revive"}, "problem": lambda s: None}
    )()
    allowed = {"yes": False}
    monkeypatch.setattr(window.core.mod_merge, "find_backend", lambda p: tool)
    monkeypatch.setattr(window.core.mod_merge, "approved", lambda t: allowed["yes"])
    shown = []
    monkeypatch.setattr(
        window, "notice", lambda *a, **k: shown.append(a[2]) or type("B", (), {"close": lambda s: None})()
    )
    prof = w.profiles / "sandbox.me3"
    w.switchTo(w.play_page)
    w._offer_tool_approval(prof)  # not over another page
    assert shown == []
    w.switchTo(w.mods_page)
    w._offer_tool_approval(prof)
    w._offer_tool_approval(prof)  # once a session
    assert shown == ["Allow the rebuild tool of revive to run?"]
    w._approval_offered = set()
    allowed["yes"] = True  # already allowed: nothing to ask
    w._offer_tool_approval(prof)
    assert len(shown) == 1


def _bars(w):
    from qfluentwidgets import InfoBar

    return [b for b in w.findChildren(InfoBar) if b.isVisible()]


def test_a_failed_check_never_says_up_to_date(sandbox):
    w = sandbox
    check = window.feed.UpdateCheck("offline", reason="GitHub could not be reached (no route)", retry_at=0.0)
    w._on_update({"check": check, "advisory": None, "force": True})
    QTest.qWait(200)
    assert "could not check" in w.launcher_line.text() and "up to date" not in w.launcher_line.text()
    titles = [b.title for b in _bars(w)]
    assert "Could not check" in titles and "Up to date" not in titles
    ok = window.feed.UpdateCheck("fresh", checked=time.time())
    w._on_update({"check": ok, "advisory": None, "force": True})
    QTest.qWait(200)
    assert "up to date" in w.launcher_line.text() and "last checked" in w.launcher_line.text()


def test_unsigned_release_offers_the_releases_page(sandbox, monkeypatch):
    w = sandbox
    monkeypatch.setattr(window, "FROZEN", True)
    offer = {"version": "9.9.9", "url": "https://example.invalid", "notes": "", "assets": {"RoundtableSouls.zip": "u"}}
    w._on_update({"check": window.feed.UpdateCheck("fresh", offer=offer), "advisory": None, "force": False})
    QTest.qWait(200)
    bar = next(b for b in _bars(w) if "9.9.9" in b.title)
    labels = [b.text() for b in bar.findChildren(QPushButton)]
    assert "Download" in labels and "Update now" not in labels and "Notes" in labels


def test_advisory_warns_once(sandbox):
    w = sandbox
    adv = {"minimum": "99.0.0", "message": "Known crash.", "url": ""}
    for _ in range(2):
        w._on_update({"check": window.feed.UpdateCheck("fresh"), "advisory": adv, "force": False})
    QTest.qWait(200)
    assert sum("should be updated" in b.title for b in _bars(w)) == 1


def test_update_outcomes_are_reported_once_at_start(sandbox):
    w = sandbox
    w._on_update_outcome({"status": "failed", "version": "9.9.9", "error": "The update did not finish installing."})
    QTest.qWait(200)
    bar = next(b for b in _bars(w) if "did not finish" in b.title)
    labels = [b.text() for b in bar.findChildren(QPushButton)]
    assert "Try again" in labels and "Releases" in labels and "did not finish installing" in bar.content
    assert window.load_settings().update_result is None  # shown once
    w._on_update_outcome({"status": "rolled_back", "version": "9.9.8", "error": "it did not finish starting"})
    QTest.qWait(200)
    bar = next(b for b in _bars(w) if "was put back" in b.title)
    assert "not offered again" in bar.content and "Try again" not in [b.text() for b in bar.findChildren(QPushButton)]


def test_update_is_refused_while_a_shortcut_play_runs(sandbox, monkeypatch):
    w = sandbox
    monkeypatch.setattr(window.updates, "busy_reason", lambda: "A Play started from a Steam shortcut is still running.")
    started = []
    monkeypatch.setattr(window.updates, "download_update", lambda *a, **k: started.append(1))
    bar = window.notice(w, "info", "x")
    w._start_update({"version": "9.9.9", "assets": {}}, bar)
    QTest.qWait(200)
    assert not started and any("Cannot update now" == b.title for b in _bars(w))


def test_a_steam_shortcut_play_is_run_by_the_open_window(sandbox, monkeypatch):
    w = sandbox
    launched = []
    monkeypatch.setattr(window.Launcher, "launch", lambda self: launched.append(self.game.key))
    w._on_instance_message("play nightreign")
    QTest.qWait(300)
    assert launched == ["nightreign"] and w.game.key == "nightreign"
    w._on_instance_message("rm -rf")  # anything else is ignored
    QTest.qWait(100)
    assert launched == ["nightreign"]


def test_the_load_order_card_says_when_me3_is_older_than_the_order_checked(sandbox):
    w = sandbox
    w._me3 = {"version": "0.13.0"}
    assert w._order_unverified() is None
    w._me3 = {"version": "0.9.2"}
    assert "not checked for me3 0.9.2" in w._order_unverified()
    w._me3 = {}
    assert w._order_unverified() is None  # unknown: nothing to say
