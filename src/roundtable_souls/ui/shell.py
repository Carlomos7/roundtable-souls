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
from typing import Any

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QSizePolicy,
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
    LineEdit,
    NavigationItemPosition,
    PasswordLineEdit,
    RoundMenu,
    SearchLineEdit,
    SpinBox,
    StrongBodyLabel,
    SwitchButton,
    TableWidget,
    Theme,
    TitleLabel,
    TransparentPushButton,
    isDarkTheme,
    setTheme,
    setThemeColor,
)
from qfluentwidgets import FluentIcon as FI

from roundtable_souls.config.settings import FROZEN, appimage, exe_dir, is_installed, is_portable
from roundtable_souls.game import catalog as games
from roundtable_souls.game.locate import Locations, installed_dir
from roundtable_souls.mods import checks as mod_checks
from roundtable_souls.mods import configs as mod_configs
from roundtable_souls.mods import conflicts as mod_overview
from roundtable_souls.mods import extract as mod_extract
from roundtable_souls.mods import history as mod_history
from roundtable_souls.mods import install as mod_install
from roundtable_souls.mods import stay_last as mod_stay_last
from roundtable_souls.mods import undo as mod_undo
from roundtable_souls.platform import data_folder, desktop, instance, trash
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.resources import ASSETS_DIR
from roundtable_souls.saves import backups as save_backups
from roundtable_souls.saves import library as save_library
from roundtable_souls.saves import transfer as save_transfer
from roundtable_souls.services import play as core
from roundtable_souls.services import saves as saves_service
from roundtable_souls.services.coop import (
    CUSTOM,
    SAVE_KINDS,
    SCALING_KEYS,
    SCALING_LABELS,
    SCALING_PRESETS,
    VOLUME_STOPS,
    choice_label,
    export_text,
    label_of,
    parse_settings_json,
    plan_import,
    read_settings_meta,
    setting_face,
    write_keys,
    write_password,
)
from roundtable_souls.services.mods import (
    create_profile,
    delete_profile,
    install_mod,
    me3_facts,
    plan_mod_install,
    profile_entries,
    read_profile_mods,
    read_profile_settings,
    replan_mod_install,
    set_mod_options,
    uninstall_mod,
    write_profile_setting,
)
from roundtable_souls.services.play import (
    TITLE,
    VERSION,
    discover,
    forget_setup,
    has_password,
    job_clear,
    job_play,
    job_play_offline,
    job_repair,
    logo_path,
    places,
    play_command,
    play_options,
    preset_of,
    read_password,
    read_scaling,
    remember_setup,
    remembered_setup,
    report_exception,
    route_logs,
    same_source,
    save_info,
    scaling_spec,
    setup_from_path,
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
    game_setting,
    load_settings,
    save_game_settings,
    save_settings,
)
from roundtable_souls.services.updates import RELEASES_URL
from roundtable_souls.ui.activity import ActivityView
from roundtable_souls.ui.config_files import ConfigFilesDialog
from roundtable_souls.ui.dialogs import (
    WRITE_SAFETY,
    WRITE_WARNING,
    ChoiceListDialog,
    ConfirmDialog,
    ModOptionsDialog,
    TextDialog,
    VersionsDialog,
    ask_unsaved,
    confirm,
)
from roundtable_souls.ui.install_dialog import InstallDialog
from roundtable_souls.ui.jobs import Jobs
from roundtable_souls.ui.notes import _save_note_widget, save_check_notes
from roundtable_souls.ui.save_dialogs import CopyCharacterDialog, CopyFileDialog, SwapDialog
from roundtable_souls.ui.theme import (
    ACCENT,
    ACCENT_LIGHT,
    BG_DARK,
    BG_LIGHT,
    COMPACT,
    HINT,
    HINT_ON_LIGHT,
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
    DropOverlay,
    EditorPanel,
    ElideLabel,
    ExpandGroupSettingCard,
    GlassCard,
    HeroBanner,
    LogoPreview,
    LogPane,
    MenuButton,
    NameWithTag,
    PairRow,
    PathTag,
    SettingRow,
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
    short_problem,
    style_menu,
    style_navigation,
    tidy_log_line,
    titled,
    tone_label,
)
from roundtable_souls.updates import apply as updates
from roundtable_souls.updates import feed
from roundtable_souls.updates import inno as migration

ROW_ACTION_W = 156  # the action button on each Mods row


