"""Small widgets and layout helpers: cards, rows, the hero banner, the log pane."""

from __future__ import annotations

import datetime
import html
import re
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QObject, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    IconWidget,
    IndeterminateProgressRing,
    LargeTitleLabel,
    MessageBox,
    ScrollArea,
    StrongBodyLabel,
    TextEdit,
    TitleLabel,
    TransparentToolButton,
)
from qfluentwidgets import ExpandGroupSettingCard as _ExpandGroupSettingCard
from qfluentwidgets import FluentIcon as FI

from roundtable_souls.ui.theme import (
    ACCENT,
    ACCENT_LIGHT,
    HINT,
    HINT_ON_LIGHT,
    RADIUS,
    RADIUS_HERO,
    ghost_btn,
    hint,
    primary_btn,
    style_editor,
    style_ghost,
    tokens,
)


class ExpandGroupSettingCard(_ExpandGroupSettingCard):
    """Same panel, with a normal ease and a height that matches what you see.

    The stock animation often runs from 0 to 0, so the panel snaps shut and keeps the open height as empty space.
    """

    DURATION = 360

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.expandAni.setDuration(self.DURATION)
        self.expandAni.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.expandAni.finished.connect(self._snap_collapsed)
        self.card.paintEvent = self._paint_header
        self.borderWidget.paintEvent = self._paint_border
        self._paint_view()

    def _paint_view(self):
        t = tokens()
        fill = t["surf"].name()
        self.view.setStyleSheet(f"QFrame#view{{background:{fill};border:none}}")
        self.scrollWidget.setStyleSheet("background:transparent;border:none")

    def _span(self):
        hinted = self.viewLayout.sizeHint().height()
        summed = sum(w.sizeHint().height() + 3 for w in self.widgets)
        return max(hinted, summed, 1)

    def setExpand(self, isExpand: bool):
        if self.isExpand == isExpand:
            return
        self._adjustViewSize()
        span = self._span()
        self.isExpand = isExpand
        self.setProperty("isExpand", isExpand)
        self.setStyle(QApplication.style())
        self.card.expandButton.setExpand(isExpand)
        self.expandAni.stop()
        self.expandAni.setDuration(self.DURATION)
        if isExpand:
            self.expandAni.setStartValue(span)
            self.expandAni.setEndValue(0)
        else:
            self.expandAni.setStartValue(0)
            self.expandAni.setEndValue(span)
        self.expandAni.start()

    def _snap_collapsed(self):
        if not self.isExpand:
            self.setFixedHeight(self.card.height())

    def _paint_header(self, e):
        w = self.card
        p = QPainter(w)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        t = tokens()
        p.setBrush(t["surf"])
        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)
        path.addRoundedRect(QRectF(w.rect().adjusted(1, 1, -1, -1)), RADIUS, RADIUS)
        if self.isExpand:
            path.addRect(1, w.height() - RADIUS, w.width() - 2, RADIUS)
        p.drawPath(path.simplified())

    def _paint_border(self, e):
        w = self.borderWidget
        p = QPainter(w)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(Qt.NoBrush)
        t = tokens()
        p.setPen(QPen(t["border"], 1))
        p.drawRoundedRect(w.rect().adjusted(1, 1, -1, -1), RADIUS, RADIUS)
        ch = self.card.height()
        if ch < w.height():
            p.setPen(QPen(t["line"], 1))
            p.drawLine(1, ch, w.width() - 1, ch)


# ----------------------------------------------------------------------------- helpers
class Bus(QObject):
    """Signals the worker threads emit; Qt delivers them on the UI thread."""

    line = Signal(str)
    done = Signal(bool, str)
    running = Signal(bool)
    steam = Signal(bool, bool)
    shells = Signal(int)
    me3 = Signal(dict)
    conflicts = Signal(dict)
    saves = Signal(list)


def page(name: str):
    """A scrollable page with a vertical layout and generous padding."""
    area = ScrollArea()
    area.setObjectName(name)
    area.setWidgetResizable(True)
    area.setStyleSheet("QScrollArea{background:transparent;border:none}")
    inner = QWidget()
    inner.setObjectName(name + "Inner")
    inner.setStyleSheet("QWidget#" + name + "Inner{background:transparent}")
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(40, 28, 40, 36)
    lay.setSpacing(20)
    lay.setAlignment(Qt.AlignTop)
    area.setWidget(inner)
    area.viewport().setStyleSheet("background:transparent")
    return area, lay


