"""Dialogs for moving saves around: swap a library copy in, copy a whole file, copy one character.

Each one shows what the target holds next to what it would get (CompareTable) before anything is written, and asks
for a name when the file being replaced goes into the library."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QTableWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, ComboBox, LineEdit, RadioButton, SubtitleLabel, TableWidget

from roundtable_souls.saves import library, transfer
from roundtable_souls.ui.dialogs import Dialog
from roundtable_souls.ui.theme import hint


def char_text(c) -> str:
    return f"{c['name']}  ·  lvl {c['level']}  ·  {transfer.hours(c['seconds'])}" if c else "empty"


class CompareTable(TableWidget):
    """Slot by slot: what the target holds now, what it would hold, and the difference in a word."""

    def __init__(self, now_title="Now", then_title="After"):
        super().__init__()
        self.setColumnCount(4)
        self.setHorizontalHeaderLabels(["Slot", now_title, then_title, ""])
        self.verticalHeader().hide()
        self.setEditTriggers(TableWidget.NoEditTriggers)
        self.setSelectionMode(TableWidget.NoSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

    def show_rows(self, rows):
        """rows: (slot, now, after) with characters as library.characters() gives them, or None."""
        self.setRowCount(len(rows))
        for r, (slot, now, then) in enumerate(rows):
            key = lambda c: (c["name"], c["level"], c["seconds"]) if c else None  # noqa: E731
            if key(now) == key(then):
                word = "same"
            elif not now:
                word = "added"
            elif not then:
                word = "removed"
            elif now["name"] != then["name"]:
                word = "replaced"
            else:
                word = "further" if (then["seconds"], then["level"]) > (now["seconds"], now["level"]) else "earlier"
            for col, val in enumerate((slot, char_text(now), char_text(then), word)):
                it = QTableWidgetItem(str(val))
                it.setToolTip(str(val))
                it.setTextAlignment(Qt.AlignCenter if col in (0, 3) else (Qt.AlignLeft | Qt.AlignVCenter))
                self.setItem(r, col, it)
        self.resizeColumnToContents(0)
        self.resizeColumnToContents(3)
        self.resizeRowsToContents()
        rows_h = sum(self.rowHeight(i) for i in range(self.rowCount())) or 36
        self.setFixedHeight(self.horizontalHeader().height() + rows_h + 2 * self.frameWidth() + 2)


def whole_file_rows(now_path: Path | None, then_path: Path | None, game) -> list:
    now = {c["slot"]: c for c in (library.characters(now_path, game) if now_path and Path(now_path).is_file() else [])}
    then = {c["slot"]: c for c in (library.characters(then_path, game) if then_path else [])}
    return [(s, now.get(s), then.get(s)) for s in sorted(set(now) | set(then))]


class SwapDialog(Dialog):
    """Put a library copy in place of a live save. The live one goes into the library first, under a name."""

    def __init__(self, parent, entry, entry_path, targets, game, active_name=None):
        super().__init__(parent)
        self.entry, self.entry_path, self.targets, self.game = entry, Path(entry_path), list(targets), game
        self.widget.setMinimumWidth(min(760, max(560, parent.width() - 160)))
        self.viewLayout.setSpacing(8)
        self.viewLayout.addWidget(SubtitleLabel(f"Swap in '{entry['name']}'"))
        self.viewLayout.addWidget(
            hint("The save it replaces goes into the library first, so you can swap it back any time.")
        )
        self.viewLayout.addWidget(BodyLabel("Replace"))
        self.target = ComboBox()
        for label, path in self.targets:
            self.target.addItem(label, userData=str(path))
        pick = next((i for i, (_l, p) in enumerate(self.targets) if Path(p).name == active_name), 0)
        self.target.setCurrentIndex(pick)
        self.target.currentIndexChanged.connect(self._refresh)
        self.viewLayout.addWidget(self.target)
        self.viewLayout.addWidget(BodyLabel("Keep the replaced save in the library as"))
        self.name = LineEdit()
        self.name.setClearButtonEnabled(True)
        self.name.textChanged.connect(self._valid)
        self.viewLayout.addWidget(self.name)
        self.table = CompareTable("Now", "After the swap")
        self.viewLayout.addWidget(self.table)
        self.note = hint("")
        self.viewLayout.addWidget(self.note)
        self.yesButton.setText("Swap in")
        self.cancelButton.setText("Cancel")
        self._refresh()

    def target_path(self) -> Path:
        return Path(self.targets[self.target.currentIndex()][1])

    def outgoing_name(self) -> str:
        return self.name.text().strip()

    def _refresh(self, *_):
        t = self.target_path()
        self.name.setText(library.default_name(t, self.game) if t.is_file() else "")
        self.name.setEnabled(t.is_file())
        self.table.show_rows(whole_file_rows(t, self.entry_path, self.game))
        self.note.setText(
            f"{t.name} is written with the copy's bytes. A backup is kept for Undo."
            if t.is_file()
            else f"{t.name} does not exist yet; it is created."
        )
        self._valid()

    def _valid(self, *_):
        self.yesButton.setEnabled(bool(self.outgoing_name()) or not self.target_path().is_file())


class CopyFileDialog(Dialog):
    """Copy a whole save file to another: replace the target (its current contents go into the library under a
    name), or only add a named library copy and leave every live file alone."""

    def __init__(self, parent, source: Path, targets, game, default_target=None):
        super().__init__(parent)
        self.source, self.targets, self.game = Path(source), list(targets), game
        self.widget.setMinimumWidth(min(760, max(560, parent.width() - 160)))
        self.viewLayout.setSpacing(8)
        self.viewLayout.addWidget(SubtitleLabel(f"Copy {self.source.name}"))
        self.replace = RadioButton("Replace another save with it")
        self.keep = RadioButton("Only add it to the library (no live save changes)")
        self.replace.setChecked(True)
        self.replace.toggled.connect(self._refresh)
        self.viewLayout.addWidget(self.replace)
        self.target = ComboBox()
        for label, path in self.targets:
            self.target.addItem(label, userData=str(path))
        pick = next((i for i, (_l, p) in enumerate(self.targets) if Path(p).name == default_target), 0)
        self.target.setCurrentIndex(pick)
        self.target.currentIndexChanged.connect(self._refresh)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(28, 0, 0, 0)
        bl.setSpacing(6)
        bl.addWidget(self.target)
        self.name_label = BodyLabel("Keep the replaced save in the library as")
        bl.addWidget(self.name_label)
        self.name = LineEdit()
        self.name.setClearButtonEnabled(True)
        self.name.textChanged.connect(self._valid)
        bl.addWidget(self.name)
        self.viewLayout.addWidget(box)
        self.viewLayout.addWidget(self.keep)
        self.lib_box = QWidget()
        ll = QVBoxLayout(self.lib_box)
        ll.setContentsMargins(28, 0, 0, 0)
        ll.addWidget(BodyLabel("Name the library copy"))
        self.lib_name = LineEdit()
        self.lib_name.setText(library.default_name(self.source, game))
        self.lib_name.setClearButtonEnabled(True)
        self.lib_name.textChanged.connect(self._valid)
        ll.addWidget(self.lib_name)
        self.viewLayout.addWidget(self.lib_box)
        self.table = CompareTable("Now", "After the copy")
        self.viewLayout.addWidget(self.table)
        self.note = hint("")
        self.note.setWordWrap(True)
        self.viewLayout.addWidget(self.note)
        self.cancelButton.setText("Cancel")
        self._refresh()

    def mode(self) -> str:
        return "replace" if self.replace.isChecked() else "library"

    def target_path(self) -> Path:
        return Path(self.targets[self.target.currentIndex()][1]) if self.targets else self.source

    def kept_name(self) -> str:
        return (self.name if self.mode() == "replace" else self.lib_name).text().strip()

    def _refresh(self, *_):
        replacing = self.mode() == "replace" and bool(self.targets)
        self.replace.setEnabled(bool(self.targets))
        for w in (self.target, self.name_label, self.name):
            w.setEnabled(replacing)
        self.lib_box.setEnabled(not replacing)
        t = self.target_path()
        if replacing:
            self.name.setText(library.default_name(t, self.game) if t.is_file() else "")
            self.table.setVisible(True)
            self.table.show_rows(whole_file_rows(t, self.source, self.game))
            self.note.setText(
                f"{t.name} gets every character in {self.source.name}. Its current contents go into the library "
                "under the name above, and a backup is kept for Undo."
            )
            self.yesButton.setText(f"Replace {t.name}")
        else:
            self.table.setVisible(False)
            self.note.setText("The copy is stored in the library; swap it in whenever you want to play it.")
            self.yesButton.setText("Add to library")
        self._valid()

    def _valid(self, *_):
        t = self.target_path()
        need = self.mode() == "library" or t.is_file()
        self.yesButton.setEnabled(bool(self.kept_name()) or not need)


class CopyCharacterDialog(Dialog):
    """Copy one character into a slot of the same or another save."""

    def __init__(self, parent, source: Path, source_info: dict, targets, game):
        super().__init__(parent)
        self.source, self.info, self.targets, self.game = Path(source), source_info, list(targets), game
        self.chars = library.characters(self.source, game)
        self.widget.setMinimumWidth(min(720, max(540, parent.width() - 180)))
        self.viewLayout.setSpacing(8)
        self.viewLayout.addWidget(SubtitleLabel(f"Copy a character from {self.source.name}"))
        self.viewLayout.addWidget(BodyLabel("Character"))
        self.who = ComboBox()
        for c in self.chars:
            self.who.addItem(f"Slot {c['slot']}: {char_text(c)}")
        self.who.currentIndexChanged.connect(self._refresh)
        self.viewLayout.addWidget(self.who)
        self.viewLayout.addWidget(BodyLabel("Into"))
        self.target = ComboBox()
        for label, path in self.targets:
            self.target.addItem(label, userData=str(path))
        self.target.currentIndexChanged.connect(self._fill_slots)
        self.viewLayout.addWidget(self.target)
        self.viewLayout.addWidget(BodyLabel("Slot"))
        self.slot = ComboBox()
        self.slot.currentIndexChanged.connect(self._refresh)
        self.viewLayout.addWidget(self.slot)
        self.table = CompareTable("Now", "After the copy")
        self.viewLayout.addWidget(self.table)
        self.note = hint("")
        self.note.setWordWrap(True)
        self.viewLayout.addWidget(self.note)
        self.yesButton.setText("Copy character")
        self.cancelButton.setText("Cancel")
        self._fill_slots()

    def source_slot(self) -> int:
        return self.chars[self.who.currentIndex()]["slot"] if self.chars else 0

    def target_path(self) -> Path:
        return Path(self.targets[self.target.currentIndex()][1])

    def target_slot(self) -> int:
        return self.slot.currentIndex() + 1

    def _fill_slots(self, *_):
        held = {c["slot"]: c for c in library.characters(self.target_path(), self.game)}
        self.slot.blockSignals(True)
        self.slot.clear()
        for s in range(1, 11):
            c = held.get(s)
            self.slot.addItem(f"Slot {s}: " + (f"replace {char_text(c)}" if c else "empty"))
        free = next((s for s in range(1, 11) if s not in held), 1)
        self.slot.setCurrentIndex(free - 1)
        self.slot.blockSignals(False)
        self._refresh()

    def _refresh(self, *_):
        if not self.chars:
            self.note.setText("This save has no characters to copy.")
            self.yesButton.setEnabled(False)
            return
        t, ts = self.target_path(), self.target_slot()
        try:
            plan = transfer.plan_character_copy(self.source, self.source_slot(), t, ts)
        except transfer.TransferError as e:
            self.table.setVisible(False)
            self.note.setText(str(e))
            self.yesButton.setEnabled(False)
            return
        self.table.setVisible(True)
        self.table.show_rows([(ts, plan["replaces"], plan["character"])])
        bits = []
        if plan["replaces"]:
            bits.append(f"{plan['replaces']['name']} in slot {ts} is overwritten.")
        mods = sum(
            len(p.get("strip") or []) + len(p.get("blocked") or [])
            for p in self.info.get("vanilla_plan") or []
            if p.get("slot") == self.source_slot() - 1
        )
        if mods:
            bits.append(
                f"This character holds {mods} item{'s' if mods != 1 else ''} the game does not define (Seamless Co-op's, "
                "for one). In a save played without that mod, Remove mod items on the Saves page takes them off."
            )
        if plan["steam_id_changes"]:
            bits.append("The two saves belong to different Steam accounts; the copy is moved to the target's account.")
        bits.append(f"{t.name} is backed up first, so Undo can put it back.")
        self.note.setText(" ".join(bits))
        self.yesButton.setEnabled(True)
