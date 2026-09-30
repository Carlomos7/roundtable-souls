"""The real window, offscreen: keyboard safety at start, page shortcuts, and layouts that fit a narrow window."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtTest = pytest.importorskip("PySide6.QtTest")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from roundtable_souls.system import common as _common  # noqa: E402
from roundtable_souls.ui import window  # noqa: E402

REAL_SAVE_FILES = _common.save_files

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


SANDBOX_PROFILE = (
    'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n\n'
    "[[natives]]\npath = 'natives/SeamlessCoop/ersc.dll'\nload_early = true\n"
)
SANDBOX_INI = "[PASSWORD]\ncooppassword = start\n[SCALING]\nenemy_health_scaling = 35\n"


@pytest.fixture
def sandbox(app, monkeypatch, tmp_path):
    """The real window pointed at a temp me3 profile and co-op ini, with no saves, so tests can type and save."""
    from roundtable_souls.system import common

    profiles = tmp_path / "profiles"
    seamless = profiles / "natives" / "SeamlessCoop"
    seamless.mkdir(parents=True)
    (seamless / "ersc.dll").write_bytes(b"d")
    (seamless / "ersc_settings.ini").write_text(SANDBOX_INI, encoding="utf-8")
    (profiles / "sandbox.me3").write_text(SANDBOX_PROFILE, encoding="utf-8")
    monkeypatch.setattr(common, "me3_profiles_dir", lambda: profiles)
    monkeypatch.setattr(common, "save_files", lambda game=None: [])
    monkeypatch.setattr(window, "launcher_update", lambda *a, **k: None)
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
    monkeypatch.setattr(window, "can_self_update", lambda *a, **k: True)
    w.resize(740, 640)
    QTest.qWait(100)
    w._on_update({"version": "9.9.9", "url": "https://example.invalid"})
    QTest.qWait(400)
    from qfluentwidgets import InfoBar

    bars = [b for b in w.findChildren(InfoBar) if b.isVisible()]
    assert bars and all(b.width() <= w.width() for b in bars)


def test_saves_page_names_the_file_play_uses_and_lists_the_library(sandbox, monkeypatch, tmp_path):
    from PySide6.QtCore import QEventLoop, QTimer

    from roundtable_souls import games
    from roundtable_souls.saves import library, regulation
    from roundtable_souls.system import common

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
    from roundtable_souls.mods import manage

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
    from roundtable_souls.mods import manage

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

    from roundtable_souls.mods import manage
    from roundtable_souls.system import common

    monkeypatch.setattr(common, "start_log", lambda *a, **k: None)  # the job's log stays out of the real logs folder
    monkeypatch.setattr(common, "log", lambda *a, **k: None)
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

    from roundtable_souls.mods import manage

    world = World(tmp_path, monkeypatch)
    plan = manage.plan_install(world.profile, _pack_source(tmp_path / "dl"))
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


def test_merge_health_shows_on_the_mods_page_and_prompts_when_it_goes_stale(sandbox, monkeypatch):
    w = sandbox
    shown = []
    monkeypatch.setattr(
        window, "notice", lambda *a, **k: shown.append(a[2]) or type("B", (), {"close": lambda s: None})()
    )
    prof = str(w.profiles / "sandbox.me3")
    base = {"profile": prof, "packs": ["p", "last"], "winner": "last", "backend": "the rebuild tool of last"}
    w.switchTo(w.mods_page)
    w._on_merge({**base, "state": "current", "text": "Combined parameters are up to date", "reasons": []})
    assert not w.merge_row.isHidden() and w.merge_btn.isHidden()
    stale = {
        **base,
        "state": "stale",
        "text": "Combined parameters are out of date",
        "reasons": ["regulation.bin: p changed"],
    }
    w._on_merge(stale)
    assert not w.merge_btn.isHidden() and "p changed" in w.merge_text.text()
    assert shown == ["Combined parameters are out of date"]  # prompted once, on the change
    w._on_merge(stale)
    assert len(shown) == 1
    w._on_merge({**base, "state": "single", "text": "", "reasons": [], "backend": None})
    assert w.merge_row.isHidden()


def test_an_install_that_asked_for_it_rebuilds_afterwards(sandbox, monkeypatch, tmp_path):
    from PySide6.QtCore import QEventLoop, QTimer

    from roundtable_souls.system import common

    monkeypatch.setattr(common, "start_log", lambda *a, **k: None)
    monkeypatch.setattr(common, "log", lambda *a, **k: None)
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

    from roundtable_souls.mods import merge

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

    from roundtable_souls.mods import manage

    world = World(tmp_path, monkeypatch)
    (world.base / "Merger" / "installation.json").unlink()
    world.pack("a")
    plan = manage.plan_install(world.profile, _pack_source(tmp_path / "dl"))
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
    monkeypatch.setattr(window.core.common, "open_path", lambda p: opened.append(p))
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
        window.core.common.log("working")
        window.core.common.log("warning: something to know")

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
    from roundtable_souls.system import logging as rl

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
        window.core.common.log("error: the save is locked")
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
    from roundtable_souls.system import logging as rl

    job = rl.begin_job("install mod a very long mod name that would never fit on a narrow window at all")
    window.core.common.log("done: " + "installed and combined with several other packs " * 3)
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
