"""The action bar (a status note with commit and undo) and the text editor panel tied to a baseline."""

from __future__ import annotations

from PySide6.QtCore import (
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QBoxLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    IconWidget,
)
from qfluentwidgets import FluentIcon as FI

from roundtable_souls.ui.dialogs.editor import code_edit
from roundtable_souls.ui.theme import (
    RADIUS,
    ghost_btn,
    hint,
    primary_btn,
    style_editor,
    tokens,
    tone_label,
)
from roundtable_souls.ui.widgets.layout import action_row


class ActionBar(QWidget):
    """A status note and the actions that commit or undo it: one secondary button and one primary. Used under the
    Co-op form, under both text editors and under Review & fix, so every save row looks and sizes the same.

    framed: painted as a card that turns gold while something is pending (a page's save row); unframed rows sit
    inside a card (an editor's footer). Below STACK_BELOW px wide the note goes above the buttons."""

    STACK_BELOW = 560

    def __init__(self, primary_text, on_primary=None, secondary=None, framed=True, note=""):
        super().__init__()
        self.framed = framed
        self.pending = False
        self.box = QBoxLayout(QBoxLayout.LeftToRight, self)
        self.box.setContentsMargins(*((20, 12, 16, 12) if framed else (0, 4, 0, 0)))
        self.box.setSpacing(12)
        noted = QWidget()
        nl = QHBoxLayout(noted)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(8)
        self.note_icon = IconWidget(FI.EDIT)
        self.note_icon.setFixedSize(16, 16)
        self.note_icon.setToolTip("Unsaved changes")
        self.note_icon.hide()
        nl.addWidget(self.note_icon, 0, Qt.AlignVCenter)
        self.note = BodyLabel(note)
        self.note.setWordWrap(True)
        nl.addWidget(self.note, 1)
        self.box.addWidget(noted, 1)
        self.acts = QWidget()
        al = QHBoxLayout(self.acts)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        al.addStretch(1)
        self.secondary = None
        if secondary is not None:
            text, icon, fn, tip = (*secondary, "")[:4]
            self.secondary = ghost_btn(text, icon)
            self.secondary.setToolTip(tip)
            if fn is not None:
                self.secondary.clicked.connect(fn)
            al.addWidget(self.secondary)
        self.primary = primary_btn(primary_text)
        if on_primary is not None:
            self.primary.clicked.connect(on_primary)
        al.addWidget(self.primary)
        self.box.addWidget(self.acts)
        self._stacked = None
        self._restack()

    def set_state(self, pending: bool, note: str) -> None:
        """Pending: the actions are live, the note is in the accent and an edit mark says it is unsaved; otherwise both
        buttons rest."""
        self.pending = pending
        self.primary.setEnabled(pending)
        if self.secondary is not None:
            self.secondary.setEnabled(pending)
        self.note_icon.setVisible(pending)
        self.note.setText(note)
        tone_label(self.note, "accent" if pending else "muted")
        self.restyle()

    def restyle(self):
        """After a theme switch: the edit mark is in the accent, like the note beside it."""
        self.note_icon.setIcon(FI.EDIT.icon(color=QColor(tokens()["accent"])))
        self.update()

    def _restack(self):
        stacked = 0 < self.width() < self.STACK_BELOW
        if stacked == self._stacked:
            return
        self._stacked = stacked
        self.box.setDirection(QBoxLayout.TopToBottom if stacked else QBoxLayout.LeftToRight)
        self.box.setSpacing(8 if stacked else 12)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._restack()

    def paintEvent(self, e):
        if not self.framed:
            return
        t = tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.setBrush(t["pending"] if self.pending else t["surf"])
        p.setPen(QPen(t["pending_border"] if self.pending else t["border"], 1.4 if self.pending else 1))
        p.drawRoundedRect(r, RADIUS, RADIUS)


class EditorPanel(QWidget):
    """A text editor tied to one baseline: a file, or the current settings. The same layout wherever text is edited:
    a caption naming the baseline with the panel's tools beside it, the editor, then an ActionBar whose note says
    whether the text still matches, with Discard (back to the baseline) and the panel's commit action.

    tools: (text, icon, fn, tip) ghost buttons for moving text in and out (copy, paste, load, save as).
    on_discard: what Discard does; by default it puts the baseline text back."""

    dirty_changed = Signal(bool)

    def __init__(
        self,
        placeholder,
        primary_text,
        on_primary,
        tools=(),
        on_discard=None,
        lang="toml",
        wrap=False,
        min_height=240,
        clean_note="Matches the file.",
        dirty_note="Edited. Not saved yet.",
        primary_tip="",
    ):
        super().__init__()
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._baseline = ""
        self._dirty = False
        self.clean_note, self.dirty_note = clean_note, dirty_note
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(12)
        self.caption = hint("")
        self.caption.setWordWrap(False)
        hl.addWidget(self.caption, 1)
        self.tools = []
        if tools:
            row, flow = action_row()
            for text, icon, fn, tip in tools:
                b = ghost_btn(text, icon)
                b.setToolTip(tip)
                b.clicked.connect(fn)
                flow.addWidget(b)
                self.tools.append(b)
            lay.addWidget(head)
            lay.addWidget(row)
        else:
            lay.addWidget(head)
        self.edit = code_edit(placeholder, wrap=wrap, lang=lang)
        self.edit.setMinimumHeight(min_height)
        self.edit.textChanged.connect(self._on_text)
        lay.addWidget(self.edit, 1)
        self.bar = ActionBar(
            primary_text,
            on_primary,
            ("Discard", FI.CANCEL, on_discard or self.discard, "Put the text back the way it was."),
            framed=False,
        )
        if primary_tip:
            self.bar.primary.setToolTip(primary_tip)
        lay.addWidget(self.bar)
        self._refresh()

    @property
    def dirty(self) -> bool:
        return self._dirty

    def text(self) -> str:
        return self.edit.toPlainText()

    def baseline(self) -> str:
        """The clean text the edits are measured against (the file as loaded, or the current settings)."""
        return self._baseline

    def set_baseline(self, text: str, caption: str = "", tip: str = "") -> None:
        """Show this text as the clean state; edits are measured against it."""
        self._baseline = text
        self.edit.blockSignals(True)
        self.edit.setPlainText(text)
        self.edit.blockSignals(False)
        self.caption.setText(caption)
        self.caption.setToolTip(tip)
        self._refresh()

    def mark_clean(self) -> None:
        """The current text is now the baseline (it was just saved)."""
        self._baseline = self.edit.toPlainText()
        self._refresh()

    def set_text(self, text: str) -> None:
        """Replace the text as an edit (a paste or a loaded file), leaving the baseline alone."""
        self.edit.setPlainText(text)

    def discard(self) -> None:
        self.edit.setPlainText(self._baseline)

    def _on_text(self):
        self._refresh()

    def _refresh(self):
        dirty = self.edit.toPlainText() != self._baseline
        self.bar.set_state(dirty, self.dirty_note if dirty else self.clean_note)
        if dirty != self._dirty:
            self._dirty = dirty
            self.dirty_changed.emit(dirty)

    def restyle(self) -> None:
        style_editor(self.edit)
        self.bar.update()
