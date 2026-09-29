"""The TOML / JSON editor: highlighting, Ctrl+/ comments, Tab indent, Ctrl+D duplicate, and a find / replace bar."""

from __future__ import annotations

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon,
    LineEdit,
    PlainTextEdit,
    PushButton,
    TransparentToggleToolButton,
    TransparentToolButton,
    isDarkTheme,
)

from roundtable_souls import find
from roundtable_souls.core import COMMENT_PREFIX, indent_lines, toggle_comment
from roundtable_souls.ui.theme import RADIUS, style_editor, tokens


class CodeHighlighter(QSyntaxHighlighter):
    """TOML for the me3 profile, JSON for share-with-a-friend, INI and plain text for mods' own settings files.
    Colours follow the theme."""

    def __init__(self, document, kind="toml"):
        super().__init__(document)
        self.kind = kind
        self._rules = []
        self.restyle()

    def restyle(self):
        if isDarkTheme():
            colors = {
                "comment": "#8A6E4A",
                "key": "#E8D2A0",
                "string": "#F9C043",
                "number": "#E08A7A",
                "keyword": "#BD6707",
                "header": "#F9C043",
            }
        else:
            colors = {
                "comment": "#385D70",
                "key": "#142F40",
                "string": "#075C8B",
                "number": "#963C48",
                "keyword": "#397E9F",
                "header": "#075C8B",
            }

        def fmt(name, bold=False):
            f = QTextCharFormat()
            f.setForeground(QColor(colors[name]))
            if bold:
                f.setFontWeight(QFont.DemiBold)
            return f

        if self.kind == "json":
            specs = (
                (r'"([^"\\]|\\.)*"\s*(?=:)', "key"),
                (r'"([^"\\]|\\.)*"', "string"),
                (r"\b-?\d+(\.\d+)?\b", "number"),
                (r"\b(true|false|null)\b", "keyword"),
                (r"^\s*//.*$", "comment"),
            )
        elif self.kind == "text":
            specs = ((r"^\s*[#;].*$", "comment"),)  # a mod's own list format: only comment lines stand out
        elif self.kind == "ini":
            specs = (
                (r"^\s*\[[^\]]+\]", "header"),
                (r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_. -]*(?=\s*=)", "key"),
                (r"\b(true|false|on|off|yes|no)\b", "keyword"),
                (r"\b-?\d+(\.\d+)?\b", "number"),
                (r"^\s*[;#].*$", "comment"),
            )
        else:
            specs = (
                (r'"[^"\\]*(\\.[^"\\]*)*"', "string"),
                (r"'[^']*'", "string"),
                (r"^\s*\[+[^\]]+\]+", "header"),
                (r"\b(true|false)\b", "keyword"),
                (r"\b-?\d+(\.\d+)?\b", "number"),
                (r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_-]*(?=\s*=)", "key"),
                (r"#.*$", "comment"),
            )
        self._rules = [(QRegularExpression(pat), fmt(name, bold=name == "header")) for pat, name in specs]
        self.rehighlight()

    def highlightBlock(self, text):
        for rx, fmt in self._rules:
            it = rx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


