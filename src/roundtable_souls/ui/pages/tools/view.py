"""Settings (the Tools page): locations, folders, me3, Play session switches, appearance, the launcher's own updates
and its Steam shortcuts.

Part of the window: ui/shell.Launcher inherits ToolsView, so its methods share the window's state (self). Moved
from ui/window.py as it was; the page's presenter (plain Python, no Qt) comes in the page-by-page work."""

# The window's state is spread over the shell and the page views, which pyright cannot follow across mixins.
# pyright: reportAttributeAccessIssue=false

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    FlowLayout,
    LineEdit,
    SwitchButton,
    Theme,
    setTheme,
    setThemeColor,
)
from qfluentwidgets import FluentIcon as FI

from roundtable_souls.config.settings import FROZEN, appimage, is_installed, is_portable
from roundtable_souls.platform import desktop
from roundtable_souls.services.mods import (
    me3_facts,
)
from roundtable_souls.services.play import (
    TITLE,
    VERSION,
    discover,
    job_clear,
    job_repair,
    places,
    play_command,
    remembered_setup,
)
from roundtable_souls.services.saves import (
    dead_shells_count,
)
from roundtable_souls.services.settings import (
    game_setting,
    load_settings,
    save_game_settings,
    save_settings,
)
from roundtable_souls.services.updates import RELEASES_URL
from roundtable_souls.ui.theme import (
    ACCENT,
    ACCENT_LIGHT,
    ghost_btn,
    hint,
    primary_btn,
    tone_label,
)
from roundtable_souls.ui.widgets.cards import ExpandGroupSettingCard, LogoPreview, PairRow, SettingRow, card, icon_btn
from roundtable_souls.ui.widgets.layout import action_row, page, titled
from roundtable_souls.ui.widgets.notices import notice
from roundtable_souls.updates import apply as updates
from roundtable_souls.updates import feed
from roundtable_souls.updates import inno as migration


class ToolsView:
    """The tools page's widgets and handlers (a mixin of ui/shell.Launcher)."""

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
                "For a mod the launcher has a config for (Nightreign Revive LITE 0.1.33), a rebuild merges it from its "
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
                "Off by default: the game keeps its own .bak, and each repair makes a copy anyway. Turn it on for a copy before every session. When a backup fails, the game waits: you choose Retry, Launch without backup or Cancel (a Steam shortcut stops unless it has --allow-without-backup).",
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
