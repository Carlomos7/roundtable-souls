"""Colours, radii and the widget styles the window shares."""

from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPalette, QPen
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QPushButton as QPushBtn
from qfluentwidgets import CaptionLabel, PushButton, isDarkTheme

# Dark: Lands Between strip (#040200 #27170D #653815 #BD6707 #F9C043).
# Light: Snow Witch. Snow-white cards on an icy page, a frost-blue rail, Carian-blue actions, one moonlit hero.
# Amber is reserved for warnings in light; it is never decoration.
ACCENT = "#F9C043"
ACCENT_LIGHT = "#245BC4"
HINT = "#C4A06A"
HINT_ON_LIGHT = "#4B6283"
TEXT_LIGHT = "#20324E"
RADIUS = 8
RADIUS_HERO = 12
RADIUS_BTN = 6
BG_DARK = "#040200"
BG_LIGHT = "#EEF4FC"
COMPACT = 880


def tokens():
    """Live colors. Both themes define the same roles; only the values differ. Dark is the gold-and-earth strip,
    light is frost and Carian blue. Accent is only the action."""
    return tokens_dark() if isDarkTheme() else tokens_light()


def _tint(hex_color: str, alpha: int) -> QColor:
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c


def tokens_dark():
    return {
        "text": "#E8D2A0",
        "surf": QColor(39, 23, 13),
        "border": QColor(101, 56, 21),
        "line": QColor(101, 56, 21),
        "hero_a": QColor(58, 34, 16),
        "hero_b": QColor(4, 2, 0),
        "hero_border": QColor(101, 56, 21),
        "hero_glow": _tint("#F9C043", 40),
        "accent": "#F9C043",
        "accent_hover": "#FFD35A",
        "accent_press": "#BD6707",
        "on_accent": "#040200",
        "ghost": "#27170D",
        "ghost_fg": "#E8D2A0",
        "ghost_bd": "#653815",
        "ghost_hv": "#3A2210",
        "selected": "#27170D",
        "sidebar_bg": QColor(BG_DARK),
        "sidebar_hover": QColor("#1A100A"),
        "sidebar_selected": QColor("#27170D"),
        "sidebar_selected_fg": QColor("#F9C043"),
        "dialog_body": "#27170D",
        "dialog_border": "#653815",
        "dialog_footer": "#1A100A",
        "accent_off": "transparent",
        "accent_off_fg": "#A88860",
        "accent_off_bd": "#653815",
        "pending": QColor(58, 32, 12),
        "pending_border": QColor(189, 103, 7),
        "editor": QColor("#1A100A"),
        "editor_fg": "#E8D2A0",
        "drop_surf": QColor(BG_DARK),
        "focus": "#F9C043",
        "focus_on_accent": "#E8D2A0",
        "focus_inner": "#040200",
        "success_fg": "#7CC89A",
        "success_bg": _tint("#7CC89A", 38),
        "warning_fg": "#F9C043",
        "warning_bg": _tint("#F9C043", 38),
        "danger": "#E08A7A",
        "danger_bg": _tint("#E08A7A", 38),
        "busy_bg": _tint("#F9C043", 38),
        "muted_bg": _tint(HINT, 38),
        "pill_edge": 255,
        "muted": HINT,
        "shadow": QColor(0, 0, 0, 110),
    }


def tokens_light():
    return {
        "text": TEXT_LIGHT,
        "surf": QColor("#FFFFFF"),
        "border": QColor("#BECFE5"),
        "line": QColor("#D5E1F0"),
        "hero_a": QColor("#A9CEF7"),
        "hero_b": QColor("#F7FAFF"),
        "hero_border": QColor("#83ADE0"),
        "hero_glow": _tint("#63B5F5", 40),
        "accent": "#245BC4",
        "accent_hover": "#194BAA",
        "accent_press": "#153A80",
        "on_accent": "#FFFFFF",
        "ghost": "#E7EFFA",
        "ghost_fg": TEXT_LIGHT,
        "ghost_bd": "#BECFE5",
        "ghost_hv": "#DAE6F6",
        "selected": "#D5E7FF",
        "sidebar_bg": QColor("#E1ECFA"),
        "sidebar_hover": QColor("#D5E5F8"),
        "sidebar_selected": QColor("#C9DFFF"),
        "sidebar_selected_fg": QColor("#194BAA"),
        "dialog_body": "#FFFFFF",
        "dialog_border": "#BECFE5",
        "dialog_footer": "#EAF1FB",
        "accent_off": "transparent",
        "accent_off_fg": "#6F84A3",
        "accent_off_bd": "#BECFE5",
        "pending": QColor("#EEF4FC"),
        "pending_border": QColor("#245BC4"),
        "editor": QColor("#F7FAFF"),
        "editor_fg": TEXT_LIGHT,
        "drop_surf": QColor("#F7FAFF"),
        "focus": "#245BC4",
        "focus_on_accent": "#153A80",
        "focus_inner": "#FFFFFF",
        "success_fg": "#2E7D4F",
        "success_bg": QColor("#EBF6EE"),  # #E8F4EC left the 12px pill type at 4.46:1, under AA
        "warning_fg": "#8A560A",
        "warning_bg": QColor("#FFF3D9"),
        "danger": "#963C48",
        "danger_bg": QColor("#FBECEF"),
        "busy_bg": QColor("#E7EFFA"),
        "muted_bg": QColor("#E7EFFA"),
        "pill_edge": 90,
        "muted": HINT_ON_LIGHT,
        "shadow": QColor(41, 76, 122, 20),
    }


