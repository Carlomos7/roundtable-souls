"""Saves: the save files and their characters, backups, the save library and copies, and the review page (one save, its
findings, fixes applied at once).

Part of the window: ui/shell.Launcher inherits SavesView, so its methods share the window's state (self). Moved
from ui/window.py as it was; the page's presenter (plain Python, no Qt) comes in the page-by-page work."""

# The window's state is spread over the shell and the page views, which pyright cannot follow across mixins.
# pyright: reportAttributeAccessIssue=false

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    FlowLayout,
    IconWidget,
    InfoBadge,
    InfoBadgePosition,
    SearchLineEdit,
    StrongBodyLabel,
    TableWidget,
    TitleLabel,
    TransparentPushButton,
)
from qfluentwidgets import FluentIcon as FI

from roundtable_souls.game import catalog as games
from roundtable_souls.platform import desktop
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.saves import backups as save_backups
from roundtable_souls.saves import library as save_library
from roundtable_souls.saves import transfer as save_transfer
from roundtable_souls.services import play as core
from roundtable_souls.services import saves as saves_service
from roundtable_souls.services.play import (
    save_info,
)
from roundtable_souls.services.saves import (
    character_detail,
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
from roundtable_souls.ui.dialogs.common import (
    WRITE_SAFETY,
    WRITE_WARNING,
    TextDialog,
    confirm,
)
from roundtable_souls.ui.dialogs.notes import _save_note_widget, save_check_notes
from roundtable_souls.ui.dialogs.saves import CopyCharacterDialog, CopyFileDialog, SwapDialog
from roundtable_souls.ui.theme import (
    ghost_btn,
    hint,
    primary_btn,
    tone_label,
)
from roundtable_souls.ui.widgets.cards import card, count_label, icon_btn
from roundtable_souls.ui.widgets.labels import ElideLabel, PathTag
from roundtable_souls.ui.widgets.layout import action_row, clear_layout, dispose, page, titled
from roundtable_souls.ui.widgets.panels import ActionBar


class SavesView:
    """The saves page's widgets and handlers (a mixin of ui/shell.Launcher)."""

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
            if b.get("metadata_unreadable"):
                warn = CaptionLabel("⚠  Protected: metadata unreadable")
                tone_label(warn, "warn")
                warn.setToolTip(
                    "This backup's note can't be read, so whether it was kept is unknown. It never ages out until "
                    "you choose: keep it for good or let it age out (the note's bytes are saved beside it first)."
                )
                text.addWidget(warn)
            row.setToolTip(detail or "No change list recorded.")
            rl.addLayout(text, 1)
            k = icon_btn(
                FI.PIN if b["keep"] else FI.UNPIN,
                "Kept for good. Click to let it age out like the others."
                if b["keep"]
                else "Protected: metadata unreadable. Click to keep it for good."
                if b.get("metadata_unreadable")
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
