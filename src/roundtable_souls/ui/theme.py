"""Colours, radii and the widget styles the window shares."""

from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPalette, QPen
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QPushButton as QPushBtn
from qfluentwidgets import CaptionLabel, PushButton, isDarkTheme

from roundtable_souls.ui import theme_tokens

# The colours come from theme_tokens, generated from scripts/theme/tokens.json (edit that, never the colours here).
# Dark: near-neutral charcoal, the gold accent the only colour. Light: Snow Witch, Carian-blue actions.
# Colour strings are #RRGGBB, or #AARRGGBB when translucent; QColor, style sheets and rich text all read both.
ACCENT = str(theme_tokens.DARK["accent"])
ACCENT_LIGHT = str(theme_tokens.LIGHT["accent"])
HINT = str(theme_tokens.DARK["textSecondary"])
HINT_ON_LIGHT = str(theme_tokens.LIGHT["textSecondary"])
TEXT_LIGHT = str(theme_tokens.LIGHT["textPrimary"])
RADIUS = 8
RADIUS_HERO = 12
RADIUS_BTN = 6
BG_DARK = str(theme_tokens.DARK["surfaceBar"])
BG_LIGHT = str(theme_tokens.LIGHT["surfaceBar"])
COMPACT = 880


def roles(dark: bool | None = None) -> dict[str, str]:
    """The theme's colour roles by their token names (accent, textSecondary, statusDanger ...), as colour strings.
    dark None follows the current theme."""
    table = theme_tokens.DARK if (isDarkTheme() if dark is None else dark) else theme_tokens.LIGHT
    return {name: value for name, value in table.items() if isinstance(value, str)}


def tokens():
    """Live colors under the Widgets views' older keys. Both themes define the same keys; only the values differ.
    Accent is only the action."""
    return tokens_dark() if isDarkTheme() else tokens_light()


# The keys the views paint with as QColor (QPainter brushes and pens, .name()); the rest are style-sheet strings.
_QCOLOR_KEYS = frozenset(
    {
        "surf",
        "border",
        "line",
        "hero_a",
        "hero_b",
        "hero_border",
        "hero_glow",
        "sidebar_bg",
        "sidebar_hover",
        "sidebar_selected",
        "sidebar_selected_fg",
        "pending",
        "pending_border",
        "editor",
        "drop_surf",
        "success_bg",
        "warning_bg",
        "danger_bg",
        "busy_bg",
        "muted_bg",
        "shadow",
    }
)


def _widget_tokens(theme: str, pill_edge: int) -> dict:
    t: dict = {k: QColor(v) if k in _QCOLOR_KEYS else v for k, v in theme_tokens.legacy_tokens(theme).items()}
    t["accent_off"] = "transparent"  # a disabled button has no fill
    t["pill_edge"] = pill_edge  # the alpha of a pill's resting edge
    return t


def tokens_dark():
    return _widget_tokens("dark", 255)


def tokens_light():
    return _widget_tokens("light", 90)


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


# tone_label level -> (light role, dark role). "warn" is a finding flagged for attention: the warning colour in
# light, and the danger colour in dark, where the warning colour sits next to the accent gold.
_TONES = {
    "error": ("statusDanger", "statusDanger"),
    "warn": ("statusWarning", "statusDanger"),
    "warning": ("statusWarning", "statusWarning"),
    "accent": ("accent", "accent"),
    "busy": ("accent", "accent"),
    "success": ("statusSuccess", "statusSuccess"),
    "muted": ("textSecondary", "textSecondary"),
}


def tone_label(lab, level="muted"):
    """Quiet status type. Colour backs up the words, never replaces them: error, warning (and a finding's "warn"),
    success, busy or accent (something changed), otherwise muted."""
    light, dark = _TONES.get(level, _TONES["muted"])
    lab.setTextColor(roles(dark=False)[light], roles(dark=True)[dark])


# The code editor's highlighting -> role, the same roles in every theme. Keywords take the success hue: the press
# shade of the accent is under 4.5:1 on the editor's ground in dark.
_SYNTAX = {
    "comment": "textSecondary",
    "key": "textPrimary",
    "string": "accent",
    "number": "statusDanger",
    "keyword": "statusSuccess",
    "header": "accent",
}