def info_btn(title, text):
    b = TransparentToolButton(FI.INFO)
    b.setFixedSize(28, 28)
    b.setIconSize(QSize(14, 14))
    b.setToolTip("What this does")
    b.clicked.connect(lambda _=False, t=title, h=text: MessageBox(t, h, b.window()).exec())
    return b


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
    """Launch output. Timestamp, one colour per level, Copy and Clear. Newest at the bottom."""

    def __init__(self):
        super().__init__()
        self._rows = []
        self.view = TextEdit()
        self.view.setReadOnly(True)
        self.view.setAcceptRichText(True)
        self.view.setPlaceholderText("Play, Repair, and Clear write here. Newest line at the bottom.")
        self.view.setLineWrapMode(TextEdit.LineWrapMode.WidgetWidth)
        style_editor(self.view)
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(8)
        self.copy_btn = ghost_btn("Copy", FI.COPY)
        self.copy_btn.clicked.connect(self.copy)
        self.clear_btn = ghost_btn("Clear", FI.DELETE)
        self.clear_btn.clicked.connect(self.clear)
        bar.addWidget(self.copy_btn)
        bar.addWidget(self.clear_btn)
        bar.addStretch()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addLayout(bar)
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
        style_ghost(self.copy_btn)
        style_ghost(self.clear_btn)
        self._paint()

    def _paint(self):
        t = tokens()
        bg = t["editor"].name()
        colors = {"info": t["editor_fg"], "warning": t["accent"], "error": t["danger"], "banner": t["muted"]}
        bits = []
        for ts, level, part in self._rows:
            color = colors.get(level, t["editor_fg"])
            if level == "banner":
                bits.append(f'<div style="color:{t["muted"]};margin:12px 0 6px 0">{html.escape("─ " * 2 + part)}</div>')
            else:
                stamp = ts.strftime("%H:%M:%S") if ts else "&nbsp;" * 8
                body = html.escape(part) if part else "&nbsp;"
                bits.append(
                    f'<div style="color:{color}"><span style="color:{t["muted"]}">{stamp}</span>&nbsp;&nbsp;{body}</div>'
                )
        self.view.setHtml(
            f"<body style=\"background:{bg};font-family:Consolas,'Cascadia Code',monospace;font-size:11pt\">{''.join(bits)}</body>"
        )


def tone_label(lab, level="muted"):
    """Quiet status type. Colour means something: gold wait, rust error, otherwise muted."""
    if level == "error":
        lab.setTextColor("#963C48", "#E08A7A")
    elif level == "warning":
        lab.setTextColor(ACCENT_LIGHT, ACCENT)
    elif level == "accent":
        lab.setTextColor(ACCENT_LIGHT, ACCENT)
    else:
        lab.setTextColor(HINT_ON_LIGHT, HINT)


def titled(lay, text, icon, sub=None, action=None):
    """Page header. The nav already shows the icon, so the title is type only. The action sits on the title row."""
    head = QVBoxLayout()
    head.setSpacing(4)
    row = QHBoxLayout()
    row.setSpacing(12)
    title = TitleLabel(text)
    row.addWidget(title)
    row.addStretch()
    if action is not None:
        row.addWidget(action, 0, Qt.AlignVCenter)
    head.addLayout(row)
    if sub:
        head.addWidget(hint(sub))
    lay.addLayout(head)