class FindBar(QFrame):
    """Find / replace, floating in the editor's top-right corner. Ctrl+F opens it, Ctrl+H with the replace row,
    Enter / Shift+Enter step through matches, Esc closes. Aa toggles case, .* toggles regular expressions."""

    def __init__(self, editor: CodeEdit):
        super().__init__(editor)
        self.editor = editor
        self.matches: list[find.Span] = []
        self.search = LineEdit()
        self.search.setPlaceholderText("Find")
        self.search.setClearButtonEnabled(True)
        self.replace = LineEdit()
        self.replace.setPlaceholderText("Replace with")
        self.count = CaptionLabel("")
        self.count.setMinimumWidth(90)
        self.case_btn = TransparentToggleToolButton()
        self.case_btn.setText("Aa")
        self.case_btn.setToolTip("Match case")
        self.regex_btn = TransparentToggleToolButton()
        self.regex_btn.setText(".*")
        self.regex_btn.setToolTip("Regular expression (Python syntax; \\1 in Replace refers to a group)")
        prev_btn = TransparentToolButton(FluentIcon.UP)
        prev_btn.setToolTip("Previous match (Shift+Enter)")
        next_btn = TransparentToolButton(FluentIcon.DOWN)
        next_btn.setToolTip("Next match (Enter)")
        close_btn = TransparentToolButton(FluentIcon.CLOSE)
        close_btn.setToolTip("Close (Esc)")
        self.replace_btn = PushButton("Replace")
        self.replace_btn.setToolTip("Replace the selected match and move to the next")
        self.all_btn = PushButton("All")
        self.all_btn.setToolTip("Replace every match (one undo step)")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(4)
        for w in (self.search, self.count, self.case_btn, self.regex_btn, prev_btn, next_btn, close_btn):
            row.addWidget(w)
        row.setStretch(0, 1)
        lay.addLayout(row)
        self.replace_row = QHBoxLayout()
        self.replace_row.setSpacing(4)
        for w in (self.replace, self.replace_btn, self.all_btn):
            self.replace_row.addWidget(w)
        self.replace_row.setStretch(0, 1)
        lay.addLayout(self.replace_row)

        self.search.textChanged.connect(self.refresh)
        self.case_btn.toggled.connect(self.refresh)
        self.regex_btn.toggled.connect(self.refresh)
        prev_btn.clicked.connect(lambda: self.step(backward=True))
        next_btn.clicked.connect(lambda: self.step())
        close_btn.clicked.connect(self.close_bar)
        self.replace_btn.clicked.connect(self.replace_current)
        self.all_btn.clicked.connect(self.replace_all)
        self.restyle()
        self.hide()

    def keyPressEvent(self, e):
        """Keys the line edits leave alone (Enter, Esc, F3) arrive here by propagation. Handle them and stop
        every key at this level so nothing ever falls through to the document underneath."""
        key, shift = e.key(), bool(e.modifiers() & Qt.ShiftModifier)
        if key in (Qt.Key_Return, Qt.Key_Enter):
            if self.replace.isVisible() and self.replace.hasFocus() and not shift:
                self.replace_current()
            else:
                self.step(backward=shift)
        elif key == Qt.Key_Escape:
            self.close_bar()
        elif key == Qt.Key_F3:
            self.step(backward=shift)
        e.accept()

    # ---- state
    def restyle(self):
        t = tokens()
        surf = t["surf"].name() if isinstance(t["surf"], QColor) else t["surf"]
        self.setStyleSheet(
            f"FindBar{{background:{surf};border:1px solid {t['border'].name()};border-radius:{RADIUS}px;}}"
        )

    def open(self, replace: bool = False):
        sel = self.editor.textCursor().selectedText()
        if sel and " " not in sel:  # a single-line selection seeds the query
            self.search.setText(sel)
        self.replace.setVisible(replace)
        self.replace_btn.setVisible(replace)
        self.all_btn.setVisible(replace)
        self.show()
        self.raise_()
        self.reposition()
        self.search.setFocus()
        self.search.selectAll()
        self.refresh()

    def close_bar(self):
        self.hide()
        self.editor.setFocus()

    def reposition(self):
        width = min(max(self.editor.viewport().width() - 24, 240), 620)
        self.setFixedWidth(width)
        self.adjustSize()
        self.move(max(0, self.editor.width() - width - 20), 8)

    def _options(self) -> dict:
        return {"regex": self.regex_btn.isChecked(), "case": self.case_btn.isChecked()}

    def refresh(self):
        query = self.search.text()
        text = self.editor.toPlainText()
        if not query:
            self.matches = []
            self.count.setText("")
            return
        if find.compile_query(query, **self._options()) is None:
            self.matches = []
            self.count.setText("Invalid pattern")
            return
        self.matches = find.find_all(text, query, **self._options())
        self._show_count()

    def _current_index(self) -> int | None:
        c = self.editor.textCursor()
        span = (c.selectionStart(), c.selectionEnd())
        return self.matches.index(span) if c.hasSelection() and span in self.matches else None

    def _show_count(self, note: str = ""):
        n = len(self.matches)
        if note:
            self.count.setText(note)
        elif n == 0:
            self.count.setText("No matches")
        else:
            i = self._current_index()
            self.count.setText(f"{i + 1} of {n}" if i is not None else f"{n} match{'es' if n != 1 else ''}")

    # ---- actions
    def step(self, backward: bool = False):
        if not self.matches:
            self.refresh()
            if not self.matches:
                return
        c = self.editor.textCursor()
        position = c.selectionStart() if backward else (c.selectionEnd() if c.hasSelection() else c.position())
        span = find.next_match(self.matches, position, backward=backward)
        if span is None:
            return
        self._select(span)
        self._show_count()

    def _select(self, span: find.Span):
        c = self.editor.textCursor()
        c.setPosition(span[0])
        c.setPosition(span[1], QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(c)
        self.editor.ensureCursorVisible()
        if self.isVisible():
            self.raise_()  # the editor repaints under the bar after a scroll

    def replace_current(self):
        c = self.editor.textCursor()
        span = (c.selectionStart(), c.selectionEnd())
        if not c.hasSelection() or span not in self.matches:
            self.step()
            return
        new = find.replace_one(
            self.editor.toPlainText(), span, self.search.text(), self.replace.text(), **self._options()
        )
        if new is None:
            self._show_count("Bad replacement")
            return
        c.insertText(new)
        self.editor.setTextCursor(c)
        self.refresh()
        self.step()

    def replace_all(self):
        text = self.editor.toPlainText()
        new, n = find.replace_all(text, self.search.text(), self.replace.text(), **self._options())
        if not n:
            self._show_count("Nothing replaced" if self.matches else "")
            return
        c = self.editor.textCursor()
        c.beginEditBlock()
        c.select(QTextCursor.SelectionType.Document)
        c.insertText(new)
        c.endEditBlock()
        self.refresh()
        self._show_count(f"Replaced {n}")


class CodeEdit(PlainTextEdit):
    """PlainTextEdit with the editor basics: Ctrl+/ toggles comments on the selected lines (# for TOML, // for JSON),
    Tab / Shift+Tab indent and outdent a multi-line selection by two spaces, Ctrl+D duplicates the line,
    Ctrl+F / Ctrl+H open find / replace. Each shortcut is one undo step."""

    def __init__(self, lang="toml"):
        super().__init__()
        self.lang = lang
        self.find_bar = FindBar(self)
        self.textChanged.connect(lambda: self.find_bar.isVisible() and self.find_bar.refresh())

    def _block_range(self):
        c = self.textCursor()
        doc = self.document()
        start, end = c.selectionStart(), c.selectionEnd()
        first = doc.findBlock(start)
        last = doc.findBlock(end)
        if c.hasSelection() and end == last.position() and last.blockNumber() > first.blockNumber():
            last = last.previous()  # a selection ending at column 0 does not include that line
        return first, last

    def _replace_lines(self, fn):
        first, last = self._block_range()
        lines = []
        b = first
        while True:
            lines.append(b.text())
            if b == last:
                break
            b = b.next()
        new = fn(lines)
        if new == lines:
            return
        start, end = first.position(), last.position() + last.length() - 1  # ints: block handles go stale on edit
        joined = "\n".join(new)
        c = self.textCursor()
        c.beginEditBlock()
        c.setPosition(start)
        c.setPosition(end, c.MoveMode.KeepAnchor)
        c.insertText(joined)
        c.endEditBlock()
        sel = self.textCursor()
        sel.setPosition(start)
        sel.setPosition(start + len(joined), sel.MoveMode.KeepAnchor)
        self.setTextCursor(sel)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.find_bar.isVisible():
            self.find_bar.reposition()

    def keyPressEvent(self, e):
        key, mods = e.key(), e.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        if self.find_bar.isVisible() and self.find_bar.isAncestorOf(self.focusWidget() or self):
            e.accept()  # a key that escaped the bar is never a document edit
            return
        if ctrl and key == Qt.Key_F:
            self.find_bar.open(replace=False)
            return
        if ctrl and key == Qt.Key_H:
            self.find_bar.open(replace=True)
            return
        if key == Qt.Key_F3:
            if not self.find_bar.isVisible():
                self.find_bar.open()
            self.find_bar.step(backward=bool(mods & Qt.ShiftModifier))
            return
        if key == Qt.Key_Escape and self.find_bar.isVisible():
            self.find_bar.close_bar()
            return
        if ctrl and key == Qt.Key_Slash:
            self._replace_lines(lambda ls: toggle_comment(ls, COMMENT_PREFIX.get(self.lang, "#")))
            return
        if ctrl and key == Qt.Key_D:
            c = self.textCursor()
            c.beginEditBlock()
            c.movePosition(c.MoveOperation.EndOfBlock)
            c.insertText("\n" + c.block().text())
            c.endEditBlock()
            self.setTextCursor(c)
            return
        first, last = self._block_range()
        multi = self.textCursor().hasSelection() and last.blockNumber() > first.blockNumber()
        if key == Qt.Key_Backtab or (key == Qt.Key_Tab and mods & Qt.ShiftModifier):
            self._replace_lines(lambda ls: indent_lines(ls, outdent=True))
            return
        if key == Qt.Key_Tab and multi:
            self._replace_lines(lambda ls: indent_lines(ls))
            return
        super().keyPressEvent(e)


def code_edit(placeholder, wrap=False, lang="toml"):
    e = CodeEdit(lang)
    e.setPlaceholderText(placeholder)
    e.setTabStopDistance(e.fontMetrics().horizontalAdvance(" ") * 4)
    e.setToolTip(
        "Ctrl+F find  ·  Ctrl+H replace  ·  Ctrl+/ comment or uncomment the selected lines  ·  "
        "Tab / Shift+Tab indent a selection  ·  Ctrl+D duplicate the line"
    )
    e.setLineWrapMode(PlainTextEdit.LineWrapMode.WidgetWidth if wrap else PlainTextEdit.LineWrapMode.NoWrap)
    style_editor(e)
    e._hl = CodeHighlighter(e.document(), lang)
    return e
