"""Notices at the top of the window, the drop overlay and the status pill."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QSizePolicy,
    QWidget,
)
from qfluentwidgets import FluentIcon as FI
from qfluentwidgets import (
    InfoBar,
    InfoBarIcon,
    InfoBarPosition,
    getFont,
)

from roundtable_souls.ui.theme import (
    RADIUS_HERO,
    tokens,
)

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
        fill = QColor(t["drop_surf"])
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


# Pills: level -> (text token, fill token, mark). Green only means "all good"; red is something to act on. The words
# and the mark say it too, so colour is never the only signal.
PILL_LEVELS = {
    "ok": ("success_fg", "success_bg", "\u2713"),
    "bad": ("danger", "danger_bg", "\u2715"),
    "warn": ("warning_fg", "warning_bg", "\u26a0"),
    "busy": ("accent", "busy_bg", ""),
    "muted": ("muted", "muted_bg", ""),
}


class StatusPill(QWidget):
    """A small rounded status: a tinted fill and outline in its level's colour, and a word or two. Clickable (and
    reachable with Tab, Enter or Space) when something listens to clicked."""

    clicked = Signal()

    def __init__(self, text="", level="muted", parent=None):
        super().__init__(parent)
        self._text, self._level = text, level
        self._font = getFont(12, QFont.DemiBold)
        self.setFixedHeight(22)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.TabFocus)

    def set(self, text, level):
        self._text, self._level = text, level
        self.updateGeometry()
        self.update()

    def text(self):
        return self._text

    def level(self):
        return self._level

    def _shown(self):
        """The text as painted: warning, error and success lead with their mark."""
        mark = PILL_LEVELS.get(self._level, PILL_LEVELS["muted"])[2]
        return f"{mark}  {self._text}" if mark and self._text else self._text

    def sizeHint(self):
        return QSize(QFontMetrics(self._font).horizontalAdvance(self._shown()) + 22, 22)

    def minimumSizeHint(self):
        return self.sizeHint()

    def setClickable(self, on=True):
        self.setCursor(Qt.PointingHandCursor if on else Qt.ArrowCursor)
        self.setFocusPolicy(Qt.StrongFocus if on else Qt.NoFocus)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        t = tokens()
        fg, bg, _mark = PILL_LEVELS.get(self._level, PILL_LEVELS["muted"])
        color, fill = QColor(t[fg]), QColor(t[bg])
        soft = QColor(color)
        soft.setAlpha(t["pill_edge"])
        edge = QPen(QColor(t["focus"]), 2) if self.hasFocus() else QPen(soft, 1)
        if self.hasFocus():
            r = r.adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(edge)
        p.setBrush(fill)
        p.drawRoundedRect(r, 11, 11)
        p.setFont(self._font)
        p.setPen(color)
        p.drawText(r, Qt.AlignCenter, self._shown())