def count_label(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def card(title=None, icon=None):
    c = GlassCard()
    lay = QVBoxLayout(c)
    lay.setContentsMargins(20, 16, 20, 18)
    lay.setSpacing(10)
    if title:
        row = QHBoxLayout()
        row.setSpacing(8)
        if icon:
            ic = IconWidget(icon)
            ic.setFixedSize(18, 18)
            row.addWidget(ic)
        row.addWidget(StrongBodyLabel(title))
        row.addStretch()
        lay.addLayout(row)
    return c, lay


class LogoPreview(QWidget):
    """The mark the way Windows 11 shows it: a square, clipped to a rounded plate."""

    def __init__(self):
        super().__init__()
        self._pix = QPixmap()
        self.setFixedSize(56, 56)

    def setPixmap(self, pix):
        self._pix = pix
        self.update()

    def paintEvent(self, e):
        if self._pix.isNull():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.setClipPath(path)
        p.drawPixmap(self.rect(), self._pix)


class PairRow(QWidget):
    """A label and an action. The action drops under the text when the row gets narrow."""

    def __init__(self, title, desc, button):
        super().__init__()
        col = QWidget()
        cl = QVBoxLayout(col)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(2)
        cl.addWidget(StrongBodyLabel(title))
        cl.addWidget(hint(desc))
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.box = QBoxLayout(QBoxLayout.LeftToRight, self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(16)
        self.box.addWidget(col, 1)
        self.box.addWidget(button, 0, Qt.AlignRight | Qt.AlignVCenter)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.box.setDirection(QBoxLayout.TopToBottom if self.width() < 520 else QBoxLayout.LeftToRight)


class SettingRow(QWidget):
    """A form row: title, optional one-line blurb, the control, and an info popup."""

    def __init__(self, title, blurb, control, help_text=""):
        super().__init__()
        self._blurb = blurb or ""
        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(4)
        hl.addWidget(StrongBodyLabel(title), 0, Qt.AlignVCenter)
        if help_text:
            hl.addWidget(info_btn(title, help_text), 0, Qt.AlignVCenter)
        hl.addStretch()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(2)
        ll.addWidget(head)
        self.d = hint(blurb) if blurb else None
        if self.d:
            ll.addWidget(self.d)
        control.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.box = QBoxLayout(QBoxLayout.LeftToRight, self)
        self.box.setContentsMargins(20, 10, 20, 10)
        self.box.setSpacing(12)
        self.box.addWidget(left, 1)
        self.box.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)
        self._fit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def sizeHint(self):
        return QSize(360, max(self.minimumHeight(), 56))

    def _fit(self):
        compact = self.width() < 500
        self.box.setDirection(QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight)
        extra = 16 if compact else 0
        if self.d and self._blurb:
            wrap = max(140, self.width() - 48)
            h = self.d.fontMetrics().boundingRect(0, 0, wrap, 400, Qt.TextWordWrap, self._blurb).height()
            self.setMinimumHeight(max(56, h + 40 + extra))
        else:
            self.setMinimumHeight(52 + extra)
        self.updateGeometry()


class GlassCard(QWidget):
    """A rounded glass tile. Same radius as the expanders, so the page reads as one surface."""

    def __init__(self, parent=None, radius=RADIUS):
        super().__init__(parent)
        self.radius = radius

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect().adjusted(1, 1, -1, -1))
        path = QPainterPath()
        path.addRoundedRect(r, self.radius, self.radius)
        t = tokens()
        p.fillPath(path, t["surf"])
        p.strokePath(path, QPen(t["border"], 1))


class Metric(QWidget):
    """One number in the hero footer. Label muted, value loud."""

    def __init__(self, label):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(hint(label))
        self.value = StrongBodyLabel("—")
        self.value.setWordWrap(True)
        f = self.value.font()
        f.setPointSize(16)
        f.setBold(True)
        self.value.setFont(f)
        lay.addWidget(self.value)


