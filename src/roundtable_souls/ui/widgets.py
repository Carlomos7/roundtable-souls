"""Small widgets and layout helpers: cards, rows, the hero banner, the log pane."""

from __future__ import annotations

import datetime
import html
import re
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    DropDownPushButton,
    FlowLayout,
    IconWidget,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarIcon,
    InfoBarPosition,
    LargeTitleLabel,
    MenuAnimationType,
    RoundMenu,
    ScrollArea,
    StrongBodyLabel,
    TextEdit,
    TitleLabel,
    TransparentToolButton,
    getFont,
)
from qfluentwidgets import ExpandGroupSettingCard as _ExpandGroupSettingCard
from qfluentwidgets import FluentIcon as FI

from roundtable_souls.ui.dialogs import InfoDialog
from roundtable_souls.ui.editor import code_edit
from roundtable_souls.ui.theme import (
    ACCENT,
    ACCENT_LIGHT,
    HINT,
    HINT_ON_LIGHT,
    RADIUS,
    RADIUS_BTN,
    RADIUS_HERO,
    ghost_btn,
    hint,
    primary_btn,
    style_editor,
    style_ghost,
    tokens,
)


class SwitcherMetrics:
    """One set of measurements for the switcher button and its menu rows, so a row's dot and name sit exactly under
    the button's. x values are from the button's left edge, which is also where the menu opens."""

    PAD = 12  # left edge to the dot
    DOT = 10
    TEXT = PAD + DOT + 10  # left edge to the name
    ARROW = 30  # room kept on the button's right for its arrow
    HEIGHT = 32  # button and menu rows alike
    STATUS_GAP = 32  # at least this much between the longest name and the statuses
    INSET = 4  # menu rows' highlight inset from the panel edge
    GAP = 4  # between the button's bottom and the menu's top
    FONT = 14
    STATUS_FONT = 12


def _draw_dot(painter, x, rect, color):
    d = SwitcherMetrics.DOT
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(QRectF(x, rect.center().y() - d / 2, d, d))


class _StatusRowDelegate(QStyledItemDelegate):
    """Paints a StatusMenu row in the launcher's colours: highlight, current-game bar, dot, name, status."""

    def paint(self, painter, option, index):
        action = index.data(Qt.UserRole)
        if not isinstance(action, QAction):
            return
        m, t = SwitcherMetrics, tokens()
        view_left = 1  # the list's 1px border: viewport x 0 is button x 1
        rect = QRectF(option.rect)
        row = rect.adjusted(m.INSET - view_left, 1, -(m.INSET - view_left), -1)
        current = action.isChecked()
        hover = bool(option.state & QStyle.State_MouseOver)
        painter.save()
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        if hover or current:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(t["ghost_hv"] if hover else t["ghost"]))
            painter.drawRoundedRect(row, RADIUS_BTN, RADIUS_BTN)
        if current:
            painter.setBrush(QColor(t["accent"]))
            painter.drawRoundedRect(QRectF(row.left() + 1, row.center().y() - 7, 3, 14), 1.5, 1.5)
        _draw_dot(painter, m.PAD - view_left, rect, action.property("dot") or t["muted"])
        font = getFont(m.FONT, QFont.DemiBold if current else QFont.Normal)
        painter.setFont(font)
        painter.setPen(QColor(t["ghost_fg"]))
        name = QRectF(m.TEXT - view_left, rect.top(), rect.width(), rect.height())
        painter.drawText(name, Qt.AlignLeft | Qt.AlignVCenter, action.text())
        status = action.property("status")
        if status:
            painter.setFont(getFont(m.STATUS_FONT))
            painter.setPen(QColor(t["muted"]))
            painter.drawText(row.adjusted(0, 0, -10, 0), Qt.AlignRight | Qt.AlignVCenter, status)
        painter.restore()


