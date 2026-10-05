"""Page grounds and layout helpers: the navigation rows' paint, a page, its header, rows of actions that wrap, and clearing a layout."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import (
    QEvent,
    QPoint,
    QRect,
    QRectF,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    FlowLayout,
    NavigationPushButton,
    ScrollArea,
    TitleLabel,
)
from qfluentwidgets.common.icon import FluentIconBase, drawIcon

from roundtable_souls.ui.theme import (
    RADIUS,
    RADIUS_HERO,
    hint,
    tokens,
)
from roundtable_souls.ui.widgets.cards import ExpandGroupSettingCard, GlassCard
from roundtable_souls.ui.widgets.hero import HeroBanner


def _paint_nav_row(w, e):
    """A navigation row, the same in both themes: sidebar_hover and sidebar_selected fills, the selected row's type
    and icon in sidebar_selected_fg (semibold) with the 3px accent bar, a 2px focus ring for the keyboard.
    Geometry (icon at 11.5 px, text at 44 px, 36 px rows) is Fluent's (PySide6-Fluent-Widgets 1.11.3)."""
    t = tokens()
    p = QPainter(w)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
    p.setPen(Qt.NoPen)
    if not w.isEnabled():
        p.setOpacity(0.4)
    elif w.isPressed:
        p.setOpacity(0.8)
    m = w._margins()
    pl, pr = m.left(), m.right()
    selected = w._canDrawIndicator()
    lit = selected or w.isAboutSelected
    hover = w.isEnabled() and w.isEnter and QRect(w.mapToGlobal(QPoint()), w.size()).contains(QCursor.pos())
    if lit or hover:
        p.setBrush(t["sidebar_selected"] if lit else t["sidebar_hover"])
        p.drawRoundedRect(QRectF(w.rect()), 5, 5)
    if selected:
        p.setBrush(QColor(t["accent"]))
        p.drawRoundedRect(w.indicatorRect(), 1.5, 1.5)
    fg = t["sidebar_selected_fg"] if lit else QColor(t["text"])
    icon_rect = QRectF(11.5 + pl, 10, 16, 16)
    if isinstance(w._icon, FluentIconBase):
        w._icon.render(p, icon_rect, fill=fg.name())
    else:
        drawIcon(w._icon, p, icon_rect)
    if not w.isCompacted:
        f = QFont(w.font())
        if lit:
            f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(fg)
        left = 44 + pl if not w.icon().isNull() else pl + 16
        p.drawText(QRectF(left, 0, w.width() - 13 - left - pr, w.height()), Qt.AlignVCenter, w.text())
    if w.hasFocus():
        p.setOpacity(1)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(t["focus"]), 2))
        p.drawRoundedRect(QRectF(w.rect()).adjusted(1, 1, -1, -1), 5, 5)


def _nav_key(w, fluent_key, e):
    if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
        w.click()
        return
    fluent_key(e)


def style_navigation(nav):
    """Give the window's navigation rows the launcher's paint and make them reachable with Tab (Enter or Space
    opens the page). Only the navigation's own rows: other lists keep Fluent's look."""
    for w in nav.findChildren(NavigationPushButton):
        if getattr(w, "_launcher_paint", False):
            continue
        w._launcher_paint = True
        w.paintEvent = partial(_paint_nav_row, w)
        w.keyPressEvent = partial(_nav_key, w, w.keyPressEvent)
        w.setFocusPolicy(Qt.TabFocus)


class _Surface(QWidget):
    """A page's ground. It paints a soft shadow (the theme's shadow colour) under its top-level cards (the hero,
    standalone cards and expanders), so they lift off the page without another outline. Painted here rather than with a
    QGraphicsDropShadowEffect: an effect re-renders the whole card, children included, on every update (the hero's
    progress ring, typing in a card) and clips at the card's edge."""

    BLUR = 16
    OFFSET = 3
    STEPS = 8

    def __init__(self):
        super().__init__()
        self._watched = set()

    def _elevated(self):
        kinds = (HeroBanner, GlassCard, ExpandGroupSettingCard)
        for kind in kinds:
            for w in self.findChildren(kind):
                if not getattr(w, "elevated", True) or not w.isVisibleTo(self):
                    continue
                up, nested = w.parentWidget(), False
                while up is not None and up is not self:
                    if isinstance(up, kinds):
                        nested = True
                        break
                    up = up.parentWidget()
                if not nested:
                    yield w

    def eventFilter(self, obj, e):
        if e.type() in (QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.Hide):
            self.update()
        return False

    def paintEvent(self, e):
        shadow = tokens()["shadow"]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        layer = QColor(shadow)
        layer.setAlphaF(shadow.alphaF() / self.STEPS)
        p.setBrush(layer)
        area = QRectF(e.rect())
        for w in self._elevated():
            if id(w) not in self._watched:
                self._watched.add(id(w))
                w.installEventFilter(self)
                w.destroyed.connect(lambda _=None, k=id(w): self._watched.discard(k))
            r = QRectF(w.geometry() if w.parentWidget() is self else QRect(w.mapTo(self, QPoint()), w.size()))
            r = r.adjusted(1, 1, -1, -1).translated(0, self.OFFSET)
            radius = RADIUS_HERO if isinstance(w, HeroBanner) else RADIUS
            if not area.intersects(r.adjusted(-self.BLUR, -self.BLUR, self.BLUR, self.BLUR)):
                continue
            for i in range(self.STEPS):
                grow = self.BLUR / 2 * (i + 1) / self.STEPS
                p.drawRoundedRect(r.adjusted(-grow, -grow, grow, grow), radius + grow, radius + grow)


def refresh_surfaces(root):
    """Repaint every page ground under root (their card shadows follow the theme)."""
    for s in root.findChildren(_Surface):
        s.update()


def page(name: str):
    """A scrollable page with a vertical layout and generous padding."""
    area = ScrollArea()
    area.setObjectName(name)
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # content reflows; a page never scrolls sideways
    area.setStyleSheet("QScrollArea{background:transparent;border:none}")
    inner = _Surface()
    inner.setObjectName(name + "Inner")
    inner.setStyleSheet("QWidget#" + name + "Inner{background:transparent}")
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(40, 28, 40, 36)
    lay.setSpacing(20)
    lay.setAlignment(Qt.AlignTop)
    area.setWidget(inner)
    area.viewport().setStyleSheet("background:transparent")
    return area, lay


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
