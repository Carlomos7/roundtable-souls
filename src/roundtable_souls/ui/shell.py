"""The window (PySide6 + Fluent Widgets): the shell. What the window does is in services/; the window is handed the
app context (app.create_app) and runs background work through ui/jobs.py.

The shell holds the title bar, the game switcher, the navigation rail, the Activity page, the job status and what
every page shares; each page's widgets and handlers are its view in ui/pages/<page>/view.py, a mixin Launcher
inherits. Game tabs pick the game every page works on (Elden Ring, Nightreign; Dark Souls III and Sekiro are
placeholders until their support lands). Settings is shared by all games.

Pages (navigation rail on the left):
  Play    who you are (from the save), which setup, one big Play button, one line saying what will happen
  Co-op   Seamless Co-op password, difficulty, and a save bar that stays on screen
  Mods    the profile's mods, their order and options, installs, merge health
  Saves   the save files and the characters in them, backups, the library, the review page
  Tools   locations, me3, Play session, appearance, updates (shown as Settings)

    roundtable-souls              the window
    roundtable-souls --check      print what would be used and exit (no window)
    roundtable-souls --shots D    render every page to PNG files in folder D, for review"""

from __future__ import annotations

import datetime
import os
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWidgets import QPushButton as QPushBtn
from qfluentwidgets import (
    Action,
    BodyLabel,
    FluentWindow,
    InfoBadge,
    InfoBadgePosition,
    NavigationItemPosition,
    Theme,
    TitleLabel,
    isDarkTheme,
    setTheme,
    setThemeColor,
)
from qfluentwidgets import FluentIcon as FI

from roundtable_souls.game import catalog as games
from roundtable_souls.game.locate import Locations, installed_dir
from roundtable_souls.platform import data_folder, desktop, instance
from roundtable_souls.resources import ASSETS_DIR
from roundtable_souls.services import play as core
from roundtable_souls.services.play import (
    TITLE,
    VERSION,
    discover,
    job_clear,
    logo_path,
    play_command,
    remember_setup,
    remembered_setup,
    report_exception,
    route_logs,
    steam_state,
)
from roundtable_souls.services.saves import (
    dead_shells_count,
)
from roundtable_souls.services.settings import (
    load_settings,
    save_settings,
)
from roundtable_souls.ui.dialogs.activity import ActivityView
from roundtable_souls.ui.dialogs.common import (
    ask_unsaved,
    confirm,
)
from roundtable_souls.ui.jobs import Jobs
from roundtable_souls.ui.pages.coop.view import CoopView
from roundtable_souls.ui.pages.mods.view import ModsView
from roundtable_souls.ui.pages.play.view import PlayView
from roundtable_souls.ui.pages.saves.view import SavesView
from roundtable_souls.ui.pages.tools.view import ToolsView
from roundtable_souls.ui.theme import (
    ACCENT,
    ACCENT_LIGHT,
    BG_DARK,
    BG_LIGHT,
    COMPACT,
    ghost_btn,
    hint,
    style_button,
    style_ghost,
    tokens,
    tone_label,
    use_theme_text,
)
from roundtable_souls.ui.widgets.cards import ExpandGroupSettingCard, GlassCard, card, count_label
from roundtable_souls.ui.widgets.layout import (
    action_row,
    clear_layout,
    page,
    refresh_surfaces,
    style_navigation,
    titled,
)
from roundtable_souls.ui.widgets.log import Bus, tidy_log_line
from roundtable_souls.ui.widgets.menus import MenuButton, StatusMenu
from roundtable_souls.ui.widgets.notices import StatusPill, notice
from roundtable_souls.ui.widgets.panels import ActionBar
from roundtable_souls.updates import apply as updates
from roundtable_souls.updates import inno as migration