class StatusMenu(RoundMenu):
    """A pick-one menu in the launcher's colours. Every row is the same: dot, name, and a status right-aligned in one
    column; the current row is tinted with an accent bar. Pair it with MenuButton, which shares its measurements."""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.view.setItemDelegate(_StatusRowDelegate(self.view))
        self.setItemHeight(SwitcherMetrics.HEIGHT)
        self.restyle()

    def restyle(self) -> None:
        t = tokens()
        self.view.setStyleSheet(
            f"MenuActionListWidget{{background:{t['editor'].name()};border:1px solid {t['ghost_bd']};"
            f"border-radius:{RADIUS}px;outline:none;}}"
            "MenuActionListWidget::item{margin:0;padding:0;border:none;background:transparent;}"
        )

    def _adjustItemText(self, item, action):
        m = SwitcherMetrics
        name = QFontMetrics(getFont(m.FONT, QFont.DemiBold)).horizontalAdvance(action.text())
        status = QFontMetrics(getFont(m.STATUS_FONT)).horizontalAdvance(str(action.property("status") or ""))
        w = m.TEXT + name + m.STATUS_GAP + status + 10 + m.INSET
        item.setText("")  # the delegate paints the row; no default text underneath it
        item.setSizeHint(QSize(w, m.HEIGHT))
        return w

    def exec(self, pos, ani=True, aniType=MenuAnimationType.DROP_DOWN):
        # PySide resolves a RoundMenu subclass's exec to QMenu.exec, which has no aniType; the library's own
        # subclasses redefine it for the same reason
        return super().exec(pos, ani, aniType)

    def add_choice(self, action: QAction, dot: str) -> None:
        action.setCheckable(True)
        action.setProperty("dot", dot)
        self.addAction(action)

    def set_statuses(self, statuses: dict[QAction, str]) -> None:
        """Set each row's status, then re-measure the rows (the widest one sets the menu width)."""
        for action, text in statuses.items():
            action.setProperty("status", text)
        for action in self.menuActions():
            item = action.property("item")
            if item is not None:
                self._adjustItemText(item, action)
        self.view.adjustSize()
        self.adjustSize()


