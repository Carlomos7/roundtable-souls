"""Confirm, choice, mod-options and text dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    ComboBox,
    LineEdit,
    MessageBoxBase,
    ScrollArea,
    SubtitleLabel,
    SwitchButton,
)
from qfluentwidgets import FluentIcon as FI

from roundtable_souls.ui.theme import BTN_H, ghost_btn, hint, style_dialog, style_ghost, style_primary, tone_label


class Dialog(MessageBoxBase):
    """Every dialog's buttons in the launcher's own styles and height: the commit action primary, the rest ghost."""

    def __init__(self, parent=None):
        super().__init__(parent)
        style_primary(self.yesButton)
        style_ghost(self.cancelButton)
        style_dialog(self)
        self.buttonGroup.setFixedHeight(BTN_H + 48)  # the base strip is sized for the library's shorter buttons


class InfoDialog(Dialog):
    """A title and some text to read, closed with one button."""

    def __init__(self, title, text, parent):
        super().__init__(parent)
        self.widget.setMinimumWidth(min(560, max(400, (parent.width() - 200) if parent else 480)))
        self.viewLayout.addWidget(SubtitleLabel(title))
        body = BodyLabel(text)
        body.setWordWrap(True)
        self.viewLayout.addWidget(body)
        self.yesButton.setText("Close")
        self.hideCancelButton()


class UnsavedDialog(Dialog):
    """Unsaved changes stand in the way of something (closing, switching games): Save first, Discard them, or Cancel.
    After exec(), `choice` is "save", "discard" or None."""

    def __init__(self, parent, what, action="closing"):
        super().__init__(parent)
        self.choice = None
        self.widget.setMinimumWidth(min(560, max(420, (parent.width() - 200) if parent else 480)))
        self.viewLayout.setSpacing(8)
        self.viewLayout.addWidget(SubtitleLabel(f"Save changes before {action}?"))
        self.viewLayout.addWidget(hint("Not saved yet"))
        for w in what:
            lab = BodyLabel("•  " + w)
            lab.setWordWrap(True)
            self.viewLayout.addWidget(lab)
        self.yesButton.setText("Save")
        self.discardButton = ghost_btn("Discard")
        self.discardButton.setToolTip("Drop the changes and carry on.")
        self.discardButton.clicked.connect(self._discard)
        self.buttonLayout.insertWidget(1, self.discardButton, 1, Qt.AlignVCenter)
        self.cancelButton.setText("Cancel")

    def validate(self):
        self.choice = self.choice or "save"
        return True

    def _discard(self):
        self.choice = "discard"
        self.accept()


def ask_unsaved(parent, what, action="closing"):
    """Save / Discard / Cancel for unsaved changes. Returns "save", "discard", or None when cancelled."""
    dlg = UnsavedDialog(parent, what, action)
    return dlg.choice if dlg.exec() else None


class ConfirmDialog(Dialog):
    """A confirm that reads top to bottom: what it is, what will happen (bullets), what keeps you safe, then the buttons.

    changes: bullet lines. safety: one line about the backup / undo. warning: the red strip for writes.
    danger=True styles the primary button as a removal (the text says what is removed)."""

    def __init__(
        self,
        title,
        parent,
        changes=(),
        safety="",
        warning="",
        detail="",
        apply_text="Continue",
        cancel_text="Cancel",
        option=None,
        option_checked=True,
        second_text=None,
    ):
        super().__init__(parent)
        self.option = None
        self.choice = None  # "apply" or "second" once accepted
        self.widget.setMinimumWidth(min(680, max(460, (parent.width() - 200) if parent else 560)))
        self.viewLayout.setSpacing(8)
        self.viewLayout.addWidget(SubtitleLabel(title))
        if warning:
            w = hint(warning)
            tone_label(w, "error")
            self.viewLayout.addWidget(w)
        changes = [c for c in changes if c]
        if changes:
            self.viewLayout.addWidget(hint("What will happen"))
            body = QWidget()
            bl = QVBoxLayout(body)
            bl.setContentsMargins(8, 0, 0, 0)
            bl.setSpacing(3)
            shown = changes[:14]
            for c in shown:
                lab = BodyLabel("\u2022  " + c)
                lab.setWordWrap(True)
                bl.addWidget(lab)
            if len(changes) > len(shown):
                bl.addWidget(hint(f"and {len(changes) - len(shown)} more"))
            self.viewLayout.addWidget(body)
        if detail:
            d = hint(detail)
            self.viewLayout.addWidget(d)
        if safety:
            self.viewLayout.addWidget(hint("Safety"))
            sl = BodyLabel(safety)
            sl.setWordWrap(True)
            self.viewLayout.addWidget(sl)
        if option:
            self.option = CheckBox(option)
            self.option.setChecked(bool(option_checked))
            self.viewLayout.addWidget(self.option)
        self.yesButton.setText(apply_text)
        self.cancelButton.setText(cancel_text)
        self.secondButton = None
        if second_text:  # a second way to go ahead, between the main one and Cancel
            self.secondButton = ghost_btn(second_text)
            self.secondButton.clicked.connect(self._second)
            self.buttonLayout.insertWidget(1, self.secondButton, 1, Qt.AlignVCenter)

    def validate(self):
        self.choice = self.choice or "apply"
        return True

    def _second(self):
        self.choice = "second"
        self.accept()

    def option_on(self) -> bool:
        return bool(self.option is not None and self.option.isChecked())


def confirm(parent, title, changes=(), safety="", warning="", detail="", apply_text="Continue") -> bool:
    return bool(
        ConfirmDialog(
            title, parent, changes=changes, safety=safety, warning=warning, detail=detail, apply_text=apply_text
        ).exec()
    )


class ModOptionsDialog(Dialog):
    """Per-mod options me3 v1 knows: enabled, and for natives optional / load_early / initializer / finalizer,
    plus load order (load_after, load_before) against the other entries of the profile."""

    def __init__(self, entry: dict, others: list, parent, overlay: bool | None = None, rebuild_file: str = ""):
        super().__init__(parent)
        self.entry = entry
        self.overlay = None
        self.rebuild_file = None
        self.widget.setMinimumWidth(min(720, max(520, parent.width() - 200)))
        self.viewLayout.setSpacing(8)
        self.viewLayout.addWidget(SubtitleLabel(entry["name"]))
        self.viewLayout.addWidget(
            hint(
                ("Package  \u00b7  " if entry["kind"] == "package" else "Native  \u00b7  ") + (entry.get("path") or "")
            )
        )
        form = QGridLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(8)
        r = 0

        def row(label, control, blurb=""):
            nonlocal r
            lab = BodyLabel(label)
            form.addWidget(lab, r, 0, Qt.AlignTop)
            form.addWidget(control, r, 1)
            r += 1
            if blurb:
                form.addWidget(hint(blurb), r, 1)
                r += 1

        self.enabled = SwitchButton()
        self.enabled.setOnText("On")
        self.enabled.setOffText("Off")
        self.enabled.setChecked(bool(entry.get("enabled", True)))
        row("Loaded", self.enabled, "Off keeps the entry in the profile but me3 skips it.")
        if entry["kind"] == "package":
            self.pkg_id = LineEdit()
            self.pkg_id.setText(entry.get("id") or "")
            self.pkg_id.setPlaceholderText("id other entries can refer to")
            row("Id", self.pkg_id, "Used by load order below. Leave as is unless another mod names it.")
            if overlay is not None:
                self.overlay = SwitchButton()
                self.overlay.setOnText("On")
                self.overlay.setOffText("Found by the launcher")
                self.overlay.setChecked(overlay)
                row(
                    "Parameter overlay",
                    self.overlay,
                    "The package that must stay last and rebuilds combined parameters with its own tool. Normally "
                    "found from its files; turn on only when it is not.",
                )
                pick = QWidget()
                pl = QHBoxLayout(pick)
                pl.setContentsMargins(0, 0, 0, 0)
                pl.setSpacing(8)
                self.rebuild_file = LineEdit()
                self.rebuild_file.setText(rebuild_file)
                self.rebuild_file.setPlaceholderText("rebuild.json (optional)")
                self.rebuild_file.setClearButtonEnabled(True)
                browse = ghost_btn("Choose...", FI.FOLDER)
                browse.clicked.connect(self._choose_rebuild_file)
                pl.addWidget(self.rebuild_file, 1)
                pl.addWidget(browse)
                row(
                    "Rebuild file",
                    pick,
                    "Only for a tool that ships no rebuild.json of its own: a rebuild.json saying how to run it "
                    "(docs/Rebuild tools.md in the project explains the format).",
                )
                self._pick_row = pick
                self.overlay.checkedChanged.connect(lambda on: pick.setEnabled(on))
                pick.setEnabled(overlay)
        else:
            self.optional = CheckBox("Optional: a load failure is not fatal")
            self.optional.setChecked(bool(entry.get("optional")))
            row("", self.optional)
            self.early = CheckBox(
                "Load early, before the game initialises (some DLLs need this, Seamless Co-op for one)"
            )
            self.early.setChecked(bool(entry.get("load_early")))
            row("", self.early)
            self.init_kind = ComboBox()
            self.init_kind.addItems(["No initializer", "Call a function", "Wait a delay (ms)"])
            self.init_kind.setMinimumWidth(180)
            self.init_value = LineEdit()
            self.init_value.setPlaceholderText("function name, or milliseconds")
            init = entry.get("initializer") or {}
            if init.get("function"):
                self.init_kind.setCurrentIndex(1)
                self.init_value.setText(str(init["function"]))
            elif isinstance(init.get("delay"), dict):
                self.init_kind.setCurrentIndex(2)
                self.init_value.setText(str(init["delay"].get("ms", 0)))
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(8)
            bl.addWidget(self.init_kind)
            bl.addWidget(self.init_value, 1)
            row(
                "Initializer",
                box,
                "Symbol me3 calls after the DLL loads, or a delay before it counts as loaded. Some mods document one, for example NrrInitialize for Nightreign Revive.",
            )
            self.fini = LineEdit()
            self.fini.setText(entry.get("finalizer") or "")
            self.fini.setPlaceholderText("symbol called on unload (rare)")
            row("Finalizer", self.fini)
        self.after = {}
        self.before = {}
        for title, store, current in (
            ("Load after", self.after, entry.get("load_after") or []),
            ("Load before", self.before, entry.get("load_before") or []),
        ):
            cur = {d["id"]: d for d in current}
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(2)
            if not others:
                bl.addWidget(hint("No other entries in this profile."))
            for o in others:
                line = QWidget()
                ll = QHBoxLayout(line)
                ll.setContentsMargins(0, 0, 0, 0)
                ll.setSpacing(12)
                cb = CheckBox(o)
                cb.setChecked(o in cur)
                opt = CheckBox("optional")
                opt.setChecked(cur.get(o, {}).get("optional", True))
                opt.setEnabled(cb.isChecked())
                cb.stateChanged.connect(lambda st, w=opt: w.setEnabled(bool(st)))
                ll.addWidget(cb, 1)
                ll.addWidget(opt)
                bl.addWidget(line)
                store[o] = (cb, opt)
            row(
                title,
                box,
                "Later in the load order wins on shared files. 'optional' means me3 does not fail when that entry is missing.",
            )
        body = QWidget()
        body.setStyleSheet("background:transparent")
        body.setLayout(form)
        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none}")
        scroll.viewport().setStyleSheet("background:transparent")
        screen_h = parent.screen().availableGeometry().height() if parent and parent.screen() else 900
        scroll.setMaximumHeight(max(280, min(560, screen_h - 320)))
        scroll.setWidget(body)
        self.viewLayout.addWidget(scroll)
        self.yesButton.setText("Save options")
        self.cancelButton.setText("Cancel")

    def _choose_rebuild_file(self):
        from PySide6.QtWidgets import QFileDialog

        got, _ = QFileDialog.getOpenFileName(self, "Rebuild file", "", "Rebuild file (rebuild.json *.json)")
        if got and self.rebuild_file is not None:
            self.rebuild_file.setText(got)

    def options(self) -> dict:
        e = self.entry
        opts = {
            "enabled": self.enabled.isChecked(),
            "load_after": [
                {"id": i, "optional": opt.isChecked()} for i, (cb, opt) in self.after.items() if cb.isChecked()
            ],
            "load_before": [
                {"id": i, "optional": opt.isChecked()} for i, (cb, opt) in self.before.items() if cb.isChecked()
            ],
        }
        if e["kind"] == "package":
            opts["id"] = self.pkg_id.text().strip()
        else:
            opts["optional"] = self.optional.isChecked()
            opts["load_early"] = self.early.isChecked()
            opts["finalizer"] = self.fini.text().strip()
            k = self.init_kind.currentIndex()
            v = self.init_value.text().strip()
            opts["initializer"] = (
                {"function": v} if k == 1 and v else ({"delay": {"ms": int(v)}} if k == 2 and v.isdigit() else None)
            )
        return opts


class TextDialog(Dialog):
    """One line of text with a title, a blurb and an optional tick box."""

    def __init__(
        self, title, blurb, parent, placeholder="", text="", option=None, option_checked=False, apply_text="OK"
    ):
        super().__init__(parent)
        self.widget.setMinimumWidth(480)
        self.viewLayout.addWidget(SubtitleLabel(title))
        if blurb:
            self.viewLayout.addWidget(hint(blurb))
        self.edit = LineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setText(text)
        self.edit.setClearButtonEnabled(True)
        self.viewLayout.addWidget(self.edit)
        self.option = None
        if option:
            self.option = CheckBox(option)
            self.option.setChecked(option_checked)
            self.viewLayout.addWidget(self.option)
        self.yesButton.setText(apply_text)
        self.cancelButton.setText("Cancel")

    def validate(self):
        return bool(self.edit.text().strip())


WRITE_WARNING = "This writes to your save file. Elden Ring must stay closed until it finishes."
WRITE_SAFETY = "A backup of the file as it is now is taken first. Undo appears at the top of the window afterwards, and Backups on the Saves page can put any backup back."


class ChoiceListDialog(Dialog):
    """Pick any of a list, all unticked to start. selected() gives the ticked indexes."""

    def __init__(self, title, blurb, labels, parent, apply_text="Continue"):
        super().__init__(parent)
        self.widget.setMinimumWidth(min(640, max(460, (parent.width() - 200) if parent else 540)))
        self.viewLayout.setSpacing(8)
        self.viewLayout.addWidget(SubtitleLabel(title))
        if blurb:
            self.viewLayout.addWidget(hint(blurb))
        body = QWidget()
        body.setStyleSheet("background:transparent")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 4, 0, 4)
        bl.setSpacing(6)
        self.boxes = []
        for label in labels:
            cb = CheckBox(label)
            cb.stateChanged.connect(self._count)
            bl.addWidget(cb)
            self.boxes.append(cb)
        bl.addStretch(1)
        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none}")
        scroll.viewport().setStyleSheet("background:transparent")
        screen_h = parent.screen().availableGeometry().height() if parent and parent.screen() else 900
        scroll.setMaximumHeight(max(220, min(420, screen_h - 360)))
        scroll.setWidget(body)
        self.viewLayout.addWidget(scroll)
        row = QHBoxLayout()
        row.setSpacing(8)
        for text, state in (("Tick all", True), ("Clear", False)):
            b = ghost_btn(text)
            b.clicked.connect(lambda _=False, on=state: [cb.setChecked(on) for cb in self.boxes])
            row.addWidget(b)
        row.addStretch(1)
        self.viewLayout.addLayout(row)
        self._apply_text = apply_text
        self.cancelButton.setText("Cancel")
        self._count()

    def _count(self, *_):
        n = len(self.selected())
        self.yesButton.setText(f"{self._apply_text} {n}" if n else self._apply_text)
        self.yesButton.setEnabled(bool(n))

    def selected(self) -> list[int]:
        return [i for i, cb in enumerate(self.boxes) if cb.isChecked()]


class VersionsDialog(Dialog):
    """Earlier versions of a profile (its history), newest first, with how much each differs from the file now.
    After exec(), chosen() is the copy to restore, or None."""

    def __init__(self, profile, versions: list[dict], current_text: str, parent, now=None):
        import datetime
        import difflib

        from qfluentwidgets import ListWidget

        super().__init__(parent)
        self.widget.setMinimumWidth(min(680, max(460, (parent.width() - 200) if parent else 560)))
        self.viewLayout.setSpacing(8)
        self.viewLayout.addWidget(SubtitleLabel(f"Earlier versions of {profile.name}"))
        self.viewLayout.addWidget(
            hint(
                "A copy is kept before every change the launcher makes (the newest 30). Restoring one keeps the "
                "current file as a version too, so it can be undone."
            )
        )
        self.list = ListWidget()
        self.list.setMinimumHeight(220)
        self._paths = []
        today = (now or datetime.datetime.now()).date()
        now_lines = current_text.splitlines()
        for v in versions:
            try:
                old = v["path"].read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            changed = sum(1 for op in difflib.ndiff(old, now_lines) if op[:1] in "+-")
            when = v["when"]
            day = (
                "Today"
                if when.date() == today
                else "Yesterday"
                if when.date() == today - datetime.timedelta(days=1)
                else when.strftime("%d %b")
            )
            differs = (
                "same as now" if not changed else f"{changed} line{' differs' if changed == 1 else 's differ'} from now"
            )
            self.list.addItem(f"{day} {when:%H:%M}  ·  {v['why']}  ·  {differs}")
            self._paths.append(v["path"])
        if not self._paths:
            self.viewLayout.addWidget(hint("No earlier versions yet: they are kept from the next change on."))
        self.list.setVisible(bool(self._paths))
        self.viewLayout.addWidget(self.list)
        self.yesButton.setText("Restore")
        self.yesButton.setEnabled(False)
        self.list.currentRowChanged.connect(lambda row: self.yesButton.setEnabled(row >= 0))
        self.cancelButton.setText("Close")

    def chosen(self):
        row = self.list.currentRow()
        return self._paths[row] if 0 <= row < len(self._paths) else None