# ----------------------------------------------------------------------------- window
class Launcher(PlayView, CoopView, ModsView, SavesView, ToolsView, FluentWindow):
    def __init__(self, ctx):
        """ctx: the app context (app.create_app); the window shows its game and is handed its locations."""
        super().__init__()
        data_folder.clear_temp()  # unpacks left by an install that crashed
        self.ctx = ctx
        self.settings = self.ctx.settings
        self.game = self.ctx.game
        self.bus = Bus()
        self.jobs = Jobs(self)
        self.busy = False
        self.game_running = False
        self.steam_bar = None
        self.steam_bad_since = None
        self.shells_bar = None
        self._toast_bar = None
        self._loading_setups = False
        self.saves_badge = None
        self._undo = None
        self._backups_all = False
        self.setups = (
            discover(remembered_setup(self.settings, self.game), self.ctx.locations) if self.game.ready else []
        )
        self.setup = None
        self.ini = None
        self.pw_file = None
        self.scaling_file = None
        self.saves = []
        self.setWindowTitle(f"{TITLE} {VERSION}")
        self.resize(1080, 760)
        self.setMinimumSize(720, 540)
        self._apply_logo()
        self.navigationInterface.setExpandWidth(190)
        self.navigationInterface.setMinimumExpandWidth(820)  # rail stays open with page names at normal window sizes
        self.navigationInterface.setReturnButtonVisible(False)  # flat pages; Back only repeated the last nav click
        self.navigationInterface.setAcrylicEnabled(True)
        try:
            self.setMicaEffectEnabled(False)
        except Exception:
            pass
        self.setCustomBackgroundColor(BG_LIGHT, BG_DARK)
        self._build_play()
        self._build_coop()
        self._build_mods()
        self._build_saves()
        self._build_tools()
        self._build_workshop()
        self._build_activity()
        self.addSubInterface(self.play_page, FI.PLAY, "Play")
        self.addSubInterface(self.coop_page, FI.PEOPLE, "Co-op")
        self.addSubInterface(self.mods_page, FI.LIBRARY, "Mods")
        self.addSubInterface(self.saves_page, FI.SAVE, "Saves")
        self.addSubInterface(self.activity_page, FI.HISTORY, "Activity")
        self.addSubInterface(self.tools_page, FI.SETTING, "Settings", NavigationItemPosition.BOTTOM)
        self._build_placeholder()
        self._build_game_tabs()
        style_navigation(self.navigationInterface)
        # Keyboard: Ctrl+1..6 open the pages in rail order. Nothing has focus at start,
        # so a stray Enter or Space when the window appears cannot press Play.
        self.setFocusPolicy(Qt.StrongFocus)
        for n, target in enumerate(
            (self.play_page, self.coop_page, self.mods_page, self.saves_page, self.activity_page, self.tools_page),
            start=1,
        ):
            nav = QShortcut(QKeySequence(f"Ctrl+{n}"), self)
            nav.activated.connect(lambda pg=target: self._shortcut_page(pg))
        sc = QShortcut(QKeySequence("Ctrl+S"), self)
        sc.activated.connect(self._shortcut_save)
        self.bus.line.connect(self._on_line)
        self._update_bar = None
        self._offered = None  # the version the update notice shows
        self._instance_hold = None
        self._instance_server = None
        self.stackedWidget.currentChanged.connect(self._on_page_changed)
        self.bus.merge.connect(self._on_merge)  # a health result on its own (the overview scan sends it too)
        core.NOTIFY = lambda title, msg: notice(self, "error", title, msg)
        sys.excepthook = lambda t, e, tb: report_exception(t, e, tb, "main thread")
        threading.excepthook = lambda a: report_exception(
            a.exc_type, a.exc_value, a.exc_traceback, f"thread {a.thread.name}"
        )
        self._fill_setups()
        self._apply_game_ui()
        if self.game.ready:
            self.refresh_saves()
        else:
            QTimer.singleShot(0, lambda: self._set_game(self.game))  # opens the placeholder page
        self._watch_game()
        self._update_activity_badge()
        self._refresh_me3()
        self._check_launcher_update()
        QTimer.singleShot(0, lambda: (self.navigationInterface.expand(useAni=False), self._restyle(), self._relayout()))

    # ---------------------------------------------------------------- game tabs
    def _base_title(self):
        return f"{TITLE} {VERSION} - {self.game.name}"

    def _shortcut_page(self, pg):
        """Ctrl+1..6. A game without support yet only has its placeholder, Activity and Settings."""
        if self.game.ready or pg in (self.tools_page, self.activity_page):
            self.switchTo(pg)

    def _build_game_tabs(self):
        """A compact switcher in the title bar: one button showing the current game and its dot, opening a menu of
        every game with its status. The label beside it stays the app name; the window title carries the game."""
        bar = self.titleBar
        try:
            self.windowTitleChanged.disconnect(bar.setTitle)
        except RuntimeError, TypeError:
            pass
        bar.titleLabel.setText(TITLE)
        self.game_btn = MenuButton(self.game.name, bar)
        self.game_btn.fit_texts(g.name for g in games.GAMES)
        self.game_btn.setMenu(self._game_menu())
        self._sync_game_btn()
        sep = QFrame(bar)
        sep.setFixedSize(1, 16)
        sep.setStyleSheet("background: rgba(196, 160, 106, 90); border: none;")  # a faint gold hairline
        at = bar.hBoxLayout.indexOf(bar.titleLabel)
        bar.hBoxLayout.insertSpacing(at + 1, 14)
        bar.hBoxLayout.insertWidget(at + 2, sep, 0, Qt.AlignVCenter)
        bar.hBoxLayout.insertSpacing(at + 3, 14)
        bar.hBoxLayout.insertWidget(at + 4, self.game_btn, 0, Qt.AlignVCenter)
        # Ctrl+Tab / Ctrl+Shift+Tab cycle games; the button and menu still work with the mouse.
        QShortcut(QKeySequence("Ctrl+Tab"), self, activated=lambda: self._cycle_game(1))
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, activated=lambda: self._cycle_game(-1))

    def _game_menu(self):
        """The switcher's drop-down: every game with its dot, a check on the current one, and its status
        (installed / not installed for ready games, 'coming soon' for the rest) right-aligned in one column."""
        self._game_menu_view = menu = StatusMenu(parent=self)
        self._game_actions = {}
        for g in games.GAMES:
            act = Action(g.name, self)
            # Qt flips the check on click before we decide (a cancelled switch, or the current game): resync after.
            act.triggered.connect(lambda _=False, k=g.key: (self._on_game_tab(k), self._sync_game_btn()))
            menu.add_choice(act, g.tint)
            self._game_actions[g.key] = act
        return menu

    def _game_status(self, g) -> str:
        if not g.ready:
            return "coming soon"
        if installed_dir(g):
            return "installed"
        return "not installed"

    def _sync_game_btn(self):
        """Point the switcher button at the active game, and refresh each menu row's dot, check and status."""
        if getattr(self, "game_btn", None) is None:
            return
        compact = getattr(self, "_compact", False)
        self.game_btn.set_choice(self.game.short if compact else self.game.name, self.game.tint)
        self.game_btn.setToolTip(f"{self.game.name} — click to switch game (Ctrl+Tab)")
        for g in games.GAMES:
            self._game_actions[g.key].setChecked(g is self.game)
        self._game_menu_view.set_statuses({self._game_actions[g.key]: self._game_status(g) for g in games.GAMES})

    def _cycle_game(self, step):
        if self.busy:
            return
        order = [g.key for g in games.GAMES]
        nxt = order[(order.index(self.game.key) + step) % len(order)]
        self._on_game_tab(nxt)

    def _on_game_tab(self, key):
        g = games.get(key)
        if g is self.game:
            return
        if self.busy:
            self._toast("Wait for the current job", "Switch games once it finishes.", info=True)
            return
        if self.game.ready and not self._settle_unsaved(f"switching to {g.name}"):
            return
        self._set_game(g, remember=True)

    def _set_game(self, g, remember=False):
        """Point every page at another game: its setups, co-op ini, mods, saves and running checks."""
        # Remember which page the game we are leaving was on, so switching back returns there.
        self._game_last_page = getattr(self, "_game_last_page", {})
        game_pages = (self.play_page, self.coop_page, self.mods_page, self.saves_page)
        if self.game.ready and self.stackedWidget.currentWidget() in game_pages:
            self._game_last_page[self.game.key] = self.stackedWidget.currentWidget().objectName()
        on_settings = self.stackedWidget.currentWidget() is self.tools_page
        if remember:
            save_settings(game=g.key)
        self.ctx.select_game(g)
        self.settings, self.game = self.ctx.settings, self.ctx.game
        self._sync_game_btn()
        self.game_running = False
        for bar_name in ("shells_bar",):
            bar = getattr(self, bar_name, None)
            if bar is not None:
                try:
                    bar.close()
                except Exception:
                    pass
                setattr(self, bar_name, None)
        # Show the destination page at once so the switch feels instant; the per-page fills below then populate it.
        # Land on the page this game was last on (default Play); Settings is shared, so stay there if that is open.
        if g.ready and not on_settings:
            want = self._game_last_page.get(g.key)
            target = {p.objectName(): p for p in game_pages}.get(want, self.play_page)
            self.switchTo(target)
        self.setups = discover(remembered_setup(self.settings, g), self.ctx.locations) if g.ready else []
        self._fill_setups()
        self._apply_game_ui()
        loc = self.ctx.locations
        self.jobs.start(lambda _progress: loc.game_running(), on_result=self._on_running)
        if g.ready:
            self.refresh_saves()
        else:
            self._update_saves_badge(0)
            self.switchTo(self.placeholder_page)
            try:  # the placeholder has no rail entry: leave none highlighted
                panel = self.navigationInterface.panel
                for item in panel.items.values():
                    item.widget.setSelected(False)
                panel._currentRouteKey = None
            except Exception:
                pass

    def _apply_game_ui(self):
        """Everything on screen that names or depends on the active game."""
        g = self.game
        self.setWindowTitle(self._base_title())
        for pg in (self.play_page, self.coop_page, self.mods_page, self.saves_page):
            try:
                self.navigationInterface.widget(pg.objectName()).setEnabled(g.ready)
            except Exception:
                pass
        self.repair_row.setVisible(g.regulation_repair)
        self.play_rows["play_repair_after"].setVisible(g.regulation_repair)
        self.play_rows["play_update_merge"].setVisible(g is games.ELDEN_RING)
        self.play_rows["build_merges"].setVisible(g is games.ELDEN_RING)
        self.off_revive_row.setVisible(g is games.ELDEN_RING)
        target, options = play_command(g)
        self.shortcut_fields["Target"].setText(target)
        self.shortcut_fields["Launch options"].setText(options)
        self.shortcut_hint.setText(
            f"Play {g.name} without opening this window: add Roundtable Souls to Steam as a non-Steam game with the "
            "launch options below (one shortcut per game). It uses the setup Play last used for that game"
            + (", repairs the saves after you quit," if g.regulation_repair else ",")
            + " then closes. Handy in Big Picture and on Steam Deck in Gaming Mode."
        )
        value = self._location_value("game_exe")
        self.loc["game_exe"].setText(value or "detected")
        self.loc["game_exe"].setToolTip(value)
        self.savefile_edit.setPlaceholderText(f"{g.save_stem}.sl2 (default)")
        if not g.ready:
            self._fill_placeholder(g)

    def _build_placeholder(self):
        """The page a game without support yet shows: what Roundtable Souls found for it, and nothing to press
        that could touch its files."""
        self.placeholder_page, lay = page("placeholderPage")
        self.ph_title = TitleLabel("")
        lay.addWidget(self.ph_title)
        self.ph_intro = hint("")
        lay.addWidget(self.ph_intro)
        c, cl = card("Found on this PC", FI.SEARCH)
        self.ph_rows = QVBoxLayout()
        self.ph_rows.setSpacing(8)
        cl.addLayout(self.ph_rows)
        row_w, row = action_row()
        self.ph_game_btn = ghost_btn("Game folder", FI.GAME)
        self.ph_game_btn.clicked.connect(lambda: desktop.open_path(self.ph_game_btn.toolTip()))
        row.addWidget(self.ph_game_btn)
        self.ph_saves_btn = ghost_btn("Saves folder", FI.FOLDER)
        self.ph_saves_btn.clicked.connect(lambda: desktop.open_path(self.ph_saves_btn.toolTip()))
        row.addWidget(self.ph_saves_btn)
        cl.addWidget(row_w)
        lay.addWidget(c)
        lay.addStretch(1)
        self.stackedWidget.addWidget(self.placeholder_page)

    def _fill_placeholder(self, g):
        loc = Locations.from_settings(self.settings, g)
        self.ph_title.setText(g.name)
        self.ph_intro.setText(
            f"Support for {g.name} is coming. Play, co-op, mods and saves stay off on this tab until then, so "
            "nothing here can change its files. Pick Elden Ring or Nightreign at the top to use the launcher."
        )
        clear_layout(self.ph_rows)
        game_dir = installed_dir(g)
        saves = loc.save_files()
        profiles = loc.me3_profiles()
        rows = (
            ("Game", str(game_dir) if game_dir else "Not found in any Steam library."),
            ("Saves", f"{count_label(len(saves), 'save file')} in {saves[0].parent}" if saves else "None found."),
            ("me3 profiles", ", ".join(p.name for p in profiles) if profiles else "None made for this game yet."),
        )
        for label, value in rows:
            line = BodyLabel(f"{label}:  {value}")
            line.setWordWrap(True)
            self.ph_rows.addWidget(line)
        self.ph_game_btn.setEnabled(bool(game_dir))
        self.ph_game_btn.setToolTip(str(game_dir or ""))
        self.ph_saves_btn.setEnabled(bool(saves))
        self.ph_saves_btn.setToolTip(str(saves[0].parent) if saves else "")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()

    def _relayout(self):
        if not hasattr(self, "hero") or not hasattr(self, "coop_head"):
            return
        compact = self.width() < COMPACT
        if compact == getattr(self, "_compact", None):
            return
        self._compact = compact
        self.hero.set_compact(compact)
        if getattr(self, "game_btn", None) is not None:
            self.game_btn.fit_texts((g.short if compact else g.name) for g in games.GAMES)
            self._sync_game_btn()
        self._layout_scaling(2 if compact else 3)
        self._set_pads(compact)
        if hasattr(self, "ws_body_lay"):
            self._ws_layout(compact)
        self.log.setMinimumHeight(140 if compact else 180)
        self.profile_edit.setMinimumHeight(200 if compact else 320)

    def _set_pads(self, compact):
        m = (18, 16, 18, 18) if compact else (40, 28, 40, 36)
        sp = 12 if compact else 20
        for area in (self.play_page, self.mods_page, self.saves_page, self.tools_page, self.coop_scroll):
            inner = area.widget()
            if inner is not None and inner.layout() is not None:
                inner.layout().setContentsMargins(*m)
                inner.layout().setSpacing(sp)
        self.coop_head.layout().setContentsMargins(m[0], m[1], m[2], 8)
        self.coop_bar.layout().setContentsMargins(m[0], 8, m[2], 16 if compact else 20)
        self.coop_scroll.widget().layout().setContentsMargins(m[0], 12, m[2], 16)

    # ---------------------------------------------------------------- one window
    def _take_instance(self, hold=None):
        """Hold the window's name and answer second starts: show (come forward) or play <game> (a Steam shortcut)."""
        from PySide6.QtNetwork import QLocalServer

        self._instance_hold = hold or self._instance_hold or instance.acquire(instance.WINDOW)
        if self._instance_server is not None:
            return
        name = instance.server_name()
        QLocalServer.removeServer(name)  # only a crashed window's leftover (Linux): we hold the name, none is live
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        server.newConnection.connect(self._on_instance_connection)
        if server.listen(name):
            self._instance_server = server
        else:
            server.deleteLater()

    def _release_instance(self):
        if self._instance_server is not None:
            self._instance_server.close()
            self._instance_server.deleteLater()
            self._instance_server = None
        if self._instance_hold is not None:
            self._instance_hold.release()
            self._instance_hold = None

    def _on_instance_connection(self):
        server = self._instance_server
        while server is not None and (sock := server.nextPendingConnection()) is not None:
            buf = bytearray()

            def read(s=sock, b=buf):
                b.extend(bytes(s.readAll().data()))
                while b"\n" in b:
                    line, _, rest = bytes(b).partition(b"\n")
                    b[:] = rest
                    self._on_instance_message(line.decode("utf-8", "replace").strip())

            sock.readyRead.connect(read)
            sock.disconnected.connect(sock.deleteLater)
            if sock.bytesAvailable():
                read()

    def _on_instance_message(self, message):
        word, _, arg = message.partition(" ")
        if word not in ("show", "play"):
            return
        self._bring_forward()
        if word == "play":
            QTimer.singleShot(0, lambda: self._play_requested(arg))

    def _bring_forward(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def _play_requested(self, arg):
        """A Steam shortcut (--play) started while this window is open: Play here, for that game. "<key>
        allow-without-backup" (--allow-without-backup): a failed backup before Play doesn't stop it."""
        key, _, flag = arg.partition(" ")
        g = games.get(key)
        if self.busy or self.game_running:
            self._toast("Play from Steam ignored", f"{self.game.name} or a job is already running here.", error=True)
            return
        if g.key != self.game.key:
            if not self._settle_unsaved(f"switching to {g.name}"):
                return
            self._set_game(g, remember=True)
        self._allow_without_backup_once = flag == "allow-without-backup"
        self.launch()

    def after_show(self):
        """For a real start only (tests build the window without it): tell an update's watchdog this version is up,
        report how the last update went, finish the move from the old installer, and tidy old downloads."""
        confirmed = updates.mark_ready("window")
        self.ctx.start_imports()  # after the ready report: the imports may take a while and never delay it

        def work(report):
            outcome = confirmed or updates.update_outcome()
            report(outcome or {})
            pending = (load_settings().update_pending or {}).get("version")
            try:
                updates.clean_downloads(keep=pending)
            except Exception:
                pass
            try:
                return migration.migrate_from_inno() or {}
            except Exception as e:
                return {"status": "failed", "reason": str(e)}

        self.jobs.start(
            work, on_result=self._on_migration, on_progress=self._on_update_outcome, name="launcher-start-tasks"
        )

    # ---------------------------------------------------------------- jobs
    def _log(self, msg):
        """A line about something done in the window itself: shown in the pane and kept in the logs."""
        self.bus.line.emit(str(msg), "")
        core.run_logging.log_shown(msg)

    def _sink(self, msg, level=""):
        """Lines from the logging layer (the running job, and warnings from anywhere), for the pane."""
        self.bus.line.emit(str(msg), level or "")

    # -------------------------------------------------------------- activity
    def _build_activity(self):
        self.activity_page, lay = page("activityPage")
        acts, al = action_row()
        refresh = ghost_btn("Refresh", FI.SYNC)
        refresh.clicked.connect(lambda: self.activity.refresh())
        folder = ghost_btn("Logs folder", FI.FOLDER)
        folder.setToolTip("Every job's log, other programs' output kept with them, and launcher.log.")
        folder.clicked.connect(self._open_logs)
        share = ghost_btn("Save logs for support...", FI.ZIP_FOLDER)
        share.setToolTip(
            "A zip of the logs folder with your user name and Steam IDs masked, to attach to a report. Nothing is "
            "sent anywhere."
        )
        share.clicked.connect(self._save_logs_for_support)
        for b in (refresh, folder, share):
            al.addWidget(b)
        titled(
            lay,
            "Activity",
            FI.HISTORY,
            "What the launcher did: every Play, repair, install and rebuild, with how it went and its full log.",
            acts,
        )
        self.activity = ActivityView(on_undo=self._run_undo)
        lay.addWidget(self.activity)
        lay.addStretch(1)
        self._activity_badge = None

    def _on_page_changed(self, *_):
        if self.stackedWidget.currentWidget() is self.activity_page:
            self.activity.refresh()
            self._mark_activity_seen()
        if self.stackedWidget.currentWidget() is self.mods_page and self.setup and self.setup.profile:
            self._offer_tool_approval(Path(self.setup.profile))

    def _open_activity(self, failed_only=False):
        self.activity.failed_only.setChecked(failed_only)
        self.switchTo(self.activity_page)
        self.activity.refresh()

    def _mark_activity_seen(self):
        save_settings(activity_seen=time.time())
        self.settings = load_settings()
        self._update_activity_badge()

    def _update_activity_badge(self):
        """A red count on the Activity item for jobs that failed since the page was last looked at."""
        seen = float(load_settings().activity_seen or 0.0)
        count = len(core.run_logging.unseen_failures(seen))
        if self._activity_badge is not None:
            try:
                self._activity_badge.close()
                self._activity_badge.deleteLater()
            except RuntimeError:
                pass
            self._activity_badge = None
        item = self.navigationInterface.widget(self.activity_page.objectName())
        if count and item is not None:
            self._activity_badge = InfoBadge.error(
                str(count) if count < 100 else "99+",
                parent=item.parent(),
                target=item,
                position=InfoBadgePosition.NAVIGATION_ITEM,
            )
            self._activity_badge.setToolTip(f"{count} job{'s' if count != 1 else ''} failed since you last looked")
        if item is not None:
            item.setToolTip(f"Activity: {count} failed since you last looked" if count else "Activity")

    def _save_logs_for_support(self):
        import shutil
        import tempfile

        where = QFileDialog.getExistingDirectory(self, "Save logs for support: pick a folder", str(Path.home()))
        if not where:
            return
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                core.run_logging.copy_logs(Path(tmp) / "logs")
                out = shutil.make_archive(str(Path(where) / f"roundtable-souls-logs-{stamp}"), "zip", tmp)
        except OSError as e:
            self._toast("Could not save the logs", str(e), error=True)
            return
        self._toast("Logs saved", f"{Path(out).name}: user names and Steam IDs are masked.", info=True)

    def _open_logs(self):
        d = core.run_logging.log_dir()
        try:
            d.mkdir(parents=True, exist_ok=True)
            desktop.open_path(str(d))
        except OSError as e:
            self._toast("Could not open the logs folder", str(e), error=True)

    def _on_line(self, msg, level=""):
        self.log_pane.add(msg, kind=level or None)
        if self.log_pane.last_level() == "error":
            self.log_exp.setExpand(True)
        shown = tidy_log_line(str(msg))
        low = shown.lstrip().lower()
        if low.startswith(
            (
                "steam:",
                "launching",
                "game ",
                "regulation",
                "done:",
                "password",
                "no dead",
                "dead ",
                "scaling",
                "applied",
            )
        ):
            self.status.setText(shown.splitlines()[0][:120])

    def _pill(self, text, level):
        self.ready.setText(text)
        tone_label(self.ready, level)

    def set_busy(self, busy, status=None):
        if busy:
            self._pill("Running", "accent")
        self.busy = busy
        self.play_btn.setEnabled(
            not busy and not self.game_running and self.setup is not None and not self.setup.problems()
        )
        self.play_btn.setText("Running..." if busy else "Play")
        self.setup_box.setEnabled(not busy)
        self.ring.setVisible(busy)
        if getattr(self, "ws_apply", None) is not None:
            self._ws_recount()
        if status:
            self.status.setText(status)
        if getattr(self, "game_btn", None) is not None:
            self.game_btn.setEnabled(not busy)  # never switch games under a running job
        self.setWindowTitle(self._base_title() + (f" - {status}" if busy and status else ""))

    def _on_done(self, ok, status):
        label = getattr(self, "_job_label", "")  # what start() was told the job does; status is only how it ended
        if label == self.UPDATE_LABEL:
            self._after_update(ok, status)
            return
        self.set_busy(False, f"{status} at {datetime.datetime.now():%H:%M}")
        self._pill("Finished" if ok else "Stopped", "success" if ok else "error")
        self.refresh_saves()
        detail = (
            "Open Log on the Play page; every job's log is in the logs folder."
            if not ok
            else (
                "Done."
                if any(
                    w in label
                    for w in (
                        "Repairing",
                        "Clearing",
                        "Fixing",
                        "Converting",
                        "Restoring",
                        "Installing",
                        "Rebuilding",
                        "Removing",
                        "Restoring",
                        "Undoing",
                        "Redoing",
                        "Combining",
                        "Swapping",
                        "Copying",
                        "Adding",
                    )
                )
                else "Saves repaired and cleanup done."
            )
        )
        if label.startswith(("Installing", "Rebuilding", "Combining", "Removing", "Restoring", "Undoing", "Redoing")):
            self._load_profile_editor(force=True)
            self._fill_mods()
            self._update_plan()
            after = getattr(self, "_merge_after", None)
            self._merge_after = None
            if ok and after is not None and label.startswith("Installing"):
                QTimer.singleShot(0, lambda p=after: self._rebuild_merge(p))  # asked for in the install dialog
            elif getattr(self, "_install_queue", None):
                QTimer.singleShot(0, self._install_next)  # the next dropped mod
        undo = self._undo if ok else None
        undo_btn = ghost_btn("Undo", FI.RETURN) if undo else None
        view_btn = ghost_btn("View in Activity", FI.HISTORY) if not ok else None
        bar = notice(
            self,
            "success" if ok else "error",
            status,
            detail + (" Undo puts the file back as it was." if undo else ""),
            actions=tuple(b for b in (undo_btn, view_btn) if b is not None),
            duration=-1 if (undo or not ok) else 6000,
        )
        if undo_btn:
            undo_btn.clicked.connect(lambda _=False, u=undo, bar=bar: (bar.close(), self._undo_last(u)))
        if view_btn:
            view_btn.clicked.connect(lambda _=False, bar=bar: (bar.close(), self._open_activity(failed_only=True)))
        self._undo = None
        if self.stackedWidget.currentWidget() is self.activity_page:
            self.activity.refresh()
            self._mark_activity_seen()
        self._update_activity_badge()

    def start(self, job, status, need_setup=True):
        if self.busy:
            return
        s = self.setup
        if need_setup:
            if not s:
                self._toast("Pick a setup first", "", error=True)
                return
            probs = s.problems()
            if probs:
                self._toast("Cannot launch", "\n".join(probs), error=True)
                return
            remember_setup(s.source, s.game)
        if self.game_running and job is not job_clear:
            self._toast(f"{self.game.name} is already running", "Close it first.", error=True)
            return
        self._job_label = status
        self.set_busy(True, status)
        self.log_pane.banner(status)
        route_logs(self._sink)
        loc = s.locations() if s is not None else self.ctx.locations  # with the saves the setup uses
        self.jobs.start_job(job, s, loc, status, lambda outcome: self._on_done(outcome.ok, outcome.status))

    def _watch_game(self):
        def work(report):
            while True:
                try:
                    loc = self.ctx.locations
                    report(("running", loc.game_running()))
                    report(("steam", steam_state()))
                    report(("shells", dead_shells_count(loc=loc)))
                except Exception:
                    pass
                time.sleep(5)

        self.jobs.start(work, on_progress=self._on_watched)

    def _on_watched(self, seen):
        what, value = seen
        if what == "running":
            self._on_running(value)
        elif what == "steam":
            self._on_steam(*value)
        else:
            self._on_shells(value)

    def _on_running(self, r):
        changed = r != self.game_running
        self.game_running = r
        if changed:
            self.refresh_saves()  # the save-block badge wording depends on it
        if getattr(self, "ws_apply", None) is not None:
            self._ws_recount()
        if changed and getattr(self, "backups_rows", None) is not None:
            self._fill_backups()
        if not self.busy:
            self.play_btn.setEnabled(not r and self.setup is not None and not self.setup.problems())
            if changed:
                self._pill("Game running" if r else "Ready", "warning" if r else "success")
                self.status.setText(f"{self.game.name} is running, Play is off until you quit." if r else "")

    def _on_steam(self, running, signed):
        """Steam running but not signed in for 20 s: say why Play would hang, and offer offline play."""
        bad = running and not signed
        if bad and self.steam_bad_since is None:
            self.steam_bad_since = time.time()
        if not bad:
            self.steam_bad_since = None
        show = bad and time.time() - self.steam_bad_since >= 20 and not self.busy
        if show and self.steam_bar is None:
            b = ghost_btn("Play offline")
            b.clicked.connect(self.launch_offline)
            self.steam_bar = notice(
                self,
                "warning",
                "Steam is not signed in",
                "Steam's login network may be down, so Play would wait and co-op cannot start. You can still play solo on the standard save.",
                actions=(b,),
                closable=False,
            )
        elif not show and self.steam_bar is not None:
            try:
                self.steam_bar.close()
            except Exception:
                pass
            self.steam_bar = None

    def _on_shells(self, n):
        """Dead copies of the game's exe make Steam and Discord think the game is still open."""
        show = n > 0 and not self.game_running and not self.busy and bool(self.settings.warn_dead_shells)
        if show and self.shells_bar is None:
            exe = self.ctx.locations.game_exe_name()
            msg = f"{n} leftover {exe} process{'es' if n != 1 else ''} with no game window. Steam may refuse to launch."
            b = ghost_btn("Clear")
            b.clicked.connect(lambda: self.start(job_clear, "Clearing leftover processes...", need_setup=False))
            self.shells_bar = notice(self, "warning", "Dead game process", msg, actions=(b,))
        elif not show and self.shells_bar is not None:
            try:
                self.shells_bar.close()
            except Exception:
                pass
            self.shells_bar = None

    # ---------------------------------------------------------------- misc
    def _toast(self, title, msg, error=False, info=False):
        if self._toast_bar is not None:
            try:
                self._toast_bar.close()
            except Exception:
                pass
        kind = "error" if error else ("info" if info else "success")
        self._toast_bar = notice(self, kind, title, msg, duration=-1 if error else 4500)

    def _apply_logo(self):
        mode = self.settings.logo
        path = logo_path(isDarkTheme(), mode)
        ico = ASSETS_DIR / "icon.ico"
        if core.logo_kind(isDarkTheme(), mode) == "dark" and ico.is_file():
            icon = QIcon(str(ico))
        else:
            icon = QIcon(str(path))
        self.setWindowIcon(icon)
        app = QApplication.instance()
        if app is not None:
            app.setWindowIcon(icon)
        if hasattr(self, "logo_preview"):
            self.logo_preview.setPixmap(QPixmap(str(path)).scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _restyle(self):
        for b in self.findChildren(QPushBtn):
            if b.objectName() == "cta" or b.property("role"):
                style_button(b)
            elif b.metaObject().className() == "PushButton":
                style_ghost(b)
        if getattr(self, "game_btn", None) is not None:
            self._game_menu_view.restyle()
            self.game_btn.update()
        tone_label(self.ready)
        tone_label(self.status)
        tone_label(self.plan, "accent" if self.ini and self._coop_pending() else "muted")
        self.hero.update()
        for w in self.findChildren(ActionBar):
            w.restyle()
        for w in self.findChildren(StatusPill):
            w.updateGeometry()
            w.update()
        self.navigationInterface.update()
        for w in self.navigationInterface.findChildren(QWidget):
            w.update()
        refresh_surfaces(self)  # card shadows
        for w in self.findChildren(GlassCard):
            w.update()
        for w in self.findChildren(ExpandGroupSettingCard):
            w._paint_view()
            w.update()
            w.card.update()
            w.borderWidget.update()
        self.log_pane.restyle()
        self.profile_panel.restyle()
        self.share_panel.restyle()
        self._apply_logo()
        self._frost()

    def showEvent(self, e):
        super().showEvent(e)
        self._frost()
        if not getattr(self, "_focused_once", False):
            self._focused_once = True
            QTimer.singleShot(0, lambda: self.setFocus(Qt.OtherFocusReason))

    def _onThemeChangedFinished(self):
        super()._onThemeChangedFinished()
        self._frost()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setPen(Qt.NoPen)
        p.setBrush(tokens()["sidebar_bg"])
        p.drawRect(self.navigationInterface.geometry())

    def _frost(self):
        """Solid canvas. Mica made dark type vanish on a light desktop; Tailwind-style apps paint their own ground."""
        try:
            self.setMicaEffectEnabled(False)
        except Exception:
            pass
        self.setCustomBackgroundColor(BG_LIGHT, BG_DARK)

    def closeEvent(self, e):
        if self.busy and not confirm(
            self,
            "Close while a job runs?",
            changes=["The game is left alone", "The save repair and the cleanup after it are skipped"],
            safety="Nothing is written by closing. Run Repair saves on Settings later if the game was played.",
            apply_text="Close anyway",
        ):
            e.ignore()
            return
        if not self._settle_unsaved("closing"):
            e.ignore()
            return
        e.accept()

    def _unsaved(self) -> list[str]:
        """What has edits that are not written yet, in words for a prompt."""
        out = []
        if self._coop_pending():
            out.append("Co-op settings: " + ", ".join(self._pending_labels()))
        if self.profile_panel.dirty:
            out.append(f"The me3 profile ({self._profile_file.name if self._profile_file else 'editor'})")
        return out

    def _settle_unsaved(self, action) -> bool:
        """Ask Save / Discard / Cancel when something is unsaved. True when it is fine to go on."""
        what = self._unsaved()
        if not what:
            return True
        choice = ask_unsaved(self, what, action)
        if choice is None:
            return False
        if choice == "discard":
            if self._coop_pending():
                self._load_coop()
            if self.profile_panel.dirty:
                self._load_profile_editor(force=True)
            return True
        if self._coop_pending() and self.save_seamless() is None:
            return False
        return not (self.profile_panel.dirty and not self._save_profile())

    def _shortcut_save(self):
        page = self.stackedWidget.currentWidget()
        if page is self.coop_page and self._coop_pending():
            self._announce_saved(self.save_seamless(), "next")
        elif page is self.mods_page and self.profile_panel.dirty:
            self._save_profile()


def main(ctx):
    """The window for ctx (app.create_app; its game is the tab the window opens on)."""
    from roundtable_souls.config import identity

    if identity.get().qt_platform:  # an isolated test build (Velopack starts it with the user's own environment)
        os.environ["QT_QPA_PLATFORM"] = identity.get().qt_platform
    app = QApplication(sys.argv)
    app.setApplicationName(TITLE)
    use_theme_text()
    dark = load_settings().theme == "dark"
    setTheme(Theme.DARK if dark else Theme.LIGHT)
    setThemeColor(ACCENT if dark else ACCENT_LIGHT)
    hold = None
    if "--shots" not in sys.argv:
        hold = instance.acquire(instance.WINDOW)
        if hold is None and instance.send("show"):
            return 0  # the open window came forward
        deadline = time.monotonic() + 5
        while hold is None and time.monotonic() < deadline:  # a window closing for an update hand-off
            time.sleep(0.25)
            hold = instance.acquire(instance.WINDOW)
        if hold is None:
            QMessageBox.warning(
                None,
                TITLE,
                f"{TITLE} is already open but does not answer. Close it (or end it in Task Manager), then start "
                "it again.",
            )
            return 1
    w = Launcher(ctx)
    if "--shots" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--shots") + 1])
        out.mkdir(parents=True, exist_ok=True)
        w.show()

        def shoot():
            w.log_pane.banner("Starting...")
            w.log_pane.add("launching me3")
            w.log_pane.add("steam: running")
            w.log_pane.add("warning: example only")
            w.log_exp.setExpand(True)
            w.profile_exp.setExpand(True)
            w.offline_exp.setExpand(True)
            t0 = time.time()
            while time.time() - t0 < 2.5 and not getattr(w, "saves", None):
                QApplication.processEvents()
            for name, pg in (
                ("play", w.play_page),
                ("coop", w.coop_page),
                ("mods", w.mods_page),
                ("saves", w.saves_page),
                ("tools", w.tools_page),
            ):
                w.switchTo(pg)
                t0 = time.time()
                while time.time() - t0 < 0.6:
                    QApplication.processEvents()  # let the page-switch animation finish
                w.grab().save(str(out / f"{name}.png"))
                if name == "play":
                    w.resize(740, 720)
                    QApplication.processEvents()
                    w._relayout()
                    QApplication.processEvents()
                    w.grab().save(str(out / "play-narrow.png"))
                    w.resize(1080, 760)
                    QApplication.processEvents()
                    w._relayout()
                    QApplication.processEvents()
                if name == "coop":  # second frame: the All-settings groups, opened and scrolled into view
                    scroll = w.coop_scroll
                    for exp in pg.findChildren(ExpandGroupSettingCard):
                        exp.setExpand(True)
                    t0 = time.time()
                    while time.time() - t0 < 0.6:
                        QApplication.processEvents()
                    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum() * 55 // 100)
                    QApplication.processEvents()
                    w.grab().save(str(out / "coop-all.png"))
                    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
                    QApplication.processEvents()
                    w.grab().save(str(out / "coop-share.png"))
                    scroll.verticalScrollBar().setValue(0)
                if name == "mods":
                    w.pack_exp.setExpand(False)
                    w.nat_exp.setExpand(False)
                    w.profile_exp.setExpand(True)
                    t0 = time.time()
                    while time.time() - t0 < 0.5:
                        QApplication.processEvents()
                    w.grab().save(str(out / "mods-edit.png"))
                    w.pack_exp.setExpand(True)
                if name == "saves":
                    # scroll to show both cards if tall
                    if hasattr(w.saves_page, "verticalScrollBar"):
                        w.saves_page.verticalScrollBar().setValue(0)
                        QApplication.processEvents()
                        w.grab().save(str(out / "saves.png"))
                        w.saves_page.verticalScrollBar().setValue(w.saves_page.verticalScrollBar().maximum())
                        QApplication.processEvents()
                        w.grab().save(str(out / "saves-bottom.png"))
                        w.saves_page.verticalScrollBar().setValue(0)
            setTheme(Theme.LIGHT)
            setThemeColor(ACCENT_LIGHT)
            w._restyle()
            for name, pg in (("play-light", w.play_page), ("coop-light", w.coop_page)):
                w.switchTo(pg)
                t0 = time.time()
                while time.time() - t0 < 0.6:
                    QApplication.processEvents()
                w.grab().save(str(out / f"{name}.png"))
            print("shots in", out)
            app.quit()

        QTimer.singleShot(2500, shoot)
        return app.exec()
    w._take_instance(hold)
    w.show()
    QTimer.singleShot(0, w.after_show)
    return app.exec()
