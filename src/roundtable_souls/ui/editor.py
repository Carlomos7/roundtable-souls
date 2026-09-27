"""The TOML / JSON editor with highlighting, Ctrl+/ comments, Tab indent and Ctrl+D."""

from __future__ import annotations

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from qfluentwidgets import PlainTextEdit, isDarkTheme

from roundtable_souls.core import COMMENT_PREFIX, indent_lines, toggle_comment
from roundtable_souls.ui.theme import style_editor


class CodeHighlighter(QSyntaxHighlighter):
    """TOML for the me3 profile, JSON for share-with-a-friend. Colours follow the theme."""

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


class CodeEdit(PlainTextEdit):
    """PlainTextEdit with the editor basics: Ctrl+/ toggles comments on the selected lines (# for TOML, // for JSON),
    Tab / Shift+Tab indent and outdent a multi-line selection by two spaces, Ctrl+D duplicates the line.
    Each shortcut is one undo step."""

    def __init__(self, lang="toml"):
        super().__init__()
        self.lang = lang

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

    def keyPressEvent(self, e):
        key, mods = e.key(), e.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
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
        "Ctrl+/ comment or uncomment the selected lines  ·  Tab / Shift+Tab indent a selection  ·  Ctrl+D duplicate the line"
    )
    e.setLineWrapMode(PlainTextEdit.LineWrapMode.WidgetWidth if wrap else PlainTextEdit.LineWrapMode.NoWrap)
    style_editor(e)
    e._hl = CodeHighlighter(e.document(), lang)
    return e