# Only a bare `color:` declaration whose value is opaque black. The look-behind skips background-color, border-color,
# selection-color and qproperty-*Color; rgba() blacks (Fluent's pressed and disabled text) are not matched.
_BLACK_TEXT = re.compile(
    r"(?<![-\w])color\s*:\s*(?:black|rgb\(\s*0\s*,\s*0\s*,\s*0\s*\)|#000000|#ff000000)(?=\s*[;}])", re.IGNORECASE
)


def use_theme_text() -> None:
    """Fluent's light style sheets (labels, cards, dialogs, menus, inputs) hardcode black text, and Fluent has no
    supported setting for it. Render them with TEXT_LIGHT instead, in one place, for every Fluent widget. Dark style
    sheets are left as the library ships them.

    Relies on qfluentwidgets.common.style_sheet.renderQss being the module global that every sheet is rendered
    through (PySide6-Fluent-Widgets 1.11.3). If a release renames it, this does nothing and light text is black."""
    from qfluentwidgets.common import style_sheet

    base = style_sheet.renderQss
    if getattr(base, "theme_text", False):
        return

    def render(qss: str) -> str:
        out = base(qss)
        return out if isDarkTheme() else _BLACK_TEXT.sub(f"color: {TEXT_LIGHT}", out)

    render.theme_text = True  # pyright: ignore[reportFunctionMemberAccess]  (marks the hook as installed)
    style_sheet.renderQss = render


def hint(text=""):
    l = CaptionLabel(text)
    l.setWordWrap(True)
    l.setTextColor(HINT_ON_LIGHT, HINT)
    return l


def css(color) -> str:
    """A token as a style sheet colour; translucent QColors keep their alpha."""
    if isinstance(color, QColor):
        return (
            color.name()
            if color.alpha() == 255
            else f"rgba({color.red()},{color.green()},{color.blue()},{color.alpha()})"
        )
    return str(color)


# tone_label level -> token. "warn" is a finding flagged for attention: the warning colour in light, and the danger
# colour in dark, where the warning colour is the accent gold.
_TONES = {
    "error": ("danger", "danger"),
    "warn": ("warning_fg", "danger"),
    "warning": ("warning_fg", "warning_fg"),
    "accent": ("accent", "accent"),
    "busy": ("accent", "accent"),
    "success": ("success_fg", "success_fg"),
    "muted": ("muted", "muted"),
}


def tone_label(lab, level="muted"):
    """Quiet status type. Colour backs up the words, never replaces them: error, warning (and a finding's "warn"),
    success, busy or accent (something changed), otherwise muted."""
    light, dark = _TONES.get(level, _TONES["muted"])
    lab.setTextColor(tokens_light()[light], tokens_dark()[dark])


# Every button in a row shares one height, radius and type size, so a primary next to a secondary never looks off.
# Only the Play button is larger (hero=True).
BTN_H = 36
BTN_MIN_W = 96
BTN_FONT = 14


class _InnerFocusRing(QObject):
    """A second, inner focus ring for solid accent buttons, which a style sheet border alone cannot draw: the sheet
    paints the outer edge (focus_on_accent), this paints focus_inner (the on-accent colour) just inside it."""

    def eventFilter(self, obj, e):
        if e.type() != QEvent.Paint or not obj.hasFocus() or not obj.isEnabled():
            return False
        type(obj).paintEvent(obj, e)
        p = QPainter(obj)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(tokens()["focus_inner"]), 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(obj.rect()).adjusted(2.75, 2.75, -2.75, -2.75), RADIUS_BTN - 2, RADIUS_BTN - 2)
        p.end()
        return True


_FOCUS_RING = None


def _inner_focus_ring(btn):
    global _FOCUS_RING
    if _FOCUS_RING is None:
        _FOCUS_RING = _InnerFocusRing(QApplication.instance())
    if not btn.property("innerRing"):
        btn.setProperty("innerRing", True)
        btn.installEventFilter(_FOCUS_RING)


def _focus_padding(pad: int, icon_pad: int) -> str:
    """Focus borders are 2px against a 1px resting border: take the extra pixel out of the padding so the type and
    icon do not move when focus arrives."""
    return (
        f"QPushButton:focus{{padding:0 {pad - 1}px;}}QPushButton[hasIcon=true]:focus{{padding-left:{icon_pad - 1}px;}}"
    )


