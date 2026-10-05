"""What an install asks: what to call it, which of its files to take, and (for a mod with a regulation.bin) where it
goes in the load order. Everything else follows from the mod itself; Options changes any of it once it is in."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CheckBox, ComboBox, LineEdit, ScrollArea, SubtitleLabel

from roundtable_souls.ui.dialogs import Dialog
from roundtable_souls.ui.theme import hint, tone_label

# what each kind of file is, and (for the ones left unticked) why it is not needed
GROUP_TEXT = {
    "game": "game files",
    "regulation": "the game's parameters",
    "dll": "the DLL mod",
    "settings": "its settings",
    "files": "its files",
    "doc": "readme / docs, not needed to play",
    "profile": "an me3 profile, not needed: the mod is added to yours",
    "loader": "another mod loader, not needed with me3",
    "other": "not recognised, installed as shipped",
}
EXTRA_TEXT = "beside the mod's folder, not part of it"

# the game's msg/<folder> names
LANGUAGES = {
    "engus": "English",
    "jpnjp": "Japanese",
    "frafr": "French",
    "deude": "German",
    "itait": "Italian",
    "spaes": "Spanish (Spain)",
    "spaar": "Spanish (Latin America)",
    "polpl": "Polish",
    "porbr": "Portuguese (Brazil)",
    "rusru": "Russian",
    "korkr": "Korean",
    "zhotw": "Chinese (Traditional)",
    "zhocn": "Chinese (Simplified)",
    "thath": "Thai",
    "araae": "Arabic",
}


def _size(n: int) -> str:
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{max(1, n // 1024)} KB"


class InstallDialog(Dialog):
    """plan: a plan_mod_install result. replan(name, pkg_id, variant) returns a new plan for the same unpacked mod.
    After exec(), .plan is the plan to install, with 'exclude' (names left out) and 'insert_before' set."""

    def __init__(self, parent, plan: dict, replan, profile: Path):
        super().__init__(parent)
        self.plan, self._replan, self.profile = plan, replan, Path(profile)
        self.widget.setMinimumWidth(min(660, max(500, parent.width() - 220)))
        self.viewLayout.setSpacing(6)
        self.title = SubtitleLabel("")
        self.viewLayout.addWidget(self.title)
        self.what = hint("")
        self.what.setWordWrap(True)
        self.viewLayout.addWidget(self.what)

        self.variant = None
        if plan.get("variants"):
            self.viewLayout.addSpacing(6)
            self.viewLayout.addWidget(BodyLabel("The archive has more than one: which to install"))
            self.variant = ComboBox()
            self.variant.addItems(plan["variants"])
            self.variant.setCurrentText(plan.get("variant") or plan["variants"][0])
            self.variant.currentIndexChanged.connect(self._variant_changed)
            self.viewLayout.addWidget(self.variant)

        # folder name and id side by side: the id follows the name until it is typed in
        names = QHBoxLayout()
        names.setSpacing(12)
        self.name = LineEdit()
        self.name.setText(plan["name"])
        self.name.setClearButtonEnabled(True)
        self.name.textEdited.connect(self._changed)
        self.where = hint("")
        self.where.setWordWrap(True)
        self.id_label = BodyLabel("Id")
        self.id = LineEdit()
        self.id.setText(plan.get("id") or plan["name"])
        self.id.setClearButtonEnabled(True)
        self.id.textEdited.connect(self._id_edited)
        self._id_follows_name = True
        self.id_note = hint("")
        self.id_note.setWordWrap(True)
        self.id_box = QWidget()
        for box, widgets in (
            (QWidget(), (BodyLabel("Folder name"), self.name, self.where)),
            (self.id_box, (self.id_label, self.id, self.id_note)),
        ):
            col = QVBoxLayout(box)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(6)
            for w in widgets:
                col.addWidget(w)
            col.addStretch(1)
            names.addWidget(box, 1)
        self.viewLayout.addSpacing(6)
        self.viewLayout.addLayout(names)

        # what to install
        self.pick_label = BodyLabel("What to install")
        self.viewLayout.addSpacing(6)
        self.viewLayout.addWidget(self.pick_label)
        self.pick_box = QWidget()
        self.pick_box.setStyleSheet("background:transparent")
        self.pick_lay = QVBoxLayout(self.pick_box)
        self.pick_lay.setContentsMargins(0, 0, 0, 0)
        self.pick_lay.setSpacing(4)
        self.pick_scroll = ScrollArea()
        self.pick_scroll.setWidgetResizable(True)
        self.pick_scroll.setFrameShape(QFrame.NoFrame)
        self.pick_scroll.setStyleSheet("QScrollArea{background:transparent;border:none}")
        self.pick_scroll.viewport().setStyleSheet("background:transparent")
        self.pick_scroll.setWidget(self.pick_box)
        self.viewLayout.addWidget(self.pick_scroll)
        self.pick_note = hint("Unticked files are left out. Tick one to keep it with the mod anyway.")
        self.viewLayout.addWidget(self.pick_note)
        self.boxes: dict[str, CheckBox] = {}

        # regulation.bin
        self.reg_label = BodyLabel("regulation.bin")
        self.reg_about = hint("")
        self.reg_about.setWordWrap(True)
        self.reg_place = ComboBox()
        self.reg_place.currentIndexChanged.connect(self._refresh_reg)
        self.viewLayout.addSpacing(6)
        self.reg_effect = hint("")
        self.reg_effect.setWordWrap(True)
        self.rebuild = CheckBox("Rebuild combined parameters after install")
        self.rebuild.setChecked(True)
        self.rebuild.stateChanged.connect(self._refresh_reg)
        self.merge_notes = hint("")
        self.merge_notes.setWordWrap(True)
        for w in (self.reg_label, self.reg_about, self.reg_place, self.rebuild, self.reg_effect, self.merge_notes):
            self.viewLayout.addWidget(w)

        # the mod that must stay last: new mods go before it, unless kept after it on purpose
        self.last_note = hint("")
        self.last_note.setWordWrap(True)
        self.after_last = CheckBox("")
        self.after_last.stateChanged.connect(self._after_last_changed)
        self.viewLayout.addSpacing(6)
        self.viewLayout.addWidget(self.last_note)
        self.viewLayout.addWidget(self.after_last)

        self.note = hint("")
        self.note.setWordWrap(True)
        self.viewLayout.addSpacing(6)
        self.viewLayout.addWidget(self.note)
        self.yesButton.setText("Install")
        self.cancelButton.setText("Cancel")
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._apply)
        self._build_contents()
        self._show()

    # -------------------------------------------------------------- edits
    def _id_edited(self, *_):
        self._id_follows_name = False
        self._changed()

    def _changed(self, *_):
        if self._id_follows_name and self.sender() is not self.id:
            self.id.setText(self.name.text())
        self._timer.start()

    def _variant_changed(self, *_):
        self._apply()
        self._build_contents()
        self._show()

    def _apply(self):
        try:
            self.plan = self._replan(
                self.name.text().strip() or None,
                self.id.text().strip() or None,
                self.variant.currentText() if self.variant else None,
            )
        except Exception as e:  # an unreadable variant: say so, keep the last good plan
            self.note.setText(str(e))
            tone_label(self.note, "error")
            return
        self._show()

    # -------------------------------------------------------------- contents
    def _build_contents(self):
        while self.pick_lay.count():
            w = self.pick_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.boxes = {}
        items = [] if self.plan.get("in_place") else self.plan.get("contents") or []
        for it in items:
            what = GROUP_TEXT.get(it["group"], it["group"])
            if it.get("extra") and it["group"] == "other":
                what = EXTRA_TEXT
            cb = CheckBox(f"{it['name']}   ·   {what}   ·   {_size(it['size'])}")
            if it.get("extra"):
                cb.setToolTip(f"{it['extra']}: ticked, it is copied into the mod's folder.")
            cb.setChecked(bool(it["on"]))
            cb.stateChanged.connect(self._contents_changed)
            self.pick_lay.addWidget(cb)
            self.boxes[it["name"]] = cb
        self.pick_lay.addStretch(1)
        shown = bool(items)
        self.pick_label.setVisible(shown)
        self.pick_scroll.setVisible(shown)
        self.pick_scroll.setFixedHeight(min(220, self.pick_lay.sizeHint().height() + 2))
        self.pick_note.setVisible(shown)

    def _contents_changed(self, *_):
        self._refresh_reg()
        self.yesButton.setEnabled(self.validate(quiet=True))

    def _after_last_changed(self, *_):
        if self.reg_place.count() > 1:  # regulation.bin follows: before it, or last (its file replaces the merge)
            self.reg_place.setCurrentIndex(1 if self.after_last.isChecked() else 0)
        self._show_last()
        self._refresh_reg()

    def _show_last(self):
        last = self.plan.get("stay_last")
        self.last_note.setVisible(bool(last))
        self.after_last.setVisible(bool(last))
        if not last:
            return
        self.after_last.setText(f"Advanced: load after {last} instead (replaces its files)")
        if self.after_last.isChecked():
            self.last_note.setText(
                f"Loads after {last}, the mod that must stay last: where both ship a file, this mod's copy is used "
                f"and {last}'s merged one is not. Only for a mod made to go on top of it."
            )
            tone_label(self.last_note, "warning")
        else:
            self.last_note.setText(
                f"Placed before {last}, the mod that must stay last, so {last} includes its changes."
            )
            tone_label(self.last_note, "muted")

    def left_out(self) -> list[str]:
        return [name for name, cb in self.boxes.items() if not cb.isChecked()]

    # -------------------------------------------------------------- regulation.bin
    def _regulation_on(self) -> bool:
        cb = self.boxes.get("regulation.bin")
        return bool(self.plan.get("kind") == "package" and cb is not None and cb.isChecked())

    def _fill_reg_places(self):
        others = self.plan.get("regulation_packages") or []
        self.reg_place.blockSignals(True)
        self.reg_place.clear()
        name = self.plan.get("merge_target") or (others[-1]["name"] if others else None)
        if name:
            self.reg_place.addItem(f"Before {name}, the package that must stay last", userData=name)
        self.reg_place.addItem("Last: this mod's regulation.bin is used", userData=None)
        self.reg_place.setCurrentIndex(0)
        self.reg_place.blockSignals(False)

    def _rebuild_shown(self) -> bool:
        """Offered when regulation.bin is ticked and there is something to do after the install: combining this pack
        with the other packs' parameters, and/or the overlay's rebuild tool (which needs the pack before it)."""
        p = self.plan
        if not (p.get("merge_offered") and self._regulation_on()):
            return False
        before = p.get("already_listed") or self.reg_place.currentData() is not None
        return bool(p.get("merge_combine") or before)

    def _rebuild_text(self) -> str:
        p = self.plan
        if p.get("merge_combine") and p.get("merge_tool"):
            return "Combine parameters and rebuild after install"
        if p.get("merge_combine"):
            return "Combine parameters with the other packs after install"
        return "Rebuild combined parameters after install"

    def _refresh_reg(self, *_):
        on = self._regulation_on()
        others = self.plan.get("regulation_packages") or []
        for w in (self.reg_label, self.reg_about):
            w.setVisible(on)
        placed = not self.plan.get("already_listed")  # a reinstall keeps its entry where it is
        self.reg_place.setVisible(on and bool(others) and placed and not self.plan.get("stay_last"))
        self.rebuild.setText(self._rebuild_text())
        self.rebuild.setVisible(self._rebuild_shown())
        notes = self.plan.get("merge_notes") or []
        self.merge_notes.setVisible(self._rebuild_shown() and self.rebuild.isChecked() and bool(notes))
        self.merge_notes.setText("\n".join(notes))
        self.reg_effect.setVisible(on and bool(others))
        if not on:
            return
        if not others:
            self.reg_about.setText(
                "It replaces the game's parameters (weapons, enemies, items...). No other package here has one, so "
                "this mod's is used."
            )
            return
        winner = others[-1]["name"]
        self.reg_about.setText(
            f"It replaces the game's parameters as one whole file, and me3 uses only the last one in the load order. "
            f"{winner}'s is used now."
        )
        combining = self._rebuild_shown() and self.rebuild.isChecked() and self.plan.get("merge_combine")
        tool = self.plan.get("merge_tool")
        if combining:
            text = (
                "Its parameters are combined with the other packs' into one file, so all of them apply; they apply "
                "once the combine succeeds."
            )
            if tool:
                text += f" Placed before {self.plan.get('merge_target') or winner}, whose rebuild tool then takes the combined file."
            self.reg_effect.setText(text)
            tone_label(self.reg_effect, "muted")
        elif placed and self.reg_place.currentData() is None:
            self.reg_effect.setText(
                f"{winner}'s parameters will not apply: this pack's regulation.bin replaces them, which usually breaks "
                f"{winner} unless this pack was made for it."
            )
            tone_label(self.reg_effect, "warning")
        elif self._rebuild_shown() and self.rebuild.isChecked():
            self.reg_effect.setText(
                f"{winner} keeps working, and the rebuild folds this pack's parameters into the package that must "
                "stay last. They apply only once the rebuild succeeds; a pack whose in-game options start hidden "
                "shows nothing until then."
            )
            tone_label(self.reg_effect, "muted")
        else:
            how = (
                f"Tick {self._rebuild_text().split(' after')[0]} to fold them in."
                if self.plan.get("merge_offered")
                else f"They would need merging into {winner}'s. Untick regulation.bin above to leave the file out."
            )
            self.reg_effect.setText(f"This pack's parameters will not apply: {winner}'s regulation.bin is used. {how}")
            tone_label(self.reg_effect, "warning")

    # -------------------------------------------------------------- what the plan says
    def _show(self):
        p = self.plan
        package = p["kind"] == "package"
        self.title.setText(f"Install {p['name']}")
        size = _size(p["size"])
        if package:
            what = f"Package  ·  {', '.join(p['assets'])}  ·  {size}"
            if p.get("languages"):
                langs = ", ".join(LANGUAGES.get(x.lower(), x) for x in p["languages"])
                what += f"\nText in {langs}; other languages keep the game's own text."
        else:
            what = f"DLL mod  ·  {', '.join(d.name for d in p['dlls'])}  ·  {size}"
        self.what.setText(what)
        try:
            where = Path(p["dest"]).relative_to(self.profile.parent)
        except KeyError, ValueError:
            where = Path(p.get("dest") or "")
        self.where.setText(f"Goes into {where}")
        self.id_box.setVisible(package)
        if package:
            if p.get("id_taken"):
                self.id_note.setText(f"'{p['id']}' is already used by another package; me3 needs each id once.")
                tone_label(self.id_note, "error")
            else:
                self.id_note.setText("What other entries use to load before or after it.")
                tone_label(self.id_note, "muted")
        lines = []
        if p.get("in_place"):
            lines.append("The files are already there; only the profile changes.")
        elif p.get("exists"):
            lines.append(f"A folder named {Path(p['dest']).name} is already there and is replaced.")
        if p.get("already_listed"):
            lines.append("It is already in the profile, so no new entry is added.")
        else:
            lines.append("Options changes its load order, and anything else, once it is in.")
        self.note.setText(" ".join(lines))
        tone_label(self.note, "error" if p.get("exists") and not p.get("in_place") else "muted")
        if self.reg_place.count() == 0 or self.reg_place.itemData(0) != (
            p.get("merge_target") or (p.get("regulation_packages") or [{}])[-1].get("name")
        ):
            self._fill_reg_places()
            if self.after_last.isChecked() and self.reg_place.count() > 1:
                self.reg_place.setCurrentIndex(1)
        self._show_last()
        self._refresh_reg()
        self.yesButton.setEnabled(self.validate(quiet=True))

    def validate(self, quiet: bool = False) -> bool:
        if self._timer.isActive() and not quiet:  # Install pressed right after typing: use what was typed
            self._timer.stop()
            self._apply()
        ok = bool(self.name.text().strip()) and not self.plan.get("error")
        if self.plan["kind"] == "package":
            ok = ok and bool(self.id.text().strip()) and not self.plan.get("id_taken")
        if self.boxes:  # something the game loads must be ticked
            ok = ok and any(
                cb.isChecked()
                for name, cb in self.boxes.items()
                if next((i["group"] for i in self.plan.get("contents") or [] if i["name"] == name), "")
                in ("game", "regulation", "dll", "files")
            )
        if ok and not quiet:
            self.plan["exclude"] = self.left_out()
            self.plan["merge"] = self._rebuild_shown() and self.rebuild.isChecked()
            placed = self._regulation_on() and not self.plan.get("already_listed")
            self.plan["insert_before"] = self.reg_place.currentData() if placed else None  # a package name
            self.plan["after_overlay"] = bool(self.plan.get("stay_last")) and self.after_last.isChecked()
        return ok
