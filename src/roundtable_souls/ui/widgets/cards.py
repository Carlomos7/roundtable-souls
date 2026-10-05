"""Cards and form rows: the expander card, glass tiles, label-and-action rows, setting rows, the logo preview."""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QRectF,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import ExpandGroupSettingCard as _ExpandGroupSettingCard
from qfluentwidgets import FluentIcon as FI
from qfluentwidgets import (
    IconWidget,
    StrongBodyLabel,
    TransparentToolButton,
)

from roundtable_souls.ui.dialogs.common import InfoDialog
from roundtable_souls.ui.theme import (
    RADIUS,
    hint,
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
        self._recheck = False
        self.view.installEventFilter(self)  # the rows' layout settles after they are polished: follow it

    def eventFilter(self, obj, e):
        if obj is self.view and e.type() == QEvent.LayoutRequest and self.isExpand and not self._recheck:
            self._recheck = True
            QTimer.singleShot(0, self._recheck_size)
        return super().eventFilter(obj, e)

    def _paint_view(self):
        t = tokens()
        fill = t["surf"].name()
        self.view.setStyleSheet(f"QFrame#view{{background:{fill};border:none}}")
        self.scrollWidget.setStyleSheet("background:transparent;border:none")

    def _span(self):
        """The open panel's height. Rows that wrap (button rows, word-wrapped text) are measured at the width they
        get; a plain size hint measures a wrapping row as one item per line and leaves the rest as empty space."""
        width = self.view.width() or self.width()
        lay = self.viewLayout
        lay.activate()  # rows just added leave the layout stale until the next event loop turn

        def height(w):
            if w.hasHeightForWidth():
                h = w.heightForWidth(width)
                if h > 0:
                    return h
            return w.sizeHint().height()

        whole = lay.heightForWidth(width) if lay.hasHeightForWidth() else lay.sizeHint().height()
        rows = sum(height(w) + 3 for w in self.widgets)
        return max(whole, rows, 1)

    def _adjustViewSize(self):
        h = self._span()
        self.spaceWidget.setFixedHeight(h)
        if self.isExpand:
            self.setFixedHeight(self.card.height() + h)

    def _recheck_size(self):
        self._recheck = False
        if self.isExpand and self.expandAni.state() != self.expandAni.State.Running:
            h = self._span()
            if self.height() != self.card.height() + h:
                self.spaceWidget.setFixedHeight(h)
                self.setFixedHeight(self.card.height() + h)

    def _onExpandValueChanged(self):
        top = self.viewportMargins().top()
        self.setFixedHeight(max(top + self._span() - self.verticalScrollBar().value(), top))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.isExpand and self.expandAni.state() != self.expandAni.State.Running:
            self._adjustViewSize()  # a new width re-wraps the rows, so the open height changes with it

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
        else:
            self._recheck_size()  # rows may have settled while it opened

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


def info_btn(title, text):
    b = TransparentToolButton(FI.INFO)
    b.setFixedSize(28, 28)
    b.setIconSize(QSize(14, 14))
    b.setToolTip("What this does")
    b.clicked.connect(lambda _=False, t=title, h=text: InfoDialog(t, h, b.window()).exec())
    return b


def icon_btn(icon, tip):
    """A square button for an action whose icon is enough on its own (delete, reset). The tooltip names it."""
    b = TransparentToolButton(icon)
    b.setFixedSize(36, 36)
    b.setToolTip(tip)
    b.setAccessibleName(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


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
        title_lab = StrongBodyLabel(title)
        title_lab.setWordWrap(True)
        cl.addWidget(title_lab)
        d = hint(desc)
        d.setWordWrap(True)
        cl.addWidget(d)
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
        title_lab = StrongBodyLabel(title)
        title_lab.setWordWrap(True)
        hl.addWidget(title_lab, 0, Qt.AlignVCenter)
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
            self.d.setWordWrap(True)  # otherwise the longest sentence sets the row's minimum width
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
    """A rounded glass tile. Same radius as the expanders, so the page reads as one surface. elevated: whether a
    page lifts it with a shadow in light (rows in a list set it False)."""

    elevated = True

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