def syntax_colors() -> dict[str, str]:
    """The code editor's highlighting colours for the current theme."""
    r = roles()
    return {part: r[role] for part, role in _SYNTAX.items()}


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
        p.setPen(QPen(QColor(roles()["textOnAccent"]), 1.5))
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
    pill. Focus: a 2px edge in the on-accent colour with a ring in the same colour inside it."""
    r = roles()
    hero = bool(btn.property("hero"))
    pad = 28 if hero else 18
    btn.setAttribute(Qt.WA_StyledBackground, True)
    btn.setFlat(True)
    if not hero:
        btn.setMinimumHeight(BTN_H)
        btn.setMinimumWidth(max(BTN_MIN_W, btn.minimumWidth()))
    btn.setStyleSheet(
        f"QPushButton{{background:{r['accent']};color:{r['textOnAccent']};border:1px solid {r['accentPress']};"
        f"border-radius:{RADIUS_BTN}px;padding:0 {pad}px;"
        f"font-size:{15 if hero else BTN_FONT}px;font-weight:600;}}"
        "QPushButton[hasIcon=true]{padding-left:36px;}"
        f"QPushButton:hover{{background:{r['accentHover']};}}"
        f"QPushButton:pressed{{background:{r['accentPress']};}}"
        f"QPushButton:focus{{border:2px solid {r['textOnAccent']};}}"
        + _focus_padding(pad, 36)
        + f"QPushButton:disabled{{background:transparent;color:{r['textDisabled']};"
        f"border:1px solid {r['borderHairline']};}}"
    )
    _inner_focus_ring(btn)
    return btn


def style_ghost(btn, fg=None, hover=None):
    """Quiet secondary. Extra left padding when Fluent paints an icon, so type does not sit under it. fg and hover
    recolour the type and hover fill (a destructive secondary). Disabled: no fill, so it never looks hovered."""
    r = roles()
    btn.setAttribute(Qt.WA_StyledBackground, True)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setMinimumHeight(BTN_H)
    if btn.property("hasIcon"):
        btn.setMinimumWidth(max(104, btn.minimumWidth()))
    btn.setStyleSheet(
        f"QPushButton{{background:{r['fillGhost']};color:{css(fg or r['textPrimary'])};"
        f"border:1px solid {r['borderHairline']};"
        f"border-radius:{RADIUS_BTN}px;padding:0 14px;font-size:{BTN_FONT}px;}}"
        "QPushButton[hasIcon=true]{padding-left:36px;}"
        f"QPushButton:hover{{background:{css(hover or r['fillGhostHover'])};}}"
        f"QPushButton:focus{{border:2px solid {r['accent']};}}"
        + _focus_padding(14, 36)
        + f"QPushButton:disabled{{background:transparent;color:{r['textDisabled']};"
        f"border:1px solid {r['borderHairline']};}}"
    )
    btn.setStyle(QApplication.style())
    return btn


def style_button(btn):
    """Restyle a button for the current theme from its role. "action": a page's main action, solid in the accent.
    "danger": a destructive secondary, type and icon in the danger colour. Anything else: primary for the CTA,
    secondary otherwise."""
    r = roles()
    role = btn.property("role")
    icon = getattr(btn, "_theme_icon", None)
    if role == "action":
        style_primary(btn)
        if icon is not None:
            btn.setIcon(icon.icon(color=QColor(r["textOnAccent"])))
    elif role == "danger":
        style_ghost(btn, fg=r["statusDanger"], hover=r["statusDangerBg"])
        if icon is not None:
            btn.setIcon(icon.icon(color=QColor(r["statusDanger"])))
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
    """The dialog's panel in the card colours and its button strip in the input colour with a soft divider, in
    place of Fluent's greys. Order and behaviour of the buttons are untouched."""
    r = roles()
    dlg.widget.setStyleSheet(
        f"#centerWidget{{background:{r['surfaceCard']};border:1px solid {r['borderHairline']};border-radius:10px;}}"
    )
    dlg.buttonGroup.setStyleSheet(
        f"#buttonGroup{{background:{r['surfaceInput']};border-top:1px solid {r['borderHairline']};border-left:none;"
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
    r = roles()
    edit.setFont(editor_font())
    edit.setStyleSheet(
        f"TextEdit,PlainTextEdit,QTextEdit,QPlainTextEdit{{background:{r['surfaceInput']};color:{r['textPrimary']};"
        f"border:1px solid {r['borderEdge']};border-radius:{RADIUS}px;padding:10px 12px;"
        f"selection-background-color:{r['accent']};selection-color:{r['textOnAccent']};}}"
    )
    pal = edit.palette()
    pal.setColor(QPalette.ColorRole.Base, QColor(r["surfaceInput"]))
    pal.setColor(QPalette.ColorRole.Text, QColor(r["textPrimary"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(r["accent"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(r["textOnAccent"]))
    edit.setPalette(pal)
    hl = getattr(edit, "_hl", None)
    if hl:
        hl.restyle()
    bar = getattr(edit, "find_bar", None)
    if bar:
        bar.restyle()
    return edit
