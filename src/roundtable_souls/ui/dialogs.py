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
    StrongBodyLabel,
    SubtitleLabel,
    SwitchButton,
    TransparentPushButton,
)

from roundtable_souls.ui.theme import hint


class ChoiceDialog(MessageBoxBase):
    """Pick what a write action changes before it runs.

    groups: [{"title": "Tarnished", "subtitle": "...", "items": [
        {"key": any, "label": "Tiny Great Pot", "section": "Seamless Co-op", "sub": "in the pouch",
         "checked": True, "enabled": True, "note": "worn: take it off in-game first"}]}]
    Every group has All / None. Disabled items stay visible so nothing is hidden. Apply is off until
    at least one item is ticked, and the summary line says exactly how many of what will change.
    """

    def __init__(self, title, warning, groups, parent, apply_text="Apply", summarize=None):
        super().__init__(parent)
        self._summarize = summarize
        self.boxes = []  # (key, CheckBox)
        self.widget.setMinimumWidth(min(820, max(560, parent.width() - 120)) if parent else 720)
        self.viewLayout.setSpacing(10)
        self.viewLayout.addWidget(SubtitleLabel(title))
        warn = hint(warning)
        warn.setTextColor("#963C48", "#E08A7A")
        self.viewLayout.addWidget(warn)
        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none}")
        scroll.viewport().setStyleSheet("background:transparent")
        screen_h = parent.screen().availableGeometry().height() if parent and parent.screen() else 900
        scroll.setMaximumHeight(max(260, min(520, screen_h - 360)))
        body = QWidget()
        body.setStyleSheet("background:transparent")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 12, 0)
        bl.setSpacing(14)
        for g in groups:
            box_list = []
            head = QHBoxLayout()
            head.setSpacing(8)
            head.addWidget(StrongBodyLabel(g["title"]))
            if g.get("subtitle"):
                head.addWidget(hint(g["subtitle"]))
            head.addStretch()
            b_all = TransparentPushButton("All")
            b_none = TransparentPushButton("None")
            b_all.clicked.connect(lambda _=False, bs=box_list: [b.setChecked(True) for b in bs if b.isEnabled()])
            b_none.clicked.connect(lambda _=False, bs=box_list: [b.setChecked(False) for b in bs if b.isEnabled()])
            head.addWidget(b_all)
            head.addWidget(b_none)
            bl.addLayout(head)
            section = None
            grid = QGridLayout()
            grid.setContentsMargins(12, 0, 0, 0)
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(4)
            r = 0
            for it in g["items"]:
                if it.get("section") and it["section"] != section:
                    section = it["section"]
                    grid.addWidget(hint(section), r, 0, 1, 2)
                    r += 1
                cb = CheckBox(it["label"])
                cb.setChecked(bool(it.get("checked", True)))
                cb.setEnabled(bool(it.get("enabled", True)))
                if it.get("tip"):
                    cb.setToolTip(it["tip"])
                cb.stateChanged.connect(self._recount)
                grid.addWidget(cb, r, 0)
                side = it.get("note") or it.get("sub") or ""
                if side:
                    sl = hint(side)
                    if it.get("note"):
                        sl.setTextColor("#963C48", "#E08A7A")
                    grid.addWidget(sl, r, 1)
                r += 1
                self.boxes.append((it["key"], cb))
                box_list.append(cb)
            grid.setColumnStretch(1, 1)
            bl.addLayout(grid)
        bl.addStretch()
        scroll.setWidget(body)
        self.viewLayout.addWidget(scroll)
        self.summary = BodyLabel("")
        self.summary.setWordWrap(True)
        self.viewLayout.addWidget(self.summary)
        self.yesButton.setText(apply_text)
        self.cancelButton.setText("Cancel")
        self._recount()

    def selected(self):
        return [key for key, cb in self.boxes if cb.isEnabled() and cb.isChecked()]

    def _recount(self, *_):
        keys = self.selected()
        self.yesButton.setEnabled(bool(keys))
        text = (
            self._summarize(keys) if self._summarize else f"{len(keys)} change{'s' if len(keys) != 1 else ''} selected"
        )
        self.summary.setText(text if keys else "Nothing selected. Tick what to change, or Cancel.")


class ConfirmDialog(MessageBoxBase):
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


class ModOptionsDialog(MessageBoxBase):
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


class TextDialog(MessageBoxBase):
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
WRITE_SAFETY = "A copy of the file as it is now goes into save-fix-backups first. Undo appears at the top of the window afterwards, and the Backups list can put any copy back."