# ----------------------------------------------------------------------------- window
class Launcher(FluentWindow):
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

    # ---------------------------------------------------------------- Play page
    def _build_play(self):
        self.play_page, lay = page("playPage")
        self.hero = HeroBanner()
        self.play_btn = self.hero.play_btn
        self.play_btn.clicked.connect(self.launch)
        self.ring = self.hero.ring
        self.ready = self.hero.ready
        self.status_pill = self.hero.status_pill
        self.status = self.hero.status
        self.stat_level = self.hero.stat_level
        self.stat_save = self.hero.stat_save
        self.stat_body = self.hero.stat_body
        lay.addWidget(self.hero)
        self.plan = hint("")
        lay.addWidget(self.plan)
        self.setup_exp = ExpandGroupSettingCard(FI.SETTING, "Setup", "The profile Play launches.")
        body = QWidget()
        cl = QVBoxLayout(body)
        cl.setContentsMargins(16, 8, 16, 12)
        cl.setSpacing(10)
        row = QHBoxLayout()
        self.setup_box = ComboBox()
        self.setup_box.setMinimumWidth(140)
        self.setup_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setup_box.currentIndexChanged.connect(self._on_setup)
        b = ghost_btn("Browse...", FI.FOLDER)
        b.clicked.connect(self.browse)
        row.addWidget(self.setup_box, 1)
        row.addWidget(b)
        row.addWidget(self._folder_btn("game", "Game folder", FI.GAME, "The game's own folder, with its exe."))
        cl.addLayout(row)
        self.setup_hint = hint()
        cl.addWidget(self.setup_hint)
        self.setup_exp.addGroupWidget(body)
        lay.addWidget(self.setup_exp)
        self.log_exp = ExpandGroupSettingCard(
            FI.HISTORY, "Log", "What the running job is doing. Opens on its own if something goes wrong."
        )
        self.log_pane = LogPane(open_folder=self._open_logs, open_activity=lambda: self.switchTo(self.activity_page))
        self.log = self.log_pane.view
        self.log.setMinimumHeight(180)
        log_body = QWidget()
        ll = QVBoxLayout(log_body)
        ll.setContentsMargins(16, 8, 16, 12)
        ll.addWidget(self.log_pane)
        self.log_exp.addGroupWidget(log_body)
        lay.addWidget(self.log_exp)
        lay.addStretch(1)

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

    def _layout_scaling(self, cols):
        if cols == getattr(self, "_scal_cols", None):
            return
        self._scal_cols = cols
        for i, (lab, sp) in enumerate(zip(self.scal_labs, self.spins)):
            self.scal_grid.addWidget(lab, (i // cols) * 2, i % cols)
            self.scal_grid.addWidget(sp, (i // cols) * 2 + 1, i % cols)
        for c in range(3):
            self.scal_grid.setColumnStretch(c, 1 if c < cols else 0)

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

    # ---------------------------------------------------------------- Co-op page
    def _build_coop(self):
        root = QWidget()
        root.setObjectName("coopPage")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.coop_head = QWidget()
        hl = QVBoxLayout(self.coop_head)
        hl.setContentsMargins(40, 28, 40, 8)
        hl.setSpacing(0)
        titled(hl, "Co-op", FI.PEOPLE, "Seamless Co-op: difficulty, options, and the password where the mod has one.")
        outer.addWidget(self.coop_head)
        self.coop_scroll, lay = page("coopScroll")
        lay.setContentsMargins(40, 12, 40, 16)
        outer.addWidget(self.coop_scroll, 1)
        off, offl = card("No co-op in this setup", FI.PEOPLE)
        offl.addWidget(
            hint(
                "This setup does not load Seamless Co-op, so there is no password or difficulty to set. Pick a setup that includes it on the Play page."
            )
        )
        lay.addWidget(off)
        self.coop_off = off
        off.hide()
        self.coop_form = []
        c, cl = card("Session password", FI.CERTIFICATE)
        self.pw_card = c
        row = QHBoxLayout()
        self.pw = PasswordLineEdit()
        self.pw.setMinimumWidth(120)
        self.pw.setPlaceholderText("Friends type this to join")
        self.pw.textChanged.connect(self._on_pw_edit)
        row.addWidget(self.pw, 1)
        cl.addLayout(row)
        self.pw_hint = hint()
        cl.addWidget(self.pw_hint)
        lay.addWidget(c)
        self.coop_form.append(c)
        c, cl = card("Difficulty", FI.SPEED_HIGH)
        self.scal_about = hint("Percent per extra player. Only the host's numbers count.")
        cl.addWidget(self.scal_about)
        self.scaling = None  # the ScalingSpec of the loaded ini: which keys, labels and presets
        preset_row = QWidget()
        row = QHBoxLayout(preset_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.preset = ComboBox()
        self.preset.addItems(list(SCALING_PRESETS) + [CUSTOM])
        self.preset.setMinimumWidth(160)
        self.preset.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.preset.currentTextChanged.connect(self._on_preset)
        row.addWidget(BodyLabel("Preset"))
        row.addWidget(self.preset, 1)
        cl.addWidget(preset_row)
        self.preset_row = preset_row
        self.scal_grid = QGridLayout()
        self.scal_grid.setHorizontalSpacing(12)
        self.scal_grid.setVerticalSpacing(6)
        self.spins = []
        self.scal_labs = []
        for _i, label in enumerate(SCALING_LABELS):
            lab = CaptionLabel(label)
            self.scal_labs.append(lab)
            sp = SpinBox()
            sp.setRange(0, 500)
            sp.setSingleStep(5)
            sp.setMinimumWidth(72)
            sp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            sp.valueChanged.connect(self._on_scaling_edit)
            self.spins.append(sp)
        self._scal_cols = None
        self._layout_scaling(3)
        cl.addLayout(self.scal_grid)
        self.scal_hint = hint()
        cl.addWidget(self.scal_hint)
        lay.addWidget(c)
        self.coop_form.append(c)
        self.other_host = QWidget()
        self.all_box = QVBoxLayout(self.other_host)
        self.all_box.setContentsMargins(0, 0, 0, 0)
        self.all_box.setSpacing(10)
        lay.addWidget(self.other_host)
        self.coop_form.append(self.other_host)
        self.all_dirty = {}
        self.all_file = {}
        share = ExpandGroupSettingCard(FI.SHARE, "Share with a friend", "Copy yours, or paste a friend's and apply.")
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 12, 16, 14)
        self.share_panel = EditorPanel(
            "Paste a friend's settings, or copy yours.",
            "Apply",
            self.share_apply,
            tools=(
                ("Copy", FI.COPY, self.share_copy, "Copy the text to send it to a friend."),
                ("Paste", FI.PASTE, self.share_paste, "Replace the text with what is on the clipboard."),
                ("Open file...", FI.FOLDER, self.share_load, "Load settings someone saved to a file."),
                ("Save as...", FI.DOWNLOAD, self.share_save, "Save the text to a file."),
            ),
            on_discard=self.share_fill,
            lang="json",
            wrap=True,
            min_height=190,
            clean_note="Your current settings.",
            dirty_note="Different from your settings. Apply writes the differences, after a confirm.",
            primary_tip="Write the settings in the text to your co-op ini (you see every change first).",
        )
        self.share = self.share_panel.edit
        bl.addWidget(self.share_panel)
        share.addGroupWidget(body)
        lay.addWidget(share)
        self.coop_form.append(share)
        lay.addStretch(1)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(40, 8, 40, 20)
        self.save_bar = ActionBar(
            "Save",
            lambda: self._announce_saved(self.save_seamless(), "next"),
            (
                "Discard",
                FI.CANCEL,
                self._discard_coop,
                "Put the password, difficulty and other options back to what the file says.",
            ),
            note="Saved.",
        )
        self.save_bar.primary.setToolTip("Write the password, difficulty and any other options you changed. Ctrl+S.")
        self.all_note, self.all_save, self.all_discard = (
            self.save_bar.note,
            self.save_bar.primary,
            self.save_bar.secondary,
        )
        wl.addWidget(self.save_bar)
        outer.addWidget(wrap)
        self.coop_bar = wrap
        self.coop_page = root

    # ---------------------------------------------------------------- Mods page
    def _build_mods(self):
        self.mods_page, lay = page("modsPage")
        self.mods_page.setAcceptDrops(True)
        self.mods_page.viewport().setAcceptDrops(True)
        self.mods_drop = DropOverlay(self.mods_page, self._drop_accepts)
        self.mods_drop.dropped.connect(self._install_paths)
        QApplication.instance().installEventFilter(self)
        acts, al = action_row()
        self.mods_refresh = ghost_btn("Refresh", FI.SYNC)
        self.mods_refresh.clicked.connect(self._fill_mods)
        self.mods_install = ghost_btn("Install mod", FI.DOWNLOAD, role="action")
        self.mods_install.setToolTip(
            "A .zip, .7z or .rar, or a folder. Roundtable Souls works out whether it is a package or a DLL and adds it at the end of the load order."
        )
        self.mods_install.clicked.connect(self._install_mod)
        self.prof_new = ghost_btn("New profile", FI.ADD)
        self.prof_new.setToolTip("A fresh .me3 in me3's profile folder, empty or copied from the current one.")
        self.prof_new.clicked.connect(self._new_profile)
        self.prof_del = ghost_btn("Delete profile", FI.DELETE, role="danger")
        self.prof_del.setToolTip("Moves the .me3 into the launcher's deleted profiles. Mod folders stay.")
        self.prof_del.clicked.connect(self._delete_profile)
        al.addWidget(
            self._folder_btn("profile", "Profile folder", FI.FOLDER, "The folder holding this .me3 and its mods.")
        )
        al.addWidget(self.mods_install)
        al.addWidget(self.prof_new)
        al.addWidget(self.prof_del)
        al.addWidget(self.mods_refresh)
        titled(lay, "Mods", FI.LIBRARY, "What this profile loads.", acts)
        head = QHBoxLayout()
        head.setSpacing(10)
        self.mods_note = hint("")
        head.addWidget(self.mods_note)
        self.merge_pill = StatusPill()
        self.merge_pill.setClickable(True)
        self.merge_pill.clicked.connect(self._show_load_order)
        self.merge_pill.hide()
        head.addWidget(self.merge_pill)
        head.addStretch(1)
        lay.addLayout(head)
        self.pack_exp = ExpandGroupSettingCard(FI.FOLDER, "Packages", "File replacements.")
        self.nat_exp = ExpandGroupSettingCard(FI.CODE, "Natives", "DLLs.")
        lay.addWidget(self.pack_exp)
        lay.addWidget(self.nat_exp)
        c, cl = card("Profile settings", FI.SETTING)
        cl.addWidget(
            hint(
                "The me3 options this profile can set. Written into the .me3 file next to profileVersion, with one .bak. me3 reads them at the next launch."
            )
        )
        self.ps = {}
        for key in ("mem_patch", "disable_arxan", "start_online"):
            box = ComboBox()
            box.addItems(["me3 default", "On", "Off"])
            box.setMinimumWidth(140)
            box.currentIndexChanged.connect(
                lambda idx, k=key: self._on_profile_setting(k, {1: True, 2: False}.get(idx))
            )
            self.ps[key] = box
            title, blurb = core.profile_tools.SETTING_TEXT[key]
            cl.addWidget(
                SettingRow(
                    title,
                    blurb,
                    box,
                    blurb + (" me3 warns this is a ban risk with modded data." if key == "start_online" else ""),
                )
            )
        sp = SpinBox()
        sp.setRange(0, 65536)
        sp.setSingleStep(1024)
        sp.setMinimumWidth(140)
        sp.editingFinished.connect(lambda: self._on_profile_setting("mem_patch_heap_size", sp.value()))
        self.ps["mem_patch_heap_size"] = sp
        title, blurb = core.profile_tools.SETTING_TEXT["mem_patch_heap_size"]
        cl.addWidget(SettingRow(title, blurb, sp, blurb))
        le = LineEdit()
        le.setClearButtonEnabled(True)
        le.setPlaceholderText(f"{self.game.save_stem}.sl2 (default)")
        le.setMinimumWidth(200)
        self.savefile_edit = le
        le.editingFinished.connect(lambda: self._on_profile_setting("savefile", le.text().strip()))
        self.ps["savefile"] = le
        title, blurb = core.profile_tools.SETTING_TEXT["savefile"]
        cl.addWidget(SettingRow(title, blurb, le, blurb + " Seamless Co-op names its own .co2 regardless."))
        self.ps_note = hint("")
        cl.addWidget(self.ps_note)
        lay.addWidget(c)
        self.ps_card = c
        self.load_exp = ExpandGroupSettingCard(FI.INFO, "Load order", "What this profile loads, and what wins.")
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 12, 16, 16)
        bl.setSpacing(8)
        # the mod that must stay last
        self.last_row = QWidget()
        ll = QVBoxLayout(self.last_row)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(6)
        self.last_head = StrongBodyLabel("Stays last")
        ll.addWidget(self.last_head)
        self.last_text = hint("")
        self.last_text.setWordWrap(True)
        ll.addWidget(self.last_text)
        lrow, lbar = action_row()
        self.fix_order_btn = ghost_btn("Fix order", FI.SYNC)
        self.fix_order_btn.setToolTip(
            "Put the mod that must stay last after these again (only its own entries change)."
        )
        self.fix_order_btn.clicked.connect(self._fix_order)
        self.keep_after_btn = ghost_btn("Keep it after", FI.ACCEPT)
        self.keep_after_btn.setToolTip("They load after it on purpose: stop warning (kept in roundtable.json).")
        self.keep_after_btn.clicked.connect(lambda: self._keep_after(True))
        self.put_before_btn = ghost_btn("Put them before", FI.RETURN)
        self.put_before_btn.setToolTip("Stop keeping these after it, and put it after them again.")
        self.put_before_btn.clicked.connect(lambda: self._keep_after(False))
        for b in (self.fix_order_btn, self.keep_after_btn, self.put_before_btn):
            lbar.addWidget(b)
        ll.addWidget(lrow)
        self.last_row.hide()
        bl.addWidget(self.last_row)
        # parameters
        self.merge_row = QWidget()
        pl = QVBoxLayout(self.merge_row)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(6)
        pl.addWidget(StrongBodyLabel("Parameters"))
        self.merge_text = hint("")
        self.merge_text.setWordWrap(True)
        pl.addWidget(self.merge_text)
        self.merge_reasons = hint("")
        self.merge_reasons.setWordWrap(True)
        pl.addWidget(self.merge_reasons)
        self.merge_rows_note = hint("")
        self.merge_rows_note.setWordWrap(True)
        self.merge_rows_note.hide()
        pl.addWidget(self.merge_rows_note)
        prow, pbar = action_row()
        self.merge_btn = ghost_btn("Rebuild", FI.SYNC)
        self.merge_btn.setToolTip(
            "Combine the packs' parameters and run the rebuild tool of the package that must stay last, if there is one."
        )
        self.merge_btn.clicked.connect(
            lambda: self._rebuild_merge(
                combine=True if (getattr(self, "_merge_health", None) or {}).get("state") == "stacked" else None
            )
        )
        pbar.addWidget(self.merge_btn)
        pl.addWidget(prow)
        brow, bbar = action_row()
        self.backups_note = hint("")
        self.backups_note.setWordWrap(True)
        self.trim_btn = ghost_btn("Keep the newest 3", FI.DELETE)
        self.trim_btn.setToolTip("Move older rebuild backups to the Recycle Bin. The newest 3 stay for Undo.")
        self.trim_btn.clicked.connect(self._trim_tool_backups)
        bbar.addWidget(self.trim_btn)
        pl.addWidget(self.backups_note)
        pl.addWidget(brow)
        self.backups_row = brow
        bl.addWidget(self.merge_row)
        # files
        files_head = StrongBodyLabel("Files two packages both ship")
        bl.addSpacing(8)
        bl.addWidget(files_head)
        bl.addWidget(
            hint(
                "me3 uses the later package's copy. Where a rebuild or the launcher's combine folds a file together, "
                "the earlier copies are in the result instead: those say combined, as long as it is up to date."
            )
        )
        self.conf_note = hint("Not scanned yet.")
        bl.addWidget(self.conf_note)
        self.conf_packages = hint("")
        self.conf_packages.setWordWrap(True)
        bl.addWidget(self.conf_packages)
        self.conf_rows = QVBoxLayout()
        self.conf_rows.setSpacing(4)
        bl.addLayout(self.conf_rows)
        crow, cbar = action_row()
        self.conf_more = ghost_btn("Show all")
        self.conf_more.setVisible(False)
        self.conf_more.clicked.connect(self._toggle_conflicts)
        cbar.addWidget(self.conf_more)
        b = ghost_btn("Refresh", FI.SYNC)
        b.clicked.connect(self._scan_conflicts)
        cbar.addWidget(b)
        bl.addWidget(crow)
        # problems
        self.problems_head = StrongBodyLabel("Entries me3 would refuse")
        bl.addSpacing(8)
        bl.addWidget(self.problems_head)
        self.problems_note = hint("")
        self.problems_note.setWordWrap(True)
        bl.addWidget(self.problems_note)
        self.load_exp.addGroupWidget(body)
        lay.addWidget(self.load_exp)
        self.conf_card = self.load_exp
        self._conf_all = False
        self._conf_result = None
        edit = ExpandGroupSettingCard(FI.EDIT, "Edit profile", "The me3 file for the setup on Play.")
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 12, 16, 14)
        vrow, vbar = action_row()
        self.versions_btn = ghost_btn("Versions...", FI.HISTORY)
        self.versions_btn.setToolTip("Earlier versions of this profile, kept before every change; restore any of them.")
        self.versions_btn.clicked.connect(self._show_versions)
        vbar.addWidget(self.versions_btn)
        bl.addWidget(vrow)
        self.profile_panel = EditorPanel(
            "The me3 file for the setup on Play.",
            "Save",
            self._save_profile,
            on_discard=lambda: self._load_profile_editor(force=True),
            min_height=320,
            clean_note="Matches the file.",
            dirty_note="Edited. Not saved yet.",
            primary_tip="Write the me3 file; one .bak of the previous version is kept. Ctrl+S.",
        )
        self.profile_panel.bar.secondary.setToolTip("Read the file again and drop the edits.")
        self.profile_edit = self.profile_panel.edit
        bl.addWidget(self.profile_panel)
        edit.addGroupWidget(body)
        lay.addWidget(edit)
        self.profile_exp = edit
        lay.addStretch(1)
        self._profile_file = None
        self._profile_crlf = False

    def _load_profile_settings(self):
        if not self.setup:
            return
        vals = read_profile_settings(self.setup.profile)
        for key in ("mem_patch", "disable_arxan", "start_online"):
            box = self.ps[key]
            box.blockSignals(True)
            box.setCurrentIndex({True: 1, False: 2}.get(vals.get(key), 0))
            box.blockSignals(False)
        sp = self.ps["mem_patch_heap_size"]
        sp.blockSignals(True)
        sp.setValue(int(vals.get("mem_patch_heap_size") or 0))
        sp.blockSignals(False)
        sp.setEnabled(vals.get("mem_patch") is not False)  # me3 only uses it with the memory patch on
        sp.setToolTip("" if vals.get("mem_patch") is not False else "Turn the memory patch on to use this.")
        le = self.ps["savefile"]
        le.blockSignals(True)
        le.setText(str(vals.get("savefile") or ""))
        le.blockSignals(False)
        self.ps_note.setText(
            "Online matchmaking is ON in this profile: me3 calls that a ban risk with modded data."
            if vals.get("start_online")
            else ""
        )
        if vals.get("start_online"):
            tone_label(self.ps_note, "error")
        else:
            tone_label(self.ps_note, "muted")

    def _on_profile_setting(self, key, value):
        if not self.setup or getattr(self, "_loading_setups", False):
            return
        if self.profile_panel.dirty:
            self._toast(
                "Profile has unsaved edits",
                "Save or reload the profile editor first, then change this setting.",
                error=True,
            )
            self._load_profile_settings()
            return
        if key == "start_online" and value is True:
            if not confirm(
                self,
                "Turn online matchmaking on",
                changes=["This profile starts the game with the official servers reachable"],
                warning="me3 blocks matchmaking by default because playing online with modded data can get the account banned.",
                safety="Nothing else in the profile changes; a .bak of the file is kept.",
                apply_text="Turn on",
            ):
                self._load_profile_settings()
                return
        try:
            changed = write_profile_setting(self.setup.profile, key, value)
        except Exception as e:
            self._toast("Could not write the profile", str(e), error=True)
            self._load_profile_settings()
            return
        if changed:
            self._log(f"profile: {key} = {value if value not in (None, '') else 'me3 default'}")
            self._undo_notice(f"{core.profile_tools.SETTING_TEXT[key][0]} changed", "It applies at the next launch.")
            self._load_profile_editor(force=True)
        self._load_profile_settings()

    def _scan_conflicts(self):
        """Work out the Load order card and the pill on a worker thread (the rebuild tool's sources are hashed,
        cached by size and date)."""
        if not self.setup:
            return
        self.conf_note.setText("Scanning packages...")
        prof = Path(self.setup.profile)

        def work(_progress):
            try:
                return mod_overview.overview(prof)
            except Exception as e:  # never leave the card saying "Scanning..."
                return {"profile": str(prof), "error": str(e)}

        self.jobs.start(work, on_result=self._fill_conflicts)

    _refresh_overview = _scan_conflicts

    def _toggle_conflicts(self):
        self._conf_all = not self._conf_all
        if self._conf_result:
            self._fill_conflicts(self._conf_result)

    def _show_load_order(self):
        self.load_exp.setExpand(True)
        QTimer.singleShot(0, lambda: self.mods_page.ensureWidgetVisible(self.load_exp, 0, 40))

    def _order_unverified(self) -> str | None:
        """A note when the installed me3 is a version whose load order the launcher's was not checked against."""
        from roundtable_souls.mods import order

        version = (getattr(self, "_me3", None) or {}).get("version")
        if not version or order.supported(version):
            return None
        return f"load order worked out as me3 {order.ME3_ORDER_VERSIONS[0]} and later do; not checked for me3 {version}"

    def _fill_conflicts(self, r):
        if self.setup and r.get("profile") and not mod_checks.same_folder(Path(r["profile"]), Path(self.setup.profile)):
            return  # an answer for a profile no longer shown
        self._conf_result = r
        if r.get("health") is not None:
            self._on_merge({**r["health"], "profile": r.get("profile", "")})
        for i in reversed(range(self.conf_rows.count())):
            it = self.conf_rows.takeAt(i)
            dispose(it.widget())
        scan = r.get("scan") or {}
        err = r.get("error") or scan.get("error")
        if err:
            self.conf_note.setText(f"Could not scan: {err}")
            tone_label(self.conf_note, "error")
            self.conf_more.setVisible(False)
            self.conf_packages.setText("")
            return
        ov = r.get("overlaps") or {}
        counts = ov.get("counts") or {}
        cf = ov.get("conflicts") or []
        pk = scan.get("packages") or []
        missing = [p["id"] for p in pk if p.get("missing")]
        parts = [f"{len(pk)} package{'s' if len(pk) != 1 else ''}, {scan.get('files', 0):,} files"]
        if not cf:
            parts.append("no file is shipped twice")
        else:
            parts.append(f"{len(cf)} shipped by more than one")
            parts += [f"{counts[k]} {mod_overview.OUTCOME_TEXT[k]}" for k in mod_overview.OUTCOMES if counts.get(k)]
        if missing:
            parts.append("missing folder: " + ", ".join(missing))
        if scan.get("truncated"):
            parts.append("scan stopped early (very large packages)")
        refused = scan.get("order_problem")
        if refused:  # first: the rest of the card assumes an order me3 would never use
            parts.insert(0, f"me3 will not start with this profile ({refused}); the order below is the file's")
        unverified = self._order_unverified()
        if unverified:
            parts.append(unverified)
        self.conf_note.setText("  \u00b7  ".join(parts))
        bad = counts.get("stale") or counts.get("unreached") or missing
        tone_label(self.conf_note, "error" if missing or refused else "warning" if bad else "muted")
        per = ov.get("packages") or {}
        lines = []
        for pid, n in per.items():
            bits = [f"{n[k]} {mod_overview.OUTCOME_TEXT[k]}" for k in mod_overview.OUTCOMES if n.get(k)]
            if n.get("wins"):
                bits.insert(0, f"used {n['wins']}")
            if bits:
                lines.append(f"{pid}: {', '.join(bits)}")
        self.conf_packages.setText("\n".join(lines))
        self.conf_packages.setVisible(bool(lines))
        shown = cf if self._conf_all else cf[:12]
        for c in shown:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(10)
            cat = CaptionLabel(c["category"])
            cat.setFixedWidth(96)
            tone_label(cat, "muted")
            rl.addWidget(cat)
            lab = ElideLabel(c["path"])
            lab.elide_mode = Qt.ElideMiddle
            lab.setText(c["path"])
            rl.addWidget(lab, 1)
            said = ", ".join(f"{l['id']} {mod_overview.OUTCOME_TEXT[l['outcome']]}" for l in c["losers"])
            who = hint(f"{c['winner']} is used; {said}")
            who.setWordWrap(True)
            worst = {l["outcome"] for l in c["losers"]}
            tone_label(who, "warning" if worst & {"stale", "unreached"} else "muted")
            rl.addWidget(who, 1)
            self.conf_rows.addWidget(row)
        self.conf_more.setVisible(len(cf) > 12)
        self.conf_more.setText("Show fewer" if self._conf_all else f"Show all {len(cf)}")
        backups = r.get("tool_backups") or []
        total = sum(b["size"] for b in backups)
        self.backups_note.setText(
            f"The rebuild tool keeps {len(backups)} backup{'s' if len(backups) != 1 else ''} "
            f"({total / 1048576:,.0f} MB) in the profile's folder; it never removes them itself."
        )
        self.backups_note.setVisible(bool(backups))
        self.backups_row.setVisible(len(backups) > 3)
        rows = r.get("rows") or []
        self.merge_rows_note.setText(
            "\n".join(rows[:13]) + (f"\n  and {len(rows) - 13} more in the rebuild's log" if len(rows) > 13 else "")
        )
        self.merge_rows_note.setVisible(bool(rows))
        late = self._fill_stay_last(r.get("stay_last"))
        probs = r.get("problems") or []
        self.problems_head.setVisible(bool(probs))
        self.problems_note.setVisible(bool(probs))
        self.problems_note.setText("\n".join(f"{p['name']}: {'; '.join(p['problems'])}" for p in probs))
        tone_label(self.problems_note, "error")
        summary = [self.merge_pill.text()] if not self.merge_pill.isHidden() else []
        summary += [f"{counts[k]} {mod_overview.OUTCOME_TEXT[k]}" for k in mod_overview.OUTCOMES if counts.get(k)]
        if late:
            summary.insert(0, f"{len(late)} load{'s' if len(late) == 1 else ''} after {r['stay_last']['name']}")
        if probs:
            summary.append(f"{len(probs)} entr{'y' if len(probs) == 1 else 'ies'} me3 would refuse")
        self.load_exp.card.setContent("  \u00b7  ".join(summary) or "No file is shipped twice")

    def _fill_stay_last(self, st) -> list[str]:
        """The Stays last section: what loads after the mod that must stay last, and the buttons to fix or keep it.
        Returns the names loading after it without being kept there on purpose."""
        self._stay_last = st
        if not st:
            self.last_row.hide()
            return []
        late, kept, name = st.get("late") or [], st.get("kept") or [], st["name"]
        lines = []
        if late:
            who = ", ".join(late[:4]) + (f" and {len(late) - 4} more" if len(late) > 4 else "")
            verb = "loads" if len(late) == 1 else "load"
            lines.append(f"{who} {verb} after {name} and replace{'s' if len(late) == 1 else ''} its files.")
        else:
            lines.append(f"{name} loads after every other mod, so it includes their changes.")
        if kept:
            lines.append(f"Kept after it on purpose: {', '.join(kept)}.")
        if st.get("problem"):
            lines.append(st["problem"])
        self.last_text.setText(" ".join(lines))
        tone_label(self.last_text, "error" if st.get("problem") else "warning" if late else "muted")
        self.fix_order_btn.setVisible(bool(late) and bool(st.get("can_fix")) and not st.get("problem"))
        self.keep_after_btn.setVisible(bool(late))
        self.put_before_btn.setVisible(bool(st.get("kept_setting")))
        self.last_row.show()
        was = getattr(self, "_late_before", None)
        self._late_before = late
        if late and late != was:
            self.load_exp.setExpand(True)  # something replaces its files: show it once
        return late

    def _fix_order(self):
        if self._mods_locked():
            return
        prof = Path(self.setup.profile)
        try:
            problem = mod_stay_last.fix(prof)
        except OSError as e:
            problem = str(e)
        if problem:
            self._toast("Could not fix the load order", problem, error=True)
            return
        name = (getattr(self, "_stay_last", None) or {}).get("name", "It")
        self._after_profile_change(f"profile: {name} put after every other mod again")
        self._undo_notice("Load order fixed", f"{name} loads after every other mod again.")

    def _keep_after(self, keep: bool):
        if self._mods_locked():
            return
        st = getattr(self, "_stay_last", None) or {}
        prof = Path(self.setup.profile)
        names = st.get("late") if keep else st.get("kept_setting")
        if not names:
            return
        try:
            mod_stay_last.keep_after(prof, list(names), keep)
            if not keep:
                problem = mod_stay_last.fix(prof)
                if problem:
                    self._toast("Could not fix the load order", problem, error=True)
        except (OSError, mod_stay_last.Unreadable) as e:
            self._toast("Could not save that", str(e), error=True)
            return
        self._after_profile_change(
            f"profile: {', '.join(names)} {'kept after' if keep else 'no longer kept after'} {st.get('name')}"
        )

    def _fill_mods(self):
        keep_p, keep_n = self.pack_exp.isExpand, self.nat_exp.isExpand
        self._load_profile_settings()
        self._scan_conflicts()  # the Load order card and the pill, from one scan
        first = not getattr(self, "_mods_seen", False)
        for exp in (self.pack_exp, self.nat_exp):
            while exp.viewLayout.count():
                it = exp.viewLayout.takeAt(0)
                w = it.widget()
                if w:
                    w.deleteLater()
            exp.widgets.clear()
        s = self.setup
        if not s or not Path(s.profile).is_file():
            self.mods_note.setText("Pick a setup on Play.")
            self.pack_exp.card.setContent("None")
            self.nat_exp.card.setContent("None")
            self._mod_group(self.pack_exp, [], "package")
            self._mod_group(self.nat_exp, [], "native")
            self._load_profile_editor()
            return
        mods = profile_entries(s.profile)
        self._profile_seen = self._profile_stamp()
        packs = [m for m in mods if m["kind"] == "package"]
        nats = [m for m in mods if m["kind"] == "native"]
        self.mods_note.setText(Path(s.profile).name)
        self._offer_tool_approval(Path(s.profile))
        self.mods_note.setToolTip(s.profile)
        try:
            self._pack_tree = mod_checks.package_tree(Path(s.profile), mods)
            self._mod_problems = mod_checks.entry_problems(Path(s.profile), mods)
            self._mod_roots = core.mod_manage.roots(Path(s.profile), core.mod_manage.read_text(Path(s.profile)))
            folders = mod_checks.folder_overview(Path(s.profile), mods, self._pack_tree)
        except OSError:
            self._pack_tree, self._mod_roots, self._mod_problems = {}, (None, None), {}
            folders = {"packages": None, "natives": None}
        holders = set((folders["packages"] or {}).get("holders") or [])
        packs = [m for m in packs if m["index"] not in holders]  # folders of mods are shown as folders, not mods
        for exp, group in ((self.pack_exp, packs), (self.nat_exp, nats)):
            on = sum(1 for m in group if m["enabled"])
            exp.card.setContent(
                (f"{on} loaded" + (f", {len(group) - on} off" if len(group) != on else "")) if group else "None"
            )
        self._mod_group(self.pack_exp, packs, "package", folders["packages"], mods)
        self._mod_group(self.nat_exp, nats, "native", folders["natives"], mods)
        self.pack_exp.setExpand(True if first else keep_p)
        self.nat_exp.setExpand(True if first else keep_n)
        self._mods_seen = True
        self._load_profile_editor()

    def _mod_group(self, exp, mods, kind, folder=None, entries=()):
        for row in self._folder_rows(kind, folder, entries) if folder else []:
            exp.addGroupWidget(row)
        if not mods:
            lab = hint("Nothing in this profile.")
            lab.setContentsMargins(20, 12, 20, 12)
            exp.addGroupWidget(lab)
            return
        tree = getattr(self, "_pack_tree", {}) or {}
        for m in mods:
            row = QWidget()
            row.setMinimumHeight(52)
            h = QHBoxLayout(row)
            h.setContentsMargins(20, 6, 16, 6)
            h.setSpacing(10)
            text = QVBoxLayout()
            text.setSpacing(2)
            line = NameWithTag(m["name"], self._where_parts(m), self._where_tip(m))
            name = line.name
            text.addWidget(line)
            node = tree.get(m["index"]) if m["kind"] == "package" else None
            bits = []
            if m["kind"] == "native" and m.get("load_early"):
                bits.append("loads early")
            for key, word in (("load_after", "after"), ("load_before", "before")):
                deps = [d["id"] for d in m.get(key) or []]
                if deps:
                    bits.append(f"{word} {', '.join(deps)}" if len(deps) <= 3 else f"{word} {len(deps)} others")
            init = m.get("initializer") or {}
            if init.get("function"):
                bits.append(f"calls {init['function']}")
            elif isinstance(init.get("delay"), dict):
                bits.append(f"waits {init['delay'].get('ms', 0)} ms")
            if m["kind"] == "native" and m.get("optional"):
                bits.append("optional")
            if node and node["folder"].is_dir() and not node["own_files"]:
                empty = not any(node["folder"].iterdir())
                bits.append(
                    "Empty for now: game folders put here (parts, chr, msg, ...) load"
                    if empty
                    else "No game folders at its top level (parts, chr, msg, ...), so me3 loads nothing from it"
                )
            if bits:
                detail = hint("  \u00b7  ".join(bits))
                detail.setWordWrap(True)
                deps = [
                    f"{w} {d['id']}" + (" (optional)" if d.get("optional") else "")
                    for w, k in (("after", "load_after"), ("before", "load_before"))
                    for d in m.get(k) or []
                ]
                if deps:
                    detail.setToolTip("\n".join(deps))
                text.addWidget(detail)
            for problem in (getattr(self, "_mod_problems", {}) or {}).get(m["index"], []):
                warn = hint(problem)
                warn.setWordWrap(True)
                tone_label(warn, "error")
                text.addWidget(warn)
            h.addLayout(text, 1)
            sw = SwitchButton()
            sw.setOnText("")
            sw.setOffText("")
            sw.setChecked(bool(m.get("enabled", True)))
            sw.setToolTip("Loaded" if m.get("enabled", True) else "Off: kept in the profile, me3 skips it")
            sw.checkedChanged.connect(lambda checked, e=m: self._toggle_mod(e, checked))
            h.addWidget(sw)
            if m["kind"] == "native" and m.get("path"):
                h.addWidget(self._settings_button(m))
            else:
                spacer = QWidget()  # keeps the columns of package and DLL rows in line
                spacer.setFixedSize(36, 36)
                h.addWidget(spacer)
            b = ghost_btn("Options", FI.SETTING)
            b.clicked.connect(lambda _=False, e=m: self._mod_options(e))
            b.setFixedWidth(ROW_ACTION_W)  # one width for Options and Not loaded, so switches line up down the list
            h.addWidget(b)
            b = icon_btn(FI.DELETE, "Remove from the profile (and optionally delete its folder)")
            b.clicked.connect(lambda _=False, e=m: self._remove_mod(e))
            h.addWidget(b)
            if m["path"]:
                row.setToolTip(m["path"])
            if not m.get("enabled", True):
                tone_label(name, "muted")
            exp.addGroupWidget(row)

    def _entry_place(self, entry):
        """The folder an entry sits in (a DLL's folder, a package folder's parent), below the profile's natives or
        packages folder when it is inside it (that folder itself is where they all live, so it names nothing), else
        below the profile's folder. None without a path."""
        if not entry.get("path") or not self.setup:
            return None, None
        prof = Path(self.setup.profile)
        target = core.mod_manage.resolve(prof, entry["path"])
        place = target.parent
        pk_root, nt_root = getattr(self, "_mod_roots", (None, None))
        for base in (nt_root if entry["kind"] == "native" else pk_root, prof.parent):
            if base is None:
                continue
            try:
                return place.resolve().relative_to(base.resolve()), target
            except OSError, ValueError:
                continue
        return place, target

    def _where_parts(self, entry):
        """The one folder an entry sits in, as its tag (the full path is in the tag's tooltip)."""
        place, _target = self._entry_place(entry)
        if place is None:
            return []
        parts = [x for x in place.parts[1 if place.anchor else 0 :] if x != "."]  # an outside folder drops its drive
        return parts[-1:]

    def _where_tip(self, entry):
        _place, target = self._entry_place(entry)
        return str(target) if target is not None else ""

    @staticmethod
    def _slot(widget):
        """A hidden copy of a row control that still takes its exact space, so a column stays in line."""
        policy = widget.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        widget.setSizePolicy(policy)
        widget.hide()
        return widget

    def _folder_rows(self, kind, info, entries):
        """The packages or natives folder as a line at the top of its list, laid out in the mod rows' columns:
        the text where the names are, Open folder in the settings-icon column, Not loaded in the Options column and
        removing a folder-only entry in the delete column. A folder-only entry elsewhere gets a line of its own."""
        by_index = {e["index"]: e for e in entries}
        holders = [by_index[i] for i in info.get("holders") or [] if i in by_index]
        unlisted = info.get("unlisted") or []
        if not holders and not unlisted:
            return []
        root = info.get("root")
        prof = Path(self.setup.profile)
        at_root = [
            e
            for e in holders
            if root is not None and mod_checks.same_folder(core.mod_manage.resolve(prof, e["path"]), root)
        ]
        elsewhere = [e for e in holders if e not in at_root]
        n = len(unlisted)
        unit = "folder" if kind == "package" else "DLL"
        rows = []
        if root is not None:
            lines = [
                f"{info.get('listed', 0)} listed below"
                + (f", {n} {unit}{'s' if n != 1 else ''} in here {'are' if n != 1 else 'is'} not loaded" if n else "")
            ]
            for e in at_root:
                lines.append(
                    f"The profile also lists this folder itself, as '{e['name']}'. It only holds the mods below, "
                    "so that entry loads nothing and can be removed."
                )
            rows.append(
                self._folder_line(
                    root.name,
                    f"{'packages' if kind == 'package' else 'DLL mods'} folder",
                    str(root),
                    lines,
                    root,
                    (kind, unlisted, root) if n else None,
                    at_root[0] if at_root else None,
                )
            )
        for e in elsewhere:
            folder = core.mod_manage.resolve(prof, e["path"])
            rows.append(
                self._folder_line(
                    e["name"],
                    "folder of mods",
                    str(folder),
                    [f"Points at {folder.name}, a folder that only holds other mods, so it loads nothing."],
                    folder,
                    None if root is not None else ((kind, unlisted, None) if n else None),
                    e,
                )
            )
        return rows

    def _folder_line(self, name, tag, tip, lines, folder, not_loaded, holder):
        row = QWidget()
        row.setMinimumHeight(52)
        h = QHBoxLayout(row)
        h.setContentsMargins(20, 6, 16, 6)  # the mod rows' margins and spacing, so the columns meet
        h.setSpacing(10)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(NameWithTag(name, [tag], tip))
        for line in lines:
            lab = hint(line)
            lab.setWordWrap(True)
            text.addWidget(lab)
        h.addLayout(text, 1)
        switch = SwitchButton()
        switch.setOnText("")
        switch.setOffText("")
        h.addWidget(self._slot(switch))
        if folder is not None:
            b = icon_btn(FI.FOLDER, f"Open {folder}")
            b.clicked.connect(lambda _=False, f=folder: desktop.open_path(str(f)))
        else:
            b = self._slot(icon_btn(FI.FOLDER, ""))
        h.addWidget(b)
        if not_loaded:
            kind, unlisted, root = not_loaded
            b = ghost_btn(f"Not loaded ({len(unlisted)})", FI.ADD)
            b.setToolTip(
                ("Mod folders" if kind == "package" else "DLLs")
                + " here that no entry points at, so me3 never loads them. Pick any to add."
            )
            b.clicked.connect(lambda _=False, k=kind, u=list(unlisted), r=root: self._add_unlisted(k, u, r))
        else:
            b = self._slot(ghost_btn("Options", FI.SETTING))
        b.setFixedWidth(ROW_ACTION_W)
        h.addWidget(b)
        if holder is not None:
            b = icon_btn(FI.DELETE, f"Remove '{holder['name']}' from the profile. The folder and every mod in it stay.")
            b.clicked.connect(lambda _=False, en=holder: self._remove_holder(en))
        else:
            b = self._slot(icon_btn(FI.DELETE, ""))
        h.addWidget(b)
        return row

    def _add_unlisted(self, kind, unlisted, root):
        if self._mods_locked():
            return
        choices = []
        for f in unlisted:
            try:
                label = f.relative_to(root).as_posix() if root else str(f)
            except ValueError:
                label = str(f)
            choices.append((label, f))
        what = "Mod folders" if kind == "package" else "DLLs"
        dlg = ChoiceListDialog(
            f"{what} that are not loaded",
            (
                "me3 loads a package only when an entry points at its folder."
                if kind == "package"
                else "me3 loads a DLL only when an entry points at it."
            )
            + " Tick the ones to add; each gets its own entry, last in the load order. Nothing is copied or moved. "
            "Leave alternates you keep switched off unticked.",
            [c[0] for c in choices],
            self,
            apply_text="Add",
        )
        if not dlg.exec():
            return
        picked = [choices[i][1] for i in dlg.selected()]
        if not picked:
            return
        try:
            out = mod_install.add_existing(Path(self.setup.profile), picked, kind=kind)
        except Exception as e:
            self._toast("Could not add", str(e), error=True)
            return
        names = ", ".join(r.get("id") or Path(r["path"]).name for r in out["entries"])
        self._after_profile_change(f"profile: added {names}")
        noun = "package" if kind == "package" else "DLL"
        self._toast(
            f"Added {len(out['entries'])} {noun}{'s' if len(out['entries']) != 1 else ''}",
            f"{names}. They load at the next launch; the profile kept a .bak.",
        )

    def _remove_holder(self, entry):
        """Take out an entry that points at a folder of mods. It loaded nothing, so the game does not change."""
        if self._mods_locked():
            return
        ref = core.mod_manage.entry_ref(entry).lower()
        needs = [
            o["name"]
            for o in profile_entries(self.setup.profile)
            if o["kind"] == "package"
            and any(
                str(d["id"]).lower() == ref and not d.get("optional")
                for d in (o.get("load_after") or []) + (o.get("load_before") or [])
            )
        ]
        if not confirm(
            self,
            f"Remove '{entry['name']}' from the profile",
            changes=[
                f"Its [[packages]] entry is deleted from {Path(self.setup.profile).name}",
                "Nothing changes in the game: it loaded no files of its own",
                "The folder and every mod in it stay, and so do their entries",
            ]
            + ([f"{', '.join(needs)} must load after it: that setting is taken out too"] if needs else []),
            safety="The profile keeps a .bak.",
            apply_text="Remove",
        ):
            return
        try:
            fresh = self._fresh_entry(entry)
            if fresh is None:
                return
            uninstall_mod(self.setup.profile, fresh["index"], delete_folder=False)
            if needs:
                for o in profile_entries(self.setup.profile):
                    if o["name"] in needs:
                        keep = lambda ds: [d for d in ds if str(d["id"]).lower() != ref]  # noqa: E731
                        set_mod_options(
                            self.setup.profile,
                            o["index"],
                            {
                                "load_after": keep(o.get("load_after") or []),
                                "load_before": keep(o.get("load_before") or []),
                            },
                        )
        except Exception as e:
            self._toast("Could not remove", str(e), error=True)
            return
        self._after_profile_change(f"profile: removed {entry['name']} (a folder of mods)")
        self._toast("Removed", f"'{entry['name']}' is out of the profile. Nothing in the game changes.")

    def _coop_ini_key(self):
        return mod_configs.key_for(self.ini) if self.ini else None

    def _settings_button(self, entry):
        """The DLL's settings files: an icon on its row that opens them (or the Co-op page for Seamless)."""
        dll = core.mod_manage.resolve(Path(self.setup.profile), entry["path"])
        coop = self._coop_ini_key()
        files = mod_configs.files_for(self.settings, dll, skip={coop} if coop else set())
        on_coop = not files and coop and any(mod_configs.key_for(p) == coop for p in mod_configs.found(dll))
        b = icon_btn(FI.DOCUMENT, "")
        if on_coop:
            b.setToolTip("Seamless Co-op's settings are on the Co-op page.")
        elif files:
            names = ", ".join(f["path"].name for f in files[:3]) + (f" +{len(files) - 3}" if len(files) > 3 else "")
            b.setToolTip(f"Edit its settings: {names}")
        else:
            b.setToolTip("No settings file found beside it. Click to tie one the mod reads.")
            quiet = QGraphicsOpacityEffect(b)  # present in every row, but quiet when there is nothing to edit yet
            quiet.setOpacity(0.45)
            b.setGraphicsEffect(quiet)
        b.clicked.connect(lambda _=False, e=entry: self._native_settings(e))
        return b

    def _native_settings(self, entry):
        dll = core.mod_manage.resolve(Path(self.setup.profile), entry["path"])
        coop = self._coop_ini_key()
        skip = {coop} if coop else set()
        files = mod_configs.files_for(self.settings, dll, skip=skip)
        if not files and coop and any(mod_configs.key_for(p) == coop for p in mod_configs.found(dll)):
            self.switchTo(self.coop_page)
            self._toast("Seamless Co-op settings", "They are on this page, with an explanation for each.", info=True)
            return

        def store(ties):
            save_settings(native_configs=ties)
            self.settings.native_configs = ties
            return mod_configs.files_for(self.settings, dll, skip=skip)

        dlg = ConfigFilesDialog(
            self,
            dll,
            files,
            tie=lambda path: store(mod_configs.with_tie(self.settings, dll, path)),
            untie=lambda path: store(mod_configs.without_tie(self.settings, dll, path)),
            toast=self._toast,
        )
        dlg.exec()
        self._fill_mods()  # the row's tooltip names the files

    def _mods_locked(self) -> bool:
        if self.busy:
            self._toast(
                "Wait for the current job", "The profile is not changed while something is running.", error=True
            )
            return True
        if not self.setup or not Path(self.setup.profile).is_file():
            self._toast("No profile", "Pick a setup on Play first.", error=True)
            return True
        if self.profile_panel.dirty:
            self._toast("Profile has unsaved edits", "Save or reload the profile editor first.", error=True)
            return True
        return False

    # -------------------------------------------------------------- merge health
    PILL = {  # health state -> (pill level); the words come from _pill_text
        "single": "ok",
        "current": "ok",
        "stacked": "bad",
        "stale": "bad",
        "failed": "bad",
    }

    @staticmethod
    def _pill_text(h) -> str:
        state = h.get("state")
        if state in ("single", "current"):
            return "Parameters OK"
        if state == "stacked":
            n = max(len(h.get("packs") or []), 2)
            return f"Parameters: 1 of {n} apply"
        if state == "stale":
            return "Parameters out of date"
        if state == "failed":
            return "Rebuild failed"
        return ""

    def _on_merge(self, h):
        if not self.setup or not mod_checks.same_folder(Path(h["profile"]), Path(self.setup.profile)):
            return  # an answer for a profile no longer shown
        before = getattr(self, "_merge_health", None)
        self._merge_health = h
        state = h.get("state")
        packs = h.get("packs") or []
        files = h.get("shared_files") or []
        show = state in ("stacked", "current", "stale", "failed") or (state == "single" and bool(packs)) or bool(files)
        level = self.PILL.get(state, "muted")
        self.merge_pill.set(self._pill_text(h), level)
        self.merge_pill.setVisible(show)
        reasons = h.get("reasons") or []
        self.merge_pill.setToolTip("\n".join(reasons) or h.get("text") or "")
        self.merge_row.setVisible(show)
        unmerged = bool(files) and not h.get("combine")  # two mods ship one file: combining merges it
        self.merge_btn.setVisible(  # a build that exists can always be rebuilt (after switching how it is built, say)
            bool(h.get("backend")) or (state == "stacked" and h.get("can_combine")) or unmerged
        )
        self.merge_btn.setText("Combine" if state == "stacked" or unmerged else "Rebuild")
        if not show:
            return
        if state == "single" and not packs:
            text = "No package ships parameters."
        elif state == "single":
            text = f"One package ships parameters ({packs[0]}): its regulation.bin is used as it is."
        elif state == "stacked":
            text = h["text"] + f": {h['winner']}'s is used."
        elif state == "current":
            text = h["text"] + f" ({h['backend']})."
        else:
            text = h["text"] + "."
            auto = play_options(self.settings)["play_update_merge"] and h.get("backend")
            if state in ("stale", "failed") and auto and self.game is games.ELDEN_RING:
                text += " Play updates them first, or Rebuild now."
        self.merge_text.setText(text)
        tone_label(self.merge_text, "muted" if level == "ok" else "error")
        self.merge_reasons.setText("\n".join(f"\u2022 {x}" for x in reasons))
        self.merge_reasons.setVisible(bool(reasons))
        turned_bad = level == "bad" and (before is None or self.PILL.get(before.get("state")) != "bad")
        if turned_bad:
            self.load_exp.setExpand(True)  # red for a reason: show it once, then leave it as the user sets it
        same = before is not None and before.get("profile") == h["profile"]
        if same and before.get("state") == "current" and state == "stale" and not self.busy:
            btn = ghost_btn("Rebuild", FI.SYNC)
            bar = notice(
                self, "warning", "Combined parameters are out of date", reasons[0] if reasons else "", actions=(btn,)
            )
            btn.clicked.connect(lambda _=False, b=bar: (b.close(), self._rebuild_merge()))

    def _warn_merge(self):
        """Play does not merge; it only says when the parameters in use are not what the packages ask for."""
        h = getattr(self, "_merge_health", None)
        if not h or not self.setup or not mod_checks.same_folder(Path(h["profile"]), Path(self.setup.profile)):
            return
        if h.get("state") == "stacked":
            notice(
                self,
                "warning",
                "Only one parameter pack applies",
                f"{h['winner']}'s regulation.bin is used. Combine them from the Mods page.",
                duration=8000,
            )
        elif h.get("state") in ("stale", "failed"):
            notice(self, "warning", h["text"], "Rebuild them from the Mods page.", duration=8000)

    def _rebuild_merge(self, profile=None, combine=None):
        prof = Path(profile or (self.setup.profile if self.setup else ""))
        if self.busy or not prof.is_file():
            return
        if self.game_running:
            self._toast("Close the game first", "The rebuild rewrites files the game has open.", error=True)
            return
        blocked = core.mod_merge.setup_problem(prof)
        if blocked:
            self._toast("It cannot be rebuilt now", blocked, error=True)
            return
        tool = core.mod_merge.find_backend(prof)
        h = core.mod_merge.health(prof)
        if tool is None and not (h.get("combine") or h.get("can_combine") or combine):
            self._toast(
                "Nothing to rebuild", "Fewer than two packs ship parameters and there is no rebuild tool.", error=True
            )
            return
        if not self._tool_ready(prof):
            return

        def job(_setup, loc):
            run_logging.start_log("launcher: rebuild combined parameters", loc.game.key)
            try:
                out = core.mod_merge.rebuild(prof, run_logging.log, combine=combine)
                core.run_logging.set_undo(out.get("undo"))
                run_logging.log(f"done: combined parameters rebuilt by {out['backend']}; {out['profile_note']}")
            except core.mod_merge.MergeError as e:
                run_logging.log(f"error: {e}")
                raise SystemExit(1) from e

        self.start(
            job,
            "Rebuilding combined parameters..." if tool is not None or h.get("combine") else "Combining parameters...",
            need_setup=False,
        )

    # -------------------------------------------------------------- profile history
    def _undo_notice(self, title, content):
        """A change to the profile just happened: say so, with Undo back to the copy kept just before it."""
        if not self.setup:
            return
        prof = Path(self.setup.profile)
        copy = mod_history.latest(prof)
        if copy is None:
            self._toast(title, content)
            return
        btn = ghost_btn("Undo", FI.RETURN)
        bar = notice(self, "success", title, content, actions=(btn,), duration=6000)
        btn.clicked.connect(lambda _=False, b=bar, c=copy: (b.close(), self._restore_version(c)))

    def _show_versions(self):
        if not self.setup or not Path(self.setup.profile).is_file():
            return
        prof = Path(self.setup.profile)
        dlg = VersionsDialog(prof, mod_history.versions(prof), core.mod_manage.read_text(prof), self)
        if dlg.exec() and dlg.chosen() is not None:
            self._restore_version(dlg.chosen())

    def _restore_version(self, copy):
        if self._mods_locked() or copy is None:
            return
        prof = Path(self.setup.profile)
        try:
            before = mod_history.restore(prof, copy)
        except OSError as e:
            self._toast("Could not restore that version", str(e), error=True)
            return
        self._after_profile_change(f"profile: restored the version kept {Path(copy).name[:15]}")
        btn = ghost_btn("Undo", FI.RETURN)
        bar = notice(
            self,
            "success",
            "Earlier version restored",
            "The one it replaced is kept too.",
            actions=(btn,),
            duration=6000,
        )
        if before is not None:
            btn.clicked.connect(lambda _=False, b=bar, c=before: (b.close(), self._restore_version(c)))

    def _after_profile_change(self, msg):
        self._log(msg)
        self._load_profile_editor(force=True)
        self._fill_mods()
        self._update_plan()

    def _fresh_entry(self, entry):
        """The same entry as it is in the file now (matched by kind, path and id, not by position), or None after
        refreshing the list when the profile changed outside this window and the entry is gone."""
        prof = Path(self.setup.profile)
        want = core.mod_manage.resolve(prof, entry.get("path") or "")
        for e in profile_entries(self.setup.profile):
            if (
                e["kind"] == entry["kind"]
                and (e.get("id") or "") == (entry.get("id") or "")
                and mod_checks.same_folder(core.mod_manage.resolve(prof, e.get("path") or ""), want)
            ):
                return e
        self._toast(
            "The profile changed",
            f"{entry['name']} is no longer where it was; the file was edited outside this window. The list is refreshed.",
            info=True,
        )
        self._fill_mods()
        return None

    def _toggle_mod(self, entry, checked):
        if self._mods_locked():
            self._fill_mods()
            return
        entry = self._fresh_entry(entry)
        if entry is None:
            return
        try:
            set_mod_options(self.setup.profile, entry["index"], {"enabled": bool(checked)})
            self._after_profile_change(f"profile: {entry['name']} {'on' if checked else 'off'}")
            self._undo_notice(f"{entry['name']} turned {'on' if checked else 'off'}", "It applies at the next launch.")
        except Exception as e:
            self._toast("Could not change the profile", str(e), error=True)
            self._fill_mods()

    def _mod_options(self, entry):
        if self._mods_locked():
            return
        others = [
            core.mod_manage.entry_ref(e)
            for e in profile_entries(self.setup.profile)
            if e["index"] != entry["index"]
            and e["kind"] == entry["kind"]
            and (e["kind"] == "native" or e.get("id"))  # a package is named by its id
        ]
        prof = Path(self.setup.profile)
        folder = core.mod_manage.resolve(prof, entry["path"]) if entry.get("path") else None
        mark = core.mod_merge.overlay_mark(prof)
        overlay = None
        rebuild_file = ""
        if entry["kind"] == "package" and folder is not None and core.mod_merge.is_elden_ring(prof):
            overlay = mark is not None and mod_checks.same_folder(mark["package"], folder)
            rebuild_file = str(mark["rebuild"]) if overlay and mark["rebuild"] else ""
        dlg = ModOptionsDialog(entry, others, self, overlay=overlay, rebuild_file=rebuild_file)
        if not dlg.exec():
            return
        try:
            fresh = self._fresh_entry(entry)
            if fresh is None:
                return
            if dlg.overlay is not None:
                picked = dlg.rebuild_file.text().strip() if dlg.rebuild_file is not None else ""
                if dlg.overlay.isChecked() != overlay or picked != rebuild_file:
                    on = dlg.overlay.isChecked()
                    core.mod_merge.set_overlay_override(
                        prof, folder if on else None, Path(picked) if on and picked else None
                    )
            set_mod_options(self.setup.profile, fresh["index"], dlg.options())
            self._after_profile_change(f"profile: options saved for {entry['name']}")
            self._undo_notice(f"{entry['name']}: options saved", "They apply at the next launch.")
        except Exception as e:
            self._toast("Could not save options", str(e), error=True)

    def _remove_mod(self, entry):
        if self._mods_locked():
            return
        prof = Path(self.setup.profile)
        where = core.mod_manage.resolve(prof, entry["path"]) if entry.get("path") else None
        folder = (where if entry["kind"] == "package" else where.parent) if where else None
        users = []
        if folder is not None:
            for o in profile_entries(self.setup.profile):
                if o["index"] == entry["index"] or not o.get("path"):
                    continue
                other = core.mod_manage.resolve(prof, o["path"])
                if other == folder or folder in other.parents:
                    users.append(o["name"])
        merged = self._merged_from(prof, entry)
        changes = [
            f"The [[{'packages' if entry['kind'] == 'package' else 'natives'}]] entry and its own comments are "
            f"deleted from {prof.name}"
        ]
        if users:
            changes.append(
                f"The folder {folder.name} stays: {', '.join(users[:4])}{' ...' if len(users) > 4 else ''} still load from it"
            )
        if merged:
            files = ", ".join(Path(f).name for f in merged[:3]) + (
                f" and {len(merged) - 3} more" if len(merged) > 3 else ""
            )
            changes.append(
                f"Its {files} {'is' if len(merged) == 1 else 'are'} still inside the merged mods: Play rebuilds them "
                "before the game starts (or Rebuild on the Mods page), so the game does not run with them"
            )
        dlg = ConfirmDialog(
            f"Remove {entry['name']} from the profile",
            self,
            changes=changes,
            warning="me3 stops loading it at the next launch. Removing a mod other entries load_after may leave them waiting on a missing id.",
            safety="Activity can restore it: the entry goes back where it was, and a folder moved to the Recycle Bin "
            "comes back with it. Edit profile > Versions keeps the profile as it was too.",
            option=(
                f"Also move the folder {folder.name} to the Recycle Bin"
                if folder and folder.is_dir() and not users
                else None
            ),
            option_checked=False,
            apply_text="Remove",
        )
        if not dlg.exec():
            return
        fresh = self._fresh_entry(entry)
        if fresh is None:
            return
        index, name, delete = fresh["index"], entry["name"], dlg.option_on()

        def job(_setup, loc):
            run_logging.start_log(f"launcher: remove {name}", loc.game.key)
            out = uninstall_mod(prof, index, delete_folder=delete)
            core.run_logging.set_undo(
                {
                    "type": "remove",
                    "profile": str(prof),
                    "name": name,
                    "path": out["path"],
                    "entry_text": out["entry_text"],
                    "where": out["where"],
                    "trash": out.get("trash"),
                    "merged": bool(merged),
                }
            )
            gone = out.get("trash") and out["trash"].get("kind") == "gone"
            run_logging.log(
                f"done: removed {name}"
                + (
                    ""
                    if not out["removed_folder"]
                    else "; its folder was deleted (the Recycle Bin could not take it)"
                    if gone
                    else "; its folder is in the Recycle Bin"
                )
            )
            if delete and not out["removed_folder"] and not users:
                run_logging.log("warning: the folder was kept (the Recycle Bin did not take it)")
            if merged:
                run_logging.log(
                    f"note: the merged mods still hold {name}'s files; Play rebuilds them before the game starts"
                )

        self.start(job, f"Removing {name}...", need_setup=False)

    def _trim_tool_backups(self):
        if self._mods_locked():
            return
        prof = Path(self.setup.profile)
        backups = core.mod_merge.tool_backups(prof)
        extra = backups[3:]
        if not extra:
            return
        size = sum(b["size"] for b in extra)
        if not confirm(
            self,
            f"Move {len(extra)} older rebuild backup{'s' if len(extra) != 1 else ''} to the Recycle Bin",
            changes=[f"{b['folder'].name}  ·  {b['size'] / 1048576:,.0f} MB" for b in extra],
            safety=f"Frees {size / 1048576:,.0f} MB once the bin is emptied; until then they can be restored from it. "
            "The newest 3 stay, so the latest rebuilds can still be undone.",
            apply_text="Move to the Recycle Bin",
        ):
            return
        moved = core.mod_merge.trim_tool_backups(prof, keep=3)
        self._log(f"mods: moved {len(moved)} older rebuild backup(s) to the Recycle Bin")
        self._toast("Older rebuild backups moved", f"{len(moved)} to the Recycle Bin.")
        self._scan_conflicts()

    def _merged_from(self, prof, entry) -> list:
        """The files of a package that a combined result was built from (from the Load order scan the page already
        has, when it is for this profile)."""
        if entry.get("kind") != "package" or not core.mod_merge.is_elden_ring(prof):
            return []
        ov = self._conf_result
        if not ov or ov.get("error") or not mod_checks.same_folder(Path(ov.get("profile") or ""), prof):
            ov = None
        try:
            return mod_overview.merged_from(prof, entry["name"], ov)
        except Exception:
            return []

    def _offer_tool_approval(self, prof: Path) -> None:
        """A mod's rebuild tool the user has not allowed yet: ask on the Mods page, once a session, so a rebuild
        (before Play, or after a change) does not stop in the middle to ask."""
        # Only while the Mods page is shown: a notice over another page would take its keyboard focus.
        if self.game is not games.ELDEN_RING or self.stackedWidget.currentWidget() is not self.mods_page:
            return
        try:
            tool: Any = core.mod_merge.find_backend(prof)  # a rebuild tool (mods.backends), or None
            if tool is None or tool.problem() or core.mod_merge.approved(tool):
                return
        except Exception:
            return
        key = (str(prof), tool.label)
        offered = getattr(self, "_approval_offered", set())
        if key in offered:
            return
        self._approval_offered = offered | {key}
        allow = ghost_btn("Allow", FI.ACCEPT)
        bar = notice(
            self,
            "info",
            f"Allow {tool.label} to run?",
            f"{tool.package['name']} rebuilds the merged mods with a program of its own. Allowing it now means a "
            "rebuild before Play does not stop to ask. Allow it only for mods you trust.",
            actions=(allow,),
        )

        def answer():
            self._tool_ready(prof)  # shows what the tool runs and asks; the answer is remembered
            try:
                bar.close()
            except Exception:
                pass

        allow.clicked.connect(answer)

    def _tool_ready(self, prof) -> bool:
        """The profile's rebuild tool can run: found, nothing stopping it, and allowed by the user (asked once per
        version of the tool). True when there is no tool (the launcher's own combine needs no permission)."""
        tool = core.mod_merge.find_backend(prof)
        if tool is None:
            return True
        if tool.problem():
            self._toast(f"{tool.label} cannot run", tool.problem(), error=True)
            return False
        if core.mod_merge.approved(tool):
            return True
        ok = confirm(
            self,
            f"Run {tool.label}?",
            detail=f"It comes with {tool.package['name']} and runs:\n\n{tool.describe()}",
            warning="It is a program from a mod: allow it only for mods you trust. You are asked again when "
            "the tool changes.",
            apply_text="Allow and run",
        )
        if ok:
            core.mod_merge.approve(tool)
        return ok

    def _run_undo(self, rec):
        """Take a job back from Activity (see mods.undo)."""
        u = dict(rec.get("undo") or {})
        if self.busy:
            self._toast("Wait for the current job", "Undo runs as a job of its own.", error=True)
            return
        if not mod_undo.available(u):
            self._toast("It cannot be taken back any more", "What it needs is gone.", error=True)
            self.activity.refresh()
            return
        prof = Path(u.get("profile") or "")
        if u.get("type") == "rebuild" and self.game_running:
            self._toast("Close the game first", "The rebuild's files are in use while it runs.", error=True)
            return
        if u.get("type") == "rebuild":
            redo = bool(u.get("redo"))
            title = "Redo the rebuild" if redo else "Undo the rebuild"
            ok = confirm(
                self,
                title,
                changes=[
                    "The rebuild tool's output is swapped with the backup it kept" if u.get("tool_restore") else "",
                    "The combined parameters are swapped with the ones kept before" if u.get("combined_before") else "",
                    f"{prof.name} goes back as it was {'after' if redo else 'before'} the rebuild"
                    if u.get("profile_before")
                    else "",
                ],
                safety="Nothing is deleted: each is swapped with its copy, so this can be done again the other way. "
                "Load order will say the parameters are out of date until you rebuild.",
                apply_text=title,
            )
            if not ok:
                return
            name = "the rebuild"
        else:
            name = u.get("name") or "it"
            in_bin = trash.exists(u.get("trash"))
            dlg = ConfirmDialog(
                f"Restore {name}",
                self,
                changes=[
                    f"Its entry goes back into {prof.name}, where it was",
                    "Its folder comes back from the Recycle Bin" if in_bin else "",
                    "Play rebuilds the merged mods with it before the game starts (or Rebuild on the Mods page)"
                    if u.get("merged")
                    else "",
                ],
                safety="The profile as it is now is kept in its versions.",
                apply_text="Restore",
            )
            if not dlg.exec():
                return
        job_id = rec.get("id")

        def job(_setup, loc):
            run_logging.start_log(
                f"launcher: {'redo' if u.get('redo') else 'undo'} the rebuild"
                if u.get("type") == "rebuild"
                else f"launcher: restore {name}",
                loc.game.key,
            )
            try:
                said = mod_undo.run(u, run_logging.log)
            except (mod_undo.UndoError, OSError) as e:
                run_logging.log(f"error: {e}")
                raise SystemExit(1) from e
            if job_id:
                core.run_logging.mark_undone(job_id)
            if u.get("type") == "rebuild":  # the same swap, the other way
                core.run_logging.set_undo({**u, "redo": not u.get("redo")})
            run_logging.log(f"done: {said}")

        self.start(
            job,
            ("Redoing the rebuild..." if u.get("redo") else "Undoing the rebuild...")
            if u.get("type") == "rebuild"
            else f"Restoring {name}...",
            need_setup=False,
        )

    def _install_mod(self):
        """Ask what the mod is, then open the one picker for it. Cancelling a picker installs nothing."""
        if self._mods_locked():
            return
        menu = style_menu(RoundMenu(parent=self))
        menu.addAction(Action(FI.ZIP_FOLDER, "From archive or DLL...", triggered=self._install_from_file))
        menu.addAction(Action(FI.FOLDER, "From folder...", triggered=self._install_from_folder))
        b = self.mods_install
        menu.exec(b.mapToGlobal(QPoint(0, b.height() + 4)))

    def _install_from_file(self):
        src, _ = QFileDialog.getOpenFileName(
            self,
            "Install a mod: pick an archive or DLL",
            "",
            "Mod archive or DLL (*.zip *.7z *.rar *.dll);;All files (*)",
        )
        if src:
            self._install_paths([Path(src)])

    def _install_from_folder(self):
        src = QFileDialog.getExistingDirectory(self, "Install a mod: pick its folder", "")
        if src:
            self._install_paths([Path(src)])

    @staticmethod
    def _drop_accepts(paths):
        """(installable, skipped): folders, .zip / .7z / .rar archives and DLL mods can be installed."""
        kinds = (*mod_extract.ARCHIVE_EXTENSIONS, ".dll")
        usable = [x for x in paths if x.is_dir() or x.suffix.lower() in kinds]
        return usable, [x for x in paths if x not in usable]

    def _install_paths(self, paths):
        """Install one or more mods, one after another: each is unpacked, named in InstallDialog, then copied in."""
        if self._mods_locked():
            return
        usable, skipped = self._drop_accepts([Path(x) for x in paths])
        if skipped:
            self._toast(
                "Skipped",
                f"{', '.join(x.name for x in skipped[:4])}: not an archive (.zip, .7z, .rar), a .dll or a folder.",
                info=True,
            )
        self._install_queue = list(getattr(self, "_install_queue", [])) + usable
        if not self.busy:
            self._install_next()

    def _install_next(self):
        queue = getattr(self, "_install_queue", [])
        if not queue or self.busy:
            return
        src = queue.pop(0)
        if self._mods_locked():
            self._install_queue = []
            return
        prof = self.setup.profile
        QApplication.setOverrideCursor(Qt.WaitCursor)  # unpacking a big archive takes a moment
        try:
            plan = plan_mod_install(prof, src)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self._toast(f"Could not read {src.name}", str(e), error=True)
            QTimer.singleShot(0, self._install_next)
            return
        QApplication.restoreOverrideCursor()

        def drop_unpacked(pl):
            if pl.get("staging"):
                core.mod_manage.shutil.rmtree(pl["staging"], ignore_errors=True)

        if plan.get("error"):
            self._toast(f"{src.name} is not a mod Roundtable Souls can install", plan["error"], error=True)
            drop_unpacked(plan)
            QTimer.singleShot(0, self._install_next)
            return
        if plan.get("in_place") and plan.get("already_listed") and len(plan["already_listed"]) == len(plan["entries"]):
            self._toast("Nothing to do", f"{plan['name']} is already installed and listed in the profile.")
            drop_unpacked(plan)
            QTimer.singleShot(0, self._install_next)
            return
        dlg = InstallDialog(
            self,
            plan,
            lambda name, pkg_id, variant: replan_mod_install(prof, plan, name, pkg_id, variant),
            Path(prof),
        )
        if not dlg.exec():
            drop_unpacked(plan)
            QTimer.singleShot(0, self._install_next)
            return
        plan = dlg.plan
        self._merge_after = Path(prof) if plan.get("merge") else None

        def job(_setup, loc):
            run_logging.start_log(f"launcher: install mod {plan['name']}", loc.game.key)
            try:
                install_mod(prof, plan, overwrite=bool(plan.get("exists")))
                run_logging.log(f"done: installed {plan['name']}")
            except Exception as e:
                run_logging.log(f"error: {e}")
                raise SystemExit(1) from e

        self.start(job, f"Installing {plan['name']}...", need_setup=False)

    def eventFilter(self, obj, e):
        # A drag entering the Mods page (or anything on it, such as the profile editor, which would take the file
        # itself) shows the drop overlay on top; the overlay then gets the rest of the drag.
        if e.type() == QEvent.DragEnter and self._on_mods_drop_area(obj):
            if self.mods_drop.begin(DropOverlay.paths_of(e)):
                e.acceptProposedAction()
                return True
        return super().eventFilter(obj, e)

    def _on_mods_drop_area(self, obj) -> bool:
        page = getattr(self, "mods_page", None)
        return (
            page is not None
            and isinstance(obj, QWidget)
            and obj is not getattr(self, "mods_drop", None)
            and (obj is page or page.isAncestorOf(obj))
            and self.stackedWidget.currentWidget() is page
            and self.game.ready
            and not self.busy
        )

    def _new_profile(self):
        cur = self.setup.profile if self.setup and Path(self.setup.profile).is_file() else None
        dlg = TextDialog(
            "New me3 profile",
            "Created in me3's profile folder with empty mod and natives folders beside it.",
            self,
            placeholder="name, e.g. vanilla-plus",
            option=(f"Start from a copy of {Path(cur).name}" if cur else None),
            option_checked=False,
            apply_text="Create",
        )
        if not dlg.exec():
            return
        try:
            p = create_profile(
                dlg.edit.text().strip(),
                copy_from=cur if (dlg.option is not None and dlg.option.isChecked()) else None,
                loc=self.ctx.locations,
            )
        except Exception as e:
            self._toast("Could not create the profile", str(e), error=True)
            return
        self._log(f"profile: created {p}")
        self.setups = discover(str(p), self.ctx.locations)
        remember_setup(str(p), self.game)
        self.settings = load_settings()
        self._fill_setups(select=str(p))
        self._toast("Profile created", f"{p.name} is now the setup on Play.")

    def _delete_profile(self):
        if not self.setup or not Path(self.setup.profile).is_file():
            self._toast("No profile", "Pick a setup on Play first.", error=True)
            return
        if self.setup.kind == "revive":
            self._toast("Not this one", "Revive's profile is managed by its installer; delete it there.", error=True)
            return
        p = Path(self.setup.profile)
        if not confirm(
            self,
            f"Delete {p.name}",
            changes=[
                f"{p.name} moves into the launcher's deleted profiles, with a note of where it lived",
                "Mod folders and natives stay where they are",
            ],
            warning="This setup disappears from the Play list.",
            safety="The moved file can be copied back by hand at any time.",
            apply_text="Delete",
        ):
            return
        try:
            gone = delete_profile(p)
        except Exception as e:
            self._toast("Could not delete", str(e), error=True)
            return
        self._log(f"profile: moved {p.name} to {gone}")
        forget_setup(self.game)  # per game: save_settings(setup=None) would wipe Elden Ring's from any tab
        self.settings = load_settings()
        self.setups = discover(None, self.ctx.locations)
        self._fill_setups()
        self._toast("Profile deleted", f"Moved to {gone.parent.name}.")

    def _load_profile_editor(self, force=False):
        """Show the setup's .me3. Unsaved edits to the same file survive a refresh unless force (Discard, or a change
        written elsewhere) asks for the file again."""
        path = Path(self.setup.profile) if self.setup and Path(self.setup.profile).is_file() else None
        panel = self.profile_panel
        if path is None:
            self._profile_file = None
            self._profile_crlf = False
            panel.set_baseline("", "No me3 profile for this setup.")
            panel.bar.setEnabled(False)
            return
        if panel.dirty and not force and self._profile_file == path:
            return
        raw = path.read_bytes()
        self._profile_crlf = b"\r\n" in raw
        text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        self._profile_file = path
        panel.bar.setEnabled(True)
        panel.set_baseline(text, path.name, str(path))

    def _profile_stamp(self):
        try:
            st = Path(self.setup.profile).stat() if self.setup else None
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size) if st else None

    def _profile_changed_outside(self) -> bool:
        """The .me3 on disk no longer matches what the editor loaded."""
        if self._profile_file is None:
            return False
        try:
            disk = self._profile_file.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            return False
        return disk.replace("\r\n", "\n").replace("\r", "\n") != self.profile_panel.baseline()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.ActivationChange and self.isActiveWindow():
            QTimer.singleShot(0, self._check_profile_on_disk)

    def _check_profile_on_disk(self):
        """Coming back to the window: pick up a profile changed elsewhere (me3, a text editor, Revive's installer)."""
        if not self.setup or self.busy or getattr(self, "_profile_seen", None) is None:
            return
        stamp = self._profile_stamp()
        if stamp == self._profile_seen:
            return
        self._profile_seen = stamp
        if self.profile_panel.dirty:
            self._toast(
                "The profile changed on disk",
                "It was edited outside this window. Your unsaved editor text is kept; Discard loads the new file.",
                info=True,
            )
            return
        self._fill_mods()

    def _save_profile(self):
        if self._profile_file is None:
            return False
        if self._profile_changed_outside() and not confirm(
            self,
            f"{self._profile_file.name} changed on disk",
            changes=[
                "It was edited outside this window after the editor loaded it",
                "Saving writes your text over those changes",
            ],
            safety="The file keeps one .bak of the version being replaced. Cancel, then Discard, to load the new file instead.",
            apply_text="Save anyway",
        ):
            return False
        text = self.profile_edit.toPlainText()
        try:
            mod_history.snapshot(self._profile_file, "before saving the editor")
            core.atomic_write(
                self._profile_file, text.replace("\n", "\r\n") if self._profile_crlf else text, backup=True
            )
        except Exception as e:
            self._toast("Could not save the profile", str(e), error=True)
            return False
        self.profile_panel.mark_clean()
        self._toast("Profile saved", "It applies the next time you start the game.")
        self._load_coop()
        self._fill_mods()
        return True

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

    # ---------------------------------------------------------------- Tools page
    def _build_tools(self):
        self.tools_page, lay = page("toolsPage")
        titled(lay, "Settings", FI.SETTING)
        c, cl = card("Launcher", FI.INFO)
        self.launcher_line = BodyLabel(f"{TITLE} {VERSION}  \u00b7  {self._install_kind()}")
        tone_label(self.launcher_line, "muted")
        self.launcher_line.setWordWrap(True)
        cl.addWidget(self.launcher_line)
        row_w, row = action_row()
        b = ghost_btn("Check for updates", FI.UPDATE)
        b.setToolTip("Ask GitHub now whether a newer version exists.")
        b.clicked.connect(lambda: self._check_launcher_update(force=True))
        row.addWidget(b)
        b = ghost_btn("Releases", FI.LINK)
        b.setToolTip("Every version of this launcher, with notes and downloads.")
        b.clicked.connect(lambda: desktop.open_path(RELEASES_URL))
        row.addWidget(b)
        b = ghost_btn("Logs", FI.DOCUMENT)
        b.setToolTip("This launcher's own logs, for when something goes wrong.")
        b.clicked.connect(lambda: self._open_logs_folder())
        row.addWidget(b)
        cl.addWidget(row_w)
        sw = SwitchButton()
        sw.setOnText("On")
        sw.setOffText("Off")
        sw.setChecked(bool(self.settings.check_launcher_updates))
        sw.checkedChanged.connect(lambda checked: self._remember_play("check_launcher_updates", checked))
        self.play_sw = {"check_launcher_updates": sw}
        cl.addWidget(
            SettingRow(
                "Check for updates on start",
                "At most once an hour, from this project's GitHub releases. A notice only; you choose when to install.",
                sw,
                "Update now downloads the release, checks its signature and checksum, installs it and restarts. "
                "Skip hides one version.",
            )
        )
        self.channel_box = ComboBox()
        self.channel_box.addItems(["Stable", "Beta"])
        self.channel_box.setMinimumWidth(140)
        self.channel_box.blockSignals(True)
        self.channel_box.setCurrentIndex(1 if self.settings.launcher_channel == "beta" else 0)
        self.channel_box.blockSignals(False)
        self.channel_box.currentIndexChanged.connect(self._on_channel)
        cl.addWidget(
            SettingRow(
                "Update channel",
                "Stable offers releases. Beta also offers pre-releases, which get less testing.",
                self.channel_box,
                "Going back to Stable never installs an older version: the next stable release is offered once it is "
                "newer than this one.",
            )
        )
        lay.addWidget(c)
        c, cl = card("Steam shortcut", FI.GAME)
        self.shortcut_hint = hint("")
        cl.addWidget(self.shortcut_hint)
        self.shortcut_fields = {}
        target, options = play_command(self.game)
        for label, value in (("Target", target), ("Launch options", options)):
            row_w, row = action_row()
            field = LineEdit()
            field.setText(value)
            field.setReadOnly(True)
            field.setMinimumWidth(220)
            field.setAccessibleName(label)
            self.shortcut_fields[label] = field
            row.addWidget(BodyLabel(label))
            row.addWidget(field)
            copy = ghost_btn("Copy", FI.COPY)
            copy.clicked.connect(
                lambda _=False, f=field, n=label: (
                    QApplication.clipboard().setText(f.text()),
                    self._toast("Copied", n, info=True),
                )
            )
            row.addWidget(copy)
            cl.addWidget(row_w)
        row_w, row = action_row()
        b = ghost_btn("Point Steam shortcuts here", FI.LINK)
        b.setToolTip(
            "Steam shortcuts with --play that start a Roundtable Souls program in another folder (an older install) "
            "start this copy instead. Steam must be closed; a backup of each changed file is kept."
        )
        b.clicked.connect(self._point_steam_shortcuts)
        row.addWidget(b)
        cl.addWidget(row_w)
        lay.addWidget(c)
        c, cl = card("Appearance", FI.BRUSH)
        row = QHBoxLayout()
        self.theme_sw = SwitchButton()
        self.theme_sw.setOnText("Dark")
        self.theme_sw.setOffText("Light")
        self.theme_sw.setChecked(self.settings.theme == "dark")
        self.theme_sw.checkedChanged.connect(self._on_theme)
        row.addWidget(BodyLabel("Theme"))
        row.addWidget(self.theme_sw)
        row.addStretch()
        cl.addLayout(row)
        brand = QHBoxLayout()
        brand.setSpacing(12)
        self.logo_preview = LogoPreview()
        brand.addWidget(self.logo_preview, 0, Qt.AlignVCenter)
        brand.addWidget(BodyLabel("Logo"), 0, Qt.AlignVCenter)
        self.logo_box = ComboBox()
        self.logo_box.addItems(["Follow theme", "Dark", "Light"])
        self.logo_box.setMinimumWidth(140)
        mode = self.settings.logo
        self.logo_box.blockSignals(True)
        self.logo_box.setCurrentIndex({"auto": 0, "dark": 1, "light": 2}.get(mode, 0))
        self.logo_box.blockSignals(False)
        self.logo_box.currentIndexChanged.connect(self._on_logo)
        brand.addWidget(self.logo_box, 0, Qt.AlignVCenter)
        brand.addStretch()
        cl.addLayout(brand)
        cl.addWidget(hint("Follow theme switches the logo with light and dark."))
        lay.addWidget(c)
        self._apply_logo()
        c, cl = card("Maintenance", FI.UPDATE)
        b = ghost_btn("Repair", FI.UPDATE)
        b.clicked.connect(lambda: self.start(job_repair, "Repairing saves...", need_setup=False))
        self.repair_row = PairRow(
            "Repair saves",
            "Runs after a session when this game needs it. Use this if the window was closed first.",
            b,
        )
        cl.addWidget(self.repair_row)
        b = ghost_btn("Clear", FI.DELETE)
        b.clicked.connect(lambda: self.start(job_clear, "Clearing leftover processes...", need_setup=False))
        cl.addWidget(
            PairRow("Leftover processes", "A dead copy of the game can make Discord think it is still open.", b)
        )
        lay.addWidget(c)
        c, cl = card("Play session", FI.PLAY)
        cl.addWidget(
            hint(
                "What Play does around the game. The game never starts with merged mods that are out of date (a "
                "removed or changed mod still inside them) without asking you first. The steps below can be turned "
                "off; the launch itself always runs."
            )
        )
        rows = (
            (
                "play_update_merge",
                "Rebuild merged mods automatically before Play",
                "When mods, their load order or the game changed, Play rebuilds the merged ones first (combined "
                "parameters, and a mod's own rebuild tool such as Nightreign Revive's), then starts the game.",
                "Off: Play asks first (rebuild, or play this once with the previous result); a Steam shortcut "
                "does not start the game and says why. A failed rebuild keeps the previous result and asks before "
                "starting. After an automatic rebuild only the newest 3 of a rebuild tool's backups are kept; older "
                "ones go to the Recycle Bin.",
            ),
            (
                "build_merges",
                "Build Nightreign Revive in the launcher (preview)",
                "For a mod the launcher has a recipe for (Nightreign Revive LITE 0.1.33), a rebuild merges it from its "
                "own download instead of running its installer: the launcher merges its animations, effects, menu "
                "text and parameters itself; only the grace menu still uses the mod's own tool.",
                "The same content as its installer makes (checked on a real profile). Your profile is never rewritten, "
                "RevivePrototype.ini keeps your values (a new version only adds its new settings), and one previous "
                "build is kept in .roundtable-build for Undo rebuild instead of a full backup on every run. Other "
                "versions still use their own installer. Off: the installer runs, as before.",
            ),
            (
                "play_boot_boost",
                "Boot boost",
                "me3 caches the decrypted game archives so the game starts faster.",
                "Turn off only if a mod misbehaves with the cache; me3 passes --no-boot-boost.",
            ),
            (
                "play_show_logos",
                "Show intro logos",
                "Play the publisher logos me3 skips by default.",
                "Passes --show-logos to me3.",
            ),
            (
                "play_diagnostics",
                "me3 diagnostics",
                "Ask me3 for extra diagnostics on this launch (slower start, bigger log).",
                "Passes --diagnostics; me3's output is kept with that Play in the logs folder.",
            ),
            (
                "play_backup_before",
                "Back up saves before Play",
                "A backup of every save before each session, listed under Backups on the Saves page.",
                "Off by default: the game keeps its own .bak, and each repair makes a copy anyway. Turn it on for a copy before every session.",
            ),
            (
                "play_clear_before",
                "Clear leftover processes before launch",
                "Ends dead copies of the game so Steam agrees to start it.",
                "A dead shell is a copy of the game's exe with no window. Steam refuses to launch while one exists.",
            ),
            (
                "play_repair_after",
                "Repair saves after quitting",
                "Puts the regulation section back in order after me3. Elden Ring copies regulation.bin in; Nightreign re-signs its encrypted sections.",
                "The game does not mind a dirty block; save editors do. Nightreign never writes Game\\regulation.bin into the save (that file is a different encoding). Turn this off if you never use editors.",
            ),
            (
                "play_clear_after",
                "Clear leftover processes after quitting",
                "Ends dead shells so Discord and Steam stop showing the game as running.",
                "Needs admin once. Turn it off if you prefer to handle processes yourself.",
            ),
            (
                "warn_dead_shells",
                "Warn about leftover processes",
                "The bar at the top of the window when a dead copy of the game is found.",
                "The Clear button on Tools still works with the warning off.",
            ),
        )
        self.play_rows = {}
        for key, title, blurb, help_text in rows:
            sw = SwitchButton()
            sw.setOnText("On")
            sw.setOffText("Off")
            sw.setChecked(bool(getattr(self.settings, key)))
            sw.checkedChanged.connect(lambda checked, k=key: self._remember_play(k, checked))
            self.play_sw[key] = sw
            self.play_rows[key] = SettingRow(title, blurb, sw, help_text)
            cl.addWidget(self.play_rows[key])
        lay.addWidget(c)
        c, cl = card("Locations", FI.FOLDER)
        cl.addWidget(
            hint(
                "Blank means detect: me3 from PATH or its installer, the game from Steam, profiles from where me3 info says. Set one only when that is wrong for this PC. The game executable is kept per game."
            )
        )
        self.loc = {}
        for key, title, blurb, is_dir, filt in (
            ("me3_path", "me3.exe", "A portable or custom me3 install.", False, "me3 (me3.exe)"),
            (
                "game_exe",
                "Game executable",
                "The game's exe outside Steam's usual folder, for the game picked at the top. me3 then launches it directly.",
                False,
                "Game (*.exe)",
            ),
            ("me3_profile_dir", "Profile folder", "Where .me3 profiles are listed from.", True, ""),
        ):
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(6)
            lab = hint(str(self._location_value(key)) or "detected")
            lab.setMaximumWidth(360)
            bl.addWidget(lab, 1)
            b = ghost_btn("Browse", FI.FOLDER)
            b.clicked.connect(lambda _=False, k=key, d=is_dir, f=filt: self._pick_location(k, d, f))
            bl.addWidget(b)
            x = icon_btn(FI.CANCEL, "Clear: detect it again")
            x.clicked.connect(lambda _=False, k=key: self._set_location(k, ""))
            bl.addWidget(x)
            self.loc[key] = lab
            cl.addWidget(SettingRow(title, blurb, box, blurb))
        lay.addWidget(c)
        c, cl = card("me3", FI.CODE)
        self.me3_line = BodyLabel("Checking me3...")
        self.me3_line.setWordWrap(True)
        cl.addWidget(self.me3_line)
        row_w, row = action_row()
        self.me3_dir_btn = ghost_btn("me3 folder", FI.FOLDER)
        self.me3_dir_btn.setEnabled(False)
        self.me3_dir_btn.clicked.connect(lambda: desktop.open_path(self.me3_dir_btn.toolTip()))
        row.addWidget(self.me3_dir_btn)
        self.me3_logs_btn = ghost_btn("me3 logs", FI.DOCUMENT)
        self.me3_logs_btn.setEnabled(False)
        self.me3_logs_btn.clicked.connect(lambda: desktop.open_path(self.me3_logs_btn.toolTip()))
        row.addWidget(self.me3_logs_btn)
        self.me3_prof_btn = ghost_btn("Profile folder", FI.FOLDER)
        self.me3_prof_btn.setEnabled(False)
        self.me3_prof_btn.clicked.connect(lambda: desktop.open_path(self.me3_prof_btn.toolTip()))
        row.addWidget(self.me3_prof_btn)
        b = ghost_btn("me3 releases", FI.LINK)
        b.setToolTip("me3's own releases page on GitHub.")
        b.clicked.connect(lambda: desktop.open_path("https://github.com/garyttierney/me3/releases"))
        row.addWidget(b)
        b = ghost_btn("Refresh", FI.SYNC)
        b.setToolTip("Read the installed me3 again.")
        b.clicked.connect(self._refresh_me3)
        row.addWidget(b)
        cl.addWidget(row_w)
        sw = SwitchButton()
        sw.setOnText("On")
        sw.setOffText("Off")
        sw.setChecked(bool(self.settings.check_me3_updates))
        sw.checkedChanged.connect(lambda checked: self._remember_play("check_me3_updates", checked))
        self.play_sw["check_me3_updates"] = sw
        cl.addWidget(
            SettingRow(
                "Check for me3 updates",
                "Once a day, from me3's GitHub releases. A notice only; nothing is installed.",
                sw,
                "Roundtable Souls never replaces me3 itself: Revive setups ship their own copy.",
            )
        )
        lay.addWidget(c)
        offline = ExpandGroupSettingCard(FI.CLOUD, "Offline play", "Solo on the standard save.")
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(8, 4, 8, 12)
        bl.setSpacing(4)
        bl.addWidget(
            hint(
                "Starts this setup without Seamless, so the game uses the standard save. Steam still needs to be running; pick Start in Offline Mode if it asks. Co-op needs Steam online."
            )
        )
        self.off_revive = SwitchButton()
        self.off_revive.setOnText("On")
        self.off_revive.setOffText("Off")
        self.off_revive.setChecked(bool(self.settings.offline_strip_revive))
        self.off_steam = SwitchButton()
        self.off_steam.setOnText("On")
        self.off_steam.setOffText("Off")
        self.off_steam.setChecked(bool(self.settings.offline_start_steam))
        self.off_quiet = SwitchButton()
        self.off_quiet.setOnText("On")
        self.off_quiet.setOffText("Off")
        self.off_quiet.setChecked(bool(self.settings.offline_skip_confirm))
        self.off_revive_row = SettingRow(
            "Skip Revive too",
            "Leave Nightreign Revive (an Elden Ring mod) off for this launch.",
            self.off_revive,
            "Turns Revive packages and natives off in a temporary copy. Your real profile is not changed.",
        )
        bl.addWidget(self.off_revive_row)
        bl.addWidget(
            SettingRow(
                "Start Steam if needed",
                "Open Steam before launch if it is not running.",
                self.off_steam,
                "Turn this off if Steam is already open. Seamless still stays off.",
            )
        )
        bl.addWidget(
            SettingRow(
                "Skip the confirmation",
                "Go straight to launch next time.",
                self.off_quiet,
                "Stops the Play offline prompt. You can turn this back off here.",
            )
        )
        for sw in (self.off_revive, self.off_steam, self.off_quiet):
            sw.checkedChanged.connect(self._remember_offline)
        row = QHBoxLayout()
        b = ghost_btn("Play offline", FI.PLAY)
        b.clicked.connect(self.launch_offline)
        row.addWidget(b)
        row.addStretch()
        bl.addLayout(row)
        offline.addGroupWidget(body)
        lay.addWidget(offline)
        self.offline_exp = offline
        files = ExpandGroupSettingCard(
            FI.FOLDER, "Folders", "me3, the game, your saves, and this launcher's own files."
        )
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 8, 16, 12)
        row = FlowLayout(needAni=False)
        row.setContentsMargins(0, 0, 0, 0)
        row.setHorizontalSpacing(8)
        row.setVerticalSpacing(8)
        row.addWidget(self._folder_btn("me3", "me3", FI.CODE, "Where me3.exe lives."))
        row.addWidget(
            self._folder_btn(
                "game", "Game", FI.GAME, "The game's own folder: its exe, regulation.bin, and mods that install there."
            )
        )
        row.addWidget(
            self._folder_btn("saves", "Saves", FI.SAVE, "The folder with your save files and the backup folders.")
        )
        b = ghost_btn("Logs", FI.DOCUMENT)
        b.setToolTip("The launcher's own logs.")
        b.clicked.connect(lambda: self._open_logs_folder())
        row.addWidget(b)
        b = ghost_btn("Settings folder", FI.FOLDER)
        b.setToolTip("Roundtable Souls's settings file.")
        b.clicked.connect(lambda: desktop.open_path(str(self.ctx.data_dir)))
        row.addWidget(b)
        bl.addLayout(row)
        where = updates.data_location_text()
        p = hint(where)
        p.setToolTip(str(self.ctx.data_dir))
        bl.addWidget(p)
        files.addGroupWidget(body)
        lay.addWidget(files)
        lay.addStretch(1)

    # ---------------------------------------------------------------- setups
    def _fill_setups(self, select=None):
        self._loading_setups = True
        self.setup_box.blockSignals(True)
        self.setup_box.clear()
        labels = [s.label for s in self.setups]
        for s, label in zip(self.setups, labels):
            if labels.count(label) > 1:  # same file name in two folders: say which folder each one is in
                label = f"{label}  ·  {Path(s.source).parent.name}"
            self.setup_box.addItem(label)
        pick = select or remembered_setup(self.settings, self.game)
        idx = next((i for i, s in enumerate(self.setups) if same_source(s.source, pick)), 0)
        if self.setups:
            self.setup_box.setCurrentIndex(idx)
        self.setup_box.blockSignals(False)
        self._on_setup()
        self._loading_setups = False

    def _on_setup(self, *_):
        s = self.setups[self.setup_box.currentIndex()] if self.setups and self.setup_box.currentIndex() >= 0 else None
        self.setup = s
        if not s:
            self.setup_hint.setText(
                f"No me3 profile for {self.game.name} yet. Create one on the Mods page, or Browse to a .me3 profile"
                + (
                    ", or to an installation.json from a launcher such as Nightreign Revive."
                    if self.game is games.ELDEN_RING
                    else "."
                )
            )
            self.setup_exp.card.setContent("None")
            self.setup_exp.setExpand(True)
            self.play_btn.setEnabled(False)
            self.ini = None
            self._note_saves_in_use(None)
            self._coop_ready = False
            self._schedule_page_fill()
            return
        probs = s.problems()
        if probs:
            self.setup_hint.setText("Cannot launch: " + "; ".join(short_problem(p) for p in probs))
            self.setup_hint.setToolTip("\n".join(probs))
            self.setup_exp.card.setContent("Cannot launch")
        else:
            me3 = s.me3_path()
            game = Path(s.exe).name if s.exe else s.game.name
            self.setup_hint.setText(f"{me3.name if me3 else 'me3 not found'}  ·  {game}")
            self.setup_hint.setToolTip(s.summary())
            self.setup_exp.card.setContent(s.label)
        tone_label(self.setup_hint, "error" if probs else "muted")
        self.setup_exp.setExpand(bool(probs))
        self.play_btn.setEnabled(not probs and not self.game_running and not self.busy)
        self.ini = s.ini
        self._note_saves_in_use(s)
        self._coop_ready = False  # the Co-op and Mods pages are rebuilt just after this paint (see _schedule_page_fill)
        self._update_plan()
        self._schedule_page_fill()
        if getattr(self, "me3_line", None) is not None:
            self._refresh_me3()
        if not same_source(remembered_setup(self.settings, self.game), s.source):
            remember_setup(s.source, s.game)
            self.settings = load_settings()

    def _schedule_page_fill(self):
        """Build the Co-op and Mods pages just after the visible (Play) page has painted, so a game switch or setup
        change feels instant. Coalesced by a token: only the newest schedule runs, and only its heavy widget builds."""
        self._page_fill_token = getattr(self, "_page_fill_token", 0) + 1
        token = self._page_fill_token
        QTimer.singleShot(0, lambda: self._do_page_fill(token))

    def _do_page_fill(self, token):
        if token != getattr(self, "_page_fill_token", 0):
            return  # a newer switch or setup change superseded this one
        self._load_coop()
        self._fill_mods()
        self._update_plan()

    def _update_plan(self):
        s = self.setup
        if not s:
            self.plan.setText("")
            return
        bits = ["me3"]
        if self.ini:
            bits.append("Seamless Co-op")
        ids = {m["id"].lower() for m in read_profile_mods(s.profile)} if Path(s.profile).is_file() else set()
        revive = (
            s.kind == "revive"
            or (Path(s.profile).parent / "NightreignRevive").is_dir()
            or "nightreign-revive" in ids
            or "reviveprototype.dll" in ids
        )
        if revive:
            bits.append("Revive")
        f = getattr(self, "_me3", None) or {}
        if f.get("update") and (f.get("latest") or {}).get("version"):
            bits.append(f"me3 {f['latest']['version']} available (Tools)")
        if self.ini and self._coop_pending():
            self.plan.setText(" · ".join(bits) + "  ·  unsaved co-op changes apply when you press Play")
            self.plan.setTextColor(ACCENT_LIGHT, ACCENT)
        else:
            self.plan.setText(" · ".join(bits) + ". Leave this open while you play.")
            self.plan.setTextColor(HINT_ON_LIGHT, HINT)

    def browse(self):
        p, _ = QFileDialog.getOpenFileName(
            self,
            "Pick a me3 profile",
            str(self.ctx.locations.me3_profiles_dir() or exe_dir()),
            "me3 profile or installation.json (*.me3 *.json);;All files (*.*)",
        )
        if not p:
            return
        s = setup_from_path(p, self.ctx.locations)
        if not s:
            self._toast(
                "Not a setup",
                "That file is not a .me3 profile, and it is not a launcher installation.json.",
                error=True,
            )
            return
        if not any(same_source(x.source, s.source) for x in self.setups):
            self.setups.append(s)
        self._fill_setups(select=s.source)

    # ---------------------------------------------------------------- co-op
    def _load_coop(self):
        ini = self.ini
        on = ini is not None
        self._coop_ready = True  # the co-op form now reflects self.ini, so pending-change detection is valid
        self.coop_off.setVisible(not on)
        for w in self.coop_form:
            w.setVisible(on)
        self.coop_bar.setVisible(on)
        for w in (self.pw, self.preset, self.share):
            w.setEnabled(on)
        if not on:
            self.pw.blockSignals(True)
            self.pw.setText("")
            self.pw.blockSignals(False)
            self.pw_file = None
            self.scaling_file = None
            self.scal_hint.setText("")
            self.share.setPlainText("")
            for sp in self.spins:
                sp.setEnabled(False)
            self._refresh_coop_actions()
            return
        self.pw_card.setVisible(has_password(ini))  # Nightreign's Seamless Co-op has no password
        self.pw_file = read_password(ini)
        self.pw.blockSignals(True)
        self.pw.setText(self.pw_file or "")
        self.pw.blockSignals(False)
        self._on_pw_edit()
        self.scaling = scaling_spec(ini)
        self.scaling_file = read_scaling(ini, self.scaling) if self.scaling else None
        self._show_scaling(self.scaling)
        if self.scaling_file is None:
            self.preset.setEnabled(False)
            for sp in self.spins:
                sp.setEnabled(False)
            self.scal_hint.setText(f"No difficulty values in {ini.name}.")
        else:
            name = preset_of(self.scaling_file, self.scaling)
            self.preset.blockSignals(True)
            self.preset.setCurrentText(name)
            self.preset.blockSignals(False)
            self._set_spins(self.scaling_file, name == CUSTOM)
            self._on_scaling_edit()
        self.share_fill()
        self._fill_all_settings()

    def _fill_all_settings(self):
        """Rebuild the section expanders from the file. Sections the quick cards already cover are skipped."""
        while self.all_box.count():
            it = self.all_box.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self.all_dirty = {}
        self.all_file = {}
        self._all_dirty_changed()
        if self.ini is None:
            return
        for sec in read_settings_meta(self.ini):
            items = [i for i in sec["items"] if sec["section"].upper() not in ("PASSWORD", "SCALING")]
            if not items:
                continue
            icon = {"GAMEPLAY": FI.GAME, "SAVE": FI.SAVE, "LANGUAGE": FI.LANGUAGE}.get(
                sec["section"].upper(), FI.SETTING
            )
            sub = {
                "GAMEPLAY": "What the session feels like",
                "SAVE": "Which file Seamless writes",
                "LANGUAGE": "Locale override",
            }.get(sec["section"].upper(), count_label(len(items), "setting"))
            exp = ExpandGroupSettingCard(icon, sec["title"], sub)
            for it in items:
                self.all_file[it["key"]] = it["value"]
                exp.addGroupWidget(self._setting_row(it))
            self.all_box.addWidget(exp)
        self.other_host.setVisible(self.ini is not None and self.all_box.count() > 0)

    def _setting_row(self, it):
        """One form row. The control shows familiar words; the ini value is written behind the scenes."""
        key, kind, val = it["key"], it["kind"], it["value"].strip()
        title, blurb, help_text = setting_face(key, it["desc"])

        def mark(new):
            self._mark_dirty(key, str(new))

        if key == "default_boot_master_volume":
            w = ComboBox()
            labels = [lab for _, lab in VOLUME_STOPS]
            nums = [n for n, _ in VOLUME_STOPS]
            w.addItems(labels)
            w.setMinimumWidth(140)
            w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            n = int(val) if val.lstrip("-").isdigit() else 5
            nearest = min(nums, key=lambda x: abs(x - n))
            w.setCurrentIndex(nums.index(nearest))
            w.currentIndexChanged.connect(lambda i, ns=nums: mark(ns[i]))
        elif key == "save_file_extension" and val in {k for k, _ in SAVE_KINDS}:
            w = ComboBox()
            kinds = [k for k, _ in SAVE_KINDS]
            w.addItems([lab for _, lab in SAVE_KINDS])
            w.setMinimumWidth(140)
            w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            w.setCurrentIndex(kinds.index(val))
            w.currentIndexChanged.connect(lambda i, ks=kinds: mark(ks[i]))
        elif kind == "bool":
            w = SwitchButton()
            w.setOnText("On")
            w.setOffText("Off")
            w.setChecked(val == "1")
            w.checkedChanged.connect(lambda on: mark(1 if on else 0))
        elif kind == "choice":
            w = ComboBox()
            labels = [choice_label(key, n, lab) for n, lab in it["extra"]]
            w.addItems(labels)
            w.setMinimumWidth(200)
            w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            nums = [n for n, _ in it["extra"]]
            w.setCurrentIndex(nums.index(int(val)) if val.lstrip("-").isdigit() and int(val) in nums else 0)
            w.setToolTip(w.currentText())
            w.currentIndexChanged.connect(lambda i, box=w, ns=nums: (box.setToolTip(box.itemText(i)), mark(ns[i])))
        elif kind == "int":
            w = SpinBox()
            lo, hi = it["extra"]
            w.setRange(lo, hi)
            w.setValue(int(val) if val.lstrip("-").isdigit() else lo)
            w.setMinimumWidth(96)
            w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            w.valueChanged.connect(mark)
        else:
            w = LineEdit()
            w.setText(val)
            w.setMinimumWidth(140)
            w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            w.setPlaceholderText("Game default" if key == "mod_language_override" else "")
            w.textChanged.connect(lambda t: mark(t.strip()))
        return SettingRow(title, blurb, w, help_text)

    def _mark_dirty(self, key, new):
        if new == self.all_file.get(key):
            self.all_dirty.pop(key, None)
        else:
            self.all_dirty[key] = new
        self._all_dirty_changed()

    def _all_dirty_changed(self):
        self._refresh_coop_actions()
        self._update_plan()

    def _on_pw_edit(self, *_):
        if self.ini is None:
            return
        changed = self.pw.text().strip() != (self.pw_file or "")
        self.pw_hint.setText("Not saved yet." if changed else "Friends type this to join.")
        self.pw_hint.setTextColor(ACCENT_LIGHT if changed else HINT_ON_LIGHT, ACCENT if changed else HINT)
        self._refresh_coop_actions()
        self._update_plan()

    def _show_scaling(self, spec):
        """Labels, visible fields and presets for this ini's set of difficulty keys (six for Elden Ring, three for
        Nightreign)."""
        n = len(spec.keys) if spec else len(self.spins)
        labels = spec.labels if spec else SCALING_LABELS
        for i, (lab, sp) in enumerate(zip(self.scal_labs, self.spins, strict=True)):
            lab.setVisible(i < n)
            sp.setVisible(i < n)
            if i < n:
                lab.setText(labels[i])
        presets = list(spec.presets) if spec else []
        self.preset.blockSignals(True)
        self.preset.clear()
        self.preset.addItems(presets + [CUSTOM])
        self.preset.blockSignals(False)
        self.preset.setEnabled(bool(presets))
        self.preset_row.setVisible(bool(presets))
        if spec:
            self.scal_about.setText(spec.hint)

    def _scaling_values(self):
        n = len(self.scaling.keys) if self.scaling else len(self.spins)
        return tuple(sp.value() for sp in self.spins[:n])

    def _set_spins(self, values, enabled):
        for sp, v in zip(self.spins, values):
            sp.blockSignals(True)
            sp.setValue(int(v))
            sp.blockSignals(False)
            sp.setEnabled(enabled)

    def _on_preset(self, name):
        if self.scaling_file is None:
            return
        presets = self.scaling.presets if self.scaling else SCALING_PRESETS
        if name in presets:
            self._set_spins(presets[name], False)
        else:
            self._set_spins(self._scaling_values() or self.scaling_file, True)
        self._on_scaling_edit()

    def _on_scaling_edit(self, *_):
        if self.scaling_file is None:
            return
        changed = self._scaling_values() != self.scaling_file
        self.scal_hint.setText("Not saved yet." if changed else "")
        self.scal_hint.setTextColor(ACCENT_LIGHT if changed else HINT_ON_LIGHT, ACCENT if changed else HINT)
        self._refresh_coop_actions()
        self._update_plan()

    def _coop_pending(self):
        if self.ini is None or not hasattr(self, "pw") or not getattr(self, "_coop_ready", False):
            return False
        pw = self.pw.text().strip() != (self.pw_file or "")
        scal = self.scaling_file is not None and self._scaling_values() != self.scaling_file
        return pw or scal or bool(getattr(self, "all_dirty", None))

    def _pending_labels(self):
        if self.ini is None:
            return []
        labels = []
        if self.pw.text().strip() != (self.pw_file or ""):
            labels.append("Password")
        if self.scaling_file is not None and self._scaling_values() != self.scaling_file:
            labels.append("Difficulty")
        labels.extend(label_of(k) for k in getattr(self, "all_dirty", {}))
        return labels

    def _refresh_coop_actions(self):
        if not hasattr(self, "all_save"):
            return
        labels = self._pending_labels()
        pending = bool(labels)
        shown = ", ".join(labels[:4]) + (" ..." if len(labels) > 4 else "")
        self.save_bar.set_state(pending, ("Not saved: " + shown) if pending else "Saved.")

    def _discard_coop(self):
        self._load_coop()
        self._toast("Changes discarded", "Co-op settings are back to what is in the file.", info=True)

    def save_seamless(self):
        """Write password, scaling, and any other edited co-op settings. Returns what was written, or None if the write failed."""
        if self.ini is None:
            return []
        new = self.pw.text().strip()
        if self.pw.text().strip() != (self.pw_file or "") and not new:
            self._toast("Password needed", "The Seamless Co-op password cannot be empty.", error=True)
            return None
        wrote = []
        if new != (self.pw_file or ""):
            try:
                write_password(self.ini, new)
                self.pw_file = new
                self._on_pw_edit()
                self._log(f"password changed in {self.ini}")
            except Exception as e:
                self._toast("Could not write the password", str(e), error=True)
                return None
            wrote.append("Password")
        if self.scaling_file is not None and self._scaling_values() != self.scaling_file:
            vals = self._scaling_values()
            keys = self.scaling.keys if self.scaling else SCALING_KEYS
            labels = self.scaling.labels if self.scaling else SCALING_LABELS
            missing = write_keys(self.ini, dict(zip(keys, vals, strict=True)))
            if missing:
                self._toast("Missing keys", f"Not in {self.ini.name}: " + ", ".join(missing), error=True)
                return None
            self.scaling_file = vals
            self._on_scaling_edit()
            self._log("scaling changed to " + ", ".join(f"{l} {v}%" for l, v in zip(labels, vals, strict=True)))
            wrote.append("Difficulty")
        if self.all_dirty:
            labels = [label_of(k) for k in self.all_dirty]
            missing = write_keys(self.ini, dict(self.all_dirty))
            if missing:
                self._toast("Missing keys", f"Not in {self.ini.name}: " + ", ".join(missing), error=True)
                return None
            self._log("settings changed: " + ", ".join(f"{k}={v}" for k, v in self.all_dirty.items()))
            wrote.extend(labels)
            self._fill_all_settings()
        self.share_fill()
        self._refresh_coop_actions()
        return wrote

    def _announce_saved(self, wrote, when):
        """Toast after a co-op save. when is 'next' (saved for the following launch) or 'play' (this launch uses them)."""
        if wrote is None:
            return False
        if not wrote:
            return True
        shown = wrote[:3]
        if len(wrote) == 1:
            what = wrote[0]
        elif len(wrote) == 2:
            what = f"{wrote[0]} and {wrote[1]}"
        elif len(wrote) == 3:
            what = f"{wrote[0]}, {wrote[1]}, and {wrote[2]}"
        else:
            what = f"{shown[0]}, {shown[1]}, and {len(wrote) - 2} more"
        if when == "play":
            self._toast("Settings applied", f"{what}. This session will use them.")
        else:
            self._toast("Settings saved", f"{what}. They apply the next time you start the game.")
        return True

    def share_fill(self):
        if self.ini:
            self.share_panel.set_baseline(export_text(self.ini), f"Your settings, from {self.ini.name}", str(self.ini))

    def share_copy(self):
        QApplication.clipboard().setText(self.share.toPlainText())
        self._toast("Copied", "Settings are on the clipboard.")

    def share_paste(self):
        t = QApplication.clipboard().text()
        if not t.strip():
            self._toast("Clipboard is empty", "Copy settings from your friend first.", info=True)
            return
        self.share_panel.set_text(t)
        self._toast("Pasted", "Apply writes the settings that differ from yours, after a confirm.", info=True)

    def share_apply(self):
        if self.ini is None:
            return
        try:
            incoming = parse_settings_json(self.share.toPlainText())
        except Exception as e:
            self._toast("Not settings text", f"The text could not be read as co-op settings: {e}", error=True)
            return
        changes, unknown = plan_import(self.ini, incoming)
        if not changes:
            self._toast(
                "Nothing to change",
                "It matches your current settings." + (f" Ignored: {', '.join(unknown)}" if unknown else ""),
                info=True,
            )
            return
        if not confirm(
            self,
            f"Apply {len(changes)} setting{'s' if len(changes) != 1 else ''} from the pasted text",
            changes=[f"{k}:  {o}  \u2192  {n}" for k, (o, n) in changes.items()],
            detail=(f"Ignored (not in your file): {', '.join(unknown)}" if unknown else ""),
            safety="They apply the next time the game starts. The ini keeps a .bak of the previous version.",
            apply_text="Apply",
        ):
            return
        try:
            write_keys(self.ini, {k: n for k, (o, n) in changes.items()})
        except Exception as e:
            self._toast("Could not write", str(e), error=True)
            return
        self._log("applied " + ", ".join(f"{k}={n}" for k, (o, n) in changes.items()))
        self._load_coop()
        self._toast(
            "Settings applied",
            f"{len(changes)} setting"
            + ("s" if len(changes) != 1 else "")
            + ". They apply the next time you start the game.",
        )

    def share_save(self):
        p, _ = QFileDialog.getSaveFileName(
            self, "Save settings as", "seamless-coop-settings.json", "Settings export (*.json)"
        )
        if p:
            Path(p).write_text(self.share.toPlainText(), encoding="utf-8")
            self._toast("File saved", Path(p).name)

    def share_load(self):
        p, _ = QFileDialog.getOpenFileName(self, "Load settings file", "", "Settings export (*.json)")
        if p:
            self.share_panel.set_text(Path(p).read_text(encoding="utf-8"))
            self._toast(
                f"Opened {Path(p).name}",
                "Apply writes the settings that differ from yours, after a confirm.",
                info=True,
            )

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

    def _open_logs_folder(self):
        logs = self.ctx.data_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        desktop.open_path(str(logs))

    def _open_place(self, key, label):
        p = places(self.setup, self.ctx.locations).get(key)
        if not p:
            why = {
                "me3": "me3 was not found on this PC. Set it under Locations, or install it.",
                "game": f"The game folder is unknown: Steam did not report {self.game.name}, and no game exe is set under Locations.",
                "saves": f"No {self.game.name} save folder in this Windows account yet.",
                "profile": "Pick a setup on Play first.",
                "mods": "Pick a setup on Play first.",
            }.get(key, "Unknown folder.")
            self._toast(f"No {label.lower()} folder", why, error=True)
            return
        desktop.open_path(str(p))

    def _folder_btn(self, key, label, icon=FI.FOLDER, tip=""):
        b = ghost_btn(label, icon)
        b.setToolTip(tip or f"Open the {label.lower()} folder in Explorer.")
        b.clicked.connect(lambda _=False, k=key, l=label: self._open_place(k, l))
        return b

    def _location_value(self, key):
        """A Locations value; the game executable is the active game's own."""
        if key == "game_exe":
            return str(game_setting(self.settings, self.game.key, "game_exe") or "")
        return str(getattr(self.settings, key) or "")

    def _pick_location(self, key, is_dir, filt):
        if is_dir:
            p = QFileDialog.getExistingDirectory(self, "Pick the folder", self._location_value(key))
        else:
            p, _ = QFileDialog.getOpenFileName(
                self, "Pick the file", self._location_value(key), filt + ";;All files (*)"
            )
        if p:
            self._set_location(key, p)

    def _set_location(self, key, value):
        if key == "game_exe":
            save_game_settings(self.game.key, game_exe=value)
        else:
            save_settings(**{key: value})
        self.settings = self.ctx.reload_settings()
        self.loc[key].setText(value or "detected")
        self.loc[key].setToolTip(value)
        self.setups = (
            discover(remembered_setup(self.settings, self.game), self.ctx.locations) if self.game.ready else []
        )
        self._fill_setups()
        self._refresh_me3()
        self._fill_mods()
        self._update_plan()
        self._toast("Location updated", "Detecting again." if not value else Path(value).name)

    def _refresh_me3(self):
        setup, loc = self.setup, self.ctx.locations

        def work(_progress):
            try:
                return me3_facts(setup, loc)
            except Exception as e:
                return {"error": str(e)}

        self.jobs.start(work, on_result=self._on_me3)

    @staticmethod
    def _install_kind() -> str:
        if not FROZEN:
            return "running from source"
        if is_installed():
            return "installed"
        if is_portable():
            return "portable"
        return "AppImage" if appimage() else "not installed"

    def _check_launcher_update(self, force=False):
        def work(_progress):
            try:
                check = feed.check_launcher_update(force=force)
            except Exception as e:
                check = feed.UpdateCheck("error", reason=str(e))
            try:
                advisory = feed.check_advisory(force=force)
            except Exception:
                advisory = None
            return {"check": check, "advisory": advisory, "force": force}

        self.jobs.start(work, on_result=self._on_update, name="launcher-update")

    def _on_channel(self, index):
        channel = "beta" if index == 1 else "stable"
        save_settings(launcher_channel=channel)
        self.settings.launcher_channel = channel
        self._offered = None
        self._check_launcher_update(force=True)

    def _launcher_status(self, check) -> tuple[str, str]:
        """The Settings line: version, kind of copy, and what the last check found (never 'up to date' after a check
        that failed)."""
        parts = [f"{TITLE} {VERSION}", self._install_kind()]
        if self.settings.launcher_channel == "beta":
            parts.append("beta channel")
        tone = "muted"
        if check.offer:
            parts.append(f"{check.offer['version']} is available")
            tone = "accent"
        elif check.failed or check.status == "waiting":
            parts.append(f"could not check: {check.reason}" if check.reason else "could not check")
            tone = "warning"
        elif check.status == "off":
            parts.append("update checks off")
        else:
            parts.append("up to date")
        if check.checked:
            same_day = time.strftime("%Y%m%d", time.localtime(check.checked)) == time.strftime("%Y%m%d")
            stamp = time.strftime("%H:%M" if same_day else "%d %b %H:%M", time.localtime(check.checked))
            parts.append(f"last checked {stamp}")
        return "  ·  ".join(parts), tone

    def _on_update(self, payload):
        check, advisory, force = payload["check"], payload.get("advisory"), payload.get("force")
        text, tone = self._launcher_status(check)
        self.launcher_line.setText(text)
        tone_label(self.launcher_line, tone)
        if advisory:
            self._show_advisory(advisory, check.offer)
        if force:
            if check.failed:
                later = (
                    f" The next automatic check is after {time.strftime('%H:%M', time.localtime(check.retry_at))}."
                    if check.retry_at
                    else ""
                )
                self._toast("Could not check", f"{check.reason}.{later}", error=True)
            elif check.blocked:
                self._toast(
                    "Not offered again",
                    f"{check.blocked} failed to start here and was undone. A newer release will be offered.",
                    info=True,
                )
            elif not check.offer:
                self._toast("Up to date", f"{TITLE} {VERSION} is the latest release.", info=True)
        if check.offer and check.offer["version"] != self._offered:
            self._offer_update(check.offer)

    def _show_advisory(self, advisory, offer):
        """The project asks everyone below a version to update (advisory.json on main). A notice only."""
        if getattr(self, "_advisory_shown", False):
            return
        self._advisory_shown = True
        msg = advisory.get("message") or "This version has a known problem."
        target = f" Update to {offer['version']}." if offer else " Update to the newest release."
        go = ghost_btn("Details", FI.LINK)
        go.clicked.connect(lambda: desktop.open_path(advisory.get("url") or RELEASES_URL))
        notice(self, "warning", f"{TITLE} {VERSION} should be updated", msg + target, actions=(go,))

    def _offer_update(self, info):
        version = info["version"]
        self._offered = version
        signed = updates.can_self_update(info)
        can_apply = FROZEN and signed
        if can_apply:
            go = primary_btn("Update now")
            go.setToolTip("Download it, check its signature and checksum, install it and restart.")
        else:
            go = ghost_btn("Download", FI.DOWNLOAD)
            go.setToolTip(
                "Open the releases page in the browser."
                if signed or not FROZEN
                else "This copy cannot update itself (or the release has no signed feed): install it from the "
                "releases page."
            )
        notes = ghost_btn("Notes")
        notes.setToolTip("The full release notes, on GitHub.")
        notes.clicked.connect(lambda: desktop.open_path(info.get("url") or RELEASES_URL))
        skip = ghost_btn("Skip this version")
        skip.setToolTip("Do not mention this version again; the next one will show.")
        summary = feed.release_notes(info.get("notes", ""), lines=4)
        how = (
            "One click, then a restart. Settings stay."
            if can_apply
            else "Get it from the releases page. Settings stay."
        )
        kind = "pre-release " if info.get("prerelease") else ""
        bar = notice(
            self,
            "info",
            f"{TITLE} {kind}{version} is available",
            f"{summary}\n\n{how}" if summary else how,
            actions=(go, notes, skip),
        )
        if can_apply:
            go.clicked.connect(lambda: self._start_update(info, bar))
        else:
            go.clicked.connect(lambda: desktop.open_path(info.get("url") or RELEASES_URL))
        skip.clicked.connect(lambda: (feed.skip_update(version), bar.close()))

    def _cannot_update(self) -> str:
        """Why the program cannot be replaced now, or ''."""
        if self.game_running:
            return f"Close {self.game.name} first."
        if self.busy:
            return "Wait for the current job."
        return updates.busy_reason()

    def _start_update(self, info, bar):
        why = self._cannot_update()
        if why:
            self._toast("Cannot update now", why, error=True)
            return
        bar.close()
        self._update_bar = notice(self, "info", f"Downloading {TITLE} {info['version']}", "Starting...", closable=False)
        version = info["version"]

        def work(report):
            def progress(done, total):
                mb = done / 1_000_000
                report(f"{mb:.0f} of {total / 1_000_000:.0f} MB" if total else f"{mb:.0f} MB")

            try:
                prepared = updates.download_update(info, progress=progress)
                report("Keeping this version, to put it back if the new one does not start")
                prepared.rollback = updates.stage_rollback()
                return {"prepared": prepared, "version": version}
            except Exception as e:
                return {"error": str(e)}

        self.jobs.start(
            work, on_result=self._on_update_ready, on_progress=self._on_update_progress, name="launcher-download"
        )

    def _on_update_progress(self, text):
        if self._update_bar is not None:
            try:
                self._update_bar.contentLabel.setText(text)
            except RuntimeError:
                self._update_bar = None

    def _on_update_ready(self, result):
        if self._update_bar is not None:
            try:
                self._update_bar.close()
            except RuntimeError:
                pass
            self._update_bar = None
        if result.get("error"):
            self._offered = None  # the next check offers it again
            notice(self, "error", "Update not applied", result["error"])
            return
        prepared = result["prepared"]
        go = primary_btn("Restart now")
        later = ghost_btn("Later")
        later.setToolTip("Keep using this version; the download is kept and the notice returns next time.")
        kind = "an update of" if prepared.delta else "the full"
        bar = notice(
            self,
            "success",
            f"{TITLE} {result['version']} is ready",
            f"Checked: signature and {kind} package. Restart to finish; if it does not start, this version comes "
            "back by itself.",
            actions=(go, later),
        )
        go.clicked.connect(lambda: self._restart_updated(prepared))
        later.clicked.connect(bar.close)

    def _restart_updated(self, prepared):
        why = self._cannot_update()
        if why:
            self._toast("Cannot restart now", why, error=True)
            return
        self.close()  # asks about unsaved edits; a cancel there leaves the window open
        if self.isVisible():
            return
        self._release_instance()  # the new version takes the window's name when it starts
        try:
            updates.apply_update(prepared)  # Velopack applies after this process exits, then restarts the launcher
        except Exception as e:
            self._take_instance()
            self.show()
            self._toast("Update not applied", f"{e} This version keeps running.", error=True)
            return
        QApplication.instance().quit()

    def _on_update_outcome(self, result):
        """How the last update went, shown once."""
        if not result:
            return
        status, version = result.get("status"), result.get("version", "")
        updates.clear_outcome()
        if status == "ok":
            was = f" (was {result['from']})" if result.get("from") else ""
            self._toast("Updated", f"{TITLE} {version} is running{was}.")
            return
        self._offered = None
        releases = ghost_btn("Releases", FI.LINK)
        releases.clicked.connect(lambda: desktop.open_path(RELEASES_URL))
        actions = [releases]
        if status == "rolled_back":
            title = f"{TITLE} {version} did not start; this version was put back"
            detail = (
                f"{version} {result.get('error') or 'did not start'}. It is not offered again; a newer release will "
                "be. Your settings and data were not touched."
            )
        else:
            title = f"The update to {TITLE} {version} did not finish"
            detail = result.get("error") or ""
            again = ghost_btn("Try again", FI.UPDATE)
            again.clicked.connect(lambda: self._check_launcher_update(force=True))
            actions.insert(0, again)
        notice(self, "error", title, detail, actions=actions)

    def _on_migration(self, record):
        """The move from the old (Inno Setup) install, reported once per state."""
        if not record:
            return
        status = record.get("status")
        if status == "waiting":
            notice(self, "warning", "The old Roundtable Souls is still open", record.get("reason", ""))
        elif status == "failed":
            notice(self, "error", "The old install could not be removed", record.get("reason", ""))
        elif status in ("done", "steam_pending"):
            steam = record.get("steam_changed") or []
            lines = [
                f"The old install ({record.get('old_version') or 'Inno Setup'}) was removed; settings, logs and "
                "backups stayed where they were.",
                "Start menu shortcut updated"
                + (" and desktop shortcut recreated." if record.get("had_desktop") else "."),
            ]
            if steam:
                lines.append(f"Steam shortcuts now start this copy: {', '.join(steam)}.")
            if status == "steam_pending":
                lines.append("Close Steam, then Settings > Steam shortcut > Point Steam shortcuts here.")
            notice(self, "success" if status == "done" else "warning", "Moved to the new installer", "\n".join(lines))

    def _point_steam_shortcuts(self):
        def work(_progress):
            try:
                record = load_settings().inno_migration or {}
                if record.get("steam_pending") or (record.get("old_exe") and not record.get("steam_done")):
                    changed = migration.finish_steam_step()
                else:
                    changed = migration.point_play_shortcuts_here()
                return {"changed": [s.name for s in changed]}
            except Exception as e:
                return {"error": str(e)}

        self.jobs.start(work, on_result=self._on_steam_retarget, name="steam-shortcuts")

    def _on_steam_retarget(self, result):
        if result.get("error"):
            self._toast("Steam shortcuts not changed", result["error"], error=True)
        elif result.get("changed"):
            self._toast("Steam shortcuts updated", f"Now starting this copy: {', '.join(result['changed'])}.")
        else:
            self._toast("Nothing to change", "No Steam shortcut with --play starts another copy.", info=True)

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

    def _on_me3(self, f):
        self._me3 = f
        if f.get("reload"):  # me3 reported its folders: its profile folder may be the one to use now
            self.ctx.reload_settings()
        if getattr(self, "_conf_result", None):  # the Load order card may need the version note
            self._fill_conflicts(self._conf_result)
        if f.get("error"):
            self.me3_line.setText(f"me3: {f['error']}")
            return
        v = f.get("version")
        latest = (f.get("latest") or {}).get("version")
        text = f"me3 {v}" if v else "me3 version unknown"
        if f.get("update") and latest:
            text += f"  \u00b7  {latest} is available"
        elif v and latest:
            text += "  \u00b7  up to date"
        self.me3_line.setText(text)
        tone_label(self.me3_line, "accent" if f.get("update") else "muted")
        self.me3_line.setToolTip(f.get("path") or "")
        info = f.get("info") or {}
        where = info.get("install_prefix") or (str(Path(f["path"]).parent) if f.get("path") else "")
        self.me3_dir_btn.setEnabled(bool(where and Path(where).is_dir()))
        self.me3_dir_btn.setToolTip(where or "me3 was not found")
        self.me3_logs_btn.setEnabled(bool(info.get("logs_dir")))
        self.me3_prof_btn.setEnabled(bool(info.get("profile_dir")))
        self.me3_logs_btn.setToolTip(info.get("logs_dir") or "me3 info did not report a logs folder")
        self.me3_prof_btn.setToolTip(info.get("profile_dir") or "")
        self._update_plan()

    def _remember_play(self, key, checked):
        save_settings(**{key: bool(checked)})
        setattr(self.settings, key, bool(checked))
        if key == "warn_dead_shells":
            self._on_shells(dead_shells_count(loc=self.ctx.locations))

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

    # ---------------------------------------------------------------- updating merged mods before Play
    UPDATE_LABEL = "Updating merged mods before Play..."

    def _update_first(self, resume) -> bool:
        """Before Play: when the merged mods are out of date (see mod_merge.play_check), rebuild them as a job and call
        resume (Play again) when it succeeds. When they cannot be rebuilt now, ask before starting with them as they
        are. True when Play is handled here (a job started, or the question asked), False to play right away."""
        s = self.setup
        if s is None or not s.profile or self.game is not games.ELDEN_RING or self.game_running:
            return False
        if getattr(self, "_skip_update_once", False):  # Play anyway, chosen for this one start
            self._skip_update_once = False
            return False
        prof = Path(s.profile)
        h = core.mod_merge.play_check(prof)
        if h is None:
            return False
        self._on_merge({**h, "profile": str(prof)})
        reason = (h.get("reasons") or [h.get("text") or "The merged mods are out of date"])[0]
        if h["blocked"]:
            return self._ask_play_stale(resume, reason, f"They cannot be rebuilt now: {h['blocked']}")
        key = tuple(h.get("reasons") or ())
        failed = getattr(self, "_update_failed", {})
        if failed.get(str(prof)) == key:
            return self._ask_play_stale(
                resume, reason, "The last rebuild with these mods failed; its log is on Activity."
            )
        if not play_options(self.settings)["play_update_merge"] and not self._ask_rebuild(resume, reason):
            return True
        if not self._tool_ready(prof):
            return self._ask_play_stale(resume, reason, "The rebuild tool did not run (not allowed, or it cannot run).")
        self._update_resume = resume
        self._update_key = (str(prof), key)
        self._update_cancelled = False
        cancel = ghost_btn("Cancel Play", FI.CLOSE)
        self._update_bar = notice(
            self,
            "info",
            "Updating merged mods for Play",
            (h.get("reasons") or [h.get("text") or ""])[0]
            + ". The game starts when it is done; a rebuild tool can take a few minutes.",
            actions=(cancel,),
        )
        cancel.clicked.connect(self._cancel_update)

        def job(_setup, loc):
            run_logging.start_log("launcher: update merged mods before Play", loc.game.key)
            try:
                out = core.mod_merge.update_before_play(prof, run_logging.log)
                if out is not None:
                    core.run_logging.set_undo(out.get("undo"))
                    run_logging.log(f"done: merged mods updated by {out['backend']}; {out['profile_note']}")
                else:
                    run_logging.log("done: the merged mods were already up to date")
            except core.mod_merge.MergeError as e:
                run_logging.log(f"error: {e}")
                raise SystemExit(1) from e

        self.start(job, self.UPDATE_LABEL, need_setup=False)
        return True

    def _ask_rebuild(self, resume, reason: str) -> bool:
        """Automatic rebuilds are off: ask before rebuilding. True to rebuild now; False when the question
        handled Play (Play anyway this once, or cancelled)."""
        dlg = ConfirmDialog(
            "Your merged mods are out of date",
            self,
            changes=[reason],
            warning="Playing anyway starts the game with the previous result: a removed or changed mod may still be "
            "inside it.",
            apply_text="Rebuild and play",
            second_text="Play anyway",
        )
        if not dlg.exec():
            return False
        if dlg.choice == "second":
            self._skip_update_once = True
            QTimer.singleShot(0, resume)
            return False
        return True

    def _ask_play_stale(self, resume, reason: str, why: str) -> bool:
        """The merged mods are out of date and are not being rebuilt: say so before the game starts. Play anyway
        starts it once with the previous result; there is no setting that skips this."""
        dlg = ConfirmDialog(
            "Your merged mods are out of date",
            self,
            changes=[reason, why],
            warning="Playing anyway starts the game with the previous result: a removed or changed mod may still be "
            "inside it. Rebuild on the Mods page brings it up to date.",
            apply_text="Play anyway",
            second_text="View details",
        )
        if not dlg.exec():
            return True
        if dlg.choice == "second":
            self._open_activity(failed_only=True)
            return True
        self._skip_update_once = True
        QTimer.singleShot(0, resume)
        return True

    def _cancel_update(self):
        """The rebuild itself finishes (a tool stopped midway could leave its files half-written); the game then does
        not start."""
        self._update_cancelled = True
        self._close_update_bar()
        self._toast("Play cancelled", "The update finishes first, then the game does not start.", info=True)

    def _close_update_bar(self):
        bar = getattr(self, "_update_bar", None)
        self._update_bar = None
        if bar is not None:
            try:
                bar.close()
            except Exception:
                pass

    def _after_update(self, ok, status):
        self.set_busy(False, f"{status} at {datetime.datetime.now():%H:%M}")
        self._pill("Ready" if ok else "Stopped", "success" if ok else "error")
        self._close_update_bar()
        self._load_profile_editor(force=True)
        self._fill_mods()
        self._update_plan()
        self._update_activity_badge()
        resume = getattr(self, "_update_resume", None)
        prof, key = getattr(self, "_update_key", ("", ()))
        self._update_resume = None
        if self._update_cancelled or resume is None:
            return
        if ok:
            getattr(self, "_update_failed", {}).pop(prof, None)
            QTimer.singleShot(0, resume)
            return
        self._update_failed = {**getattr(self, "_update_failed", {}), prof: key}
        run = core.mod_merge.last_run(Path(prof)) or {}
        dlg = ConfirmDialog(
            "The merged mods could not be updated",
            self,
            changes=[run.get("message") or "The rebuild stopped; its log is on Activity."],
            safety="Nothing was replaced: the previous result is still in place, so the game starts with it (without "
            "the latest changes).",
            apply_text="Play anyway",
            second_text="View details",
        )
        if not dlg.exec():
            return
        if dlg.choice == "second":
            self._open_activity(failed_only=True)
            return
        self._skip_update_once = True
        QTimer.singleShot(0, resume)

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

    def launch(self):
        if self.busy or not self.setup:
            return
        if self._update_first(self.launch):
            return
        self._warn_merge()
        wrote = self.save_seamless()
        if wrote is None or not self._announce_saved(wrote, "play"):
            return
        self.start(job_play, "Starting...")

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

    def _remember_offline(self, *_):
        strip = self.off_revive.isChecked()
        steam = self.off_steam.isChecked()
        quiet = self.off_quiet.isChecked()
        save_settings(offline_strip_revive=strip, offline_start_steam=steam, offline_skip_confirm=quiet)
        self.settings.offline_strip_revive, self.settings.offline_start_steam = strip, steam
        self.settings.offline_skip_confirm = quiet

    def launch_offline(self):
        if self.busy or not self.setup:
            return
        if self._update_first(self.launch_offline):
            return
        self._warn_merge()
        strip = self.off_revive.isChecked()
        steam = self.off_steam.isChecked()
        quiet = self.off_quiet.isChecked()
        self._remember_offline()
        if not quiet:
            bits = ["Seamless stays off, so the game uses the standard save"]
            if strip:
                bits.append("Revive stays off too")
            if steam:
                bits.append("Steam is started if it is not running")
            if not confirm(
                self,
                "Play offline",
                changes=bits,
                safety="A temporary .offline.me3 copy is used; your real profile is not changed.",
                detail="Skip this prompt with the switch on Tools.",
                apply_text="Play offline",
            ):
                return

        def job(setup, loc):
            job_play_offline(setup, loc, strip_revive=strip, start_steam=steam)

        self.start(job, "Starting offline...")

    # ---------------------------------------------------------------- misc
    def _toast(self, title, msg, error=False, info=False):
        if self._toast_bar is not None:
            try:
                self._toast_bar.close()
            except Exception:
                pass
        kind = "error" if error else ("info" if info else "success")
        self._toast_bar = notice(self, kind, title, msg, duration=-1 if error else 4500)

    def _on_theme(self, dark):
        save_settings(theme="dark" if dark else "light")
        self.settings.theme = "dark" if dark else "light"
        setTheme(Theme.DARK if dark else Theme.LIGHT)
        setThemeColor(ACCENT if dark else ACCENT_LIGHT)
        self._restyle()

    def _on_logo(self, index):
        mode = ("auto", "dark", "light")[index] if 0 <= index < 3 else "auto"
        save_settings(logo=mode)
        self.settings.logo = mode
        self._apply_logo()

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