class MenuButton(DropDownPushButton):
    """The switcher button: dot, name and arrow in the launcher's colours, at the same x as StatusMenu's rows. Its
    menu opens flush with its left edge, just below it (the library centres menus on the button)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)  # the library re-enters __init__ per overload: pass everything through
        self._dot = None
        self._widest = 0
        self.setFixedHeight(SwitcherMetrics.HEIGHT)
        self.setCursor(Qt.PointingHandCursor)

    def set_choice(self, text: str, dot: str) -> None:
        self._dot = dot
        self.setText(text)
        self.updateGeometry()
        self.update()

    def fit_texts(self, texts) -> None:
        """Keep one width whichever of these texts is shown, so the button and what follows it never shift."""
        fm = QFontMetrics(getFont(SwitcherMetrics.FONT))
        self._widest = max((fm.horizontalAdvance(t) for t in texts), default=0)
        self.updateGeometry()

    def sizeHint(self):
        fm = QFontMetrics(getFont(SwitcherMetrics.FONT))
        text = max(self._widest, fm.horizontalAdvance(self.text()))
        return QSize(SwitcherMetrics.TEXT + text + SwitcherMetrics.ARROW, SwitcherMetrics.HEIGHT)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, e):
        m, t = SwitcherMetrics, tokens()
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.45)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QColor(t["ghost_bd"]))
        painter.setBrush(QColor(t["ghost_hv"] if (self.isHover or self.isPressed) else t["ghost"]))
        painter.drawRoundedRect(rect, RADIUS_BTN, RADIUS_BTN)
        if self._dot:
            _draw_dot(painter, m.PAD, rect, self._dot)
        painter.setFont(getFont(m.FONT))
        painter.setPen(QColor(t["ghost_fg"]))
        text = QRectF(m.TEXT, 0, self.width() - m.TEXT - m.ARROW, self.height())
        painter.drawText(text, Qt.AlignLeft | Qt.AlignVCenter, self.text())
        y = self.height() / 2 - 5 + (self.arrowAni.y if self.isEnabled() else 0)
        FI.ARROW_DOWN.render(painter, QRectF(self.width() - 22, y, 10, 10), fill=t["ghost_fg"])

    def _showMenu(self):
        menu = self.menu()
        if not menu:
            return
        menu.view.setMinimumWidth(self.width())
        menu.view.adjustSize()
        menu.adjustSize()
        # the drop-down animation puts the list 4px under the point it is given, less the menu's top margin
        top = menu.layout().contentsMargins().top() - 4
        down = self.mapToGlobal(QPoint(0, self.height() + SwitcherMetrics.GAP - top))
        up = self.mapToGlobal(QPoint(0, -SwitcherMetrics.GAP))
        drop, pull = MenuAnimationType.DROP_DOWN, MenuAnimationType.PULL_UP
        if menu.view.heightForAnimation(down, drop) >= menu.view.heightForAnimation(up, pull):
            menu.view.adjustSize(down, drop)
            menu.exec(down, aniType=drop)
        else:
            menu.view.adjustSize(up, pull)
            menu.exec(up, aniType=pull)


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


# ----------------------------------------------------------------------------- helpers
class Bus(QObject):
    """Signals the worker threads emit; Qt delivers them on the UI thread."""

    line = Signal(str)
    done = Signal(bool, str)
    running = Signal(bool)
    steam = Signal(bool, bool)
    shells = Signal(int)
    me3 = Signal(dict)
    update = Signal(object)
    update_checked = Signal(object)
    update_progress = Signal(str)
    update_ready = Signal(object)
    conflicts = Signal(dict)
    saves = Signal(dict)


def page(name: str):
    """A scrollable page with a vertical layout and generous padding."""
    area = ScrollArea()
    area.setObjectName(name)
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # content reflows; a page never scrolls sideways
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
    b.clicked.connect(lambda _=False, t=title, h=text: InfoDialog(t, h, b.window()).exec())
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
    """Page header: the title, a one-line subtitle, then the page's actions on a row that wraps when narrow.
    The nav already shows the icon, so the title is type only."""
    head = QVBoxLayout()
    head.setSpacing(4)
    head.addWidget(TitleLabel(text))
    if sub:
        head.addWidget(hint(sub))
    if action is not None:
        head.addSpacing(8)
        head.addWidget(action)
    lay.addLayout(head)


class _RightFlowLayout(FlowLayout):
    """FlowLayout with each line pushed to the right edge (actions that belong to the row above them)."""

    def _doLayout(self, rect, move):
        m = self.contentsMargins()
        left, right = rect.x() + m.left(), rect.right() - m.right()
        gap_x, gap_y = self.horizontalSpacing(), self.verticalSpacing()
        lines, line, used = [], [], 0
        for item in self._items:
            if item.widget() and not item.widget().isVisible() and self.isTight:
                continue
            w = item.sizeHint().width()
            if line and used + gap_x + w > right - left + 1:
                lines.append(line)
                line, used = [], 0
            used = w if not line else used + gap_x + w
            line.append(item)
        if line:
            lines.append(line)
        y = rect.y() + m.top()
        for line in lines:
            width = sum(i.sizeHint().width() for i in line) + gap_x * (len(line) - 1)
            x = max(left, right - width + 1)
            if move:
                for item in line:
                    item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
                    x += item.sizeHint().width() + gap_x
            y += max(i.sizeHint().height() for i in line) + gap_y
        return (y - gap_y if lines else y) + m.bottom() - rect.y()


def action_row(align: str = "left"):
    """A container whose buttons wrap onto a second line instead of squeezing, lined up on the left, or on the right
    for actions that belong to what is above them. Returns (widget, layout)."""
    w = QWidget()
    flow = (_RightFlowLayout if align == "right" else FlowLayout)(w, needAni=False)
    flow.setContentsMargins(0, 0, 0, 0)
    flow.setHorizontalSpacing(8)
    flow.setVerticalSpacing(8)
    return w, flow


def dispose(widget):
    """Delete a widget that is being rebuilt. Fluent's FlowLayout watches its widgets through an event filter and
    walks its item list on every reparent; emptying it first keeps that filter away from deleted items."""
    if widget is None:
        return
    for flow in widget.findChildren(FlowLayout):
        flow.removeAllWidgets()
    widget.setParent(None)
    widget.deleteLater()


def clear_layout(layout):
    """Remove and dispose every widget in a layout (flow layouts included)."""
    if isinstance(layout, FlowLayout):
        widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
        layout.removeAllWidgets()
        for w in widgets:
            dispose(w)
        return
    for i in reversed(range(layout.count())):
        item = layout.takeAt(i)
        if item is None:
            continue
        if item.widget() is not None:
            dispose(item.widget())
        elif item.layout() is not None:
            clear_layout(item.layout())


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
        self.play_btn = primary_btn("Play", hero=True)
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
        self.note = BodyLabel(note)
        self.note.setWordWrap(True)
        self.box.addWidget(self.note, 1)
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
        """Pending: the actions are live and the note is gold; otherwise both buttons rest."""
        self.pending = pending
        self.primary.setEnabled(pending)
        if self.secondary is not None:
            self.secondary.setEnabled(pending)
        self.note.setText(note)
        self.note.setTextColor(ACCENT_LIGHT if pending else HINT_ON_LIGHT, ACCENT if pending else HINT)
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


_NOTICE_ICONS = {
    "info": InfoBarIcon.INFORMATION,
    "success": InfoBarIcon.SUCCESS,
    "warning": InfoBarIcon.WARNING,
    "error": InfoBarIcon.ERROR,
}


def notice(parent, kind, title, content="", actions=(), closable=True, duration=-1):
    """A message at the top of the window. With actions, the buttons sit in one row under the text, so the bar is
    never wider than the window and its buttons never squeeze the text; without, title and text share a line.

    kind: info / success / warning / error. actions: buttons (ghost_btn / primary_btn), in reading order."""
    orient = Qt.Vertical if actions else Qt.Horizontal
    bar = InfoBar(
        _NOTICE_ICONS[kind],
        title,
        content,
        orient=orient,
        isClosable=closable,
        duration=duration,
        position=InfoBarPosition.TOP,
        parent=parent,
    )
    if actions:
        row = QWidget()
        row.setAttribute(Qt.WA_TranslucentBackground)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 4, 0, 0)
        rl.setSpacing(8)
        for b in actions:
            rl.addWidget(b)
        rl.addStretch(1)
        bar.addWidget(row)
    bar.show()
    return bar


class PathTag(QWidget):
    """Where an entry sits, as one tag: folder names joined by a chevron ("natives > SeamlessCoop"). Nested folders
    stay a single tag. Long paths keep their last folders and start with an ellipsis."""

    SEP = "\u203a"
    MAX_W = 320

    def __init__(self, parts, tip=""):
        super().__init__()
        self.parts = [str(p) for p in parts if str(p)]
        self.setToolTip(tip or " / ".join(self.parts))
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._font = getFont(12)
        self.setFixedHeight(22)

    def _text(self, width=None):
        fm = QFontMetrics(self._font)
        text = f"  {self.SEP}  ".join(self.parts)
        room = (width or self.MAX_W) - 20
        if fm.horizontalAdvance(text) <= room:
            return text
        for start in range(1, len(self.parts)):  # drop leading folders first: the nearest ones say the most
            short = "\u2026  " + f"  {self.SEP}  ".join(self.parts[start:])
            if fm.horizontalAdvance(short) <= room:
                return short
        return fm.elidedText(self.parts[-1], Qt.ElideMiddle, room)

    def sizeHint(self):
        fm = QFontMetrics(self._font)
        return QSize(min(self.MAX_W, fm.horizontalAdvance(self._text()) + 20), 22)

    def minimumSizeHint(self):
        return QSize(min(self.sizeHint().width(), 90), 22)

    def paintEvent(self, e):
        t = tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(t["ghost_bd"]), 1))
        p.setBrush(QColor(t["ghost"]))
        p.drawRoundedRect(r, 11, 11)
        p.setFont(self._font)
        p.setPen(QColor(t["ghost_fg"]))
        p.drawText(r.adjusted(10, 0, -10, 0), Qt.AlignVCenter | Qt.AlignLeft, self._text(self.width()))


class ElideLabel(BodyLabel):
    """A one-line label that gives way when its row runs short: it ends in an ellipsis instead of pushing the row's
    buttons out of view. The full text stays in the tooltip. (No __init__: the base constructor dispatches on its
    arguments and hands the text to setText, which sets everything up.)"""

    def setText(self, text):
        self._full = text
        self.setToolTip(text)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._fit()

    def full_text(self):
        return getattr(self, "_full", super().text())

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.full_text()) + 2, super().sizeHint().height())

    def minimumSizeHint(self):
        return QSize(min(60, self.sizeHint().width()), super().minimumSizeHint().height())

    def _fit(self):
        full = self.full_text()
        mode = getattr(self, "elide_mode", Qt.ElideRight)  # paths read better cut in the middle
        shown = self.fontMetrics().elidedText(full, mode, max(self.width(), 1))
        super().setText(shown if self.width() > 1 else full)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()


class NameWithTag(QWidget):
    """A row's name with its folder tag beside it. When the row is too narrow for both, the tag steps aside (the
    name's tooltip still says where it sits) instead of both being cut short."""

    GAP = 10

    def __init__(self, name: str, tag_parts=(), tag_tip: str = "", muted: bool = False):
        super().__init__()
        self.name = ElideLabel(name)
        if muted:
            tone_label(self.name, "muted")
        self.tag = PathTag(tag_parts, tag_tip) if tag_parts else None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(self.GAP)
        lay.addWidget(self.name)
        if self.tag is not None:
            lay.addWidget(self.tag)
            self.name.setToolTip(f"{name}  \u00b7  in {' / '.join(self.tag.parts)}")
        lay.addStretch(1)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def _need(self) -> int:
        return self.name.sizeHint().width() + (self.GAP + self.tag.sizeHint().width() if self.tag else 0)

    def sizeHint(self):
        return QSize(self._need(), max(self.name.sizeHint().height(), 22))

    def minimumSizeHint(self):
        return QSize(self.name.minimumSizeHint().width(), max(self.name.sizeHint().height(), 22))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.tag is not None:
            self.tag.setVisible(self.width() >= self._need())