def style_primary(btn):
    """Solid accent CTA (gold in dark, Carian blue in light). Own stylesheet so Fluent cannot wash it into a pale
    pill. Focus: an outer edge in focus_on_accent with a ring in the on-accent colour inside it."""
    t = tokens()
    hero = bool(btn.property("hero"))
    pad = 28 if hero else 18
    btn.setAttribute(Qt.WA_StyledBackground, True)
    btn.setFlat(True)
    if not hero:
        btn.setMinimumHeight(BTN_H)
        btn.setMinimumWidth(max(BTN_MIN_W, btn.minimumWidth()))
    btn.setStyleSheet(
        f"QPushButton{{background:{t['accent']};color:{t['on_accent']};border:1px solid {t['accent_press']};"
        f"border-radius:{RADIUS_BTN}px;padding:0 {pad}px;"
        f"font-size:{15 if hero else BTN_FONT}px;font-weight:600;}}"
        "QPushButton[hasIcon=true]{padding-left:36px;}"
        f"QPushButton:hover{{background:{t['accent_hover']};}}"
        f"QPushButton:pressed{{background:{t['accent_press']};}}"
        f"QPushButton:focus{{border:2px solid {t['focus_on_accent']};}}"
        + _focus_padding(pad, 36)
        + f"QPushButton:disabled{{background:{t['accent_off']};color:{t['accent_off_fg']};"
        f"border:1px solid {t['accent_off_bd']};}}"
    )
    _inner_focus_ring(btn)
    return btn


def style_ghost(btn, fg=None, hover=None):
    """Quiet secondary. Extra left padding when Fluent paints an icon, so type does not sit under it. fg and hover
    recolour the type and hover fill (a destructive secondary). Disabled: no fill, so it never looks hovered."""
    t = tokens()
    btn.setAttribute(Qt.WA_StyledBackground, True)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setMinimumHeight(BTN_H)
    if btn.property("hasIcon"):
        btn.setMinimumWidth(max(104, btn.minimumWidth()))
    btn.setStyleSheet(
        f"QPushButton{{background:{t['ghost']};color:{css(fg or t['ghost_fg'])};border:1px solid {t['ghost_bd']};"
        f"border-radius:{RADIUS_BTN}px;padding:0 14px;font-size:{BTN_FONT}px;}}"
        "QPushButton[hasIcon=true]{padding-left:36px;}"
        f"QPushButton:hover{{background:{css(hover or t['ghost_hv'])};}}"
        f"QPushButton:focus{{border:2px solid {t['focus']};}}"
        + _focus_padding(14, 36)
        + f"QPushButton:disabled{{background:{t['accent_off']};color:{t['accent_off_fg']};"
        f"border:1px solid {t['accent_off_bd']};}}"
    )
    btn.setStyle(QApplication.style())
    return btn


def style_button(btn):
    """Restyle a button for the current theme from its role. "action": a page's main action, solid in the accent.
    "danger": a destructive secondary, type and icon in the danger colour. Anything else: primary for the CTA,
    secondary otherwise."""
    t = tokens()
    role = btn.property("role")
    icon = getattr(btn, "_theme_icon", None)
    if role == "action":
        style_primary(btn)
        if icon is not None:
            btn.setIcon(icon.icon(color=QColor(t["on_accent"])))
    elif role == "danger":
        style_ghost(btn, fg=t["danger"], hover=t["danger_bg"])
        if icon is not None:
            btn.setIcon(icon.icon(color=QColor(t["danger"])))
    elif btn.objectName() == "cta":
        style_primary(btn)
    else:
        style_ghost(btn)
    return btn


def primary_btn(text, hero=False):
    b = QPushBtn(text)
    b.setObjectName("cta")
    b.setProperty("hero", hero)
    b.setCursor(Qt.PointingHandCursor)
    return style_primary(b)


def ghost_btn(text, icon=None, role=None):
    """A secondary button. role "action" or "danger": see style_button."""
    b = PushButton(icon, text) if icon is not None else PushButton(text)
    if role is None:
        return style_ghost(b)
    b.setProperty("role", role)
    b._theme_icon = icon
    return style_button(b)


def style_dialog(dlg):
    """The dialog's panel in the card colours and its button strip in dialog_footer with a soft divider, in place of
    Fluent's greys. Order and behaviour of the buttons are untouched."""
    t = tokens()
    dlg.widget.setStyleSheet(
        f"#centerWidget{{background:{t['dialog_body']};border:1px solid {t['dialog_border']};border-radius:10px;}}"
    )
    dlg.buttonGroup.setStyleSheet(
        f"#buttonGroup{{background:{t['dialog_footer']};border-top:1px solid {css(t['line'])};border-left:none;"
        "border-right:none;border-bottom:none;border-bottom-left-radius:8px;border-bottom-right-radius:8px;}"
    )


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
