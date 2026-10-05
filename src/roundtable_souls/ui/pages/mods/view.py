"""Mods: the profile's mods, their order and options, installs and removals, the Load order card, merge health and the
profile's history.

Part of the window: ui/shell.Launcher inherits ModsView, so its methods share the window's state (self). Moved
from ui/window.py as it was; the page's presenter (plain Python, no Qt) comes in the page-by-page work."""

# The window's state is spread over the shell and the page views, which pyright cannot follow across mixins.
# pyright: reportAttributeAccessIssue=false

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    CaptionLabel,
    ComboBox,
    LineEdit,
    RoundMenu,
    SpinBox,
    StrongBodyLabel,
    SwitchButton,
)
from qfluentwidgets import FluentIcon as FI

from roundtable_souls.game import catalog as games
from roundtable_souls.mods import checks as mod_checks
from roundtable_souls.mods import configs as mod_configs
from roundtable_souls.mods import conflicts as mod_overview
from roundtable_souls.mods import extract as mod_extract
from roundtable_souls.mods import history as mod_history
from roundtable_souls.mods import install as mod_install
from roundtable_souls.mods import stay_last as mod_stay_last
from roundtable_souls.mods import undo as mod_undo
from roundtable_souls.platform import desktop, trash
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.services import play as core
from roundtable_souls.services.mods import (
    create_profile,
    delete_profile,
    install_mod,
    plan_mod_install,
    profile_entries,
    read_profile_settings,
    replan_mod_install,
    set_mod_options,
    uninstall_mod,
    write_profile_setting,
)
from roundtable_souls.services.play import (
    discover,
    forget_setup,
    play_options,
    remember_setup,
)
from roundtable_souls.services.settings import (
    load_settings,
    save_settings,
)
from roundtable_souls.ui.config_files import ConfigFilesDialog
from roundtable_souls.ui.dialogs.common import (
    ChoiceListDialog,
    ConfirmDialog,
    ModOptionsDialog,
    TextDialog,
    VersionsDialog,
    confirm,
)
from roundtable_souls.ui.install_dialog import InstallDialog
from roundtable_souls.ui.theme import (
    ghost_btn,
    hint,
    tone_label,
)
from roundtable_souls.ui.widgets.cards import ExpandGroupSettingCard, SettingRow, card, icon_btn
from roundtable_souls.ui.widgets.labels import ElideLabel, NameWithTag
from roundtable_souls.ui.widgets.layout import action_row, dispose, page, titled
from roundtable_souls.ui.widgets.menus import style_menu
from roundtable_souls.ui.widgets.notices import DropOverlay, StatusPill, notice
from roundtable_souls.ui.widgets.panels import EditorPanel

ROW_ACTION_W = 156  # the action button on each Mods row


class ModsView:
    """The mods page's widgets and handlers (a mixin of ui/shell.Launcher)."""

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
