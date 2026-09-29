"""Colours, radii and the widget styles the window shares."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QPushButton as QPushBtn
from qfluentwidgets import CaptionLabel, PushButton, isDarkTheme

# Dark: Lands Between strip (#040200 #27170D #653815 #BD6707 #F9C043).
# Light: mid ice paper, deep sea accent (#075C8B).
ACCENT = "#F9C043"
ACCENT_LIGHT = "#075C8B"
HINT = "#C4A06A"
HINT_ON_LIGHT = "#385D70"
RADIUS = 8
RADIUS_HERO = 12
RADIUS_BTN = 6
BG_DARK = "#040200"
BG_LIGHT = "#AFCCD9"
COMPACT = 880


def tokens():
    """Live colors. Dark is the gold strip. Light is frost paper and sea blue. Accent is only the action."""
    if isDarkTheme():
        return {
            "surf": QColor(39, 23, 13),
            "border": QColor(101, 56, 21),
            "line": QColor(101, 56, 21),
            "hero_a": QColor(58, 34, 16),
            "hero_b": QColor(4, 2, 0),
            "hero_border": QColor(101, 56, 21),
            "glow": QColor(249, 192, 67, 48),
            "accent": "#F9C043",
            "accent_hover": "#FFD35A",
            "accent_press": "#BD6707",
            "on_accent": "#040200",
            "ghost": "#27170D",
            "ghost_fg": "#E8D2A0",
            "ghost_bd": "#653815",
            "ghost_hv": "#3A2210",
            "accent_off": "transparent",
            "accent_off_fg": "#A88860",
            "accent_off_bd": "#653815",
            "pending": QColor(58, 32, 12),
            "pending_border": QColor(189, 103, 7),
            "editor": QColor("#1A100A"),
            "editor_fg": "#E8D2A0",
            "danger": "#E08A7A",
            "muted": HINT,
        }
    return {
        "surf": QColor("#C7E0EB"),
        "border": QColor("#6496AD"),
        "line": QColor("#82AEBF"),
        "hero_a": QColor("#58A4C9"),
        "hero_b": QColor("#AFCCD9"),
        "hero_border": QColor("#397E9F"),
        "glow": QColor(20, 143, 203, 115),
        "accent": "#075C8B",
        "accent_hover": "#074B73",
        "accent_press": "#063B5B",
        "on_accent": "#FFFFFF",
        "ghost": "#94C4DA",
        "ghost_fg": "#153F58",
        "ghost_bd": "#4B8CAC",
        "ghost_hv": "#7AB7D2",
        "accent_off": "transparent",
        "accent_off_fg": "#42677B",
        "accent_off_bd": "#6496AD",
        "pending": QColor("#A7C7D2"),
        "pending_border": QColor("#397E9F"),
        "editor": QColor("#D6EAF2"),
        "editor_fg": "#142F40",
        "danger": "#963C48",
        "muted": HINT_ON_LIGHT,
    }


def hint(text=""):
    l = CaptionLabel(text)
    l.setWordWrap(True)
    l.setTextColor(HINT_ON_LIGHT, HINT)
    return l


# Every button in a row shares one height, radius and type size, so a primary next to a secondary never looks off.
# Only the Play button is larger (hero=True).
BTN_H = 36
BTN_MIN_W = 96
BTN_FONT = 14


def style_primary(btn):
    """Solid gold CTA. Own stylesheet so Fluent cannot wash it into a pale pill."""
    t = tokens()
    hero = bool(btn.property("hero"))
    btn.setAttribute(Qt.WA_StyledBackground, True)
    btn.setFlat(True)
    if not hero:
        btn.setMinimumHeight(BTN_H)
        btn.setMinimumWidth(max(BTN_MIN_W, btn.minimumWidth()))
    btn.setStyleSheet(
        f"QPushButton{{background:{t['accent']};color:{t['on_accent']};border:1px solid {t['accent_press']};"
        f"border-radius:{RADIUS_BTN}px;padding:0 {28 if hero else 18}px;"
        f"font-size:{15 if hero else BTN_FONT}px;font-weight:600;}}"
        f"QPushButton:hover{{background:{t['accent_hover']};}}"
        f"QPushButton:pressed{{background:{t['accent_press']};}}"
        f"QPushButton:focus{{border:2px solid {t['ghost_fg']};}}"
        f"QPushButton:disabled{{background:{t['accent_off']};color:{t['accent_off_fg']};border:1px solid {t['accent_off_bd']};}}"
    )
    return btn


def style_ghost(btn):
    """Quiet secondary. Extra left padding when Fluent paints an icon, so type does not sit under it."""
    t = tokens()
    btn.setAttribute(Qt.WA_StyledBackground, True)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setMinimumHeight(BTN_H)
    if btn.property("hasIcon"):
        btn.setMinimumWidth(max(104, btn.minimumWidth()))
    btn.setStyleSheet(
        f"QPushButton{{background:{t['ghost']};color:{t['ghost_fg']};border:1px solid {t['ghost_bd']};"
        f"border-radius:{RADIUS_BTN}px;padding:0 14px;font-size:{BTN_FONT}px;}}"
        f"QPushButton[hasIcon=true]{{padding-left:36px;}}"
        f"QPushButton:hover{{background:{t['ghost_hv']};}}"
        f"QPushButton:focus{{border:2px solid {t['accent']};}}"
        f"QPushButton:disabled{{color:{t['accent_off_fg']};border:1px solid {t['accent_off_bd']};}}"
    )
    btn.setStyle(QApplication.style())
    return btn


def primary_btn(text, hero=False):
    b = QPushBtn(text)
    b.setObjectName("cta")
    b.setProperty("hero", hero)
    b.setCursor(Qt.PointingHandCursor)
    return style_primary(b)


def ghost_btn(text, icon=None):
    b = PushButton(icon, text) if icon is not None else PushButton(text)
    return style_ghost(b)


def editor_font():
    families = set(QFontDatabase.families())
    for name in ("Cascadia Code", "Cascadia Mono", "JetBrains Mono", "Consolas", "Courier New"):
        if name in families:
            f = QFont(name, 11)
            f.setStyleHint(QFont.Monospace)
            return f
    f = QFont("Consolas", 11)
    f.setStyleHint(QFont.Monospace)
    return f


def style_editor(edit):
    """A code well. Same radius and hairline as the cards, monospace, theme colours."""
    t = tokens()
    bg = t["editor"].name() if isinstance(t["editor"], QColor) else t["editor"]
    edit.setFont(editor_font())
    edit.setStyleSheet(
        f"TextEdit,PlainTextEdit,QTextEdit,QPlainTextEdit{{background:{bg};color:{t['editor_fg']};"
        f"border:1px solid {t['border'].name()};border-radius:{RADIUS}px;padding:10px 12px;"
        f"selection-background-color:{t['accent']};selection-color:{t['on_accent']};}}"
    )
    pal = edit.palette()
    pal.setColor(QPalette.ColorRole.Base, t["editor"] if isinstance(t["editor"], QColor) else QColor(t["editor"]))
    pal.setColor(QPalette.ColorRole.Text, QColor(t["editor_fg"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(t["accent"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(t["on_accent"]))
    edit.setPalette(pal)
    hl = getattr(edit, "_hl", None)
    if hl:
        hl.restyle()
    bar = getattr(edit, "find_bar", None)
    if bar:
        bar.restyle()
    return edit