class HeroBanner(QWidget):
    """One featured panel: who you are, the Play action, then three quiet facts."""

    def __init__(self):
        super().__init__()
        self._compact = False
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.name_col = QWidget()
        col = QVBoxLayout(self.name_col)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        col.addStretch()
        self.name = LargeTitleLabel("Reading your save...")
        f = self.name.font()
        f.setPointSize(28)
        f.setBold(True)
        self.name.setFont(f)
        self.name.setWordWrap(True)
        col.addWidget(self.name)
        self.sub = hint("")
        col.addWidget(self.sub)
        col.addStretch()
        self.side = QWidget()
        side = QVBoxLayout(self.side)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(8)
        side.addStretch()
        self.play_btn = primary_btn("Play")
        self.play_btn.setFixedSize(148, 48)
        pf = QFont()
        pf.setPointSize(15)
        pf.setBold(True)
        self.play_btn.setFont(pf)
        self.ring = IndeterminateProgressRing()
        self.ring.setFixedSize(16, 16)
        self.ring.setStrokeWidth(2)
        self.ring.hide()
        self.ready = CaptionLabel("Ready")
        tone_label(self.ready)
        self.status_pill = self.ready
        self.status = BodyLabel("")
        self.status.setWordWrap(True)
        tone_label(self.status)
        meta = QHBoxLayout()
        meta.setSpacing(8)
        meta.setContentsMargins(0, 0, 0, 0)
        meta.addWidget(self.ring)
        meta.addWidget(self.ready)
        meta.addStretch()
        side.addWidget(self.play_btn, 0, Qt.AlignRight)
        side.addLayout(meta)
        side.addWidget(self.status)
        side.addStretch()
        self.metrics = QWidget()
        row = QHBoxLayout(self.metrics)
        row.setContentsMargins(0, 4, 0, 0)
        row.setSpacing(0)
        self.stat_level = Metric("Level")
        self.stat_save = Metric("Save")
        self.stat_body = Metric("Body")
        for i, m in enumerate((self.stat_level, self.stat_save, self.stat_body)):
            if i:
                row.addSpacing(28)
            row.addWidget(m, 1)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(28, 24, 28, 20)
        self.grid.setHorizontalSpacing(24)
        self.grid.setVerticalSpacing(18)
        self.grid.addWidget(self.name_col, 0, 0)
        self.grid.addWidget(self.side, 0, 1, Qt.AlignRight | Qt.AlignVCenter)
        self.grid.addWidget(self.metrics, 1, 0, 1, 2)
        self.grid.setColumnStretch(0, 1)

    def set_compact(self, compact):
        if compact == self._compact:
            return
        self._compact = compact
        f = self.name.font()
        f.setPointSize(22 if compact else 28)
        self.name.setFont(f)
        self.setMinimumHeight(248 if compact else 220)
        self.grid.setContentsMargins(*(20, 16, 20, 16) if compact else (28, 24, 28, 20))
        self.grid.removeWidget(self.name_col)
        self.grid.removeWidget(self.side)
        self.grid.removeWidget(self.metrics)
        if compact:
            self.grid.addWidget(self.name_col, 0, 0)
            self.grid.addWidget(self.side, 1, 0, Qt.AlignLeft)
            self.grid.addWidget(self.metrics, 2, 0)
        else:
            self.grid.addWidget(self.name_col, 0, 0)
            self.grid.addWidget(self.side, 0, 1, Qt.AlignRight | Qt.AlignVCenter)
            self.grid.addWidget(self.metrics, 1, 0, 1, 2)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 0)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect().adjusted(1, 1, -1, -1))
        path = QPainterPath()
        path.addRoundedRect(r, RADIUS_HERO, RADIUS_HERO)
        t = tokens()
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, t["hero_a"])
        g.setColorAt(1, t["hero_b"])
        p.fillPath(path, g)
        orb = QRadialGradient(QPointF(r.left() + r.width() * 0.18, r.top() + 8), r.width() * 0.42)
        orb.setColorAt(0, t["glow"])
        orb.setColorAt(1, QColor(t["glow"].red(), t["glow"].green(), t["glow"].blue(), 0))
        p.fillPath(path, orb)
        p.strokePath(path, QPen(t["hero_border"], 1))
        y = self.metrics.y() - 6
        if y > 20:
            p.setPen(QPen(t["line"], 1))
            p.drawLine(int(r.left()) + 20, y, int(r.right()) - 20, y)


class SaveBar(QWidget):
    """The co-op save row. It stays under the scrolling form, and picks up gold while something is unsaved."""

    def __init__(self):
        super().__init__()
        self.pending = False
        self.setMinimumHeight(64)

    def paintEvent(self, e):
        t = tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        fill = t["pending"] if self.pending else t["surf"]
        border = t["pending_border"] if self.pending else t["border"]
        p.setBrush(fill)
        p.setPen(QPen(border, 1.4 if self.pending else 1))
        p.drawRoundedRect(r, RADIUS, RADIUS)
