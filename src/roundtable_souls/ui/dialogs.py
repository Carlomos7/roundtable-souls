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

from roundtable_souls.ui.theme import BTN_H, ghost_btn, hint, style_ghost, style_primary


class Dialog(MessageBoxBase):
    """Every dialog's buttons in the launcher's own styles and height: the commit action primary, the rest ghost."""

    def __init__(self, parent=None):
        super().__init__(parent)
        style_primary(self.yesButton)
        style_ghost(self.cancelButton)
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
    ):
        super().__init__(parent)
        self.option = None
        self.widget.setMinimumWidth(min(680, max(460, (parent.width() - 200) if parent else 560)))
        self.viewLayout.setSpacing(8)
        self.viewLayout.addWidget(SubtitleLabel(title))
        if warning:
            w = hint(warning)
            w.setTextColor("#963C48", "#E08A7A")
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

    def __init__(self, entry: dict, others: list, parent):
        super().__init__(parent)
        self.entry = entry
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
