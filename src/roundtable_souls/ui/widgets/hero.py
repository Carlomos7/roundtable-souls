"""The Play page's hero banner and its metrics."""

from __future__ import annotations

from PySide6.QtCore import (
    QPointF,
    QRectF,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    IndeterminateProgressRing,
    LargeTitleLabel,
    StrongBodyLabel,
)

from roundtable_souls.ui.theme import (
    RADIUS_HERO,
    hint,
    primary_btn,
    tokens,
    tone_label,
)


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


def _mix(a: QColor, b: QColor, k: float) -> QColor:
    """a blended k of the way toward b."""
    return QColor(
        round(a.red() + (b.red() - a.red()) * k),
        round(a.green() + (b.green() - a.green()) * k),
        round(a.blue() + (b.blue() - a.blue()) * k),
    )


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
        self._paint_ground(p, path, r, t)
        p.strokePath(path, QPen(t["hero_border"], 1))
        y = self.metrics.y() - 6
        if y > 20:
            p.setPen(QPen(t["line"], 1))
            p.drawLine(int(r.left()) + 20, y, int(r.right()) - 20, y)

    @staticmethod
    def _paint_ground(p, path, r, t):
        """The hero's ground, one geometry for both themes: the quiet colour (hero_b: snow, or the black of the page)
        over the left two-thirds where the name sits, the rich colour (hero_a: frost, or brown) gathering toward the
        right edge, and one faint bloom of hero_glow (moonlight, or gold) in the upper right. Static: no stars,
        particles or animation."""
        quiet, rich = QColor(t["hero_b"]), QColor(t["hero_a"])
        g = QLinearGradient(r.topLeft(), r.topRight())
        g.setColorAt(0.0, quiet)
        g.setColorAt(0.62, quiet)
        g.setColorAt(0.82, _mix(quiet, rich, 0.45))
        g.setColorAt(1.0, rich)
        p.fillPath(path, g)
        glow = QColor(t["hero_glow"])
        centre = QPointF(r.right() - r.width() * 0.12, r.top() + r.height() * 0.16)
        bloom = QRadialGradient(centre, max(r.height() * 0.95, r.width() * 0.26))
        bloom.setColorAt(0.0, glow)
        glow.setAlpha(0)
        bloom.setColorAt(1.0, glow)
        p.fillPath(path, bloom)
