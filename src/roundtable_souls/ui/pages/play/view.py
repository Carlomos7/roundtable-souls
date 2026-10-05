"""Play: who you are, which setup, the Play and Play offline buttons, and the merged-mods update that runs first.

Part of the window: ui/shell.Launcher inherits PlayView, so its methods share the window's state (self). Moved
from ui/window.py as it was; the page's presenter (plain Python, no Qt) comes in the page-by-page work."""

# The window's state is spread over the shell and the page views, which pyright cannot follow across mixins.
# pyright: reportAttributeAccessIssue=false

from __future__ import annotations

import datetime
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    ComboBox,
)
from qfluentwidgets import FluentIcon as FI

from roundtable_souls.config.settings import exe_dir
from roundtable_souls.game import catalog as games
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.services import play as core
from roundtable_souls.services.mods import (
    read_profile_mods,
)
from roundtable_souls.services.play import (
    job_play,
    job_play_offline,
    play_options,
    remember_setup,
    remembered_setup,
    same_source,
    setup_from_path,
)
from roundtable_souls.services.settings import (
    load_settings,
    save_settings,
)
from roundtable_souls.ui.dialogs import (
    ConfirmDialog,
    confirm,
)
from roundtable_souls.ui.theme import (
    ACCENT,
    ACCENT_LIGHT,
    HINT,
    HINT_ON_LIGHT,
    ghost_btn,
    hint,
)
from roundtable_souls.ui.widgets import (
    ExpandGroupSettingCard,
    HeroBanner,
    LogPane,
    notice,
    page,
    short_problem,
    tone_label,
)


class PlayView:
    """The play page's widgets and handlers (a mixin of ui/shell.Launcher)."""

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
