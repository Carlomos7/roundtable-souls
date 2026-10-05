"""The switcher button and the pick-one menus, in the launcher's colours."""

from __future__ import annotations

from PySide6.QtCore import (
    QPoint,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
)
from PySide6.QtWidgets import (
    QStyle,
    QStyledItemDelegate,
)
from qfluentwidgets import (
    DropDownPushButton,
    MenuAnimationType,
    RoundMenu,
    getFont,
)
from qfluentwidgets import FluentIcon as FI

from roundtable_souls.ui.theme import (
    RADIUS,
    RADIUS_BTN,
    css,
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
            painter.setBrush(QColor(t["ghost_hv"] if hover else t["selected"]))
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


def style_menu(menu: RoundMenu) -> RoundMenu:
    """A plain menu (icon and text rows) on the same panel as StatusMenu, with the theme's text and hover."""
    t = tokens()
    menu.view.setStyleSheet(
        f"MenuActionListWidget{{background:{t['editor'].name()};border:1px solid {t['ghost_bd']};"
        f"border-radius:{RADIUS}px;outline:none;}}"
        f"MenuActionListWidget::item{{color:{css(t['ghost_fg'])};}}"
        f"MenuActionListWidget::item:hover,MenuActionListWidget::item:selected"
        f"{{background:{css(t['ghost_hv'])};color:{css(t['ghost_fg'])};}}"
    )
    return menu


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
