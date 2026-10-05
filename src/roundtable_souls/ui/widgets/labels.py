"""Labels that give way in narrow rows: a path tag, an eliding label, a name with its tag."""

from __future__ import annotations

from PySide6.QtCore import (
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    getFont,
)

from roundtable_souls.ui.theme import (
    tokens,
    tone_label,
)


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
