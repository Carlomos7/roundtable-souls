"""The log: the Bus that carries its lines to the UI thread, the pane that shows them, and tidying a line for display."""

from __future__ import annotations

import datetime
import html
import re
from pathlib import Path

from PySide6.QtCore import (
    QObject,
    Signal,
)
from PySide6.QtGui import (
    QFont,
    QFontMetrics,
)
from PySide6.QtWidgets import (
    QApplication,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import FluentIcon as FI
from qfluentwidgets import (
    TextEdit,
)

from roundtable_souls.ui.theme import (
    ghost_btn,
    style_editor,
    style_ghost,
    tokens,
)
from roundtable_souls.ui.widgets.layout import action_row


# ----------------------------------------------------------------------------- helpers
class Bus(QObject):
    """Signals emitted on any thread; Qt delivers them on the UI thread. Background work reports through ui/jobs.py;
    what is left here is the log lines the window shows, which arrive from every thread."""

    line = Signal(str, str)  # message, level (info / warning / error, or empty to read it from the text)
    merge = Signal(dict)


_ABS_PATH = re.compile(r"(?i)(?:[A-Z]:\\|/)(?:[^\s\\/]+[\\/])+([^\s\\/]+)")


def tidy_log_line(s: str) -> str:
    """Show the file name, not a long path, so the log is the same on any PC."""
    return _ABS_PATH.sub(r"\1", s)


def classify_log(msg: str) -> str:
    low = msg.lstrip().lower()
    if low.startswith(("error", "traceback", "exception", "failed")):
        return "error"
    if low.startswith(("warning", "warn:", "warn ")):
        return "warning"
    return "info"


def short_problem(text: str) -> str:
    """Keep the reason, drop a long path so the line is not this PC's folder tree."""
    if ": " not in text:
        return text
    kind, rest = text.split(": ", 1)
    if "\\" in rest or "/" in rest:
        return f"{kind}: {Path(rest).name}"
    return text


LOG_KEEP = 1500


class LogPane(QWidget):
    """What the running job is doing: timestamp, one colour per level, Copy, Clear and the logs folder. Newest at
    the bottom. Every job's full log is kept in the logs folder; this pane keeps the last LOG_KEEP lines."""

    def __init__(self, open_folder=None, open_activity=None):
        super().__init__()
        self._rows = []
        self.view = TextEdit()
        self.view.setReadOnly(True)
        self.view.setAcceptRichText(True)
        self.view.setPlaceholderText("Play, repairs, installs and rebuilds write here. Newest line at the bottom.")
        self.view.setLineWrapMode(TextEdit.LineWrapMode.WidgetWidth)
        style_editor(self.view)
        row, bar = action_row()  # the buttons wrap onto a second line in a narrow window
        self.copy_btn = ghost_btn("Copy", FI.COPY)
        self.copy_btn.setToolTip("Copy the lines shown here.")
        self.copy_btn.clicked.connect(self.copy)
        self.clear_btn = ghost_btn("Clear", FI.DELETE)
        self.clear_btn.setToolTip("Clear this view. The job logs in the logs folder are kept.")
        self.clear_btn.clicked.connect(self.clear)
        bar.addWidget(self.copy_btn)
        bar.addWidget(self.clear_btn)
        self.folder_btn = None
        if open_folder is not None:
            self.folder_btn = ghost_btn("Logs folder", FI.FOLDER)
            self.folder_btn.setToolTip("Every job's full log, me3's output and launcher.log.")
            self.folder_btn.clicked.connect(open_folder)
            bar.addWidget(self.folder_btn)
        self.activity_btn = None
        if open_activity is not None:
            self.activity_btn = ghost_btn("Activity", FI.HISTORY)
            self.activity_btn.setToolTip("Every job so far, with how it went and its full log.")
            self.activity_btn.clicked.connect(open_activity)
            bar.addWidget(self.activity_btn)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(row)
        lay.addWidget(self.view)

    def add(self, msg, kind=None):
        now = datetime.datetime.now()
        parts = tidy_log_line(str(msg)).replace("\r\n", "\n").replace("\r", "\n").split("\n") or [""]
        for i, part in enumerate(parts):
            self._rows.append((now if i == 0 else None, kind or classify_log(part), part))
        if len(self._rows) > LOG_KEEP:
            self._rows = self._rows[-LOG_KEEP:]
        self._paint()
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def banner(self, title):
        self.add(title, kind="banner")

    def last_level(self):
        return self._rows[-1][1] if self._rows else "info"

    def copy(self):
        lines = []
        for ts, _level, part in self._rows:
            stamp = ts.strftime("%H:%M:%S") if ts else ""
            lines.append(f"{stamp}  {part}".rstrip())
        QApplication.clipboard().setText("\n".join(lines))

    def clear(self):
        self._rows.clear()
        self.view.clear()

    def restyle(self):
        style_editor(self.view)
        for b in (self.copy_btn, self.clear_btn, self.folder_btn, self.activity_btn):
            if b is not None:
                style_ghost(b)
        self._paint()

    def _paint(self):
        rows = [(ts.strftime("%H:%M:%S") if ts else "", level, part) for ts, level, part in self._rows]
        self.view.setHtml(log_html(rows))


def log_html(rows, stamp_width: str = "00:00:00") -> str:
    """Log lines as the editor-styled HTML both the Play page's Log and the Activity page show: one colour per
    level, a muted time, and a hanging indent so wrapped text lines up with the message. rows: (time text, level,
    text) with level info / warning / error / debug / banner."""
    t = tokens()
    bg = t["editor"].name()
    colors = {
        "info": t["editor_fg"],
        "debug": t["muted"],
        "warning": t["warning_fg"],
        "error": t["danger"],
        "banner": t["muted"],
    }
    f = QFont("Consolas")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPointSize(11)
    indent = QFontMetrics(f).horizontalAdvance(stamp_width + "  ")
    bits = []
    for stamp, level, part in rows:
        color = colors.get(level, t["editor_fg"])
        if level == "banner":
            bits.append(f'<div style="color:{t["muted"]};margin:12px 0 6px 0">{html.escape("─ " * 2 + part)}</div>')
            continue
        shown = html.escape(stamp) if stamp else "&nbsp;" * len(stamp_width)
        for i, line in enumerate(str(part).split("\n") or [""]):
            body = html.escape(line) if line else "&nbsp;"
            lead = shown if i == 0 else "&nbsp;" * len(stamp_width)
            bits.append(
                f'<div style="color:{color};margin-left:{indent}px;text-indent:-{indent}px">'
                f'<span style="color:{t["muted"]}">{lead}</span>&nbsp;&nbsp;{body}</div>'
            )
    return (
        f"<body style=\"background:{bg};font-family:Consolas,'Cascadia Code',monospace;font-size:11pt\">"
        f"{''.join(bits)}</body>"
    )
