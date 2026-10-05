"""The window (PySide6 + Fluent Widgets). All logic lives in core.py.

Game tabs in the title bar pick the game every page works on (Elden Ring, Nightreign; Dark Souls III and Sekiro are
placeholders until their support lands). Settings is shared by all games.

Pages (navigation rail on the left):
  Play    who you are (from the save), which setup, one big Play button, one line saying what will happen
  Co-op   Seamless Co-op password, difficulty, and a save bar that stays on screen
  Saves   the save files and the characters in them, read-only
  Tools   repair, cleanup, logs, theme

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
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWidgets import QPushButton as QPushBtn
from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    FlowLayout,
    FluentWindow,
    IconWidget,
    InfoBadge,
    InfoBadgePosition,
    NavigationItemPosition,
    SearchLineEdit,
    StrongBodyLabel,
    TableWidget,
    Theme,
    TitleLabel,
    TransparentPushButton,
    isDarkTheme,
    setTheme,
    setThemeColor,
)
from qfluentwidgets import FluentIcon as FI

from roundtable_souls.game import catalog as games
from roundtable_souls.game.locate import Locations, installed_dir
from roundtable_souls.platform import data_folder, desktop, instance
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.resources import ASSETS_DIR
from roundtable_souls.saves import backups as save_backups
from roundtable_souls.saves import library as save_library
from roundtable_souls.saves import transfer as save_transfer
from roundtable_souls.services import play as core
from roundtable_souls.services import saves as saves_service
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
    save_info,
    steam_state,
)
from roundtable_souls.services.saves import (
    character_detail,
    dead_shells_count,
    delete_backup,
    fix_checksums,
    fix_loading,
    health_report,
    list_backups,
    repair_available,
    repair_save,
    restore_backup,
    restore_vanilla,
    save_summary,
)
from roundtable_souls.services.settings import (
    load_settings,
    save_settings,
)
from roundtable_souls.ui.activity import ActivityView
from roundtable_souls.ui.dialogs import (
    WRITE_SAFETY,
    WRITE_WARNING,
    TextDialog,
    ask_unsaved,
    confirm,
)
from roundtable_souls.ui.jobs import Jobs
from roundtable_souls.ui.notes import _save_note_widget, save_check_notes
from roundtable_souls.ui.pages.coop.view import CoopView
from roundtable_souls.ui.pages.mods.view import ModsView
from roundtable_souls.ui.pages.play.view import PlayView
from roundtable_souls.ui.pages.tools.view import ToolsView
from roundtable_souls.ui.save_dialogs import CopyCharacterDialog, CopyFileDialog, SwapDialog
from roundtable_souls.ui.theme import (
    ACCENT,
    ACCENT_LIGHT,
    BG_DARK,
    BG_LIGHT,
    COMPACT,
    ghost_btn,
    hint,
    primary_btn,
    style_button,
    style_ghost,
    tokens,
    use_theme_text,
)
from roundtable_souls.ui.widgets import (
    ActionBar,
    Bus,
    ElideLabel,
    ExpandGroupSettingCard,
    GlassCard,
    MenuButton,
    PathTag,
    StatusMenu,
    StatusPill,
    action_row,
    card,
    clear_layout,
    count_label,
    dispose,
    icon_btn,
    notice,
    page,
    refresh_surfaces,
    style_navigation,
    tidy_log_line,
    titled,
    tone_label,
)
from roundtable_souls.updates import apply as updates
from roundtable_souls.updates import inno as migration


# ----------------------------------------------------------------------------- window
class Launcher(PlayView, CoopView, ModsView, ToolsView, FluentWindow):
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

    # ---------------------------------------------------------------- Saves page
    def _build_saves(self):
        self.saves_page, lay = page("savesPage")
        acts, al = action_row()
        al.addWidget(
            self._folder_btn(
                "saves", "Saves folder", FI.FOLDER, "The folder with your save files and the backup folders."
            )
        )
        b = ghost_btn("Refresh", FI.SYNC)
        b.clicked.connect(self.refresh_saves)
        al.addWidget(b)
        titled(lay, "Saves", FI.SAVE, "Your characters, with checks and repairs.", acts)
        self.saves_note = hint("Reading saves...")
        lay.addWidget(self.saves_note)
        self.library_card, ll = card("Save library", FI.LIBRARY)
        ll.addWidget(
            hint(
                "Named copies of whole saves, kept in the launcher's own folder. Swap in puts one in place of a live "
                "save; the save it replaces is added here first, under a name you choose. Copies here are never "
                "removed unless you remove them."
            )
        )
        self.library_rows = QVBoxLayout()
        self.library_rows.setSpacing(6)
        ll.addLayout(self.library_rows)
        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.library_note = hint("")
        foot.addWidget(self.library_note, 1)
        b = ghost_btn("Import a save file...", FI.DOWNLOAD)
        b.setToolTip("Add a .sl2 or .co2 from anywhere (a friend's, an old backup) to the library. The file is copied.")
        b.clicked.connect(self._import_save)
        foot.addWidget(b)
        b = ghost_btn("Library folder", FI.FOLDER)
        b.clicked.connect(self._open_library)
        foot.addWidget(b)
        ll.addLayout(foot)
        lay.addWidget(self.library_card)
        self._libs = {}
        self.backups_card, bl = card("Backups", FI.HISTORY)
        bl.addWidget(
            hint(
                f"A backup is taken before every change to a save. The newest {save_backups.KEEP_NEWEST} of each save "
                f"and everything from the last {save_backups.KEEP_DAYS} days are kept; Keep holds on to one for good. "
                "Restore puts a backup back, and backs up the save as it is then, so a restore can be undone."
            )
        )
        self.backups_rows = QVBoxLayout()
        self.backups_rows.setSpacing(6)
        bl.addLayout(self.backups_rows)
        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.backups_note = hint("")
        foot.addWidget(self.backups_note, 1)
        self.backups_more = ghost_btn("Show all")
        self.backups_more.clicked.connect(self._toggle_backups)
        foot.addWidget(self.backups_more)
        b = ghost_btn("Backups folder", FI.FOLDER)
        b.clicked.connect(self._open_backups_folder)
        foot.addWidget(b)
        bl.addLayout(foot)
        lay.addWidget(self.backups_card)
        lay.addStretch(1)
        self.saves_lay = lay

    # ---------------------------------------------------------------- saves
    def refresh_saves(self):
        self.saves_note.setText("Reading saves...")
        # A game-tab switch and the running-game watcher can both ask at once; a token lets a stale read's result be
        # dropped in _fill_saves instead of reading and rebuilding the cards twice.
        self._saves_token = getattr(self, "_saves_token", 0) + 1
        token, game, loc = self._saves_token, self.game, self.ctx.locations

        def work(_progress):
            files = loc.save_files()
            for d in {p.parent for p in files}:  # older tools may still drop backup folders beside the saves
                save_backups.adopt_legacy_save_folders(d, game, again=True)
            infos = [save_info(p, game, loc=loc) for p in files]
            libs = {str(f): save_library.load(f) for f in sorted({p.parent for p in files})}
            return {"token": token, "infos": infos, "libs": libs}

        self.jobs.start(work, on_result=self._fill_saves)

    def _fill_saves(self, payload):
        # Ignore a read that a newer refresh has already superseded (avoids reading and rebuilding the cards twice).
        if payload["token"] != getattr(self, "_saves_token", 0):
            return
        infos = [i for i in payload["infos"] if games.for_save(i["path"]) in (self.game, None)]
        self.saves = infos
        for w in getattr(self, "_save_cards", []):
            self.saves_lay.removeWidget(w)
            dispose(w)
        self._save_cards = []
        if infos:
            n_bad = sum(1 for s in infos if s.get("needs_repair"))
            note = count_label(len(infos), "save")
            if n_bad and not self.game_running:
                note += f"  ·  {n_bad} can be repaired for editors"
            if self.game.save_reader == "container":
                note += (
                    f"  ·  {self.game.name} encrypts its saves, so characters and repairs are not shown yet. "
                    "Backups, restore, and copies between the co-op and standard save work."
                )
            used = getattr(self, "_saves_in_use", None)
            if used:
                note += f"  ·  Play uses {used['active']}" + (
                    f", Play offline uses {used['standard']}" if used.get("coop") else ""
                )
            self.saves_note.setText(note)
            self.saves_note.setToolTip(str(infos[0]["path"].parent))
            tone_label(self.saves_note, "muted")
        else:
            self.saves_note.setText(f"No {self.game.name} saves in this Windows account.")
            self.saves_note.setToolTip("")
            tone_label(self.saves_note)
        self._update_saves_badge(sum(1 for s in infos if repair_available(s)) if not self.game_running else 0)

        # Co-op first when present — that is what you play.
        ordered = sorted(infos, key=lambda s: 0 if s.get("kind") == "Seamless Co-op" else 1)

        for s in ordered:
            icon = FI.PEOPLE if s["kind"] == "Seamless Co-op" else FI.GAME
            c, cl = card()
            cl.setSpacing(14)
            head = QHBoxLayout()
            head.setSpacing(10)
            ic = IconWidget(icon)
            ic.setFixedSize(20, 20)
            head.addWidget(ic, 0, Qt.AlignTop)
            titles = QVBoxLayout()
            titles.setSpacing(2)
            titles.setContentsMargins(0, 0, 0, 0)
            titles.addWidget(StrongBodyLabel(s["kind"]))
            sub = f"{s['name']}  ·  {s['modified']}"
            role = self._save_role(s["name"])
            if role:
                sub += f"  ·  {role}"
            if s.get("needs_repair") and not self.game_running:
                sub += "  ·  repair available"
            elif s.get("needs_repair") and self.game_running:
                sub += "  ·  repair after you quit"
            titles.addWidget(hint(sub))
            chips_w, chips = action_row()
            chips.setHorizontalSpacing(12)
            chips.setVerticalSpacing(2)
            for text, tone in save_summary(s):
                c_lab = CaptionLabel(
                    ("\u2713  " if tone == "success" else "\u26a0  " if tone == "warn" else "\u2022  ") + text
                )
                tone_label(c_lab, "success" if tone == "success" else "warn" if tone == "warn" else "muted")
                chips.addWidget(c_lab)
            titles.addWidget(chips_w)
            head.addLayout(titles, 1)
            cl.addLayout(head)

            if s["error"] and not s.get("characters") and not s.get("findings"):
                cl.addWidget(hint(f"Could not read this file: {s['error']}"))
            elif s["characters"]:
                t = TableWidget()
                t.setColumnCount(6)
                t.setHorizontalHeaderLabels(["Slot", "Character", "Level", "Body", "Max HP", "Runes held"])
                t.setRowCount(len(s["characters"]))
                t.verticalHeader().hide()
                t.setEditTriggers(TableWidget.NoEditTriggers)
                t.setSelectionMode(TableWidget.NoSelection)
                t.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                t.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                for r, ch in enumerate(s["characters"]):
                    for col, val in enumerate(
                        (
                            ch["slot"],
                            ch["name"] + ("" if ch["ok"] else "  (checksum)"),
                            ch["level"],
                            ch["body"],
                            f"{ch['hp']:,}",
                            f"{ch['runes']:,}",
                        )
                    ):
                        it = QTableWidgetItem(str(val))
                        it.setTextAlignment(
                            Qt.AlignCenter
                            if col in (0, 3)
                            else (Qt.AlignRight | Qt.AlignVCenter)
                            if col in (2, 4, 5)
                            else (Qt.AlignLeft | Qt.AlignVCenter)
                        )
                        t.setItem(r, col, it)
                t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
                t.resizeColumnsToContents()
                table_h = t.horizontalHeader().height() + 38 * max(1, len(s["characters"])) + 8
                t.setFixedHeight(table_h)
                cl.addWidget(t)
            elif self.game.save_reader not in ("container", "nightreign") and not any(
                f.get("code") == "contents" for f in s.get("findings") or []
            ):
                cl.addWidget(hint("No active characters in this file."))

            notes = save_check_notes(s)
            if notes:
                cl.addWidget(hint("Notes"))
                for n in notes:
                    cl.addWidget(_save_note_widget(n))
            else:
                cl.addWidget(hint("Looks fine for play."))

            row = FlowLayout(needAni=False)
            row.setContentsMargins(0, 4, 0, 0)
            row.setHorizontalSpacing(8)
            row.setVerticalSpacing(8)
            fixable = repair_available(s) and not self.game_running
            if s.get("characters") or fixable:
                b = primary_btn("Review && fix") if fixable else ghost_btn("Review", FI.VIEW)
                b.setToolTip(
                    "Open this save: every character, every finding, and tick boxes for each fix. Nothing changes until you press Apply."
                )
                b.clicked.connect(lambda _=False, info=s: self.open_workshop(info))
                row.addWidget(b)
            b = ghost_btn("Copy report", FI.COPY)
            b.setToolTip("Full plain-text check for sharing or notes.")
            b.clicked.connect(lambda _=False, info=s: self._copy_health_report(info))
            row.addWidget(b)
            if not self.game_running and not (s.get("error") and not s.get("characters")):
                b = ghost_btn("Copy to...", FI.SAVE_AS)
                b.setToolTip(
                    "Copy this whole file over another save (that one is kept in the library first), or only add "
                    "a named copy to the library. You see every character before and after."
                )
                b.clicked.connect(lambda _=False, info=s: self._copy_save_file(info))
                row.addWidget(b)
                if s.get("characters") and self.game.save_reader == "eldenring":
                    b = ghost_btn("Copy a character...", FI.PEOPLE)
                    b.setToolTip("Copy one character into a slot of this or another save: a free slot, or replace one.")
                    b.clicked.connect(lambda _=False, info=s: self._copy_character(info))
                    row.addWidget(b)
                b = ghost_btn("Add to library...", FI.ADD)
                b.setToolTip("Keep a named copy of this file in the save library, to swap back in later.")
                b.clicked.connect(lambda _=False, info=s: self._stash_save(info))
                row.addWidget(b)
            cl.addLayout(row)

            self.saves_lay.insertWidget(self.saves_lay.indexOf(self.library_card), c)
            self._save_cards.append(c)

        self._fill_library(payload.get("libs") or {})
        self._fill_backups()
        self._ws_refresh(infos)
        pick = next((s for s in ordered if s["kind"] == "Seamless Co-op" and s["characters"]), None) or next(
            (s for s in ordered if s["characters"]), None
        )
        contents_unread = [s for s in ordered if any(f.get("code") == "contents" for f in s.get("findings") or [])]
        nr_only = [s for s in ordered if any(f.get("code") == "checksum" for f in s.get("findings") or [])]
        if (contents_unread or nr_only) and not (pick and pick["characters"]):
            newest = max(contents_unread or nr_only, key=lambda s: str(s.get("modified")))
            self.hero.name.setText(self.game.name)
            self.hero.sub.setText(f"Last saved {newest['modified']}")
            self.stat_level.setVisible(False)  # no character data to show for this game yet
            self.stat_body.setVisible(False)
            self.stat_save.value.setText("Co-op" if newest["kind"] == "Seamless Co-op" else newest["kind"])
            self.stat_save.value.setToolTip(newest["kind"])
        elif pick and pick["characters"]:
            self.stat_level.setVisible(True)
            self.stat_body.setVisible(True)
            ch = pick["characters"][0]
            self.hero.name.setText(ch["name"])
            extra = f"  ·  {len(pick['characters'])} characters" if len(pick["characters"]) > 1 else ""
            self.hero.sub.setText(f"Last played {pick['modified']}{extra}")
            self.stat_level.value.setText(str(ch["level"]))
            self.stat_save.value.setText("Co-op" if pick["kind"] == "Seamless Co-op" else pick["kind"])
            self.stat_save.value.setToolTip(pick["kind"])
            self.stat_body.value.setText(ch["body"])
            self.stat_body.value.setToolTip(ch["body"])
        else:
            self.stat_level.setVisible(True)
            self.stat_body.setVisible(True)
            self.hero.name.setText("No characters yet")
            self.hero.sub.setText("Your saves show here once you have played.")
            for s in (self.stat_level, self.stat_save, self.stat_body):
                s.value.setText("—")

    def _copy_health_report(self, info):
        try:
            text = health_report(info=info)
            QApplication.clipboard().setText(text)
            self._toast("Copied", f"Report for {info.get('name', 'save')} is on the clipboard.")
        except Exception as e:
            self._toast("Could not copy", str(e), error=True)

    def _update_saves_badge(self, n):
        """Count on the Saves nav item only when Roundtable Souls can repair something (never for mod-item notes)."""
        if n > 0 and self.saves_badge is None:
            try:
                target = self.navigationInterface.widget(self.saves_page.objectName())
                self.saves_badge = InfoBadge.attension(
                    str(n), parent=self.navigationInterface, target=target, position=InfoBadgePosition.NAVIGATION_ITEM
                )
            except Exception:
                self.saves_badge = None
        elif n > 0 and self.saves_badge is not None:
            self.saves_badge.setText(str(n))
        elif n == 0 and self.saves_badge is not None:
            try:
                self.saves_badge.hide()
                self.saves_badge.deleteLater()
            except Exception:
                pass
            self.saves_badge = None

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

    def _play_requested(self, key):
        """A Steam shortcut (--play) started while this window is open: Play here, for that game."""
        g = games.get(key)
        if self.busy or self.game_running:
            self._toast("Play from Steam ignored", f"{self.game.name} or a job is already running here.", error=True)
            return
        if g.key != self.game.key:
            if not self._settle_unsaved(f"switching to {g.name}"):
                return
            self._set_game(g, remember=True)
        self.launch()

    def after_show(self):
        """For a real start only (tests build the window without it): tell an update's watchdog this version is up,
        report how the last update went, finish the move from the old installer, and tidy old downloads."""
        confirmed = updates.mark_ready("window")

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

    # ---------------------------------------------------------------- Backups card (Saves page)
    def _fill_backups(self):
        for i in reversed(range(self.backups_rows.count())):
            it = self.backups_rows.takeAt(i)
            dispose(it.widget())
        try:
            rows = list_backups(loc=self.ctx.locations)
        except Exception:
            rows = []
        shown = rows if self._backups_all else rows[:6]
        for b in shown:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 4, 0, 4)
            rl.setSpacing(10)
            detail = "\n".join(b["changes"][:12]) + ("\n..." if len(b["changes"]) > 12 else "")
            text = QVBoxLayout()
            text.setSpacing(2)
            what = BodyLabel(f"{b['action']}  ·  {b['save_name']}")
            what.setWordWrap(True)
            text.addWidget(what)
            first = (
                b["changes"][0] + (f" (+{len(b['changes']) - 1} more)" if len(b["changes"]) > 1 else "")
                if b["changes"]
                else ""
            )
            sub = hint(b["when"][:16] + (f"  ·  {first}" if first else ""))
            sub.setWordWrap(True)
            text.addWidget(sub)
            row.setToolTip(detail or "No change list recorded.")
            rl.addLayout(text, 1)
            k = icon_btn(
                FI.PIN if b["keep"] else FI.UNPIN,
                "Kept for good. Click to let it age out like the others."
                if b["keep"]
                else "Keep this backup whatever its age.",
            )
            k.clicked.connect(lambda _=False, bk=b: self._keep_backup(bk))
            rl.addWidget(k, 0, Qt.AlignVCenter)
            r = ghost_btn("Restore", FI.RETURN)
            r.setEnabled(not self.game_running and not self.busy)
            r.setToolTip(
                f"Close {self.game.name} first."
                if self.game_running
                else "Put this backup back over the save. The save as it is now is backed up first."
            )
            r.clicked.connect(lambda _=False, bk=b: self._restore_backup(bk))
            rl.addWidget(r, 0, Qt.AlignVCenter)
            d = icon_btn(FI.DELETE, "Delete this backup")
            d.clicked.connect(lambda _=False, bk=b: self._delete_backup(bk))
            rl.addWidget(d, 0, Qt.AlignVCenter)
            self.backups_rows.addWidget(row)
        n = len(rows)
        size = sum(b["size"] for b in rows) / 1_000_000
        self.backups_note.setText(
            "No backups yet. One is taken before the first change to a save."
            if not n
            else count_label(n, "backup")
            + f", {size:,.0f} MB"
            + ("" if self._backups_all or n <= 6 else f"  ·  newest {len(shown)} shown")
        )
        self.backups_more.setVisible(n > 6)
        self.backups_more.setText("Show fewer" if self._backups_all else "Show all")

    def _toggle_backups(self):
        self._backups_all = not self._backups_all
        self._fill_backups()

    def _keep_backup(self, b):
        try:
            saves_service.keep_backup(b["path"], not b["keep"])
        except OSError as e:
            self._toast("Could not change it", str(e), error=True)
            return
        self._fill_backups()

    def _open_backups_folder(self):
        folders = saves_service.backup_folders(loc=self.ctx.locations)
        if not folders:
            self._toast("No saves yet", f"Play {self.game.name} once so it creates its save folder.", info=True)
            return
        folders[0].mkdir(parents=True, exist_ok=True)
        desktop.open_path(str(folders[0]))

    def _restore_backup(self, b):
        if self.busy or self.game_running:
            self._toast(
                "Cannot restore now",
                f"Close {self.game.name} first." if self.game_running else "Wait for the current job.",
                error=True,
            )
            return
        save = saves_service.save_for_backup(b["path"], loc=self.ctx.locations)
        if not confirm(
            self,
            f"Restore {save.name} from {b['when'][:16]}",
            changes=[f"{save.name} goes back to the backup taken {b['action'][:1].lower()}{b['action'][1:]}"]
            + [f"Undone with it: {c}" for c in b["changes"][:6]],
            warning=WRITE_WARNING,
            safety="The save as it is now is backed up first, so this restore can itself be undone from Backups.",
            apply_text="Restore",
        ):
            return

        def job(_setup, loc):
            run_logging.start_log(f"launcher: restore backup {b['path'].name}", loc.game.key)
            try:
                safety = restore_backup(b["path"], save, loc=loc)
                self._undo = (save, safety) if safety else None
                run_logging.log(f"done: restored {b['path'].name} over {save.name}")
            except Exception as e:
                run_logging.log(f"error: {e}")
                raise SystemExit(1) from e

        self.start(job, f"Restoring {save.name}...", need_setup=False)

    def _delete_backup(self, b):
        if not confirm(
            self,
            "Delete this backup",
            changes=[f"{b['path'].name}", f"Taken {b['when'][:16]} before: {b['action']}"],
            warning="Deleting a backup cannot be undone. The live save is not touched.",
            apply_text="Delete",
        ):
            return
        try:
            delete_backup(b["path"])
            self._fill_backups()
            self._toast("Backup deleted", b["path"].name)
        except Exception as e:
            self._toast("Could not delete", str(e), error=True)

    # ---------------------------------------------------------------- saves in use, library, copies
    def _note_saves_in_use(self, setup):
        names = core.setup_saves(setup, self.game)
        self.ctx.note_setup_saves({k: names[k] for k in ("standard", "coop")})
        if names == getattr(self, "_saves_in_use", None):
            return
        self._saves_in_use = names
        if getattr(self, "_saves_token", 0) and self.game.ready:
            self.refresh_saves()  # a different setup can mean different files

    def _save_role(self, name) -> str:
        used = getattr(self, "_saves_in_use", None) or {}
        if name.lower() == str(used.get("active") or "").lower():
            return "Play uses this"
        if used.get("coop") and name.lower() == str(used.get("standard") or "").lower():
            return "Play offline uses this"
        return ""

    def _save_targets(self, folder, exclude=None):
        """(label, path) for the live saves in one account folder, plus the files the setup uses that do not exist
        yet (a swap or copy can create them)."""
        folder = Path(folder)
        out, seen = [], set()
        for info in self.saves:
            p = Path(info["path"])
            if p.parent != folder or (exclude and p == Path(exclude)):
                continue
            role = self._save_role(p.name)
            out.append((f"{p.name}  ·  {info['kind']}" + (f"  ·  {role}" if role else ""), p))
            seen.add(p.name.lower())
        used = getattr(self, "_saves_in_use", None) or {}
        for key in ("coop", "standard"):
            name = used.get(key)
            if name and name.lower() not in seen and not (exclude and Path(exclude).name.lower() == name.lower()):
                made_by = "me3 makes it at the next launch" if key == "standard" else "not created yet"
                out.append((f"{name}  ·  {made_by}  ·  {self._save_role(name)}", folder / name))
        return out

    def _saves_blocked(self, what) -> bool:
        if self.busy or self.game_running:
            self._toast(
                f"Cannot {what} now",
                f"Close {self.game.name} first." if self.game_running else "Wait for the current job.",
                error=True,
            )
            return True
        return False

    def _fill_library(self, libs):
        self._libs = libs
        for i in reversed(range(self.library_rows.count())):
            it = self.library_rows.takeAt(i)
            dispose(it.widget())
        total = 0
        several = len(libs) > 1
        for folder, doc in libs.items():
            entries = sorted(doc.get("entries") or [], key=lambda e: e.get("added") or "", reverse=True)
            total += len(entries)
            for e in entries:
                row = QWidget()
                rl = QHBoxLayout(row)
                rl.setContentsMargins(0, 4, 0, 4)
                rl.setSpacing(10)
                text = QVBoxLayout()
                text.setSpacing(2)
                title = QHBoxLayout()
                title.setSpacing(8)
                title.addWidget(ElideLabel(e["name"]))
                kind = "Co-op" if e.get("format") != "sl2" else "Standard"
                title.addWidget(PathTag([kind], f"A {kind.lower()} save (.{e.get('format')})"))
                if several:
                    title.addWidget(PathTag([Path(folder).name], folder))
                title.addStretch(1)
                text.addLayout(title)
                chars = e.get("characters") or []
                who = ", ".join(f"{c['name']} {c['level']}" for c in chars[:3]) + (
                    f" +{len(chars) - 3}" if len(chars) > 3 else ""
                )
                bits = [
                    who or "no characters read",
                    f"from {e.get('from', '?')}",
                    (e.get("added") or "")[:16].replace("T", " "),
                ]
                if e.get("missing"):
                    bits.insert(0, "file missing")
                sub = hint("  ·  ".join(b for b in bits if b))
                sub.setWordWrap(True)
                text.addWidget(sub)
                row.setToolTip(
                    "\n".join(f"Slot {c['slot']}: {c['name']}, level {c['level']}" for c in chars) or e["name"]
                )
                rl.addLayout(text, 1)
                b = ghost_btn("Swap in", FI.SYNC)
                b.setEnabled(not e.get("missing") and not self.game_running and not self.busy)
                b.setToolTip(
                    f"Close {self.game.name} first." if self.game_running else "Put this copy in place of a live save."
                )
                b.clicked.connect(lambda _=False, f=folder, en=e: self._swap_in(f, en))
                rl.addWidget(b, 0, Qt.AlignVCenter)
                b = ghost_btn("Rename", FI.EDIT)
                b.clicked.connect(lambda _=False, f=folder, en=e: self._rename_entry(f, en))
                rl.addWidget(b, 0, Qt.AlignVCenter)
                d = icon_btn(
                    FI.DELETE, "Take this copy out of the library (its file moves to the library's removed folder)"
                )
                d.clicked.connect(lambda _=False, f=folder, en=e: self._delete_entry(f, en))
                rl.addWidget(d, 0, Qt.AlignVCenter)
                self.library_rows.addWidget(row)
        self.library_note.setText(
            (f"{total} saved cop{'y' if total == 1 else 'ies'}")
            if total
            else "Nothing here yet. Add to library on a save, or import a file."
        )

    def _stash_save(self, info):
        if self._saves_blocked("add to the library"):
            return
        path = Path(info["path"])
        dlg = TextDialog(
            f"Add {path.name} to the library",
            "A copy of the whole file is kept under this name. The save itself does not change.",
            self,
            text=save_library.default_name(path, self.game),
            apply_text="Add",
        )
        if not dlg.exec():
            return
        name, game = dlg.edit.text().strip(), self.game

        def job(_setup, loc):
            run_logging.start_log(f"launcher: add {path.name} to the library", loc.game.key)
            try:
                saves_service.assert_writable(path, loc=loc)
                e = save_library.add(path.parent, path, name, game, action="stash")
                run_logging.log(f"done: '{e['name']}' ({e['file']}) added from {path.name}")
            except Exception as ex:
                run_logging.log(f"error: {ex}")
                raise SystemExit(1) from ex

        self.start(job, f"Adding {path.name} to the library...", need_setup=False)

    def _swap_in(self, folder, entry):
        if self._saves_blocked("swap saves"):
            return
        targets = self._save_targets(folder)
        if not targets:
            self._toast("No save to swap into", "Play once so the game creates its save file.", error=True)
            return
        src = save_library.entry_path(Path(folder), entry)
        dlg = SwapDialog(self, entry, src, targets, self.game, (self._saves_in_use or {}).get("active"))
        if not dlg.exec():
            return
        target, keep_as, game = dlg.target_path(), dlg.outgoing_name(), self.game
        if save_library.changed_outside(Path(folder), entry) and not confirm(
            self,
            f"'{entry['name']}' changed outside the launcher",
            changes=["Its file no longer matches what the library recorded when it was added"],
            safety="The save it replaces still goes into the library first.",
            apply_text="Swap in anyway",
        ):
            return

        def job(_setup, loc):
            run_logging.start_log(f"launcher: swap '{entry['name']}' into {target.name}", loc.game.key)
            try:
                saves_service.assert_writable(target, loc=loc)
                out = save_library.swap_in(Path(folder), entry["id"], target, keep_as, game)
                if out["backup"]:
                    self._undo = (target, out["backup"])
                if out["outgoing"]:
                    run_logging.log(f"kept the replaced save as '{out['outgoing']['name']}'")
                run_logging.log(f"done: '{entry['name']}' is now {target.name}")
            except Exception as ex:
                run_logging.log(f"error: {ex}")
                raise SystemExit(1) from ex

        self.start(job, f"Swapping '{entry['name']}' in...", need_setup=False)

    def _copy_save_file(self, info):
        if self._saves_blocked("copy saves"):
            return
        path = Path(info["path"])
        used = self._saves_in_use or {}
        other = used.get("standard") if info["kind"] == "Seamless Co-op" else used.get("coop")
        dlg = CopyFileDialog(self, path, self._save_targets(path.parent, exclude=path), self.game, other)
        if not dlg.exec():
            return
        mode, target, name, game = dlg.mode(), dlg.target_path(), dlg.kept_name(), self.game
        target_kind = next((i["kind"] for i in self.saves if Path(i["path"]) == target), None) or (
            "Standard" if target.name == used.get("standard") else "Seamless Co-op"
        )
        holders = [p for p in info.get("vanilla_plan") or [] if p.get("strip") or p.get("blocked")]
        if mode == "replace" and target_kind == "Standard" and holders:
            if not confirm(
                self,
                "The copy carries mod items into a standard save",
                changes=[
                    f"{len(holders)} character{'s' if len(holders) != 1 else ''} hold items the game does not define"
                ],
                safety="Remove mod items on the Saves page can take them off afterwards; the replaced save is kept in the library.",
                apply_text="Copy anyway",
            ):
                return

        def job(_setup, loc):
            try:
                if mode == "replace":
                    run_logging.start_log(f"launcher: copy {path.name} over {target.name}", loc.game.key)
                    saves_service.assert_writable(target, loc=loc)
                    out = save_transfer.copy_file(path, target, game, keep_as=name)
                    if out["backup"]:
                        self._undo = (target, out["backup"])
                    if out["kept"]:
                        run_logging.log(f"kept the replaced save as '{out['kept']['name']}'")
                    run_logging.log(f"done: {target.name} now holds {path.name}'s characters")
                else:
                    run_logging.start_log(f"launcher: add {path.name} to the library", loc.game.key)
                    saves_service.assert_writable(path, loc=loc)
                    e = save_library.add(path.parent, path, name, game, action="copy")
                    run_logging.log(f"done: '{e['name']}' added from {path.name}")
            except Exception as ex:
                run_logging.log(f"error: {ex}")
                raise SystemExit(1) from ex

        self.start(job, f"Copying {path.name}...", need_setup=False)

    def _copy_character(self, info):
        if self._saves_blocked("copy characters"):
            return
        path = Path(info["path"])
        dlg = CopyCharacterDialog(self, path, info, self._save_targets(path.parent), self.game)
        if not dlg.exec():
            return
        src_slot, target, dst_slot = dlg.source_slot(), dlg.target_path(), dlg.target_slot()
        if not target.is_file():
            self._toast("No file to copy into yet", f"{target.name} does not exist. Use Copy to... first.", error=True)
            return

        def job(_setup, loc):
            run_logging.start_log(
                f"launcher: copy slot {src_slot} of {path.name} into slot {dst_slot} of {target.name}", loc.game.key
            )
            try:
                saves_service.assert_writable(target, loc=loc)
                out = save_transfer.copy_character(path, src_slot, target, dst_slot)
                self._undo = (target, out["backup"])
                who = out["character"] or {}
                run_logging.log(f"done: {who.get('name', '?')} is in slot {dst_slot} of {target.name}")
            except Exception as ex:
                run_logging.log(f"error: {ex}")
                raise SystemExit(1) from ex

        self.start(job, f"Copying a character into {target.name}...", need_setup=False)

    def _rename_entry(self, folder, entry):
        dlg = TextDialog("Rename", entry.get("from", ""), self, text=entry["name"], apply_text="Rename")
        if not dlg.exec():
            return
        try:
            save_library.rename(Path(folder), entry["id"], dlg.edit.text())
        except Exception as ex:
            self._toast("Could not rename", str(ex), error=True)
            return
        self.refresh_saves()

    def _delete_entry(self, folder, entry):
        if not confirm(
            self,
            f"Take '{entry['name']}' out of the library",
            changes=[
                "It no longer shows here",
                "Its file moves to the library's removed folder, with a note of what it was",
            ],
            safety="No live save changes. The moved file can be copied back by hand.",
            apply_text="Remove",
        ):
            return
        try:
            save_library.remove(Path(folder), entry["id"])
        except Exception as ex:
            self._toast("Could not remove", str(ex), error=True)
            return
        self.refresh_saves()

    def _library_folder(self):
        folders = [Path(f) for f in self._libs] or sorted({Path(i["path"]).parent for i in self.saves})
        return folders[0] if folders else None

    def _import_save(self):
        folder = self._library_folder()
        if folder is None:
            self._toast("No save folder yet", f"Play {self.game.name} once so it creates one.", error=True)
            return
        src, _ = QFileDialog.getOpenFileName(
            self, "Import a save file into the library", "", "Save files (*.sl2 *.co2);;All files (*)"
        )
        if not src:
            return
        dlg = TextDialog(
            "Import into the library",
            f"{Path(src).name} is copied into the library under this name. Nothing live changes.",
            self,
            text=save_library.default_name(Path(src), self.game),
            apply_text="Import",
        )
        if not dlg.exec():
            return
        name, game = dlg.edit.text().strip(), self.game

        def job(_setup, loc):
            run_logging.start_log(f"launcher: import {src} into the library", loc.game.key)
            try:
                e = save_library.add(folder, Path(src), name, game, action="import")
                run_logging.log(f"done: '{e['name']}' imported")
            except Exception as ex:
                run_logging.log(f"error: {ex}")
                raise SystemExit(1) from ex

        self.start(job, f"Adding {Path(src).name} to the library...", need_setup=False)

    def _open_library(self):
        folder = self._library_folder()
        if folder is None:
            self._toast("No save folder yet", f"Play {self.game.name} once so it creates one.", error=True)
            return
        lib = save_library.folder_for(folder)
        lib.mkdir(exist_ok=True)
        desktop.open_path(str(lib))

    def _undo_last(self, undo):
        save, bak = undo
        if self.busy or self.game_running:
            self._toast(
                "Cannot undo now",
                f"Close {self.game.name} first." if self.game_running else "Wait for the current job.",
                error=True,
            )
            return
        if not confirm(
            self,
            f"Undo the last change to {save.name}",
            changes=[f"{save.name} goes back to the copy taken just before the last change ({bak.name})"],
            warning=WRITE_WARNING,
            safety="The file as it is now is copied first, so the undo can be undone from the Backups list.",
            apply_text="Undo",
        ):
            return

        def job(_setup, loc):
            run_logging.start_log(f"launcher: undo {bak.name}", loc.game.key)
            try:
                safety = restore_backup(bak, save, loc=loc)
                self._undo = (save, safety) if safety else None
                run_logging.log(f"done: {save.name} is back as it was")
            except Exception as e:
                run_logging.log(f"error: {e}")
                raise SystemExit(1) from e

        self.start(job, f"Undoing in {save.name}...", need_setup=False)

    # ---------------------------------------------------------------- Save workshop (review one save, tick fixes, apply once)
    def _build_workshop(self):
        root = QWidget()
        root.setObjectName("workshopPage")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QWidget()
        hl = QVBoxLayout(head)
        hl.setContentsMargins(40, 20, 40, 8)
        hl.setSpacing(4)
        self.ws_head_lay = hl
        top = QHBoxLayout()
        back = ghost_btn("Back to Saves", FI.LEFT_ARROW)
        back.clicked.connect(lambda: self.switchTo(self.saves_page))
        top.addWidget(back)
        top.addStretch()
        hl.addLayout(top)
        self.ws_title = TitleLabel("")
        hl.addWidget(self.ws_title)
        self.ws_sub = hint("")
        self.ws_sub.setWordWrap(True)
        hl.addWidget(self.ws_sub)
        chips_w, self.ws_chips = action_row()
        self.ws_chips.setHorizontalSpacing(12)
        self.ws_chips.setVerticalSpacing(2)
        hl.addWidget(chips_w)
        outer.addWidget(head)
        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(40, 8, 40, 4)
        bl.setSpacing(16)
        self.ws_body_lay = bl
        rail = QWidget()
        rail.setFixedWidth(236)
        self.ws_rail = QVBoxLayout(rail)
        self.ws_rail.setContentsMargins(0, 0, 0, 0)
        self.ws_rail.setSpacing(8)
        self.ws_rail.setAlignment(Qt.AlignTop)
        self.ws_rail_w = rail
        bl.addWidget(rail, 0, Qt.AlignTop)
        column = QVBoxLayout()
        column.setSpacing(8)
        self.ws_picker = ComboBox()  # stands in for the rail when the window is narrow
        self.ws_picker.setVisible(False)
        self.ws_picker.currentIndexChanged.connect(self._ws_picker_changed)
        column.addWidget(self.ws_picker)
        self.ws_scroll, self.ws_lay = page("workshopScroll")
        self.ws_lay.setContentsMargins(0, 0, 8, 16)
        self.ws_lay.setSpacing(14)
        column.addWidget(self.ws_scroll, 1)
        bl.addLayout(column, 1)
        outer.addWidget(body, 1)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(40, 4, 40, 20)
        self.ws_wrap_lay = wl
        self.ws_bar = ActionBar(
            "Apply",
            self._ws_apply,
            ("Reset", FI.CANCEL, self._ws_reset, "Put every tick box back to its default."),
            note="Nothing selected.",
        )
        self.ws_note, self.ws_reset, self.ws_apply = self.ws_bar.note, self.ws_bar.secondary, self.ws_bar.primary
        wl.addWidget(self.ws_bar)
        outer.addWidget(wrap)
        self.workshop_page = root
        esc = QShortcut(QKeySequence("Escape"), root)
        esc.setContext(Qt.WidgetWithChildrenShortcut)  # only while focus is on this page
        esc.activated.connect(lambda: self.switchTo(self.saves_page))
        self.ws_apply.setEnabled(False)  # joins the page stack on first open, never at startup
        self.ws_info = None
        self.ws_slot = None
        self.ws_state = {}
        self.ws_boxes = {}
        self.ws_item_rows = []
        self.ws_search = None
        self._ws_picker_slots = []

    def _ws_layout(self, compact):
        """Narrow window: the character rail becomes a dropdown above the fixes, margins shrink, the bar stacks."""
        side = 18 if compact else 40
        self.ws_head_lay.setContentsMargins(side, 16 if compact else 20, side, 8)
        self.ws_body_lay.setContentsMargins(side, 8, side, 4)
        self.ws_wrap_lay.setContentsMargins(side, 4, side, 16 if compact else 20)
        self.ws_rail_w.setVisible(not compact)
        self.ws_picker.setVisible(compact and bool(self._ws_picker_slots))

    def _ws_picker_changed(self, index):
        if 0 <= index < len(self._ws_picker_slots) and self._ws_picker_slots[index] != self.ws_slot:
            self._ws_pick(self._ws_picker_slots[index])

    def open_workshop(self, info):
        self.ws_info = info
        self.ws_slot = None
        self.ws_state = {}
        if self.stackedWidget.indexOf(self.workshop_page) < 0:
            self.stackedWidget.addWidget(self.workshop_page)
        self._ws_head()
        self._ws_build_rail()
        self._ws_build_content()
        self.switchTo(self.workshop_page)

    def _ws_refresh(self, infos):
        if not self.ws_info:
            return
        new = next((i for i in infos if i["path"] == self.ws_info["path"]), None)
        if new is None:
            return
        self.ws_info = new
        self.ws_state = {}
        if self.ws_slot is not None and not any(c["slot"] - 1 == self.ws_slot for c in new.get("characters") or []):
            self.ws_slot = None
        self._ws_head()
        self._ws_build_rail()
        self._ws_build_content()

    def _ws_head(self):
        s = self.ws_info
        self.ws_title.setText(f"{s['kind']} save")
        self.ws_sub.setText(f"{s['name']}  \u00b7  {s['modified']}  \u00b7  {s['path'].parent}")
        clear_layout(self.ws_chips)
        for text, tone in save_summary(s):
            c_lab = CaptionLabel(
                ("\u2713  " if tone == "success" else "\u26a0  " if tone == "warn" else "\u2022  ") + text
            )
            tone_label(c_lab, "success" if tone == "success" else "warn" if tone == "warn" else "muted")
            self.ws_chips.addWidget(c_lab)

    def _ws_rail_entry(self, title, sub, slot):
        b = primary_btn(title) if self.ws_slot == slot else ghost_btn(title)
        b.setMinimumHeight(36)
        b.clicked.connect(lambda _=False, sl=slot: self._ws_pick(sl))
        self.ws_rail.addWidget(b)
        if sub:
            self.ws_rail.addWidget(hint(sub))

    def _ws_build_rail(self):
        for i in reversed(range(self.ws_rail.count())):
            it = self.ws_rail.takeAt(i)
            dispose(it.widget())
        s = self.ws_info
        self.ws_rail.addWidget(hint("Characters"))
        n_fix = sum(1 for _ in self._ws_fix_keys(None))
        self._ws_rail_entry(
            "All characters",
            f"{len(s.get('characters') or [])} on this file" + (f"  \u00b7  {n_fix} possible fixes" if n_fix else ""),
            None,
        )
        for u in s.get("unreadable") or []:
            lab = ghost_btn((u.get("name") or f"Slot {u['slot']}") + "  (old layout)")
            lab.setEnabled(False)
            lab.setMinimumHeight(36)
            self.ws_rail.addWidget(lab)
            self.ws_rail.addWidget(hint(f"Lv {u['level']}  \u00b7  save version {u['ver']}  \u00b7  not touched"))
        for ch in s.get("characters") or []:
            d = character_detail(s, ch["slot"] - 1)
            bits = [f"Lv {ch['level']}"]
            if d.get("loading"):
                bits.append("may not load")
            n_mod = sum((d.get("mods") or {}).values())
            if n_mod:
                bits.append(f"{n_mod} mod item{'s' if n_mod != 1 else ''}")
            if not ch.get("ok"):
                bits.append("checksum")
            self._ws_rail_entry(ch["name"] or f"Slot {ch['slot']}", "  \u00b7  ".join(bits), ch["slot"] - 1)
        self._ws_picker_slots = [None] + [ch["slot"] - 1 for ch in s.get("characters") or []]
        self.ws_picker.blockSignals(True)
        self.ws_picker.clear()
        self.ws_picker.addItems(
            [f"All characters  ({n_fix} possible fixes)" if n_fix else "All characters"]
            + [
                f"{ch['name'] or 'Slot ' + str(ch['slot'])}  \u00b7  Lv {ch['level']}"
                for ch in s.get("characters") or []
            ]
        )
        self.ws_picker.setCurrentIndex(
            self._ws_picker_slots.index(self.ws_slot) if self.ws_slot in self._ws_picker_slots else 0
        )
        self.ws_picker.blockSignals(False)
        self.ws_picker.setVisible(bool(getattr(self, "_compact", False)))

    def _ws_pick(self, slot):
        self.ws_slot = slot
        self._ws_build_rail()
        self._ws_build_content()

    def _ws_fix_keys(self, slot):
        """Every possible fix key on this save (or one character), with its default tick and section."""
        s = self.ws_info
        want = lambda sl: slot is None or sl == slot
        for p in s.get("loading_plan") or []:
            if want(p["slot"]):
                for k in p["issues"]:
                    yield ("loading", p["slot"], k), True
        for p in s.get("vanilla_plan") or []:
            if not want(p["slot"]):
                continue
            for e in p.get("strip") or []:
                yield ("item", p["slot"], e["handle"]), False
            if p.get("orphans"):
                yield ("orphans", p["slot"]), False
        cs = s.get("checksum_fixes") or {}
        for sl in cs.get("slots") or []:
            if want(sl):
                yield ("checksum", sl), True
        if cs.get("ud10") and slot is None:
            yield ("checksum", "ud10"), True
        if s.get("needs_repair") and slot is None:
            yield ("regulation",), True

    def _ws_box(self, key, label, default, sub="", enabled=True, note="", section=None, source=None):
        cb = CheckBox(label)
        cb.setEnabled(enabled)
        cb.setChecked(bool(self.ws_state.get(key, default)) if enabled else False)
        cb.stateChanged.connect(lambda st, k=key: (self.ws_state.__setitem__(k, bool(st)), self._ws_recount()))
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)
        rl.addWidget(cb)
        side = note or sub
        if side:
            sl = hint(side)
            if note:
                tone_label(sl, "error")
            rl.addWidget(sl, 1)
        else:
            rl.addStretch()
        self.ws_boxes[key] = cb
        return row, cb

    def _ws_build_content(self):
        for i in reversed(range(self.ws_lay.count())):
            it = self.ws_lay.takeAt(i)
            dispose(it.widget())
        self.ws_boxes = {}
        self.ws_item_rows = []
        s = self.ws_info
        slot = self.ws_slot
        chars = [c for c in s.get("characters") or [] if slot is None or c["slot"] - 1 == slot]
        name_of = {c["slot"] - 1: (c["name"] or f"Slot {c['slot']}") for c in s.get("characters") or []}
        any_section = False

        if slot is not None and chars:
            ch = chars[0]
            d = character_detail(s, slot)
            c, cl = card(ch["name"] or f"Slot {ch['slot']}", FI.PEOPLE)
            grid = QGridLayout()
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(4)
            st = ch.get("stats") or {}
            facts = [
                ("Level", str(ch["level"])),
                ("Body", ch["body"]),
                ("Max HP", f"{ch['hp']:,}"),
                ("Runes held", f"{ch['runes']:,}"),
                ("Where", ch.get("where", "?")),
                ("Torrent", ch.get("torrent", "?")),
                ("Stats", "  ".join(f"{k.upper()} {v}" for k, v in st.items()) if st else "?"),
                ("Mod items", ", ".join(f"{k} {v}" for k, v in (d.get("mods") or {}).items()) or "none"),
                ("Tarnished Edition", "enabled" if s.get("tarnished_flag") else "not on this save"),
                ("Checksum", "OK" if ch.get("ok") else "mismatch"),
            ]
            for r, (k, v) in enumerate(facts):
                lab = hint(k)
                grid.addWidget(lab, r, 0)
                val = BodyLabel(v)
                val.setWordWrap(True)
                grid.addWidget(val, r, 1)
            grid.setColumnStretch(1, 1)
            cl.addLayout(grid)
            self.ws_lay.addWidget(c)

        loading = [p for p in s.get("loading_plan") or [] if slot is None or p["slot"] == slot]
        if loading:
            any_section = True
            c, cl = card("May not load", FI.POWER_BUTTON)
            cl.addWidget(
                hint("These states hang the loading screen. Ticked by default; the same repair the save editors apply.")
            )
            for p in loading:
                who = name_of.get(p["slot"], f"slot {p['slot'] + 1}")
                for k, label, action in zip(p["issues"], p["labels"], p["actions"]):
                    row, _ = self._ws_box(
                        ("loading", p["slot"], k), (f"{who}: " if slot is None else "") + label, True, sub=action
                    )
                    cl.addWidget(row)
            self.ws_lay.addWidget(c)

        vplan = [
            p
            for p in s.get("vanilla_plan") or []
            if (slot is None or p["slot"] == slot) and (p.get("strip") or p.get("blocked"))
        ]
        if vplan:
            any_section = True
            c, cl = card("Remove mod items", FI.BROOM)
            cl.addWidget(
                hint(
                    "Items the game does not define, named from the mods that added them where possible. Off by default: tick what to remove. The mods give them back in co-op; a standard save should not carry them."
                )
            )
            tools = QHBoxLayout()
            tools.setSpacing(8)
            self.ws_search = SearchLineEdit()
            self.ws_search.setPlaceholderText("Search items")
            self.ws_search.setMaximumWidth(280)
            self.ws_search.textChanged.connect(self._ws_filter_items)
            tools.addWidget(self.ws_search, 1)
            sources = sorted(
                {
                    e.get("source") or "Other mod"
                    for p in vplan
                    for e in list(p.get("strip") or []) + list(p.get("blocked") or [])
                }
            )
            self.ws_filter = None
            if len(sources) > 1:  # a filter by mod only helps when there is more than one
                self.ws_filter = ComboBox()
                self.ws_filter.addItems(["All mods", *sources])
                self.ws_filter.setMinimumWidth(160)
                self.ws_filter.currentIndexChanged.connect(self._ws_filter_items)
                tools.addWidget(self.ws_filter)
            tools.addStretch()
            cl.addLayout(tools)
            for p in vplan:
                who = name_of.get(p["slot"], f"slot {p['slot'] + 1}")
                if slot is None:
                    cl.addWidget(StrongBodyLabel(who))
                by_src = {}
                for e in p.get("strip") or []:
                    by_src.setdefault(e.get("source") or "Other mod", []).append(e)
                for src, entries in by_src.items():
                    head = QHBoxLayout()
                    head.setSpacing(6)
                    lab = hint(f"{src}  \u00b7  {len(entries)}")
                    head.addWidget(lab)
                    head.addStretch()
                    keys = [("item", p["slot"], e["handle"]) for e in entries]
                    b_all = TransparentPushButton("All")
                    b_all.clicked.connect(lambda _=False, ks=keys: self._ws_set(ks, True))
                    head.addWidget(b_all)
                    b_none = TransparentPushButton("None")
                    b_none.clicked.connect(lambda _=False, ks=keys: self._ws_set(ks, False))
                    head.addWidget(b_none)
                    cl.addLayout(head)
                    for e in entries:
                        where = "chest" if e["box"] == "storage" else "held"
                        if e.get("pouch"):
                            where += ", in the pouch"
                        elif e.get("quick"):
                            where += ", in a quick slot"
                        row, cb = self._ws_box(
                            ("item", p["slot"], e["handle"]),
                            e["name"] + (f"  x{e['qty']}" if e["qty"] > 1 else ""),
                            False,
                            sub=where,
                        )
                        self.ws_item_rows.append((row, e["name"].lower(), src))
                        cl.addWidget(row)
                for b in p.get("blocked") or []:
                    row, cb = self._ws_box(
                        ("blocked", p["slot"], b.get("handle")),
                        b["name"],
                        False,
                        enabled=False,
                        note="worn: take it off in-game first"
                        if b.get("why") == "worn"
                        else "remove the ash in-game first",
                    )
                    self.ws_item_rows.append((row, b["name"].lower(), b.get("source") or "Other mod"))
                    cl.addWidget(row)
            self.ws_lay.addWidget(c)

        orphans = [p for p in s.get("vanilla_plan") or [] if (slot is None or p["slot"] == slot) and p.get("orphans")]
        if orphans:
            any_section = True
            c, cl = card("Cleanup", FI.DELETE)
            cl.addWidget(
                hint(
                    "Leftover item rows nothing holds or wears, usually from co-op partners' gear. Invisible in play. Off by default."
                )
            )
            for p in orphans:
                who = name_of.get(p["slot"], f"slot {p['slot'] + 1}")
                names = ", ".join(o["name"] for o in p["orphans"][:6]) + (
                    f", +{len(p['orphans']) - 6} more" if len(p["orphans"]) > 6 else ""
                )
                row, _ = self._ws_box(
                    ("orphans", p["slot"]),
                    f"{who}: clear {len(p['orphans'])} leftover row{'s' if len(p['orphans']) != 1 else ''}",
                    False,
                    sub=names,
                )
                cl.addWidget(row)
            self.ws_lay.addWidget(c)

        cs = s.get("checksum_fixes") or {}
        ed = [sl for sl in cs.get("slots") or [] if slot is None or sl == slot]
        if ed or (slot is None and (cs.get("ud10") or s.get("needs_repair"))):
            any_section = True
            c, cl = card("For save editors", FI.CERTIFICATE)
            cl.addWidget(hint("The game loads the file either way; save editors refuse it. Ticked by default."))
            for sl in ed:
                row, _ = self._ws_box(
                    ("checksum", sl),
                    f"Recompute the checksum: {name_of.get(sl, 'slot ' + str(sl + 1))}",
                    True,
                    sub="stale character checksum",
                )
                cl.addWidget(row)
            if slot is None and cs.get("ud10"):
                row, _ = self._ws_box(("checksum", "ud10"), "Recompute the profile summary checksum", True)
                cl.addWidget(row)
            if slot is None and s.get("needs_repair"):
                nr = any(f.get("code") == "checksum" for f in s.get("findings") or [])
                row, _ = self._ws_box(
                    ("regulation",),
                    "Repair the regulation block",
                    True,
                    sub=(
                        "re-signs every section; restores entry 12 from a healthy copy next to this file when it can"
                        if nr
                        else "puts the game's regulation.bin back; me3 dirties it every session"
                    ),
                )
                cl.addWidget(row)
            self.ws_lay.addWidget(c)

        damaged = [
            f for f in s.get("findings") or [] if f.get("code") in ("layout", "read") and f.get("level") == "error"
        ]
        if damaged and slot is None:
            c, cl = card("This file could not be read fully", FI.INFO)
            for f in damaged:
                lab = BodyLabel(f.get("title") or "Damaged")
                lab.setWordWrap(True)
                cl.addWidget(lab)
                cl.addWidget(hint(f.get("detail") or ""))
            cl.addWidget(
                hint(
                    "Nothing here is written to a damaged file. Restore a backup from before the crash on the Saves page."
                )
            )
            self.ws_lay.addWidget(c)
        elif not any_section:
            c, cl = card("Nothing to fix here", FI.ACCEPT)
            cl.addWidget(
                hint(
                    "No loading risk, no mod items, no stale checksum"
                    + (" on this character." if slot is not None else " on this file.")
                )
            )
            self.ws_lay.addWidget(c)
        self._ws_recount()

    def _ws_set(self, keys, value):
        for k in keys:
            cb = self.ws_boxes.get(k)
            if cb is not None and cb.isEnabled():
                cb.setChecked(value)

    def _ws_filter_items(self, *_):
        text = (self.ws_search.text() if self.ws_search else "").strip().lower()
        source = self.ws_filter.currentText() if getattr(self, "ws_filter", None) else "All mods"
        for row, name, src in self.ws_item_rows:
            row.setVisible((not text or text in name) and source in ("All mods", src))

    def _ws_reset(self):
        self.ws_state = {}
        self._ws_build_content()

    def _ws_selected(self):
        if self.ws_info is None:
            return []
        keys = [k for k, dflt in self._ws_fix_keys(None) if self.ws_state.get(k, dflt)]
        return keys

    def _ws_recount(self):
        if self.ws_info is None:
            return  # workshop never opened yet
        keys = self._ws_selected()
        kinds = {}
        for k in keys:
            kinds[k[0]] = kinds.get(k[0], 0) + 1
        chars = {k[1] for k in keys if len(k) > 1 and isinstance(k[1], int)}
        if not keys:
            self.ws_note.setText(
                "Nothing selected. Tick the fixes to apply; loading and checksum fixes start ticked, removals start off."
            )
        else:
            bits = []
            if kinds.get("loading"):
                bits.append(f"{kinds['loading']} loading fix{'es' if kinds['loading'] != 1 else ''}")
            if kinds.get("item"):
                bits.append(f"remove {kinds['item']} item{'s' if kinds['item'] != 1 else ''}")
            if kinds.get("orphans"):
                bits.append(
                    f"clear leftover rows on {kinds['orphans']} character{'s' if kinds['orphans'] != 1 else ''}"
                )
            if kinds.get("checksum"):
                bits.append(f"{kinds['checksum']} checksum{'s' if kinds['checksum'] != 1 else ''}")
            if kinds.get("regulation"):
                bits.append("regulation block repair")
            self.ws_note.setText(
                f"Apply {len(keys)} change{'s' if len(keys) != 1 else ''}: "
                + ", ".join(bits)
                + (f" on {len(chars)} character{'s' if len(chars) != 1 else ''}" if chars else "")
                + ". A backup is made first; Undo appears afterwards."
            )
        if self.game_running:
            self.ws_note.setText(
                f"{self.game.name} is running. You can review and tick, but nothing is written until you quit the game."
                + (f"  ({len(keys)} ticked)" if keys else "")
            )
        elif self.busy:
            self.ws_note.setText("A job is running. Apply unlocks when it finishes.")
        self.ws_bar.pending = bool(keys) and not self.game_running
        self.ws_bar.update()
        self.ws_apply.setEnabled(bool(keys) and not self.busy and not self.game_running)
        self.ws_apply.setText("Apply" if not keys else f"Apply {len(keys)}")
        self.ws_apply.setToolTip(
            f"Close {self.game.name} first."
            if self.game_running
            else ("Wait for the current job." if self.busy else "Write the ticked changes, after one more confirm.")
        )

    def _ws_apply(self):
        if self.busy or self.game_running:
            self._toast(
                "Cannot apply now",
                f"Close {self.game.name} first." if self.game_running else "Wait for the current job.",
                error=True,
            )
            return
        keys = self._ws_selected()
        if not keys:
            return
        path = self.ws_info["path"]
        loading = {}
        vanilla = {}
        checksums = False
        regulation = False
        for k in keys:
            if k[0] == "loading":
                loading.setdefault(k[1], []).append(k[2])
            elif k[0] == "item":
                vanilla.setdefault(k[1], {"items": set(), "orphans": False})["items"].add(k[2])
            elif k[0] == "orphans":
                vanilla.setdefault(k[1], {"items": set(), "orphans": False})["orphans"] = True
            elif k[0] == "checksum":
                checksums = True
            elif k[0] == "regulation":
                regulation = True
        n_items = sum(len(v["items"]) for v in vanilla.values())
        names = {c["slot"] - 1: (c["name"] or f"slot {c['slot']}") for c in self.ws_info.get("characters") or []}
        lines = []
        for sl, keys_l in loading.items():
            lines.append(f"{names.get(sl, sl)}: {len(keys_l)} loading fix{'es' if len(keys_l) != 1 else ''}")
        for sl, v in vanilla.items():
            bits = []
            if v["items"]:
                bits.append(f"remove {len(v['items'])} item{'s' if len(v['items']) != 1 else ''}")
            if v["orphans"]:
                bits.append("clear leftover rows")
            lines.append(f"{names.get(sl, sl)}: " + ", ".join(bits))
        if checksums:
            lines.append("Recompute the stale checksums")
        if regulation:
            lines.append("Repair the regulation block")
        if not confirm(
            self,
            f"Apply {len(keys)} change{'s' if len(keys) != 1 else ''} to {path.name}",
            changes=lines,
            warning=WRITE_WARNING,
            safety=WRITE_SAFETY,
            detail=(
                f"{n_items} item{'s' if n_items != 1 else ''} will be gone from this file. The mods give them back in co-op."
                if n_items
                else ""
            ),
            apply_text=f"Apply {len(keys)}",
        ):
            return

        def job(_setup, loc):
            run_logging.start_log(f"launcher: apply {len(keys)} change(s) to {path.name}", loc.game.key)
            backups = []
            try:
                if loading:
                    out = fix_loading(path, selection=loading, loc=loc)
                    backups.append(out.get("backup"))
                if vanilla:
                    out = restore_vanilla(path, selection=vanilla, loc=loc)
                    backups.append(out.get("backup"))
                if checksums:
                    out = fix_checksums(path, loc=loc)
                    backups.append(out.get("backup"))
                if regulation:
                    repair_save(path, loc=loc)
                first = next((b for b in backups if b), None)
                self._undo = (path, first) if first else None
                run_logging.log(f"done: applied {len(keys)} change(s) to {path.name}")
            except Exception as e:
                run_logging.log(f"error: {e}")
                raise SystemExit(1) from e

        self.start(job, f"Applying changes to {path.name}...", need_setup=False)

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