class DropOverlay(QWidget):
    """Covers a page while files are dragged over it: a tinted panel with a moving dashed border that fades in, says
    what would happen on release, and fades out on leave or drop. accepts(paths) -> (usable, refused) decides; a drop with anything usable
    emits every dropped path, so the receiver can name what it skipped."""

    dropped = Signal(list)

    def __init__(self, parent, accepts):
        super().__init__(parent)
        self._accepts = accepts
        self._usable, self._refused = [], []
        self._dash = 0.0
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(0.0)
        self.setGraphicsEffect(self._fx)
        self._fade = QPropertyAnimation(self._fx, b"opacity", self)
        self._fade.setDuration(160)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self._faded)
        self._march = QTimer(self)
        self._march.setInterval(40)
        self._march.timeout.connect(self._step)
        self.hide()

    # -------------------------------------------------------------- showing
    def begin(self, paths: list[Path]) -> bool:
        """A drag entered the page: show what it would do. False when nothing in it is a file or folder."""
        if not paths:
            return False
        self._usable, self._refused = self._accepts(paths)
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self._fade_to(1.0)
        self._march.start()
        self.update()
        return True

    def end(self):
        self._march.stop()
        self._fade_to(0.0)

    def _fade_to(self, value: float):
        self._fade.stop()
        self._fade.setStartValue(self._fx.opacity())
        self._fade.setEndValue(value)
        self._fade.start()

    def _faded(self):
        if self._fx.opacity() <= 0.01:
            self.hide()

    def _step(self):
        self._dash = (self._dash + 1.0) % 16
        self.update()

    # -------------------------------------------------------------- drag events once it is on top
    @staticmethod
    def paths_of(event) -> list[Path]:
        md = event.mimeData()
        return [Path(u.toLocalFile()) for u in md.urls() if u.isLocalFile()] if md.hasUrls() else []

    def dragEnterEvent(self, e):
        e.acceptProposedAction() if self._usable else e.ignore()

    def dragMoveEvent(self, e):
        e.acceptProposedAction() if self._usable else e.ignore()

    def dragLeaveEvent(self, e):
        self.end()

    def dropEvent(self, e):
        usable, refused = list(self._usable), list(self._refused)
        self.end()
        if usable:
            e.acceptProposedAction()
            self.dropped.emit(usable + refused)  # the receiver says what it skipped
        else:
            e.ignore()

    # -------------------------------------------------------------- drawing
    def paintEvent(self, e):
        t = tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        ok = bool(self._usable)
        edge = QColor(t["accent"] if ok else t["danger"])
        fill = QColor(t["hero_b"] if isinstance(t["hero_b"], QColor) else QColor(t["hero_b"]))
        fill.setAlpha(215)
        r = QRectF(self.rect()).adjusted(12, 12, -12, -12)
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(r, RADIUS_HERO, RADIUS_HERO)
        pen = QPen(edge, 2, Qt.DashLine)
        pen.setDashOffset(-self._dash)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(4, 4, -4, -4), RADIUS_HERO, RADIUS_HERO)
        icon = QRectF(r.center().x() - 20, r.center().y() - 64, 40, 40)
        (FI.DOWNLOAD if ok else FI.CANCEL).render(p, icon, fill=edge.name())
        n = len(self._usable)
        title = (f"Drop to install {n} mods" if n > 1 else "Drop to install") if ok else "Nothing here can be installed"
        sub = (
            "An archive, a DLL or a mod folder. You check each one before it goes in."
            if ok
            else "Mods come as a .zip, .7z or .rar archive, a .dll, or a folder."
        )
        if ok and self._refused:
            sub = f"{', '.join(x.name for x in self._refused[:3])} {'is' if len(self._refused) == 1 else 'are'} skipped: not an archive, DLL or folder."
        p.setPen(QColor(t["ghost_fg"]))
        f = getFont(20, QFont.DemiBold)
        p.setFont(f)
        p.drawText(QRectF(r.left(), r.center().y() - 12, r.width(), 32), Qt.AlignHCenter | Qt.AlignVCenter, title)
        p.setFont(getFont(13))
        p.setPen(QColor(t["muted"]))
        p.drawText(
            QRectF(r.left() + 24, r.center().y() + 24, r.width() - 48, 44),
            Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
            sub,
        )
