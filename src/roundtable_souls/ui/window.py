"""The window (PySide6 + Fluent Widgets). All logic lives in core.py.

Pages (navigation rail on the left):
  Play    who you are (from the save), which setup, one big Play button, one line saying what will happen
  Co-op   Seamless Co-op password, difficulty, and a save bar that stays on screen
  Saves   the save files and the characters in them, read-only
  Tools   repair, cleanup, logs, theme

    roundtable-souls              the window
    roundtable-souls --check      print what would be used and exit (no window)
    roundtable-souls --shots D    render every page to PNG files in folder D, for review
"""
from __future__ import annotations

import datetime
import html
import os
import re
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QObject, QPointF, QRectF, QRegularExpression, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QRadialGradient,
    QShortcut,
    QSyntaxHighlighter,
    QTextCharFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QSizePolicy,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWidgets import QPushButton as QPushBtn
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    FlowLayout,
    FluentWindow,
    IconWidget,
    IndeterminateProgressRing,
    InfoBadge,
    InfoBadgePosition,
    InfoBar,
    InfoBarPosition,
    LargeTitleLabel,
    LineEdit,
    MessageBox,
    MessageBoxBase,
    NavigationItemPosition,
    PasswordLineEdit,
    PlainTextEdit,
    PushButton,
    ScrollArea,
    SearchLineEdit,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
    SwitchButton,
    TableWidget,
    TextEdit,
    Theme,
    TitleLabel,
    TransparentPushButton,
    TransparentToolButton,
    isDarkTheme,
    setTheme,
    setThemeColor,
)
from qfluentwidgets import ExpandGroupSettingCard as _ExpandGroupSettingCard
from qfluentwidgets import FluentIcon as FI

from roundtable_souls import core
from roundtable_souls.core import (
    COMMENT_PREFIX,
    CUSTOM,
    LOGS,
    PLAY_DEFAULTS,
    SAVE_KINDS,
    SCALING_KEYS,
    SCALING_LABELS,
    SCALING_PRESETS,
    TITLE,
    VERSION,
    VOLUME_STOPS,
    apply_overrides,
    character_detail,
    choice_label,
    convert_co2_to_sl2,
    create_profile,
    dead_shells_count,
    delete_backup,
    delete_profile,
    discover,
    export_text,
    fix_checksums,
    fix_loading,
    fix_quest_flags,
    health_report,
    indent_lines,
    install_mod,
    job_clear,
    job_play,
    job_play_offline,
    job_repair,
    label_of,
    list_backups,
    load_settings,
    logo_path,
    me3_facts,
    parse_settings_json,
    places,
    plan_import,
    plan_mod_install,
    preset_of,
    profile_entries,
    read_password,
    read_profile_mods,
    read_profile_settings,
    read_scaling,
    read_settings_meta,
    repair_available,
    repair_save,
    report_exception,
    restore_backup,
    restore_vanilla,
    route_logs,
    run_job,
    save_info,
    save_settings,
    save_summary,
    scan_profile_conflicts,
    set_mod_options,
    setting_face,
    setup_from_path,
    steam_state,
    toggle_comment,
    uninstall_mod,
    write_keys,
    write_password,
    write_profile_setting,
)
from roundtable_souls.resources import ASSETS_DIR


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

    def _paint_view(self):
        t = tokens()
        fill = t["surf"].name()
        self.view.setStyleSheet(f"QFrame#view{{background:{fill};border:none}}")
        self.scrollWidget.setStyleSheet("background:transparent;border:none")

    def _span(self):
        hinted = self.viewLayout.sizeHint().height()
        summed = sum(w.sizeHint().height() + 3 for w in self.widgets)
        return max(hinted, summed, 1)

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

    def _paint_header(self, e):
        w = self.card
        p = QPainter(w); p.setRenderHint(QPainter.Antialiasing); p.setPen(Qt.NoPen)
        t = tokens(); p.setBrush(t["surf"])
        path = QPainterPath(); path.setFillRule(Qt.WindingFill)
        path.addRoundedRect(QRectF(w.rect().adjusted(1, 1, -1, -1)), RADIUS, RADIUS)
        if self.isExpand:
            path.addRect(1, w.height() - RADIUS, w.width() - 2, RADIUS)
        p.drawPath(path.simplified())

    def _paint_border(self, e):
        w = self.borderWidget
        p = QPainter(w); p.setRenderHint(QPainter.Antialiasing); p.setBrush(Qt.NoBrush)
        t = tokens(); p.setPen(QPen(t["border"], 1))
        p.drawRoundedRect(w.rect().adjusted(1, 1, -1, -1), RADIUS, RADIUS)
        ch = self.card.height()
        if ch < w.height():
            p.setPen(QPen(t["line"], 1)); p.drawLine(1, ch, w.width() - 1, ch)

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
            "surf": QColor(39, 23, 13), "border": QColor(101, 56, 21), "line": QColor(101, 56, 21),
            "hero_a": QColor(58, 34, 16), "hero_b": QColor(4, 2, 0),
            "hero_border": QColor(101, 56, 21), "glow": QColor(249, 192, 67, 48),
            "accent": "#F9C043", "accent_hover": "#FFD35A", "accent_press": "#BD6707",
            "on_accent": "#040200", "ghost": "#27170D", "ghost_fg": "#E8D2A0",
            "ghost_bd": "#653815", "ghost_hv": "#3A2210",
            "accent_off": "transparent", "accent_off_fg": "#A88860", "accent_off_bd": "#653815",
            "pending": QColor(58, 32, 12), "pending_border": QColor(189, 103, 7),
            "editor": QColor("#1A100A"), "editor_fg": "#E8D2A0", "danger": "#E08A7A", "muted": HINT,
        }
    return {
        "surf": QColor("#C7E0EB"), "border": QColor("#6496AD"), "line": QColor("#82AEBF"),
        "hero_a": QColor("#58A4C9"), "hero_b": QColor("#AFCCD9"),
        "hero_border": QColor("#397E9F"), "glow": QColor(20, 143, 203, 115),
        "accent": "#075C8B", "accent_hover": "#074B73", "accent_press": "#063B5B",
        "on_accent": "#FFFFFF", "ghost": "#94C4DA", "ghost_fg": "#153F58",
        "ghost_bd": "#4B8CAC", "ghost_hv": "#7AB7D2",
            "accent_off": "transparent", "accent_off_fg": "#42677B", "accent_off_bd": "#6496AD",
            "pending": QColor("#A7C7D2"), "pending_border": QColor("#397E9F"),
            "editor": QColor("#D6EAF2"), "editor_fg": "#142F40", "danger": "#963C48", "muted": HINT_ON_LIGHT,
        }


# ----------------------------------------------------------------------------- helpers
class Bus(QObject):
    """Signals the worker threads emit; Qt delivers them on the UI thread."""
    line = Signal(str)
    done = Signal(bool, str)
    running = Signal(bool)
    steam = Signal(bool, bool)
    shells = Signal(int)
    me3 = Signal(dict)
    conflicts = Signal(dict)
    saves = Signal(list)


def page(name: str):
    """A scrollable page with a vertical layout and generous padding."""
    area = ScrollArea(); area.setObjectName(name); area.setWidgetResizable(True); area.setStyleSheet("QScrollArea{background:transparent;border:none}")
    inner = QWidget(); inner.setObjectName(name + "Inner"); inner.setStyleSheet("QWidget#" + name + "Inner{background:transparent}")
    lay = QVBoxLayout(inner); lay.setContentsMargins(40, 28, 40, 36); lay.setSpacing(20); lay.setAlignment(Qt.AlignTop)
    area.setWidget(inner); area.viewport().setStyleSheet("background:transparent")
    return area, lay


def hint(text=""):
    l = CaptionLabel(text); l.setWordWrap(True); l.setTextColor(HINT_ON_LIGHT, HINT); return l


def style_primary(btn):
    """Solid gold CTA. Own stylesheet so Fluent cannot wash it into a pale pill."""
    t = tokens()
    btn.setAttribute(Qt.WA_StyledBackground, True)
    btn.setFlat(True)
    btn.setStyleSheet(
        f"QPushButton{{background:{t['accent']};color:{t['on_accent']};border:1px solid {t['accent_press']};"
        f"border-radius:{RADIUS_BTN}px;padding:0 28px;font-size:15px;font-weight:600;}}"
        f"QPushButton:hover{{background:{t['accent_hover']};}}"
        f"QPushButton:pressed{{background:{t['accent_press']};}}"
        f"QPushButton:disabled{{background:{t['accent_off']};color:{t['accent_off_fg']};border:1px solid {t['accent_off_bd']};}}"
    )
    return btn


def style_ghost(btn):
    """Quiet secondary. Extra left padding when Fluent paints an icon, so type does not sit under it."""
    t = tokens()
    btn.setAttribute(Qt.WA_StyledBackground, True)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setMinimumHeight(36)
    if btn.property("hasIcon"):
        btn.setMinimumWidth(max(104, btn.minimumWidth()))
    btn.setStyleSheet(
        f"PushButton{{background:{t['ghost']};color:{t['ghost_fg']};border:1px solid {t['ghost_bd']};"
        f"border-radius:{RADIUS}px;padding:5px 14px 6px 14px;}}"
        f"PushButton[hasIcon=true]{{padding-left:36px;}}"
        f"PushButton:hover{{background:{t['ghost_hv']};}}"
        f"PushButton:disabled{{color:{t['accent_off_fg']};border:1px solid {t['accent_off_bd']};}}"
    )
    btn.setStyle(QApplication.style())
    return btn


def primary_btn(text):
    b = QPushBtn(text); b.setObjectName("cta"); b.setCursor(Qt.PointingHandCursor)
    b.setMinimumHeight(44); b.setMinimumWidth(128); return style_primary(b)


def ghost_btn(text, icon=None):
    b = PushButton(icon, text) if icon is not None else PushButton(text)
    return style_ghost(b)


def editor_font():
    families = set(QFontDatabase.families())
    for name in ("Cascadia Code", "Cascadia Mono", "JetBrains Mono", "Consolas", "Courier New"):
        if name in families:
            f = QFont(name, 11); f.setStyleHint(QFont.Monospace); return f
    f = QFont("Consolas", 11); f.setStyleHint(QFont.Monospace); return f


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
    if hl: hl.restyle()
    return edit


class CodeHighlighter(QSyntaxHighlighter):
    """TOML for the me3 profile, JSON for share-with-a-friend. Colours follow the theme."""
    def __init__(self, document, kind="toml"):
        super().__init__(document); self.kind = kind; self._rules = []; self.restyle()

    def restyle(self):
        if isDarkTheme():
            colors = {"comment": "#8A6E4A", "key": "#E8D2A0", "string": "#F9C043", "number": "#E08A7A", "keyword": "#BD6707", "header": "#F9C043"}
        else:
            colors = {"comment": "#385D70", "key": "#142F40", "string": "#075C8B", "number": "#963C48", "keyword": "#397E9F", "header": "#075C8B"}
        def fmt(name, bold=False):
            f = QTextCharFormat(); f.setForeground(QColor(colors[name]))
            if bold: f.setFontWeight(QFont.DemiBold)
            return f
        if self.kind == "json":
            specs = (
                (r'"([^"\\]|\\.)*"\s*(?=:)', "key"),
                (r'"([^"\\]|\\.)*"', "string"),
                (r"\b-?\d+(\.\d+)?\b", "number"),
                (r"\b(true|false|null)\b", "keyword"),
                (r"^\s*//.*$", "comment"),
            )
        else:
            specs = (
                (r'"[^"\\]*(\\.[^"\\]*)*"', "string"),
                (r"'[^']*'", "string"),
                (r"^\s*\[+[^\]]+\]+", "header"),
                (r"\b(true|false)\b", "keyword"),
                (r"\b-?\d+(\.\d+)?\b", "number"),
                (r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_-]*(?=\s*=)", "key"),
                (r"#.*$", "comment"),
            )
        self._rules = [(QRegularExpression(pat), fmt(name, bold=name == "header")) for pat, name in specs]
        self.rehighlight()

    def highlightBlock(self, text):
        for rx, fmt in self._rules:
            it = rx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


class CodeEdit(PlainTextEdit):
    """PlainTextEdit with the editor basics: Ctrl+/ toggles comments on the selected lines (# for TOML, // for JSON),
    Tab / Shift+Tab indent and outdent a multi-line selection by two spaces, Ctrl+D duplicates the line.
    Each shortcut is one undo step."""
    def __init__(self, lang="toml"):
        super().__init__(); self.lang = lang

    def _block_range(self):
        c = self.textCursor(); doc = self.document()
        start, end = c.selectionStart(), c.selectionEnd()
        first = doc.findBlock(start); last = doc.findBlock(end)
        if c.hasSelection() and end == last.position() and last.blockNumber() > first.blockNumber():
            last = last.previous()                     # a selection ending at column 0 does not include that line
        return first, last

    def _replace_lines(self, fn):
        first, last = self._block_range()
        lines = []
        b = first
        while True:
            lines.append(b.text())
            if b == last: break
            b = b.next()
        new = fn(lines)
        if new == lines: return
        start, end = first.position(), last.position() + last.length() - 1      # ints: block handles go stale on edit
        joined = "\n".join(new)
        c = self.textCursor(); c.beginEditBlock()
        c.setPosition(start); c.setPosition(end, c.MoveMode.KeepAnchor)
        c.insertText(joined); c.endEditBlock()
        sel = self.textCursor(); sel.setPosition(start); sel.setPosition(start + len(joined), sel.MoveMode.KeepAnchor)
        self.setTextCursor(sel)

    def keyPressEvent(self, e):
        key, mods = e.key(), e.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        if ctrl and key == Qt.Key_Slash:
            self._replace_lines(lambda ls: toggle_comment(ls, COMMENT_PREFIX.get(self.lang, "#"))); return
        if ctrl and key == Qt.Key_D:
            c = self.textCursor(); c.beginEditBlock(); c.movePosition(c.MoveOperation.EndOfBlock)
            c.insertText("\n" + c.block().text()); c.endEditBlock(); self.setTextCursor(c); return
        first, last = self._block_range()
        multi = self.textCursor().hasSelection() and last.blockNumber() > first.blockNumber()
        if key == Qt.Key_Backtab or (key == Qt.Key_Tab and mods & Qt.ShiftModifier):
            self._replace_lines(lambda ls: indent_lines(ls, outdent=True)); return
        if key == Qt.Key_Tab and multi:
            self._replace_lines(lambda ls: indent_lines(ls)); return
        super().keyPressEvent(e)


def code_edit(placeholder, wrap=False, lang="toml"):
    e = CodeEdit(lang); e.setPlaceholderText(placeholder); e.setTabStopDistance(e.fontMetrics().horizontalAdvance(" ") * 4)
    e.setToolTip("Ctrl+/ comment or uncomment the selected lines  ·  Tab / Shift+Tab indent a selection  ·  Ctrl+D duplicate the line")
    e.setLineWrapMode(PlainTextEdit.LineWrapMode.WidgetWidth if wrap else PlainTextEdit.LineWrapMode.NoWrap)
    style_editor(e)
    e._hl = CodeHighlighter(e.document(), lang)
    return e


def info_btn(title, text):
    b = TransparentToolButton(FI.INFO); b.setFixedSize(28, 28); b.setIconSize(QSize(14, 14))
    b.setToolTip("What this does")
    b.clicked.connect(lambda _=False, t=title, h=text: MessageBox(t, h, b.window()).exec())
    return b


_ABS_PATH = re.compile(r'(?i)(?:[A-Z]:\\|/)(?:[^\s\\/]+[\\/])+([^\s\\/]+)')


def tidy_log_line(s: str) -> str:
    """Show the file name, not a long path, so the log is the same on any PC."""
    return _ABS_PATH.sub(r"\1", s)


def classify_log(msg: str) -> str:
    low = msg.lstrip().lower()
    if low.startswith(("error", "traceback", "exception", "failed")): return "error"
    if low.startswith(("warning", "warn:", "warn ")): return "warning"
    return "info"


def short_problem(text: str) -> str:
    """Keep the reason, drop a long path so the line is not this PC's folder tree."""
    if ": " not in text: return text
    kind, rest = text.split(": ", 1)
    if "\\" in rest or "/" in rest: return f"{kind}: {Path(rest).name}"
    return text


LOG_KEEP = 1500


class LogPane(QWidget):
    """Launch output. Timestamp, one colour per level, Copy and Clear. Newest at the bottom."""
    def __init__(self):
        super().__init__()
        self._rows = []
        self.view = TextEdit(); self.view.setReadOnly(True); self.view.setAcceptRichText(True)
        self.view.setPlaceholderText("Play, Repair, and Clear write here. Newest line at the bottom.")
        self.view.setLineWrapMode(TextEdit.LineWrapMode.WidgetWidth)
        style_editor(self.view)
        bar = QHBoxLayout(); bar.setContentsMargins(0, 0, 0, 0); bar.setSpacing(8)
        self.copy_btn = ghost_btn("Copy", FI.COPY); self.copy_btn.clicked.connect(self.copy)
        self.clear_btn = ghost_btn("Clear", FI.DELETE); self.clear_btn.clicked.connect(self.clear)
        bar.addWidget(self.copy_btn); bar.addWidget(self.clear_btn); bar.addStretch()
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(8)
        lay.addLayout(bar); lay.addWidget(self.view)

    def add(self, msg, kind=None):
        now = datetime.datetime.now()
        parts = tidy_log_line(str(msg)).replace("\r\n", "\n").replace("\r", "\n").split("\n") or [""]
        for i, part in enumerate(parts):
            self._rows.append((now if i == 0 else None, kind or classify_log(part), part))
        if len(self._rows) > LOG_KEEP: self._rows = self._rows[-LOG_KEEP:]
        self._paint()
        bar = self.view.verticalScrollBar(); bar.setValue(bar.maximum())

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
        self._rows.clear(); self.view.clear()

    def restyle(self):
        style_editor(self.view); style_ghost(self.copy_btn); style_ghost(self.clear_btn); self._paint()

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
                bits.append(f'<div style="color:{color}"><span style="color:{t["muted"]}">{stamp}</span>&nbsp;&nbsp;{body}</div>')
        self.view.setHtml(f'<body style="background:{bg};font-family:Consolas,\'Cascadia Code\',monospace;font-size:11pt">{"".join(bits)}</body>')


def tone_label(lab, level="muted"):
    """Quiet status type. Colour means something: gold wait, rust error, otherwise muted."""
    if level == "error": lab.setTextColor("#963C48", "#E08A7A")
    elif level == "warning": lab.setTextColor(ACCENT_LIGHT, ACCENT)
    elif level == "accent": lab.setTextColor(ACCENT_LIGHT, ACCENT)
    else: lab.setTextColor(HINT_ON_LIGHT, HINT)


def titled(lay, text, icon, sub=None, action=None):
    """Page header. The nav already shows the icon, so the title is type only. The action sits on the title row."""
    head = QVBoxLayout(); head.setSpacing(4)
    row = QHBoxLayout(); row.setSpacing(12); title = TitleLabel(text); row.addWidget(title); row.addStretch()
    if action is not None: row.addWidget(action, 0, Qt.AlignVCenter)
    head.addLayout(row)
    if sub: head.addWidget(hint(sub))
    lay.addLayout(head)


def count_label(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def _slot_names(title: str) -> str:
    """Character names from 'slot N (Name)' in a finding title."""
    names = re.findall(r"slot\s+\d+\s+\(([^)]+)\)", title or "", flags=re.I)
    if not names: return ""
    if len(names) == 1: return names[0]
    return ", ".join(names)


def save_check_notes(info: dict) -> list[dict]:
    """Calm, grouped notes for the Saves panel. Empty when nothing useful to say."""
    notes = []
    findings = [f for f in (info.get("findings") or []) if f.get("level") in ("warn", "error")]
    if info.get("needs_repair"):
        notes.append({
            "kind": "action",
            "title": "Repair for save editors",
            "detail": "me3 left extra data at the end of the file. The game does not mind. Repair puts the real regulation.bin back so editors can open it.",
        })
    by = {}
    for f in findings:
        if f.get("code") == "regulation":
            continue  # covered above
        by.setdefault(f.get("code") or "other", []).append(f)

    if "layout" in by:
        torn = [f for f in by["layout"] if (f.get("title") or "").startswith("Torn write")]
        if torn:
            notes.append({
                "kind": "issue",
                "title": "Damaged by a crash while saving",
                "rows": [(_slot_names(f.get("title") or "") or "Character", "bytes shifted inside the character", f.get("detail") or "") for f in torn],
                "detail": "Roundtable Souls does not repair torn writes. Restore a backup, or run er-save-manager's deep scan. Everything else here is still read-only.",
            })
        else:
            notes.append({
                "kind": "issue",
                "title": "Could not read this save",
                "detail": by["layout"][0].get("detail") or "The file is not a PC Elden Ring save, or the layout does not parse.",
            })
    if "old_slot" in by:
        notes.append({
            "kind": "note",
            "title": "One character could not be read",
            "rows": [(_slot_names(f.get("title") or "") or (f.get("title") or "").replace("Cannot read ", ""), "old save layout, left alone", f.get("detail") or "") for f in by["old_slot"]],
            "detail": "Load that character in the game once so it is saved in the current layout, then Refresh here. The other characters are unaffected.",
        })
    if "loading" in by:
        rows = []
        for f in by["loading"]:
            who = _slot_names(f.get("title") or "") or "Character"
            label = (f.get("title") or "Loading problem").split(" (")[0]
            rows.append((who, label, f.get("detail") or ""))
        notes.append({
            "kind": "issue",
            "title": "May not load",
            "rows": rows,
            "detail": "These states hang the loading screen. Review & fix applies the same repair the save editors use, with a backup.",
        })
    if "unknown_item" in by:
        rows = _mod_item_rows(info)
        if not rows:
            for f in by["unknown_item"]:
                rows.append((_slot_names(f.get("title") or "") or "Character", (f.get("detail") or "").split(". ")[0], ""))
        worn = any("worn" in text for _, text, _ in rows)
        notes.append({
            "kind": "note",
            "title": "Mod items held",
            "rows": rows,
            "detail": "Fine for co-op. Review & fix can remove them for a standard .sl2"
                      + (". Worn pieces come off in-game first." if worn else "."),
        })
    if "quest_flags" in by:
        rows = []
        for f in by["quest_flags"]:
            who = _slot_names(f.get("title") or "") or "Character"
            label = (f.get("title") or "Quest flag").split(" (")[0]
            rows.append((who, label, f.get("detail") or ""))
        notes.append({
            "kind": "note",
            "title": "Quest soft-lock",
            "rows": rows,
            "detail": "Play still works. Review & fix clears it the way a save editor would, with a backup.",
        })
    if "duplicate_inventory" in by:
        who = ", ".join(filter(None, (_slot_names(f["title"]) for f in by["duplicate_inventory"])))
        notes.append({
            "kind": "note",
            "title": "Duplicate inventory entries",
            "detail": (("On " + who + ". ") if who else "")
                      + "Some editors refuse to write that character. The game usually still loads.",
        })
    for code in ("slot_checksum", "ud10_checksum"):
        if code not in by: continue
        notes.append({
            "kind": "note",
            "title": "Checksum mismatch",
            "detail": (by[code][0].get("detail") or "Unusual, but characters still show.") + " Fix checksums recomputes it, with a backup.",
        })
    for code, group in by.items():
        if code in ("layout", "loading", "old_slot", "unknown_item", "quest_flags", "duplicate_inventory", "slot_checksum", "ud10_checksum", "regulation", "read"):
            continue
        for f in group:
            notes.append({"kind": "note", "title": f.get("title") or code, "detail": f.get("detail") or ""})
    return notes


def _mod_item_rows(info: dict) -> list:
    """(character, 'Seamless Co-op 12  ·  Tarnished Pack 11 (2 worn)', tooltip with the names) per character."""
    rows = []
    for p in info.get("vanilla_plan") or []:
        entries = list(p.get("strip") or []) + [b for b in (p.get("blocked") or []) if b.get("why") == "worn"]
        if not entries:
            continue
        by = {}
        for e in entries:
            src = e.get("source") or "Other mod"
            names, worn = by.setdefault(src, ([], set()))
            if e["name"] not in names: names.append(e["name"])
            if e.get("why") == "worn": worn.add(e["name"])     # only gear Restore vanilla has to leave on
        parts, tip = [], []
        for src, (names, worn) in by.items():
            parts.append(f"{src} {len(names)}" + (f" ({len(worn)} worn)" if worn else ""))
            tip.append(src + ":\n  " + "\n  ".join(n + ("  (worn)" if n in worn else "") for n in names))
        rows.append((p.get("name") or f"slot {p['slot'] + 1}", "  ·  ".join(parts), "\n".join(tip)))
    return rows


class ChoiceDialog(MessageBoxBase):
    """Pick what a write action changes before it runs.

    groups: [{"title": "Tarnished", "subtitle": "...", "items": [
        {"key": any, "label": "Tiny Great Pot", "section": "Seamless Co-op", "sub": "in the pouch",
         "checked": True, "enabled": True, "note": "worn: take it off in-game first"}]}]
    Every group has All / None. Disabled items stay visible so nothing is hidden. Apply is off until
    at least one item is ticked, and the summary line says exactly how many of what will change.
    """
    def __init__(self, title, warning, groups, parent, apply_text="Apply", summarize=None):
        super().__init__(parent)
        self._summarize = summarize
        self.boxes = []                                   # (key, CheckBox)
        self.widget.setMinimumWidth(min(820, max(560, parent.width() - 120)) if parent else 720)
        self.viewLayout.setSpacing(10)
        self.viewLayout.addWidget(SubtitleLabel(title))
        warn = hint(warning); warn.setTextColor("#963C48", "#E08A7A"); self.viewLayout.addWidget(warn)
        scroll = ScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none}"); scroll.viewport().setStyleSheet("background:transparent")
        screen_h = parent.screen().availableGeometry().height() if parent and parent.screen() else 900
        scroll.setMaximumHeight(max(260, min(520, screen_h - 360)))
        body = QWidget(); body.setStyleSheet("background:transparent")
        bl = QVBoxLayout(body); bl.setContentsMargins(0, 0, 12, 0); bl.setSpacing(14)
        for g in groups:
            box_list = []
            head = QHBoxLayout(); head.setSpacing(8)
            head.addWidget(StrongBodyLabel(g["title"]))
            if g.get("subtitle"): head.addWidget(hint(g["subtitle"]))
            head.addStretch()
            b_all = TransparentPushButton("All"); b_none = TransparentPushButton("None")
            b_all.clicked.connect(lambda _=False, bs=box_list: [b.setChecked(True) for b in bs if b.isEnabled()])
            b_none.clicked.connect(lambda _=False, bs=box_list: [b.setChecked(False) for b in bs if b.isEnabled()])
            head.addWidget(b_all); head.addWidget(b_none); bl.addLayout(head)
            section = None
            grid = QGridLayout(); grid.setContentsMargins(12, 0, 0, 0); grid.setHorizontalSpacing(12); grid.setVerticalSpacing(4)
            r = 0
            for it in g["items"]:
                if it.get("section") and it["section"] != section:
                    section = it["section"]
                    grid.addWidget(hint(section), r, 0, 1, 2); r += 1
                cb = CheckBox(it["label"]); cb.setChecked(bool(it.get("checked", True))); cb.setEnabled(bool(it.get("enabled", True)))
                if it.get("tip"): cb.setToolTip(it["tip"])
                cb.stateChanged.connect(self._recount)
                grid.addWidget(cb, r, 0)
                side = it.get("note") or it.get("sub") or ""
                if side:
                    sl = hint(side)
                    if it.get("note"): sl.setTextColor("#963C48", "#E08A7A")
                    grid.addWidget(sl, r, 1)
                r += 1
                self.boxes.append((it["key"], cb)); box_list.append(cb)
            grid.setColumnStretch(1, 1)
            bl.addLayout(grid)
        bl.addStretch()
        scroll.setWidget(body); self.viewLayout.addWidget(scroll)
        self.summary = BodyLabel(""); self.summary.setWordWrap(True); self.viewLayout.addWidget(self.summary)
        self.yesButton.setText(apply_text); self.cancelButton.setText("Cancel")
        self._recount()

    def selected(self):
        return [key for key, cb in self.boxes if cb.isEnabled() and cb.isChecked()]

    def _recount(self, *_):
        keys = self.selected()
        self.yesButton.setEnabled(bool(keys))
        text = self._summarize(keys) if self._summarize else f"{len(keys)} change{'s' if len(keys) != 1 else ''} selected"
        self.summary.setText(text if keys else "Nothing selected. Tick what to change, or Cancel.")


class ConfirmDialog(MessageBoxBase):
    """A confirm that reads top to bottom: what it is, what will happen (bullets), what keeps you safe, then the buttons.

    changes: bullet lines. safety: one line about the backup / undo. warning: the red strip for writes.
    danger=True styles the primary button as a removal (the text says what is removed)."""
    def __init__(self, title, parent, changes=(), safety="", warning="", detail="", apply_text="Continue", cancel_text="Cancel", option=None, option_checked=True):
        super().__init__(parent)
        self.option = None
        self.widget.setMinimumWidth(min(680, max(460, (parent.width() - 200) if parent else 560)))
        self.viewLayout.setSpacing(8)
        self.viewLayout.addWidget(SubtitleLabel(title))
        if warning:
            w = hint(warning); w.setTextColor("#963C48", "#E08A7A"); self.viewLayout.addWidget(w)
        changes = [c for c in changes if c]
        if changes:
            self.viewLayout.addWidget(hint("What will happen"))
            body = QWidget(); bl = QVBoxLayout(body); bl.setContentsMargins(8, 0, 0, 0); bl.setSpacing(3)
            shown = changes[:14]
            for c in shown:
                lab = BodyLabel("\u2022  " + c); lab.setWordWrap(True); bl.addWidget(lab)
            if len(changes) > len(shown):
                bl.addWidget(hint(f"and {len(changes) - len(shown)} more"))
            self.viewLayout.addWidget(body)
        if detail:
            d = hint(detail); self.viewLayout.addWidget(d)
        if safety:
            self.viewLayout.addWidget(hint("Safety"))
            sl = BodyLabel(safety); sl.setWordWrap(True); self.viewLayout.addWidget(sl)
        if option:
            self.option = CheckBox(option); self.option.setChecked(bool(option_checked)); self.viewLayout.addWidget(self.option)
        self.yesButton.setText(apply_text); self.cancelButton.setText(cancel_text)

    def option_on(self) -> bool:
        return bool(self.option is not None and self.option.isChecked())


def confirm(parent, title, changes=(), safety="", warning="", detail="", apply_text="Continue") -> bool:
    return bool(ConfirmDialog(title, parent, changes=changes, safety=safety, warning=warning, detail=detail, apply_text=apply_text).exec())


class ModOptionsDialog(MessageBoxBase):
    """Per-mod options me3 v1 knows: enabled, and for natives optional / load_early / initializer / finalizer,
    plus load order (load_after, load_before) against the other entries of the profile."""
    def __init__(self, entry: dict, others: list, parent):
        super().__init__(parent)
        self.entry = entry
        self.widget.setMinimumWidth(min(720, max(520, parent.width() - 200)))
        self.viewLayout.setSpacing(8)
        self.viewLayout.addWidget(SubtitleLabel(entry["name"]))
        self.viewLayout.addWidget(hint(("Package  \u00b7  " if entry["kind"] == "package" else "Native  \u00b7  ") + (entry.get("path") or "")))
        form = QGridLayout(); form.setHorizontalSpacing(16); form.setVerticalSpacing(8); r = 0
        def row(label, control, blurb=""):
            nonlocal r
            lab = BodyLabel(label); form.addWidget(lab, r, 0, Qt.AlignTop); form.addWidget(control, r, 1); r += 1
            if blurb: form.addWidget(hint(blurb), r, 1); r += 1
        self.enabled = SwitchButton(); self.enabled.setOnText("On"); self.enabled.setOffText("Off"); self.enabled.setChecked(bool(entry.get("enabled", True)))
        row("Loaded", self.enabled, "Off keeps the entry in the profile but me3 skips it.")
        if entry["kind"] == "package":
            self.pkg_id = LineEdit(); self.pkg_id.setText(entry.get("id") or ""); self.pkg_id.setPlaceholderText("id other entries can refer to")
            row("Id", self.pkg_id, "Used by load order below. Leave as is unless another mod names it.")
        else:
            self.optional = CheckBox("Optional: a load failure is not fatal"); self.optional.setChecked(bool(entry.get("optional"))); row("", self.optional)
            self.early = CheckBox("Load early, before the game initialises (some DLLs need this, Seamless Co-op for one)"); self.early.setChecked(bool(entry.get("load_early"))); row("", self.early)
            self.init_kind = ComboBox(); self.init_kind.addItems(["No initializer", "Call a function", "Wait a delay (ms)"]); self.init_kind.setMinimumWidth(180)
            self.init_value = LineEdit(); self.init_value.setPlaceholderText("function name, or milliseconds")
            init = entry.get("initializer") or {}
            if init.get("function"): self.init_kind.setCurrentIndex(1); self.init_value.setText(str(init["function"]))
            elif isinstance(init.get("delay"), dict): self.init_kind.setCurrentIndex(2); self.init_value.setText(str(init["delay"].get("ms", 0)))
            box = QWidget(); bl = QHBoxLayout(box); bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(8); bl.addWidget(self.init_kind); bl.addWidget(self.init_value, 1)
            row("Initializer", box, "Symbol me3 calls after the DLL loads, or a delay before it counts as loaded. Some mods document one, for example NrrInitialize for Nightreign Revive.")
            self.fini = LineEdit(); self.fini.setText(entry.get("finalizer") or ""); self.fini.setPlaceholderText("symbol called on unload (rare)")
            row("Finalizer", self.fini)
        self.after = {}; self.before = {}
        for title, store, current in (("Load after", self.after, entry.get("load_after") or []), ("Load before", self.before, entry.get("load_before") or [])):
            cur = {d["id"]: d for d in current}
            box = QWidget(); bl = QVBoxLayout(box); bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(2)
            if not others: bl.addWidget(hint("No other entries in this profile."))
            for o in others:
                line = QWidget(); ll = QHBoxLayout(line); ll.setContentsMargins(0, 0, 0, 0); ll.setSpacing(12)
                cb = CheckBox(o); cb.setChecked(o in cur); opt = CheckBox("optional"); opt.setChecked(cur.get(o, {}).get("optional", True)); opt.setEnabled(cb.isChecked())
                cb.stateChanged.connect(lambda st, w=opt: w.setEnabled(bool(st)))
                ll.addWidget(cb, 1); ll.addWidget(opt); bl.addWidget(line); store[o] = (cb, opt)
            row(title, box, "Later in the load order wins on shared files. 'optional' means me3 does not fail when that entry is missing.")
        body = QWidget(); body.setStyleSheet("background:transparent"); body.setLayout(form)
        scroll = ScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none}"); scroll.viewport().setStyleSheet("background:transparent")
        screen_h = parent.screen().availableGeometry().height() if parent and parent.screen() else 900
        scroll.setMaximumHeight(max(280, min(560, screen_h - 320))); scroll.setWidget(body)
        self.viewLayout.addWidget(scroll)
        self.yesButton.setText("Save options"); self.cancelButton.setText("Cancel")

    def options(self) -> dict:
        e = self.entry
        opts = {"enabled": self.enabled.isChecked(),
                "load_after": [{"id": i, "optional": opt.isChecked()} for i, (cb, opt) in self.after.items() if cb.isChecked()],
                "load_before": [{"id": i, "optional": opt.isChecked()} for i, (cb, opt) in self.before.items() if cb.isChecked()]}
        if e["kind"] == "package":
            opts["id"] = self.pkg_id.text().strip()
        else:
            opts["optional"] = self.optional.isChecked(); opts["load_early"] = self.early.isChecked(); opts["finalizer"] = self.fini.text().strip()
            k = self.init_kind.currentIndex(); v = self.init_value.text().strip()
            opts["initializer"] = {"function": v} if k == 1 and v else ({"delay": {"ms": int(v)}} if k == 2 and v.isdigit() else None)
        return opts


class TextDialog(MessageBoxBase):
    """One line of text with a title, a blurb and an optional tick box."""
    def __init__(self, title, blurb, parent, placeholder="", text="", option=None, option_checked=False, apply_text="OK"):
        super().__init__(parent)
        self.widget.setMinimumWidth(480)
        self.viewLayout.addWidget(SubtitleLabel(title))
        if blurb: self.viewLayout.addWidget(hint(blurb))
        self.edit = LineEdit(); self.edit.setPlaceholderText(placeholder); self.edit.setText(text); self.edit.setClearButtonEnabled(True); self.viewLayout.addWidget(self.edit)
        self.option = None
        if option:
            self.option = CheckBox(option); self.option.setChecked(option_checked); self.viewLayout.addWidget(self.option)
        self.yesButton.setText(apply_text); self.cancelButton.setText("Cancel")

    def validate(self):
        return bool(self.edit.text().strip())


WRITE_WARNING = "This writes to your save file. Elden Ring must stay closed until it finishes."
WRITE_SAFETY = "A copy of the file as it is now goes into save-fix-backups first. Undo appears at the top of the window afterwards, and the Backups list can put any copy back."


def _save_note_widget(note: dict) -> QWidget:
    """Title, optional character rows (name | text, names in the tooltip), then one calm line."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lab = StrongBodyLabel(note["title"]); lab.setWordWrap(True)
    if note.get("kind") == "issue": lab.setTextColor("#963C48", "#E08A7A")
    lay.addWidget(lab)
    rows = note.get("rows") or []
    if rows:
        grid = QGridLayout(); grid.setContentsMargins(0, 0, 0, 0); grid.setHorizontalSpacing(14); grid.setVerticalSpacing(2)
        for r, (who, text, tip) in enumerate(rows):
            name = BodyLabel(who); name.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            body = BodyLabel(text); body.setWordWrap(True)
            if tip:
                name.setToolTip(tip); body.setToolTip(tip)
            grid.addWidget(name, r, 0, Qt.AlignTop); grid.addWidget(body, r, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
    if note.get("detail"):
        lay.addWidget(hint(note["detail"]))
    return w


def card(title=None, icon=None):
    c = GlassCard(); lay = QVBoxLayout(c); lay.setContentsMargins(20, 16, 20, 18); lay.setSpacing(10)
    if title:
        row = QHBoxLayout(); row.setSpacing(8)
        if icon: ic = IconWidget(icon); ic.setFixedSize(18, 18); row.addWidget(ic)
        row.addWidget(StrongBodyLabel(title)); row.addStretch(); lay.addLayout(row)
    return c, lay


class LogoPreview(QWidget):
    """The mark the way Windows 11 shows it: a square, clipped to a rounded plate."""
    def __init__(self):
        super().__init__(); self._pix = QPixmap(); self.setFixedSize(56, 56)

    def setPixmap(self, pix):
        self._pix = pix; self.update()

    def paintEvent(self, e):
        if self._pix.isNull(): return
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath(); path.addRoundedRect(r, 12, 12)
        p.setClipPath(path); p.drawPixmap(self.rect(), self._pix)


class PairRow(QWidget):
    """A label and an action. The action drops under the text when the row gets narrow."""
    def __init__(self, title, desc, button):
        super().__init__()
        col = QWidget(); cl = QVBoxLayout(col); cl.setContentsMargins(0, 0, 0, 0); cl.setSpacing(2)
        cl.addWidget(StrongBodyLabel(title)); cl.addWidget(hint(desc))
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.box = QBoxLayout(QBoxLayout.LeftToRight, self); self.box.setContentsMargins(0, 0, 0, 0); self.box.setSpacing(16)
        self.box.addWidget(col, 1); self.box.addWidget(button, 0, Qt.AlignRight | Qt.AlignVCenter)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.box.setDirection(QBoxLayout.TopToBottom if self.width() < 520 else QBoxLayout.LeftToRight)


class SettingRow(QWidget):
    """A form row: title, optional one-line blurb, the control, and an info popup."""
    def __init__(self, title, blurb, control, help_text=""):
        super().__init__()
        self._blurb = blurb or ""
        head = QWidget(); hl = QHBoxLayout(head); hl.setContentsMargins(0, 0, 0, 0); hl.setSpacing(4)
        hl.addWidget(StrongBodyLabel(title), 0, Qt.AlignVCenter)
        if help_text: hl.addWidget(info_btn(title, help_text), 0, Qt.AlignVCenter)
        hl.addStretch()
        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 0, 0); ll.setSpacing(2)
        ll.addWidget(head)
        self.d = hint(blurb) if blurb else None
        if self.d: ll.addWidget(self.d)
        control.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.box = QBoxLayout(QBoxLayout.LeftToRight, self); self.box.setContentsMargins(20, 10, 20, 10); self.box.setSpacing(12)
        self.box.addWidget(left, 1); self.box.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)
        self._fit()

    def resizeEvent(self, e):
        super().resizeEvent(e); self._fit()

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
        super().__init__(parent); self.radius = radius

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect().adjusted(1, 1, -1, -1))
        path = QPainterPath(); path.addRoundedRect(r, self.radius, self.radius)
        t = tokens(); p.fillPath(path, t["surf"]); p.strokePath(path, QPen(t["border"], 1))


class Metric(QWidget):
    """One number in the hero footer. Label muted, value loud."""
    def __init__(self, label):
        super().__init__()
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(2)
        lay.addWidget(hint(label))
        self.value = StrongBodyLabel("—"); self.value.setWordWrap(True)
        f = self.value.font(); f.setPointSize(16); f.setBold(True); self.value.setFont(f); lay.addWidget(self.value)


class HeroBanner(QWidget):
    """One featured panel: who you are, the Play action, then three quiet facts."""
    def __init__(self):
        super().__init__(); self._compact = False; self.setMinimumHeight(220); self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.name_col = QWidget(); col = QVBoxLayout(self.name_col); col.setContentsMargins(0, 0, 0, 0); col.setSpacing(6); col.addStretch()
        self.name = LargeTitleLabel("Reading your save..."); f = self.name.font(); f.setPointSize(28); f.setBold(True); self.name.setFont(f); self.name.setWordWrap(True); col.addWidget(self.name)
        self.sub = hint(""); col.addWidget(self.sub); col.addStretch()
        self.side = QWidget(); side = QVBoxLayout(self.side); side.setContentsMargins(0, 0, 0, 0); side.setSpacing(8); side.addStretch()
        self.play_btn = primary_btn("Play"); self.play_btn.setFixedSize(148, 48)
        pf = QFont(); pf.setPointSize(15); pf.setBold(True); self.play_btn.setFont(pf)
        self.ring = IndeterminateProgressRing(); self.ring.setFixedSize(16, 16); self.ring.setStrokeWidth(2); self.ring.hide()
        self.ready = CaptionLabel("Ready"); tone_label(self.ready); self.status_pill = self.ready
        self.status = BodyLabel(""); self.status.setWordWrap(True); tone_label(self.status)
        meta = QHBoxLayout(); meta.setSpacing(8); meta.setContentsMargins(0, 0, 0, 0)
        meta.addWidget(self.ring); meta.addWidget(self.ready); meta.addStretch()
        side.addWidget(self.play_btn, 0, Qt.AlignRight); side.addLayout(meta); side.addWidget(self.status); side.addStretch()
        self.metrics = QWidget(); row = QHBoxLayout(self.metrics); row.setContentsMargins(0, 4, 0, 0); row.setSpacing(0)
        self.stat_level = Metric("Level"); self.stat_save = Metric("Save"); self.stat_body = Metric("Body")
        for i, m in enumerate((self.stat_level, self.stat_save, self.stat_body)):
            if i: row.addSpacing(28)
            row.addWidget(m, 1)
        self.grid = QGridLayout(self); self.grid.setContentsMargins(28, 24, 28, 20); self.grid.setHorizontalSpacing(24); self.grid.setVerticalSpacing(18)
        self.grid.addWidget(self.name_col, 0, 0); self.grid.addWidget(self.side, 0, 1, Qt.AlignRight | Qt.AlignVCenter)
        self.grid.addWidget(self.metrics, 1, 0, 1, 2); self.grid.setColumnStretch(0, 1)

    def set_compact(self, compact):
        if compact == self._compact: return
        self._compact = compact
        f = self.name.font(); f.setPointSize(22 if compact else 28); self.name.setFont(f)
        self.setMinimumHeight(248 if compact else 220)
        self.grid.setContentsMargins(*(20, 16, 20, 16) if compact else (28, 24, 28, 20))
        self.grid.removeWidget(self.name_col); self.grid.removeWidget(self.side); self.grid.removeWidget(self.metrics)
        if compact:
            self.grid.addWidget(self.name_col, 0, 0); self.grid.addWidget(self.side, 1, 0, Qt.AlignLeft); self.grid.addWidget(self.metrics, 2, 0)
        else:
            self.grid.addWidget(self.name_col, 0, 0); self.grid.addWidget(self.side, 0, 1, Qt.AlignRight | Qt.AlignVCenter)
            self.grid.addWidget(self.metrics, 1, 0, 1, 2)
        self.grid.setColumnStretch(0, 1); self.grid.setColumnStretch(1, 0)

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect().adjusted(1, 1, -1, -1))
        path = QPainterPath(); path.addRoundedRect(r, RADIUS_HERO, RADIUS_HERO)
        t = tokens()
        g = QLinearGradient(r.topLeft(), r.bottomRight()); g.setColorAt(0, t["hero_a"]); g.setColorAt(1, t["hero_b"])
        p.fillPath(path, g)
        orb = QRadialGradient(QPointF(r.left() + r.width() * 0.18, r.top() + 8), r.width() * 0.42)
        orb.setColorAt(0, t["glow"]); orb.setColorAt(1, QColor(t["glow"].red(), t["glow"].green(), t["glow"].blue(), 0))
        p.fillPath(path, orb); p.strokePath(path, QPen(t["hero_border"], 1))
        y = self.metrics.y() - 6
        if y > 20:
            p.setPen(QPen(t["line"], 1)); p.drawLine(int(r.left()) + 20, y, int(r.right()) - 20, y)


class SaveBar(QWidget):
    """The co-op save row. It stays under the scrolling form, and picks up gold while something is unsaved."""
    def __init__(self):
        super().__init__(); self.pending = False; self.setMinimumHeight(64)

    def paintEvent(self, e):
        t = tokens(); p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); r = self.rect().adjusted(1, 1, -1, -1)
        fill = t["pending"] if self.pending else t["surf"]
        border = t["pending_border"] if self.pending else t["border"]
        p.setBrush(fill); p.setPen(QPen(border, 1.4 if self.pending else 1)); p.drawRoundedRect(r, RADIUS, RADIUS)


# ----------------------------------------------------------------------------- window
class Launcher(FluentWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings(); self.bus = Bus(); self.busy = False; self.game_running = False; self.steam_bar = None; self.steam_bad_since = None; self.shells_bar = None; self._toast_bar = None; self._loading_setups = False; self.saves_badge = None; self._undo = None; self._backups_all = False
        self.setups = discover(self.settings.get("setup")); self.setup = None; self.ini = None; self.pw_file = None; self.scaling_file = None; self.saves = []
        self.setWindowTitle(f"{TITLE} {VERSION}"); self.resize(1080, 760); self.setMinimumSize(720, 540)
        self._apply_logo()
        self.navigationInterface.setExpandWidth(190); self.navigationInterface.setMinimumExpandWidth(820)   # rail stays open with page names at normal window sizes
        self.navigationInterface.setReturnButtonVisible(False)  # flat pages; Back only repeated the last nav click
        self.navigationInterface.setAcrylicEnabled(True)
        try: self.setMicaEffectEnabled(False)
        except Exception: pass
        self.setCustomBackgroundColor(BG_LIGHT, BG_DARK)
        self._build_play(); self._build_coop(); self._build_mods(); self._build_saves(); self._build_tools(); self._build_workshop()
        self.addSubInterface(self.play_page, FI.PLAY, "Play"); self.addSubInterface(self.coop_page, FI.PEOPLE, "Co-op")
        self.addSubInterface(self.mods_page, FI.LIBRARY, "Mods"); self.addSubInterface(self.saves_page, FI.SAVE, "Saves"); self.addSubInterface(self.tools_page, FI.DEVELOPER_TOOLS, "Tools", NavigationItemPosition.BOTTOM)
        sc = QShortcut(QKeySequence("Ctrl+S"), self); sc.activated.connect(self._shortcut_save)
        self.bus.line.connect(self._on_line); self.bus.done.connect(self._on_done); self.bus.running.connect(self._on_running); self.bus.saves.connect(self._fill_saves); self.bus.steam.connect(self._on_steam); self.bus.shells.connect(self._on_shells)
        self.bus.me3.connect(self._on_me3); self.bus.conflicts.connect(self._fill_conflicts)
        core.NOTIFY = lambda title, msg: InfoBar.error(title, msg, duration=-1, position=InfoBarPosition.TOP, parent=self)
        sys.excepthook = lambda t, e, tb: report_exception(t, e, tb, "main thread")
        threading.excepthook = lambda a: report_exception(a.exc_type, a.exc_value, a.exc_traceback, f"thread {a.thread.name}")
        self._fill_setups(); self.refresh_saves(); self._watch_game(); self._refresh_me3()
        QTimer.singleShot(0, lambda: (self.navigationInterface.expand(useAni=False), self._restyle(), self._relayout()))

    # ---------------------------------------------------------------- Play page
    def _build_play(self):
        self.play_page, lay = page("playPage")
        self.hero = HeroBanner(); self.play_btn = self.hero.play_btn; self.play_btn.clicked.connect(self.launch)
        self.ring = self.hero.ring; self.ready = self.hero.ready; self.status_pill = self.hero.status_pill; self.status = self.hero.status
        self.stat_level = self.hero.stat_level; self.stat_save = self.hero.stat_save; self.stat_body = self.hero.stat_body
        lay.addWidget(self.hero)
        self.plan = hint(""); lay.addWidget(self.plan)
        self.setup_exp = ExpandGroupSettingCard(FI.SETTING, "Setup", "The profile Play launches.")
        body = QWidget(); cl = QVBoxLayout(body); cl.setContentsMargins(16, 8, 16, 12); cl.setSpacing(10)
        row = QHBoxLayout(); self.setup_box = ComboBox(); self.setup_box.setMinimumWidth(140); self.setup_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); self.setup_box.currentIndexChanged.connect(self._on_setup)
        b = ghost_btn("Browse...", FI.FOLDER); b.clicked.connect(self.browse); row.addWidget(self.setup_box, 1); row.addWidget(b)
        row.addWidget(self._folder_btn("game", "Game folder", FI.GAME, "The folder with eldenring.exe.")); cl.addLayout(row)
        self.setup_hint = hint(); cl.addWidget(self.setup_hint); self.setup_exp.addGroupWidget(body); lay.addWidget(self.setup_exp)
        self.log_exp = ExpandGroupSettingCard(FI.HISTORY, "Launch log", "Opens on its own if something goes wrong.")
        self.log_pane = LogPane(); self.log = self.log_pane.view; self.log.setMinimumHeight(180)
        log_body = QWidget(); ll = QVBoxLayout(log_body); ll.setContentsMargins(16, 8, 16, 12); ll.addWidget(self.log_pane)
        self.log_exp.addGroupWidget(log_body); lay.addWidget(self.log_exp); lay.addStretch(1)

    def resizeEvent(self, e):
        super().resizeEvent(e); self._relayout()

    def _relayout(self):
        if not hasattr(self, "hero") or not hasattr(self, "coop_head"): return
        compact = self.width() < COMPACT
        if compact == getattr(self, "_compact", None): return
        self._compact = compact
        self.hero.set_compact(compact); self._layout_scaling(2 if compact else 3)
        if hasattr(self, "save_box"): self.save_box.setDirection(QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight)
        self._set_pads(compact)
        self.log.setMinimumHeight(140 if compact else 180); self.profile_edit.setMinimumHeight(200 if compact else 320)

    def _layout_scaling(self, cols):
        if cols == getattr(self, "_scal_cols", None): return
        self._scal_cols = cols
        for i, (lab, sp) in enumerate(zip(self.scal_labs, self.spins)):
            self.scal_grid.addWidget(lab, (i // cols) * 2, i % cols)
            self.scal_grid.addWidget(sp, (i // cols) * 2 + 1, i % cols)
        for c in range(3): self.scal_grid.setColumnStretch(c, 1 if c < cols else 0)

    def _set_pads(self, compact):
        m = (18, 16, 18, 18) if compact else (40, 28, 40, 36); sp = 12 if compact else 20
        for area in (self.play_page, self.mods_page, self.saves_page, self.tools_page, self.coop_scroll):
            inner = area.widget()
            if inner is not None and inner.layout() is not None:
                inner.layout().setContentsMargins(*m); inner.layout().setSpacing(sp)
        self.coop_head.layout().setContentsMargins(m[0], m[1], m[2], 8)
        self.coop_bar.layout().setContentsMargins(m[0], 8, m[2], 16 if compact else 20)
        self.coop_scroll.widget().layout().setContentsMargins(m[0], 12, m[2], 16)

    # ---------------------------------------------------------------- Co-op page
    def _build_coop(self):
        root = QWidget(); root.setObjectName("coopPage"); outer = QVBoxLayout(root); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        self.coop_head = QWidget(); hl = QVBoxLayout(self.coop_head); hl.setContentsMargins(40, 28, 40, 8); hl.setSpacing(0)
        titled(hl, "Co-op", FI.PEOPLE, "Password and difficulty for Seamless."); outer.addWidget(self.coop_head)
        self.coop_scroll, lay = page("coopScroll"); lay.setContentsMargins(40, 12, 40, 16); outer.addWidget(self.coop_scroll, 1)
        off, offl = card("No co-op in this setup", FI.PEOPLE); offl.addWidget(hint("This setup does not load Seamless Co-op, so there is no password or difficulty to set. Pick a setup that includes it on the Play page.")); lay.addWidget(off); self.coop_off = off; off.hide()
        self.coop_form = []
        c, cl = card("Session password", FI.CERTIFICATE); row = QHBoxLayout(); self.pw = PasswordLineEdit(); self.pw.setMinimumWidth(120); self.pw.setPlaceholderText("Friends type this to join"); self.pw.textChanged.connect(self._on_pw_edit)
        row.addWidget(self.pw, 1); cl.addLayout(row); self.pw_hint = hint(); cl.addWidget(self.pw_hint); lay.addWidget(c); self.coop_form.append(c)
        c, cl = card("Difficulty", FI.SPEED_HIGH); cl.addWidget(hint("Percent per extra player. Only the host's numbers count."))
        row = QHBoxLayout(); self.preset = ComboBox(); self.preset.addItems(list(SCALING_PRESETS) + [CUSTOM]); self.preset.setMinimumWidth(160); self.preset.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); self.preset.currentTextChanged.connect(self._on_preset); row.addWidget(BodyLabel("Preset")); row.addWidget(self.preset, 1); cl.addLayout(row)
        self.scal_grid = QGridLayout(); self.scal_grid.setHorizontalSpacing(12); self.scal_grid.setVerticalSpacing(6); self.spins = []; self.scal_labs = []
        for _i, label in enumerate(SCALING_LABELS):
            lab = CaptionLabel(label); self.scal_labs.append(lab)
            sp = SpinBox(); sp.setRange(0, 500); sp.setSingleStep(5); sp.setMinimumWidth(72); sp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); sp.valueChanged.connect(self._on_scaling_edit); self.spins.append(sp)
        self._scal_cols = None; self._layout_scaling(3)
        cl.addLayout(self.scal_grid); self.scal_hint = hint(); cl.addWidget(self.scal_hint); lay.addWidget(c); self.coop_form.append(c)
        self.other_host = QWidget(); self.all_box = QVBoxLayout(self.other_host); self.all_box.setContentsMargins(0, 0, 0, 0); self.all_box.setSpacing(10)
        lay.addWidget(self.other_host); self.coop_form.append(self.other_host); self.all_dirty = {}; self.all_file = {}
        share = ExpandGroupSettingCard(FI.SHARE, "Share with a friend", "Copy yours, or paste a friend's and apply.")
        body = QWidget(); bl = QVBoxLayout(body); bl.setContentsMargins(16, 8, 16, 12)
        self.share = code_edit("Paste a friend's settings, or copy yours.", wrap=True, lang="json"); self.share.setMinimumHeight(190); bl.addWidget(self.share)
        row = QHBoxLayout()
        for text, icon, fn in (("Copy", FI.COPY, self.share_copy), ("Paste", FI.PASTE, self.share_paste), ("Reset", FI.SYNC, self.share_fill)):
            b = ghost_btn(text, icon); b.clicked.connect(fn); row.addWidget(b)
        row.addStretch(); apply = primary_btn("Apply"); apply.clicked.connect(self.share_apply); row.addWidget(apply); bl.addLayout(row)
        row2 = QHBoxLayout()
        for text, icon, fn in (("Save file...", FI.DOWNLOAD, self.share_save), ("Load file...", FI.FOLDER, self.share_load)):
            b = ghost_btn(text, icon); b.clicked.connect(fn); row2.addWidget(b)
        row2.addStretch(); bl.addLayout(row2); self.share_hint = hint(); bl.addWidget(self.share_hint); share.addGroupWidget(body); lay.addWidget(share); self.coop_form.append(share); lay.addStretch(1)
        wrap = QWidget(); wl = QVBoxLayout(wrap); wl.setContentsMargins(40, 8, 40, 20)
        self.save_bar = SaveBar(); self.save_box = QBoxLayout(QBoxLayout.LeftToRight, self.save_bar); self.save_box.setContentsMargins(20, 12, 16, 12); self.save_box.setSpacing(12)
        self.all_note = BodyLabel("All changes are saved."); self.all_note.setWordWrap(True); self.save_box.addWidget(self.all_note, 1)
        acts = QWidget(); al = QHBoxLayout(acts); al.setContentsMargins(0, 0, 0, 0); al.setSpacing(8)
        self.all_discard = ghost_btn("Discard", FI.CANCEL); self.all_discard.setToolTip("Puts the password, difficulty, and other options back to the file."); self.all_discard.clicked.connect(self._discard_coop); al.addWidget(self.all_discard)
        self.all_save = primary_btn("Save changes"); self.all_save.setToolTip("Writes the password, difficulty, and any other options you changed. Ctrl+S."); self.all_save.setMinimumHeight(40); self.all_save.setMinimumWidth(120)
        self.all_save.clicked.connect(lambda: self._announce_saved(self.save_seamless(), "next")); al.addWidget(self.all_save)
        self.save_box.addWidget(acts); wl.addWidget(self.save_bar); outer.addWidget(wrap); self.coop_bar = wrap; self.coop_page = root

    # ---------------------------------------------------------------- Mods page
    def _build_mods(self):
        self.mods_page, lay = page("modsPage")
        acts = QWidget(); al = QHBoxLayout(acts); al.setContentsMargins(0, 0, 0, 0); al.setSpacing(8)
        self.mods_refresh = ghost_btn("Refresh", FI.SYNC); self.mods_refresh.clicked.connect(self._fill_mods)
        self.profile_save = primary_btn("Save profile"); self.profile_save.setToolTip("Writes the me3 file and keeps one .bak. Ctrl+S."); self.profile_save.clicked.connect(self._save_profile)
        self.profile_save.setEnabled(False); self.profile_save.setVisible(False)
        self.mods_install = ghost_btn("Install mod", FI.DOWNLOAD); self.mods_install.setToolTip("A .zip, .7z or .rar, or a folder. Roundtable Souls works out whether it is a package or a DLL and adds it at the end of the load order.")
        self.mods_install.clicked.connect(self._install_mod)
        self.prof_new = ghost_btn("New profile", FI.ADD); self.prof_new.setToolTip("A fresh .me3 in me3's profile folder, empty or copied from the current one."); self.prof_new.clicked.connect(self._new_profile)
        self.prof_del = ghost_btn("Delete profile", FI.DELETE); self.prof_del.setToolTip("Moves the .me3 into deleted-profiles beside it. Mod folders stay."); self.prof_del.clicked.connect(self._delete_profile)
        al.addWidget(self._folder_btn("profile", "Profile folder", FI.FOLDER, "The folder holding this .me3 and its mods."))
        al.addWidget(self.mods_install); al.addWidget(self.prof_new); al.addWidget(self.prof_del); al.addWidget(self.mods_refresh); al.addWidget(self.profile_save)
        titled(lay, "Mods", FI.LIBRARY, "What this profile loads.", acts)
        self.mods_note = hint(""); lay.addWidget(self.mods_note)
        self.pack_exp = ExpandGroupSettingCard(FI.FOLDER, "Packages", "File replacements.")
        self.nat_exp = ExpandGroupSettingCard(FI.CODE, "Natives", "DLLs.")
        lay.addWidget(self.pack_exp); lay.addWidget(self.nat_exp)
        c, cl = card("Profile settings", FI.SETTING)
        cl.addWidget(hint("The me3 options this profile can set. Written into the .me3 file next to profileVersion, with one .bak. me3 reads them at the next launch."))
        self.ps = {}
        for key in ("mem_patch", "disable_arxan", "start_online"):
            box = ComboBox(); box.addItems(["me3 default", "On", "Off"]); box.setMinimumWidth(140)
            box.currentIndexChanged.connect(lambda idx, k=key: self._on_profile_setting(k, {1: True, 2: False}.get(idx)))
            self.ps[key] = box
            title, blurb = core.profile_tools.SETTING_TEXT[key]
            cl.addWidget(SettingRow(title, blurb, box, blurb + (" me3 warns this is a ban risk with modded data." if key == "start_online" else "")))
        sp = SpinBox(); sp.setRange(0, 65536); sp.setSingleStep(1024); sp.setMinimumWidth(140); sp.editingFinished.connect(lambda: self._on_profile_setting("mem_patch_heap_size", sp.value())); self.ps["mem_patch_heap_size"] = sp
        title, blurb = core.profile_tools.SETTING_TEXT["mem_patch_heap_size"]; cl.addWidget(SettingRow(title, blurb, sp, blurb))
        le = PasswordLineEdit(); le.setPasswordVisible(True); le.setClearButtonEnabled(True); le.setPlaceholderText("ER0000.sl2 (default)"); le.setMinimumWidth(200)
        le.editingFinished.connect(lambda: self._on_profile_setting("savefile", le.text().strip())); self.ps["savefile"] = le
        title, blurb = core.profile_tools.SETTING_TEXT["savefile"]; cl.addWidget(SettingRow(title, blurb, le, blurb + " Seamless Co-op names its own .co2 regardless."))
        self.ps_note = hint(""); cl.addWidget(self.ps_note); lay.addWidget(c); self.ps_card = c
        c, cl = card("Conflicts", FI.INFO)
        cl.addWidget(hint("Files two enabled packages both ship. The package later in the load order wins; this is what me3 does, shown before you play. Read-only."))
        self.conf_note = hint("Not scanned yet."); cl.addWidget(self.conf_note)
        self.conf_rows = QVBoxLayout(); self.conf_rows.setSpacing(4); cl.addLayout(self.conf_rows)
        row = QHBoxLayout(); self.conf_more = ghost_btn("Show all"); self.conf_more.setVisible(False); self.conf_more.clicked.connect(self._toggle_conflicts); row.addWidget(self.conf_more)
        b = ghost_btn("Rescan", FI.SYNC); b.clicked.connect(self._scan_conflicts); row.addWidget(b); row.addStretch(); cl.addLayout(row)
        lay.addWidget(c); self.conf_card = c; self._conf_all = False; self._conf_result = None
        edit = ExpandGroupSettingCard(FI.EDIT, "Edit profile", "The me3 file for the setup on Play.")
        body = QWidget(); bl = QVBoxLayout(body); bl.setContentsMargins(16, 8, 16, 12)
        self.profile_path = hint(""); bl.addWidget(self.profile_path)
        self.profile_edit = code_edit("The me3 file for the setup on Play."); self.profile_edit.setMinimumHeight(320)
        self.profile_edit.textChanged.connect(self._profile_dirty); bl.addWidget(self.profile_edit)
        self.profile_note = hint("Matches the file."); bl.addWidget(self.profile_note)
        row = QHBoxLayout()
        self.profile_reload = ghost_btn("Reload", FI.SYNC); self.profile_reload.clicked.connect(lambda: self._load_profile_editor(force=True)); row.addWidget(self.profile_reload); row.addStretch(); bl.addLayout(row)
        edit.addGroupWidget(body); lay.addWidget(edit); self.profile_exp = edit; lay.addStretch(1)
        self._profile_disk = ""; self._profile_file = None; self._profile_crlf = False

    def _load_profile_settings(self):
        if not self.setup: return
        vals = read_profile_settings(self.setup.profile)
        for key in ("mem_patch", "disable_arxan", "start_online"):
            box = self.ps[key]; box.blockSignals(True); box.setCurrentIndex({True: 1, False: 2}.get(vals.get(key), 0)); box.blockSignals(False)
        sp = self.ps["mem_patch_heap_size"]; sp.blockSignals(True); sp.setValue(int(vals.get("mem_patch_heap_size") or 0)); sp.blockSignals(False)
        le = self.ps["savefile"]; le.blockSignals(True); le.setText(str(vals.get("savefile") or "")); le.blockSignals(False)
        self.ps_note.setText("Online matchmaking is ON in this profile: me3 calls that a ban risk with modded data." if vals.get("start_online") else "")
        if vals.get("start_online"): tone_label(self.ps_note, "error")
        else: tone_label(self.ps_note, "muted")

    def _on_profile_setting(self, key, value):
        if not self.setup or getattr(self, "_loading_setups", False): return
        if self._profile_file is not None and self.profile_edit.toPlainText() != self._profile_disk:
            self._toast("Profile has unsaved edits", "Save or reload the profile editor first, then change this setting.", error=True)
            self._load_profile_settings(); return
        if key == "start_online" and value is True:
            if not confirm(self, "Turn online matchmaking on", changes=["This profile starts the game with the official servers reachable"],
                           warning="me3 blocks matchmaking by default because playing online with modded data can get the account banned.",
                           safety="Nothing else in the profile changes; a .bak of the file is kept.", apply_text="Turn on"):
                self._load_profile_settings(); return
        try:
            changed = write_profile_setting(self.setup.profile, key, value)
        except Exception as e:
            self._toast("Could not write the profile", str(e), error=True); self._load_profile_settings(); return
        if changed:
            self._log(f"profile: {key} = {value if value not in (None, '') else 'me3 default'}")
            self._toast("Profile updated", f"{core.profile_tools.SETTING_TEXT[key][0]} applies at the next launch.")
            self._load_profile_editor(force=True)
        self._load_profile_settings()

    def _scan_conflicts(self):
        if not self.setup: return
        self.conf_note.setText("Scanning packages..."); prof = self.setup.profile
        def work():
            try: self.bus.conflicts.emit(scan_profile_conflicts(prof))
            except Exception as e: self.bus.conflicts.emit({"error": str(e)})
        threading.Thread(target=work, daemon=True).start()

    def _toggle_conflicts(self):
        self._conf_all = not self._conf_all
        if self._conf_result: self._fill_conflicts(self._conf_result)

    def _fill_conflicts(self, r):
        self._conf_result = r
        for i in reversed(range(self.conf_rows.count())):
            it = self.conf_rows.takeAt(i); w = it.widget()
            if w: w.setParent(None); w.deleteLater()
        if r.get("error"):
            self.conf_note.setText(f"Could not scan: {r['error']}"); self.conf_more.setVisible(False); return
        pk = r.get("packages") or []; cf = r.get("conflicts") or []
        missing = [p["id"] for p in pk if p.get("missing")]
        parts = [f"{len(pk)} package{'s' if len(pk) != 1 else ''}, {r.get('files', 0):,} files"]
        parts.append("no overlapping files" if not cf else f"{len(cf)} overlapping file{'s' if len(cf) != 1 else ''}: " + ", ".join(f"{k} {v}" for k, v in sorted(r["by_category"].items())))
        if missing: parts.append("missing folder: " + ", ".join(missing))
        if r.get("truncated"): parts.append("scan stopped early (very large packages)")
        self.conf_note.setText("  \u00b7  ".join(parts)); tone_label(self.conf_note, "error" if missing else "muted")
        if cf:
            wins = sorted(((p["id"], p["wins"], p["loses"]) for p in pk if p["wins"] or p["loses"]), key=lambda x: -x[1])
            self.conf_rows.addWidget(hint("Load order result: " + "  \u00b7  ".join(f"{i} wins {w}, loses {l}" for i, w, l in wins)))
        shown = cf if self._conf_all else cf[:12]
        for c in shown:
            row = QWidget(); rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(10)
            cat = CaptionLabel(c["category"]); cat.setFixedWidth(96); tone_label(cat, "muted"); rl.addWidget(cat)
            lab = BodyLabel(c["path"]); lab.setToolTip(c["path"]); rl.addWidget(lab, 1)
            who = hint(f"{c['winner']} wins over " + ", ".join(l["id"] for l in c["losers"])); rl.addWidget(who, 1)
            self.conf_rows.addWidget(row)
        self.conf_more.setVisible(len(cf) > 12); self.conf_more.setText("Show fewer" if self._conf_all else f"Show all {len(cf)}")

    def _fill_mods(self):
        keep_p, keep_n = self.pack_exp.isExpand, self.nat_exp.isExpand
        self._load_profile_settings(); self._scan_conflicts()
        first = not getattr(self, "_mods_seen", False)
        for exp in (self.pack_exp, self.nat_exp):
            while exp.viewLayout.count():
                it = exp.viewLayout.takeAt(0); w = it.widget()
                if w: w.deleteLater()
            exp.widgets.clear()
        s = self.setup
        if not s or not Path(s.profile).is_file():
            self.mods_note.setText("Pick a setup on Play.")
            self.pack_exp.card.setContent("None"); self.nat_exp.card.setContent("None")
            self._mod_group(self.pack_exp, []); self._mod_group(self.nat_exp, [])
            self._load_profile_editor(); return
        mods = profile_entries(s.profile)
        packs = [m for m in mods if m["kind"] == "package"]; nats = [m for m in mods if m["kind"] == "native"]
        self.mods_note.setText(Path(s.profile).name); self.mods_note.setToolTip(s.profile)
        on_p = sum(1 for m in packs if m["enabled"]); on_n = sum(1 for m in nats if m["enabled"])
        self.pack_exp.card.setContent((f"{on_p} loaded" + (f", {len(packs) - on_p} off" if len(packs) != on_p else "")) if packs else "None")
        self.nat_exp.card.setContent((f"{on_n} loaded" + (f", {len(nats) - on_n} off" if len(nats) != on_n else "")) if nats else "None")
        self._mod_group(self.pack_exp, packs); self._mod_group(self.nat_exp, nats)
        self.pack_exp.setExpand(True if first else keep_p); self.nat_exp.setExpand(True if first else keep_n)
        self._mods_seen = True; self._load_profile_editor()

    def _mod_group(self, exp, mods):
        if not mods:
            lab = hint("Nothing in this profile."); lab.setContentsMargins(20, 12, 20, 12); exp.addGroupWidget(lab); return
        for m in mods:
            row = QWidget(); row.setFixedHeight(52); h = QHBoxLayout(row); h.setContentsMargins(20, 0, 20, 0); h.setSpacing(10)
            name = BodyLabel(m["name"]); h.addWidget(name)
            bits = []
            if m["kind"] == "native" and m.get("load_early"): bits.append("early")
            if m.get("load_after"): bits.append("after " + ", ".join(d["id"] for d in m["load_after"]))
            if m.get("load_before"): bits.append("before " + ", ".join(d["id"] for d in m["load_before"]))
            if m.get("initializer"): bits.append("initializer")
            if bits: h.addWidget(hint("  \u00b7  ".join(bits)))
            h.addStretch()
            sw = SwitchButton(); sw.setOnText("On"); sw.setOffText("Off"); sw.setChecked(bool(m.get("enabled", True)))
            sw.checkedChanged.connect(lambda checked, idx=m["index"]: self._toggle_mod(idx, checked)); h.addWidget(sw)
            b = ghost_btn("Options", FI.SETTING); b.clicked.connect(lambda _=False, e=m: self._mod_options(e)); h.addWidget(b)
            b = ghost_btn("", FI.DELETE); b.setToolTip("Remove from the profile, and optionally delete its folder."); b.clicked.connect(lambda _=False, e=m: self._remove_mod(e)); h.addWidget(b)
            if m["path"]: row.setToolTip(m["path"])
            if not m.get("enabled", True): tone_label(name, "muted")
            exp.addGroupWidget(row)

    def _mods_locked(self) -> bool:
        if self.busy:
            self._toast("Wait for the current job", "The profile is not changed while something is running.", error=True); return True
        if not self.setup or not Path(self.setup.profile).is_file():
            self._toast("No profile", "Pick a setup on Play first.", error=True); return True
        if self._profile_file is not None and self.profile_edit.toPlainText() != self._profile_disk:
            self._toast("Profile has unsaved edits", "Save or reload the profile editor first.", error=True); return True
        return False

    def _after_profile_change(self, msg):
        self._log(msg); self._load_profile_editor(force=True); self._fill_mods(); self._update_plan()

    def _toggle_mod(self, index, checked):
        if self._mods_locked(): self._fill_mods(); return
        try:
            set_mod_options(self.setup.profile, index, {"enabled": bool(checked)})
            self._after_profile_change(f"profile: entry {index + 1} {'on' if checked else 'off'}")
        except Exception as e:
            self._toast("Could not change the profile", str(e), error=True); self._fill_mods()

    def _mod_options(self, entry):
        if self._mods_locked(): return
        others = [e["name"] for e in profile_entries(self.setup.profile) if e["index"] != entry["index"]]
        dlg = ModOptionsDialog(entry, others, self)
        if not dlg.exec(): return
        try:
            set_mod_options(self.setup.profile, entry["index"], dlg.options())
            self._after_profile_change(f"profile: options saved for {entry['name']}")
            self._toast("Options saved", f"{entry['name']} applies at the next launch.")
        except Exception as e:
            self._toast("Could not save options", str(e), error=True)

    def _remove_mod(self, entry):
        if self._mods_locked(): return
        where = core.mod_manage.resolve(Path(self.setup.profile), entry["path"]) if entry.get("path") else None
        folder = (where if entry["kind"] == "package" else where.parent) if where else None
        dlg = ConfirmDialog(f"Remove {entry['name']} from the profile", self,
                            changes=[f"The [[{'packages' if entry['kind'] == 'package' else 'natives'}]] entry is deleted from {Path(self.setup.profile).name}"],
                            warning="me3 stops loading it at the next launch. Removing a mod other entries load_after may leave them waiting on a missing id.",
                            safety="The profile keeps a .bak. A deleted folder is gone for good, so leave the box unticked to keep the files.",
                            option=(f"Also delete the folder {folder}" if folder and folder.is_dir() else None), option_checked=False, apply_text="Remove")
        if not dlg.exec(): return
        try:
            out = uninstall_mod(self.setup.profile, entry["index"], delete_folder=dlg.option_on())
            self._after_profile_change(f"profile: removed {entry['name']}" + (" and its folder" if out["removed_folder"] else ""))
            self._toast("Removed", entry["name"] + (" and its folder." if out["removed_folder"] else ". Its files are still on disk."))
        except Exception as e:
            self._toast("Could not remove", str(e), error=True)

    def _install_mod(self):
        if self._mods_locked(): return
        src, _ = QFileDialog.getOpenFileName(self, "Install a mod: pick an archive (or Cancel to pick a folder)", "", "Mod archive (*.zip *.7z *.rar);;All files (*)")
        if not src:
            src = QFileDialog.getExistingDirectory(self, "Install a mod: pick its folder", "")
            if not src: return
        prof = self.setup.profile
        try:
            plan = plan_mod_install(prof, src)
        except Exception as e:
            self._toast("Could not read that", str(e), error=True); return
        if plan.get("error"):
            self._toast("Not a mod Roundtable Souls can install", plan["error"], error=True)
            if plan.get("staging"): core.mod_manage.shutil.rmtree(plan["staging"], ignore_errors=True)
            return
        name_dlg = TextDialog("Install " + ("package" if plan["kind"] == "package" else "native DLL mod"),
                              ("Game folders: " + ", ".join(plan["assets"]) if plan["kind"] == "package" else "DLLs: " + ", ".join(p.name for p in plan["dlls"]))
                              + f"  \u00b7  {plan['size'] / 1048576:.1f} MB", self, placeholder="folder name", text=plan["name"], apply_text="Next")
        if not name_dlg.exec():
            if plan.get("staging"): core.mod_manage.shutil.rmtree(plan["staging"], ignore_errors=True)
            return
        if name_dlg.edit.text().strip() != plan["name"]:
            plan = plan_mod_install(prof, Path(plan["root"]) if plan.get("staging") else src, name_dlg.edit.text().strip()) | ({"staging": plan["staging"]} if plan.get("staging") else {})
        listed = set(plan.get("already_listed") or [])
        changes = ([] if plan.get("in_place") else [f"Copy into {plan['dest']}"]) + [f"Add [[{ 'packages' if e['kind'] == 'package' else 'natives'}]] path = {e['path']}" for e in plan["entries"] if e["path"] not in listed]
        if listed: changes.append("Already in the profile: " + ", ".join(listed) + " (kept as is)")
        if not plan.get("in_place"): changes.append("It goes last in the load order, so it overrides earlier packages on shared files")
        else: changes.append("The folder is already in place; only the profile changes")
        if plan.get("array_form"): changes.append("This profile uses the inline list form; it is rewritten as blocks first")
        if plan.get("exists") and not plan.get("in_place"): changes.append(f"{Path(plan['dest']).name} already exists there and will be replaced")
        if plan.get("in_place") and not [e for e in plan["entries"] if e["path"] not in listed]:
            self._toast("Nothing to do", f"{plan['name']} is already installed and listed in the profile."); return
        if not confirm(self, f"Install {plan['name']}", changes=changes, warning=("The existing folder is deleted and replaced." if plan.get("exists") and not plan.get("in_place") else ""),
                       safety="The profile keeps a .bak. Conflicts rescan afterwards so you see what it overrides before you play.", apply_text="Install"):
            if plan.get("staging"): core.mod_manage.shutil.rmtree(plan["staging"], ignore_errors=True)
            return
        def job(_setup):
            common = core.common; common.start_log(f"launcher: install mod {plan['name']}")
            try:
                install_mod(prof, plan, overwrite=bool(plan.get("exists")))
                common.log(f"done: installed {plan['name']}")
            except Exception as e:
                common.log(f"error: {e}"); raise SystemExit(1) from e
        self.start(job, f"Installing {plan['name']}...", need_setup=False)

    def _new_profile(self):
        cur = self.setup.profile if self.setup and Path(self.setup.profile).is_file() else None
        dlg = TextDialog("New me3 profile", "Created in me3's profile folder with empty mod and natives folders beside it.", self, placeholder="name, e.g. vanilla-plus",
                         option=(f"Start from a copy of {Path(cur).name}" if cur else None), option_checked=False, apply_text="Create")
        if not dlg.exec(): return
        try:
            p = create_profile(dlg.edit.text().strip(), copy_from=cur if (dlg.option is not None and dlg.option.isChecked()) else None)
        except Exception as e:
            self._toast("Could not create the profile", str(e), error=True); return
        self._log(f"profile: created {p}")
        self.setups = discover(str(p)); save_settings(setup=str(p)); self._fill_setups(select=str(p))
        self._toast("Profile created", f"{p.name} is now the setup on Play.")

    def _delete_profile(self):
        if not self.setup or not Path(self.setup.profile).is_file(): self._toast("No profile", "Pick a setup on Play first.", error=True); return
        if self.setup.kind == "revive": self._toast("Not this one", "Revive's profile is managed by its installer; delete it there.", error=True); return
        p = Path(self.setup.profile)
        if not confirm(self, f"Delete {p.name}", changes=[f"{p.name} moves into deleted-profiles beside it", "Mod folders and natives stay where they are"],
                       warning="This setup disappears from the Play list.", safety="The moved file can be copied back by hand at any time.", apply_text="Delete"):
            return
        try:
            gone = delete_profile(p)
        except Exception as e:
            self._toast("Could not delete", str(e), error=True); return
        self._log(f"profile: moved {p.name} to {gone}")
        self.setups = discover(None); save_settings(setup=None); self._fill_setups()
        self._toast("Profile deleted", f"Moved to {gone.parent.name}.")

    def _load_profile_editor(self, force=False):
        path = Path(self.setup.profile) if self.setup and Path(self.setup.profile).is_file() else None
        if path is None:
            self._profile_file = None; self._profile_disk = ""; self._profile_crlf = False
            self.profile_edit.blockSignals(True); self.profile_edit.setPlainText(""); self.profile_edit.blockSignals(False)
            self.profile_path.setText("No me3 profile for this setup."); self.profile_path.setToolTip(""); self._profile_dirty(); return
        dirty = self._profile_file is not None and self.profile_edit.toPlainText() != self._profile_disk
        if dirty and not force and self._profile_file == path: return
        if dirty and force and not MessageBox("Discard edits?", "Reload the profile from disk and lose unsaved edits?", self).exec(): return
        raw = path.read_bytes(); self._profile_crlf = b"\r\n" in raw
        text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        self._profile_file = path; self._profile_disk = text
        self.profile_edit.blockSignals(True); self.profile_edit.setPlainText(text); self.profile_edit.blockSignals(False)
        self.profile_path.setText(path.name); self.profile_path.setToolTip(str(path)); self._profile_dirty()

    def _profile_dirty(self, *_):
        dirty = self._profile_file is not None and self.profile_edit.toPlainText() != self._profile_disk
        self.profile_note.setText("Unsaved edits." if dirty else "Matches the file.")
        self.profile_note.setTextColor(ACCENT_LIGHT if dirty else HINT_ON_LIGHT, ACCENT if dirty else HINT)
        self.profile_save.setEnabled(dirty); self.profile_save.setVisible(dirty); self.profile_reload.setEnabled(self._profile_file is not None)

    def _save_profile(self):
        if self._profile_file is None: return False
        text = self.profile_edit.toPlainText()
        try: core.atomic_write(self._profile_file, text.replace("\n", "\r\n") if self._profile_crlf else text, backup=True)
        except Exception as e: self._toast("Could not save the profile", str(e), error=True); return False
        self._profile_disk = self.profile_edit.toPlainText(); self._profile_dirty()
        self._toast("Profile saved", "It applies the next time you start the game.")
        self._load_coop(); self._fill_mods(); return True

    # ---------------------------------------------------------------- Saves page
    def _build_saves(self):
        self.saves_page, lay = page("savesPage")
        acts = QWidget(); al = QHBoxLayout(acts); al.setContentsMargins(0, 0, 0, 0); al.setSpacing(8)
        al.addWidget(self._folder_btn("saves", "Saves folder", FI.FOLDER, "The folder with ER0000.sl2 / ER0000.co2 and the backup folders."))
        b = ghost_btn("Refresh", FI.SYNC); b.clicked.connect(self.refresh_saves); al.addWidget(b)
        titled(lay, "Saves", FI.SAVE, "Your characters. Optional checks for editors and converting.", acts)
        self.saves_note = hint("Reading saves..."); lay.addWidget(self.saves_note)
        self.backups_card, bl = card("Backups", FI.HISTORY)
        bl.addWidget(hint("Every repair keeps a dated copy of the file as it was. Restore puts one back (the current file is copied first, so a restore can be undone)."))
        self.backups_rows = QVBoxLayout(); self.backups_rows.setSpacing(6); bl.addLayout(self.backups_rows)
        foot = QHBoxLayout(); foot.setSpacing(8)
        self.backups_note = hint(""); foot.addWidget(self.backups_note, 1)
        self.backups_more = ghost_btn("Show all"); self.backups_more.clicked.connect(self._toggle_backups); foot.addWidget(self.backups_more)
        b = ghost_btn("Folder", FI.FOLDER); b.clicked.connect(self._open_backups_folder); foot.addWidget(b); bl.addLayout(foot)
        lay.addWidget(self.backups_card); lay.addStretch(1); self.saves_lay = lay

    # ---------------------------------------------------------------- Tools page
    def _build_tools(self):
        self.tools_page, lay = page("toolsPage"); titled(lay, "Tools", FI.DEVELOPER_TOOLS)
        c, cl = card("Appearance", FI.BRUSH); row = QHBoxLayout(); self.theme_sw = SwitchButton(); self.theme_sw.setOnText("Dark"); self.theme_sw.setOffText("Light"); self.theme_sw.setChecked(self.settings.get("theme", "dark") == "dark")
        self.theme_sw.checkedChanged.connect(self._on_theme); row.addWidget(BodyLabel("Theme")); row.addWidget(self.theme_sw); row.addStretch(); cl.addLayout(row)
        brand = QHBoxLayout(); brand.setSpacing(12)
        self.logo_preview = LogoPreview()
        brand.addWidget(self.logo_preview, 0, Qt.AlignVCenter)
        brand.addWidget(BodyLabel("Logo"), 0, Qt.AlignVCenter)
        self.logo_box = ComboBox(); self.logo_box.addItems(["Follow theme", "Dark", "Light"]); self.logo_box.setMinimumWidth(140)
        mode = self.settings.get("logo", "auto")
        self.logo_box.blockSignals(True); self.logo_box.setCurrentIndex({"auto": 0, "dark": 1, "light": 2}.get(mode, 0)); self.logo_box.blockSignals(False)
        self.logo_box.currentIndexChanged.connect(self._on_logo)
        brand.addWidget(self.logo_box, 0, Qt.AlignVCenter); brand.addStretch(); cl.addLayout(brand)
        cl.addWidget(hint("Follow theme uses the gold plate in dark and the frost plate in light. Windows rounds the square. Dark and Light stay put.")); lay.addWidget(c)
        self._apply_logo()
        c, cl = card("Maintenance", FI.UPDATE)
        b = ghost_btn("Repair", FI.UPDATE); b.clicked.connect(lambda: self.start(job_repair, "Repairing saves...", need_setup=False))
        cl.addWidget(PairRow("Repair saves", "Runs after every session. Use this if the window was closed first.", b))
        b = ghost_btn("Clear", FI.DELETE); b.clicked.connect(lambda: self.start(job_clear, "Clearing leftover processes...", need_setup=False))
        cl.addWidget(PairRow("Leftover processes", "A dead eldenring.exe can make Discord think the game is still open.", b))
        lay.addWidget(c)
        c, cl = card("Play session", FI.PLAY)
        cl.addWidget(hint("What Play does around the game. Each step can be turned off; the launch itself always runs."))
        self.play_sw = {}
        rows = (("play_boot_boost", "Boot boost", "me3 caches the decrypted game archives so the game starts faster.",
                 "Turn off only if a mod misbehaves with the cache; me3 passes --no-boot-boost."),
                ("play_show_logos", "Show intro logos", "Play the publisher logos me3 skips by default.", "Passes --show-logos to me3."),
                ("play_diagnostics", "me3 diagnostics", "Ask me3 for extra diagnostics on this launch (slower start, bigger log).", "Passes --diagnostics; the output lands in me3_launch.log under Logs."),
                ("play_backup_before", "Back up saves before Play", "A dated copy of every save into save-fix-backups, listed under Backups on the Saves page.",
                 "Off by default: the game keeps its own .bak, and each repair makes a copy anyway. Turn it on for a copy before every session."),
                ("play_clear_before", "Clear leftover processes before launch", "Ends dead eldenring.exe shells so Steam agrees to start the game.",
                 "A dead shell is an eldenring.exe with no window. Steam refuses to launch while one exists."),
                ("play_repair_after", "Repair saves after quitting", "Puts the real regulation.bin back in the save block me3 dirties.",
                 "The game does not mind the dirty block; save editors do. Turn this off if you never use editors."),
                ("play_clear_after", "Clear leftover processes after quitting", "Ends dead shells so Discord and Steam stop showing the game as running.",
                 "Needs admin once. Turn it off if you prefer to handle processes yourself."),
                ("warn_dead_shells", "Warn about leftover processes", "The bar at the top of the window when a dead eldenring.exe is found.",
                 "The Clear button on Tools still works with the warning off."))
        for key, title, blurb, help_text in rows:
            sw = SwitchButton(); sw.setOnText("On"); sw.setOffText("Off"); sw.setChecked(bool(self.settings.get(key, PLAY_DEFAULTS[key])))
            sw.checkedChanged.connect(lambda checked, k=key: self._remember_play(k, checked)); self.play_sw[key] = sw
            cl.addWidget(SettingRow(title, blurb, sw, help_text))
        lay.addWidget(c)
        c, cl = card("Locations", FI.FOLDER)
        cl.addWidget(hint("Blank means detect: me3 from PATH or its installer, the game from Steam, profiles from where me3 info says. Set one only when that is wrong for this PC."))
        self.loc = {}
        for key, title, blurb, is_dir, filt in (("me3_path", "me3.exe", "A portable or custom me3 install.", False, "me3 (me3.exe)"),
                                                 ("game_exe", "Game executable", "eldenring.exe outside Steam's usual folder. me3 then launches it directly.", False, "Elden Ring (eldenring.exe)"),
                                                 ("me3_profile_dir", "Profile folder", "Where .me3 profiles are listed from.", True, "")):
            box = QWidget(); bl = QHBoxLayout(box); bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(6)
            lab = hint(str(self.settings.get(key) or "") or "detected"); lab.setMaximumWidth(360); bl.addWidget(lab, 1)
            b = ghost_btn("Browse", FI.FOLDER); b.clicked.connect(lambda _=False, k=key, d=is_dir, f=filt: self._pick_location(k, d, f)); bl.addWidget(b)
            x = ghost_btn("", FI.CANCEL); x.setToolTip("Back to detecting it."); x.clicked.connect(lambda _=False, k=key: self._set_location(k, "")); bl.addWidget(x)
            self.loc[key] = lab
            cl.addWidget(SettingRow(title, blurb, box, blurb))
        lay.addWidget(c)
        c, cl = card("me3", FI.CODE)
        self.me3_line = BodyLabel("Checking me3..."); cl.addWidget(self.me3_line)
        row = QHBoxLayout(); row.setSpacing(8)
        self.me3_dir_btn = ghost_btn("me3 folder", FI.FOLDER); self.me3_dir_btn.setEnabled(False); self.me3_dir_btn.clicked.connect(lambda: os.startfile(self.me3_dir_btn.toolTip())); row.addWidget(self.me3_dir_btn)
        row.addWidget(self._folder_btn("me3", "me3 folder", FI.FOLDER, "Where me3.exe lives."))
        self.me3_logs_btn = ghost_btn("me3 logs", FI.DOCUMENT); self.me3_logs_btn.setEnabled(False); self.me3_logs_btn.clicked.connect(lambda: os.startfile(self.me3_logs_btn.toolTip())); row.addWidget(self.me3_logs_btn)
        self.me3_prof_btn = ghost_btn("Profile folder", FI.FOLDER); self.me3_prof_btn.setEnabled(False); self.me3_prof_btn.clicked.connect(lambda: os.startfile(self.me3_prof_btn.toolTip())); row.addWidget(self.me3_prof_btn)
        b = ghost_btn("Releases", FI.LINK); b.clicked.connect(lambda: os.startfile("https://github.com/garyttierney/me3/releases")); row.addWidget(b)
        b = ghost_btn("Check again", FI.SYNC); b.clicked.connect(self._refresh_me3); row.addWidget(b); row.addStretch(); cl.addLayout(row)
        sw = SwitchButton(); sw.setOnText("On"); sw.setOffText("Off"); sw.setChecked(bool(self.settings.get("check_me3_updates", True)))
        sw.checkedChanged.connect(lambda checked: self._remember_play("check_me3_updates", checked)); self.play_sw["check_me3_updates"] = sw
        cl.addWidget(SettingRow("Check for me3 updates", "Once a day, from GitHub releases. Only a notice; nothing is installed.", sw, "Roundtable Souls never replaces me3 itself: Revive setups ship their own copy."))
        lay.addWidget(c)
        c, cl = card("Save checks", FI.CERTIFICATE)
        self.tarn_box = ComboBox(); self.tarn_box.addItems(["Read the save (default)", "Always vanilla", "Never vanilla"]); self.tarn_box.setMinimumWidth(190)
        cur = str(self.settings.get("tarnished_owned", "auto")).lower(); self.tarn_box.setCurrentIndex({"yes": 1, "no": 2}.get(cur, 0))
        self.tarn_box.currentIndexChanged.connect(self._on_tarnished)
        self.dlc_box = ComboBox(); self.dlc_box.addItems(["Check the game folder (default)", "Installed", "Not installed"]); self.dlc_box.setMinimumWidth(190)
        cur = str(self.settings.get("dlc_owned", "auto")).lower(); self.dlc_box.setCurrentIndex({"yes": 1, "no": 2}.get(cur, 0))
        self.dlc_box.currentIndexChanged.connect(self._on_dlc)
        cl.addWidget(SettingRow("Shadow of the Erdtree", "Decides whether DLC items and places count as part of the game for these saves.", self.dlc_box,
                                "By default Roundtable Souls looks for DLC.bdt next to eldenring.exe on this PC. Set Not installed when checking a save for someone without the DLC: their DLC items then show under Remove mod items, and standing in the Land of Shadow is a loading risk."))
        cl.addWidget(SettingRow("Tarnished Edition gear", "Official paid content. Counts as vanilla when the pack flag is set on the save.", self.tarn_box,
                                "The Tarnished Edition pack sets a flag in every character that owns it; Roundtable Souls reads that flag. Always / Never override it, for a save that has the gear without the flag, or one you want checked as plain vanilla."))
        lay.addWidget(c)
        offline = ExpandGroupSettingCard(FI.CLOUD, "Offline play", "Solo on the standard save.")
        body = QWidget(); bl = QVBoxLayout(body); bl.setContentsMargins(8, 4, 8, 12); bl.setSpacing(4)
        bl.addWidget(hint("Starts this setup without Seamless, so the game uses the standard save. Steam still needs to be running; pick Start in Offline Mode if it asks. Co-op needs Steam online."))
        self.off_revive = SwitchButton(); self.off_revive.setOnText("On"); self.off_revive.setOffText("Off")
        self.off_revive.setChecked(bool(self.settings.get("offline_strip_revive", False)))
        self.off_steam = SwitchButton(); self.off_steam.setOnText("On"); self.off_steam.setOffText("Off")
        self.off_steam.setChecked(bool(self.settings.get("offline_start_steam", True)))
        self.off_quiet = SwitchButton(); self.off_quiet.setOnText("On"); self.off_quiet.setOffText("Off")
        self.off_quiet.setChecked(bool(self.settings.get("offline_skip_confirm", False)))
        bl.addWidget(SettingRow("Skip Revive too", "Leave Nightreign Revive off for this launch.", self.off_revive,
                                "Turns Revive packages and natives off in a temporary copy. Your real profile is not changed."))
        bl.addWidget(SettingRow("Start Steam if needed", "Open Steam before launch if it is not running.", self.off_steam,
                                "Turn this off if Steam is already open. Seamless still stays off."))
        bl.addWidget(SettingRow("Skip the confirmation", "Go straight to launch next time.", self.off_quiet,
                                "Stops the Play offline prompt. You can turn this back off here."))
        for sw in (self.off_revive, self.off_steam, self.off_quiet):
            sw.checkedChanged.connect(self._remember_offline)
        row = QHBoxLayout(); b = ghost_btn("Play offline", FI.PLAY); b.clicked.connect(self.launch_offline); row.addWidget(b); row.addStretch(); bl.addLayout(row)
        offline.addGroupWidget(body); lay.addWidget(offline); self.offline_exp = offline
        files = ExpandGroupSettingCard(FI.FOLDER, "Folders", "me3, the game, your saves, and this launcher's own files.")
        body = QWidget(); bl = QVBoxLayout(body); bl.setContentsMargins(16, 8, 16, 12)
        row = FlowLayout(needAni=False); row.setContentsMargins(0, 0, 0, 0); row.setHorizontalSpacing(8); row.setVerticalSpacing(8)
        row.addWidget(self._folder_btn("me3", "me3", FI.CODE, "Where me3.exe lives."))
        row.addWidget(self._folder_btn("game", "Game", FI.GAME, "The folder with eldenring.exe: ReShade, ERSS and regulation.bin live here."))
        row.addWidget(self._folder_btn("saves", "Saves", FI.SAVE, "The folder with ER0000.sl2 / ER0000.co2 and the backup folders."))
        b = ghost_btn("Logs", FI.DOCUMENT); b.setToolTip("The launcher's own logs."); b.clicked.connect(lambda: (LOGS.mkdir(parents=True, exist_ok=True), os.startfile(str(LOGS)))); row.addWidget(b)
        b = ghost_btn("Data", FI.FOLDER); b.setToolTip("Roundtable Souls's settings file."); b.clicked.connect(lambda: os.startfile(str(core.DATA_DIR))); row.addWidget(b); bl.addLayout(row)
        where = "Next to this exe." if core.DATA_DIR == core.HERE else "In this Windows account's app data."
        p = hint(where); p.setToolTip(str(core.DATA_DIR)); bl.addWidget(p); files.addGroupWidget(body); lay.addWidget(files)
        lay.addWidget(hint(f"{TITLE} {VERSION}")); lay.addStretch(1)

    # ---------------------------------------------------------------- setups
    def _fill_setups(self, select=None):
        self._loading_setups = True; self.setup_box.blockSignals(True); self.setup_box.clear()
        for s in self.setups: self.setup_box.addItem(s.label)
        pick = select or self.settings.get("setup"); idx = next((i for i, s in enumerate(self.setups) if pick and s.source.lower() == str(pick).lower()), 0)
        if self.setups: self.setup_box.setCurrentIndex(idx)
        self.setup_box.blockSignals(False); self._on_setup(); self._loading_setups = False

    def _on_setup(self, *_):
        s = self.setups[self.setup_box.currentIndex()] if self.setups and self.setup_box.currentIndex() >= 0 else None; self.setup = s
        if not s:
            self.setup_hint.setText("Browse to a .me3 profile, or to an installation.json from a launcher such as Nightreign Revive.")
            self.setup_exp.card.setContent("None"); self.setup_exp.setExpand(True)
            self.play_btn.setEnabled(False); self.ini = None; self._load_coop(); self._fill_mods(); return
        probs = s.problems()
        if probs:
            self.setup_hint.setText("Cannot launch: " + "; ".join(short_problem(p) for p in probs)); self.setup_hint.setToolTip("\n".join(probs))
            self.setup_exp.card.setContent("Cannot launch")
        else:
            me3 = s.me3_path(); game = Path(s.exe).name if s.exe else "Elden Ring"
            self.setup_hint.setText(f"{me3.name if me3 else 'me3 not found'}  ·  {game}")
            self.setup_hint.setToolTip(s.summary()); self.setup_exp.card.setContent(s.label)
        self.setup_hint.setTextColor("#963C48" if probs else HINT_ON_LIGHT, "#E08A7A" if probs else HINT)
        self.setup_exp.setExpand(bool(probs))
        self.play_btn.setEnabled(not probs and not self.game_running and not self.busy); self.ini = s.ini; self._load_coop(); self._fill_mods(); self._update_plan()
        if getattr(self, "me3_line", None) is not None: self._refresh_me3()
        remembered = str(self.settings.get("setup") or "")
        if remembered.lower() != s.source.lower():
            save_settings(setup=s.source); self.settings["setup"] = s.source

    def _update_plan(self):
        s = self.setup
        if not s: self.plan.setText(""); return
        bits = ["me3"]
        if self.ini: bits.append("Seamless Co-op")
        ids = {m["id"].lower() for m in read_profile_mods(s.profile)} if Path(s.profile).is_file() else set()
        revive = s.kind == "revive" or (Path(s.profile).parent / "NightreignRevive").is_dir() or "nightreign-revive" in ids or "reviveprototype.dll" in ids
        if revive: bits.append("Revive")
        f = getattr(self, "_me3", None) or {}
        if f.get("update") and (f.get("latest") or {}).get("version"): bits.append(f"me3 {f['latest']['version']} available (Tools)")
        if self.ini and self._coop_pending():
            self.plan.setText(" · ".join(bits) + "  ·  unsaved co-op changes apply when you press Play")
            self.plan.setTextColor(ACCENT_LIGHT, ACCENT)
        else:
            self.plan.setText(" · ".join(bits) + ". Leave this open while you play.")
            self.plan.setTextColor(HINT_ON_LIGHT, HINT)

    def browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "Pick a me3 profile", str(core.common.me3_profiles_dir() or core.HERE), "me3 profile or installation.json (*.me3 *.json);;All files (*.*)")
        if not p: return
        s = setup_from_path(p)
        if not s: self._toast("Not a setup", "That file is not a .me3 profile, and it is not a launcher installation.json.", error=True); return
        if s.source.lower() not in {x.source.lower() for x in self.setups}: self.setups.append(s)
        self._fill_setups(select=s.source)

    # ---------------------------------------------------------------- co-op
    def _load_coop(self):
        ini = self.ini; on = ini is not None
        self.coop_off.setVisible(not on)
        for w in self.coop_form: w.setVisible(on)
        self.coop_bar.setVisible(on)
        for w in (self.pw, self.preset, self.share): w.setEnabled(on)
        if not on:
            self.pw.blockSignals(True); self.pw.setText(""); self.pw.blockSignals(False); self.pw_file = None; self.scaling_file = None
            self.scal_hint.setText(""); self.share.setPlainText("")
            for sp in self.spins: sp.setEnabled(False)
            self._refresh_coop_actions(); return
        self.pw_file = read_password(ini); self.pw.blockSignals(True); self.pw.setText(self.pw_file or ""); self.pw.blockSignals(False); self._on_pw_edit()
        self.scaling_file = read_scaling(ini)
        if self.scaling_file is None: self.preset.setEnabled(False); self.scal_hint.setText("No [SCALING] section in this ersc_settings.ini.")
        else:
            name = preset_of(self.scaling_file); self.preset.blockSignals(True); self.preset.setCurrentText(name); self.preset.blockSignals(False); self._set_spins(self.scaling_file, name == CUSTOM); self._on_scaling_edit()
        self.share_fill(); self._fill_all_settings()

    def _fill_all_settings(self):
        """Rebuild the section expanders from the file. Sections the quick cards already cover are skipped."""
        while self.all_box.count():
            it = self.all_box.takeAt(0); w = it.widget()
            if w: w.deleteLater()
        self.all_dirty = {}; self.all_file = {}; self._all_dirty_changed()
        if self.ini is None: return
        for sec in read_settings_meta(self.ini):
            items = [i for i in sec["items"] if sec["section"].upper() not in ("PASSWORD", "SCALING")]
            if not items: continue
            icon = {"GAMEPLAY": FI.GAME, "SAVE": FI.SAVE, "LANGUAGE": FI.LANGUAGE}.get(sec["section"].upper(), FI.SETTING)
            sub = {"GAMEPLAY": "What the session feels like", "SAVE": "Which file Seamless writes", "LANGUAGE": "Locale override"}.get(sec["section"].upper(), count_label(len(items), "setting"))
            exp = ExpandGroupSettingCard(icon, sec["title"], sub)
            for it in items:
                self.all_file[it["key"]] = it["value"]; exp.addGroupWidget(self._setting_row(it))
            self.all_box.addWidget(exp)
        self.other_host.setVisible(self.ini is not None and self.all_box.count() > 0)

    def _setting_row(self, it):
        """One form row. The control shows familiar words; the ini value is written behind the scenes."""
        key, kind, val = it["key"], it["kind"], it["value"].strip()
        title, blurb, help_text = setting_face(key, it["desc"])
        def mark(new): self._mark_dirty(key, str(new))
        if key == "default_boot_master_volume":
            w = ComboBox(); labels = [lab for _, lab in VOLUME_STOPS]; nums = [n for n, _ in VOLUME_STOPS]
            w.addItems(labels); w.setMinimumWidth(140); w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            n = int(val) if val.lstrip("-").isdigit() else 5
            nearest = min(nums, key=lambda x: abs(x - n)); w.setCurrentIndex(nums.index(nearest))
            w.currentIndexChanged.connect(lambda i, ns=nums: mark(ns[i]))
        elif key == "save_file_extension" and val in {k for k, _ in SAVE_KINDS}:
            w = ComboBox(); kinds = [k for k, _ in SAVE_KINDS]; w.addItems([lab for _, lab in SAVE_KINDS])
            w.setMinimumWidth(140); w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            w.setCurrentIndex(kinds.index(val)); w.currentIndexChanged.connect(lambda i, ks=kinds: mark(ks[i]))
        elif kind == "bool":
            w = SwitchButton(); w.setOnText("On"); w.setOffText("Off"); w.setChecked(val == "1"); w.checkedChanged.connect(lambda on: mark(1 if on else 0))
        elif kind == "choice":
            w = ComboBox(); labels = [choice_label(key, n, lab) for n, lab in it["extra"]]; w.addItems(labels)
            w.setMinimumWidth(200); w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            nums = [n for n, _ in it["extra"]]; w.setCurrentIndex(nums.index(int(val)) if val.lstrip("-").isdigit() and int(val) in nums else 0)
            w.setToolTip(w.currentText()); w.currentIndexChanged.connect(lambda i, box=w, ns=nums: (box.setToolTip(box.itemText(i)), mark(ns[i])))
        elif kind == "int":
            w = SpinBox(); lo, hi = it["extra"]; w.setRange(lo, hi); w.setValue(int(val) if val.lstrip("-").isdigit() else lo)
            w.setMinimumWidth(96); w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed); w.valueChanged.connect(mark)
        else:
            w = LineEdit(); w.setText(val); w.setMinimumWidth(140); w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            w.setPlaceholderText("Game default" if key == "mod_language_override" else "")
            w.textChanged.connect(lambda t: mark(t.strip()))
        return SettingRow(title, blurb, w, help_text)

    def _mark_dirty(self, key, new):
        if new == self.all_file.get(key): self.all_dirty.pop(key, None)
        else: self.all_dirty[key] = new
        self._all_dirty_changed()

    def _all_dirty_changed(self):
        self._refresh_coop_actions(); self._update_plan()

    def _on_pw_edit(self, *_):
        if self.ini is None: return
        changed = self.pw.text().strip() != (self.pw_file or "")
        self.pw_hint.setText("Not saved yet." if changed else "Friends type this to join.")
        self.pw_hint.setTextColor(ACCENT_LIGHT if changed else HINT_ON_LIGHT, ACCENT if changed else HINT); self._refresh_coop_actions(); self._update_plan()

    def _scaling_values(self): return tuple(sp.value() for sp in self.spins)

    def _set_spins(self, values, enabled):
        for sp, v in zip(self.spins, values): sp.blockSignals(True); sp.setValue(int(v)); sp.blockSignals(False); sp.setEnabled(enabled)

    def _on_preset(self, name):
        if self.scaling_file is None: return
        if name in SCALING_PRESETS: self._set_spins(SCALING_PRESETS[name], False)
        else: self._set_spins(self._scaling_values() or self.scaling_file, True)
        self._on_scaling_edit()

    def _on_scaling_edit(self, *_):
        if self.scaling_file is None: return
        changed = self._scaling_values() != self.scaling_file
        self.scal_hint.setText("Not saved yet." if changed else "")
        self.scal_hint.setTextColor(ACCENT_LIGHT if changed else HINT_ON_LIGHT, ACCENT if changed else HINT); self._refresh_coop_actions(); self._update_plan()

    def _coop_pending(self):
        if self.ini is None or not hasattr(self, "pw"): return False
        pw = self.pw.text().strip() != (self.pw_file or "")
        scal = self.scaling_file is not None and self._scaling_values() != self.scaling_file
        return pw or scal or bool(getattr(self, "all_dirty", None))

    def _pending_labels(self):
        if self.ini is None: return []
        labels = []
        if self.pw.text().strip() != (self.pw_file or ""): labels.append("Password")
        if self.scaling_file is not None and self._scaling_values() != self.scaling_file: labels.append("Difficulty")
        labels.extend(label_of(k) for k in getattr(self, "all_dirty", {}))
        return labels

    def _refresh_coop_actions(self):
        if not hasattr(self, "all_save"): return
        labels = self._pending_labels(); pending = bool(labels)
        self.all_save.setEnabled(pending); self.all_discard.setEnabled(pending)
        self.save_bar.pending = pending; self.save_bar.update()
        if not pending: text = "Saved."
        else:
            shown = ", ".join(labels[:4]) + (" ..." if len(labels) > 4 else "")
            text = "Not saved: " + shown
        self.all_note.setText(text); self.all_note.setTextColor(ACCENT_LIGHT if pending else HINT_ON_LIGHT, ACCENT if pending else HINT)

    def _discard_coop(self):
        self._load_coop(); self._toast("Changes discarded", "Co-op settings are back to what is in the file.", info=True)

    def save_seamless(self):
        """Write password, scaling, and any other edited co-op settings. Returns what was written, or None if the write failed."""
        if self.ini is None: return []
        new = self.pw.text().strip()
        if self.pw.text().strip() != (self.pw_file or "") and not new:
            self._toast("Password needed", "The Seamless Co-op password cannot be empty.", error=True); return None
        wrote = []
        if new != (self.pw_file or ""):
            try: write_password(self.ini, new); self.pw_file = new; self._on_pw_edit(); self._log(f"password changed in {self.ini}")
            except Exception as e: self._toast("Could not write the password", str(e), error=True); return None
            wrote.append("Password")
        if self.scaling_file is not None and self._scaling_values() != self.scaling_file:
            vals = self._scaling_values(); missing = write_keys(self.ini, dict(zip(SCALING_KEYS, vals)))
            if missing: self._toast("Missing keys", "Not in ersc_settings.ini: " + ", ".join(missing), error=True); return None
            self.scaling_file = vals; self._on_scaling_edit(); self._log("scaling changed to " + ", ".join(f"{l} {v}%" for l, v in zip(SCALING_LABELS, vals)))
            wrote.append("Difficulty")
        if self.all_dirty:
            labels = [label_of(k) for k in self.all_dirty]; missing = write_keys(self.ini, dict(self.all_dirty))
            if missing: self._toast("Missing keys", "Not in ersc_settings.ini: " + ", ".join(missing), error=True); return None
            self._log("settings changed: " + ", ".join(f"{k}={v}" for k, v in self.all_dirty.items())); wrote.extend(labels); self._fill_all_settings()
        self.share_fill(); self._refresh_coop_actions(); return wrote

    def _announce_saved(self, wrote, when):
        """Toast after a co-op save. when is 'next' (saved for the following launch) or 'play' (this launch uses them)."""
        if wrote is None: return False
        if not wrote: return True
        shown = wrote[:3]
        if len(wrote) == 1: what = wrote[0]
        elif len(wrote) == 2: what = f"{wrote[0]} and {wrote[1]}"
        elif len(wrote) == 3: what = f"{wrote[0]}, {wrote[1]}, and {wrote[2]}"
        else: what = f"{shown[0]}, {shown[1]}, and {len(wrote) - 2} more"
        if when == "play": self._toast("Settings applied", f"{what}. This session will use them.")
        else: self._toast("Settings saved", f"{what}. They apply the next time you start the game.")
        return True

    def share_fill(self):
        if self.ini: self.share.setPlainText(export_text(self.ini)); self.share_hint.setText("Current settings.")
    def share_copy(self):
        QApplication.clipboard().setText(self.share.toPlainText()); self.share_hint.setText("Copied. Paste it to your friend."); self._toast("Copied", "Settings are on the clipboard.")
    def share_paste(self):
        t = QApplication.clipboard().text()
        if not t.strip(): self.share_hint.setText("The clipboard has no text."); self._toast("Clipboard is empty", "Copy settings from your friend first.", info=True); return
        self.share.setPlainText(t); self.share_hint.setText("Pasted. Click Apply to use these settings."); self._toast("Pasted", "Click Apply to use these settings.", info=True)
    def share_apply(self):
        if self.ini is None: return
        try: incoming = parse_settings_json(self.share.toPlainText())
        except Exception as e: self.share_hint.setText(f"That is not valid settings text: {e}"); return
        changes, unknown = plan_import(self.ini, incoming)
        if not changes: self._toast("Nothing to change", "It matches your current settings." + (f" Ignored: {', '.join(unknown)}" if unknown else ""), info=True); return
        if not confirm(self, f"Apply {len(changes)} setting{'s' if len(changes) != 1 else ''} from the pasted text",
                       changes=[f"{k}:  {o}  \u2192  {n}" for k, (o, n) in changes.items()],
                       detail=(f"Ignored (not in your file): {', '.join(unknown)}" if unknown else ""),
                       safety="They apply the next time the game starts. The ini keeps a .bak of the previous version.", apply_text="Apply"): return
        try: write_keys(self.ini, {k: n for k, (o, n) in changes.items()})
        except Exception as e: self._toast("Could not write", str(e), error=True); return
        self._log("applied " + ", ".join(f"{k}={n}" for k, (o, n) in changes.items())); self._load_coop(); self._toast("Settings applied", f"{len(changes)} setting" + ("s" if len(changes) != 1 else "") + ". They apply the next time you start the game.")
    def share_save(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save settings as", "seamless-coop-settings.json", "Settings export (*.json)")
        if p: Path(p).write_text(self.share.toPlainText(), encoding="utf-8"); self.share_hint.setText(f"Saved {Path(p).name}."); self._toast("File saved", Path(p).name)
    def share_load(self):
        p, _ = QFileDialog.getOpenFileName(self, "Load settings file", "", "Settings export (*.json)")
        if p: self.share.setPlainText(Path(p).read_text(encoding="utf-8")); self.share_hint.setText(f"Loaded {Path(p).name}. Click Apply to use these settings."); self._toast("File loaded", "Click Apply to use these settings.", info=True)

    # ---------------------------------------------------------------- saves
    def refresh_saves(self):
        self.saves_note.setText("Reading saves...")
        def work(): self.bus.saves.emit([save_info(p) for p in core.common.save_files()])
        threading.Thread(target=work, daemon=True).start()

    def _fill_saves(self, infos):
        self.saves = infos
        for w in getattr(self, "_save_cards", []):
            self.saves_lay.removeWidget(w); w.deleteLater()
        self._save_cards = []
        if infos:
            n_bad = sum(1 for s in infos if s.get("needs_repair"))
            note = count_label(len(infos), "save")
            if n_bad and not self.game_running:
                note += f"  ·  {n_bad} can be repaired for editors"
            self.saves_note.setText(note); self.saves_note.setToolTip(str(infos[0]["path"].parent))
            tone_label(self.saves_note, "muted")
        else:
            self.saves_note.setText("No Elden Ring saves in this Windows account."); self.saves_note.setToolTip(""); tone_label(self.saves_note)
        self._update_saves_badge(sum(1 for s in infos if repair_available(s)) if not self.game_running else 0)

        # Co-op first when present — that is what you play.
        ordered = sorted(infos, key=lambda s: 0 if s.get("kind") == "Seamless Co-op" else 1)

        for s in ordered:
            icon = FI.PEOPLE if s["kind"] == "Seamless Co-op" else FI.GAME
            c, cl = card()
            cl.setSpacing(14)
            head = QHBoxLayout(); head.setSpacing(10)
            ic = IconWidget(icon); ic.setFixedSize(20, 20); head.addWidget(ic, 0, Qt.AlignTop)
            titles = QVBoxLayout(); titles.setSpacing(2); titles.setContentsMargins(0, 0, 0, 0)
            titles.addWidget(StrongBodyLabel(s["kind"]))
            sub = f"{s['name']}  ·  {s['modified']}"
            if s.get("needs_repair") and not self.game_running:
                sub += "  ·  repair available"
            elif s.get("needs_repair") and self.game_running:
                sub += "  ·  repair after you quit"
            titles.addWidget(hint(sub))
            chips = QHBoxLayout(); chips.setSpacing(12); chips.setContentsMargins(0, 4, 0, 0)
            for text, tone in save_summary(s):
                c_lab = CaptionLabel(("\u2713  " if tone == "success" else "\u26a0  " if tone == "warn" else "\u2022  ") + text)
                tone_label(c_lab, "success" if tone == "success" else "error" if tone == "warn" else "muted"); chips.addWidget(c_lab)
            chips.addStretch(); titles.addLayout(chips)
            head.addLayout(titles, 1); cl.addLayout(head)

            if s["error"] and not s.get("characters") and not s.get("findings"):
                cl.addWidget(hint(f"Could not read this file: {s['error']}"))
            elif s["characters"]:
                t = TableWidget(); t.setColumnCount(6); t.setHorizontalHeaderLabels(["Slot", "Character", "Level", "Body", "Max HP", "Runes held"]); t.setRowCount(len(s["characters"])); t.verticalHeader().hide(); t.setEditTriggers(TableWidget.NoEditTriggers); t.setSelectionMode(TableWidget.NoSelection)
                t.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff); t.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                for r, ch in enumerate(s["characters"]):
                    for col, val in enumerate((ch["slot"], ch["name"] + ("" if ch["ok"] else "  (checksum)"), ch["level"], ch["body"], f"{ch['hp']:,}", f"{ch['runes']:,}")):
                        it = QTableWidgetItem(str(val)); it.setTextAlignment(Qt.AlignCenter if col in (0, 3) else (Qt.AlignRight | Qt.AlignVCenter) if col in (2, 4, 5) else (Qt.AlignLeft | Qt.AlignVCenter)); t.setItem(r, col, it)
                t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch); t.resizeColumnsToContents()
                table_h = t.horizontalHeader().height() + 38 * max(1, len(s["characters"])) + 8; t.setFixedHeight(table_h); cl.addWidget(t)
            else:
                cl.addWidget(hint("No active characters in this file."))

            notes = save_check_notes(s)
            if notes:
                cl.addWidget(hint("Worth knowing"))
                for n in notes:
                    cl.addWidget(_save_note_widget(n))
            else:
                cl.addWidget(hint("Looks fine for play."))

            row = FlowLayout(needAni=False); row.setContentsMargins(0, 4, 0, 0); row.setHorizontalSpacing(8); row.setVerticalSpacing(8)
            if s.get("characters"):
                fixable = repair_available(s) and not self.game_running
                b = primary_btn("Review && fix") if fixable else ghost_btn("Review", FI.VIEW)
                if fixable: b.setMinimumHeight(34)
                b.setToolTip("Open this save: every character, every finding, and tick boxes for each fix. Nothing changes until you press Apply.")
                b.clicked.connect(lambda _=False, info=s: self.open_workshop(info)); row.addWidget(b)
            b = ghost_btn("Copy report", FI.COPY); b.setToolTip("Full plain-text check for sharing or notes.")
            b.clicked.connect(lambda _=False, info=s: self._copy_health_report(info)); row.addWidget(b)
            if s["kind"] == "Seamless Co-op" and not self.game_running:
                b = ghost_btn("To .sl2", FI.SAVE_AS); b.setToolTip("Make a standard-save copy. Best when the check is clear.")
                b.clicked.connect(lambda _=False, p=s["path"], ok=s.get("convert_ok"): self._convert_co2(p, ok)); row.addWidget(b)
            b = ghost_btn("Folder", FI.FOLDER); b.clicked.connect(lambda _=False, p=s["path"]: os.startfile(str(p.parent))); row.addWidget(b)
            cl.addLayout(row)

            self.saves_lay.insertWidget(self.saves_lay.indexOf(self.backups_card), c); self._save_cards.append(c)

        self._fill_backups(); self._ws_refresh(infos)
        pick = next((s for s in ordered if s["kind"] == "Seamless Co-op" and s["characters"]), None) or next((s for s in ordered if s["characters"]), None)
        if pick and pick["characters"]:
            ch = pick["characters"][0]; self.hero.name.setText(ch["name"])
            extra = f"  ·  {len(pick['characters'])} characters" if len(pick["characters"]) > 1 else ""
            self.hero.sub.setText(f"Last played {pick['modified']}{extra}")
            self.stat_level.value.setText(str(ch["level"]))
            self.stat_save.value.setText("Co-op" if pick["kind"] == "Seamless Co-op" else pick["kind"]); self.stat_save.value.setToolTip(pick["kind"])
            self.stat_body.value.setText(ch["body"]); self.stat_body.value.setToolTip(ch["body"])
        else:
            self.hero.name.setText("No characters yet"); self.hero.sub.setText("Your saves show here once you have played.")
            for s in (self.stat_level, self.stat_save, self.stat_body): s.value.setText("—")

    def _copy_health_report(self, info):
        try:
            text = health_report(info=info)
            QApplication.clipboard().setText(text)
            self._toast("Copied", f"Report for {info.get('name', 'save')} is on the clipboard.")
        except Exception as e:
            self._toast("Could not copy", str(e), error=True)

    def _convert_co2(self, path, convert_ok):
        if self.busy or self.game_running:
            self._toast("Cannot convert now", "Close Elden Ring first." if self.game_running else "Wait for the current job.", error=True); return
        path = Path(path)
        dest = path.with_suffix(".sl2")
        force = False
        changes = [f"{path.name} is copied to {dest.name}", "The .co2 itself is left alone"]
        if dest.exists(): changes.append(f"{dest.name} already exists and is backed up first")
        if not convert_ok:
            if not confirm(self, "Copy to a standard save with notes still open", changes=changes,
                           warning="This co-op save still has notes on the Saves page (mod items, quest flags, or repair). A standard .sl2 copy carries them over.",
                           safety="Anything overwritten goes into co2-to-sl2-backups first, with a copy of the source.", apply_text="Copy anyway"):
                return
            force = True
        else:
            if not confirm(self, "Make a standard copy", changes=changes, safety="Anything overwritten goes into co2-to-sl2-backups first, with a copy of the source.",
                           detail="Use the standard save when Seamless is off.", apply_text="Copy"):
                return
        def job(_setup):
            common = core.common
            common.start_log(f"launcher: convert {path.name} -> .sl2")
            try:
                out = convert_co2_to_sl2(path, dest, force=force)
                common.log(f"done: wrote {out}")
            except Exception as e:
                common.log(f"error: {e}"); raise SystemExit(1) from e
        self.start(job, f"Converting {path.name}...", need_setup=False)

    def _update_saves_badge(self, n):
        """Count on the Saves nav item only when Roundtable Souls can repair something (never for mod-item notes)."""
        if n > 0 and self.saves_badge is None:
            try:
                target = self.navigationInterface.widget(self.saves_page.objectName())
                self.saves_badge = InfoBadge.attension(str(n), parent=self.navigationInterface, target=target, position=InfoBadgePosition.NAVIGATION_ITEM)
            except Exception:
                self.saves_badge = None
        elif n > 0 and self.saves_badge is not None:
            self.saves_badge.setText(str(n))
        elif n == 0 and self.saves_badge is not None:
            try: self.saves_badge.hide(); self.saves_badge.deleteLater()
            except Exception: pass
            self.saves_badge = None

    def _fix_loading_one(self, path, plan):
        if self.busy or self.game_running:
            self._toast("Cannot fix now", "Close Elden Ring first." if self.game_running else "Wait for the current job.", error=True); return
        path = Path(path)
        groups = []
        for p in plan:
            who = p.get("name") or f"slot {p['slot'] + 1}"
            items = [{"key": (p["slot"], k), "label": label, "sub": action} for k, label, action in zip(p["issues"], p["labels"], p["actions"])]
            groups.append({"title": who, "subtitle": f"{len(items)} fix{'es' if len(items) != 1 else ''}", "items": items})
        def summarize(keys):
            chars = {k[0] for k in keys}
            return f"Apply {len(keys)} fix{'es' if len(keys) != 1 else ''} on {len(chars)} character{'s' if len(chars) != 1 else ''}. Progress, items and flags stay as they are."
        dlg = ChoiceDialog("Fix loading", WRITE_WARNING, groups, self, apply_text="Fix selected", summarize=summarize)
        if not dlg.exec():
            return
        selection = {}
        for slot, key in dlg.selected():
            selection.setdefault(slot, []).append(key)
        def job(_setup):
            common = core.common
            common.start_log(f"launcher: fix loading {path.name}")
            try:
                out = fix_loading(path, selection=selection)
                n = len(out.get("fixed") or [])
                common.log(f"done: fixed {n} character{'s' if n != 1 else ''} in {path.name}")
            except Exception as e:
                common.log(f"error: {e}"); raise SystemExit(1) from e
        self.start(job, f"Fixing loading in {path.name}...", need_setup=False)
    def _restore_one(self, path, plan):
        if self.busy or self.game_running:
            self._toast("Cannot restore now", "Close Elden Ring first." if self.game_running else "Wait for the current job.", error=True); return
        path = Path(path)
        groups = []
        for p in plan:
            who = p.get("name") or f"slot {p['slot'] + 1}"
            items = []
            by_src = {}
            for e in p.get("strip") or []:
                by_src.setdefault(e.get("source") or "Other mod", []).append(e)
            for src, entries in by_src.items():
                for e in entries:
                    where = "chest" if e["box"] == "storage" else "held"
                    if e.get("pouch"): where += ", in the pouch"
                    elif e.get("quick"): where += ", in a quick slot"
                    items.append({"key": ("item", p["slot"], e["handle"]), "label": e["name"] + (f"  x{e['qty']}" if e["qty"] > 1 else ""),
                                  "section": src, "sub": where, "checked": True})
            for b in p.get("blocked") or []:
                items.append({"key": ("blocked", p["slot"], b.get("handle")), "label": b["name"], "section": b.get("source") or "Other mod",
                              "checked": False, "enabled": False, "note": "worn: take it off in-game first" if b.get("why") == "worn" else "remove the ash in-game first"})
            if p.get("orphans"):
                n_o = len(p["orphans"])
                items.append({"key": ("orphans", p["slot"]), "label": f"Clear {n_o} leftover item row{'s' if n_o != 1 else ''} nothing holds",
                              "section": "Cleanup", "sub": "invisible in play; leftovers from partners' gear", "checked": True})
            for k, label in zip(p.get("quest") or [], p.get("quest_labels") or []):
                items.append({"key": ("quest", p["slot"], k), "label": f"Fix: {label}", "section": "Quest flags", "sub": core.save_analyze.FLAG_FIX_TEXT.get(k, ""), "checked": True})
            n_items = sum(1 for it in items if it["key"][0] == "item")
            groups.append({"title": who, "subtitle": f"{n_items} item{'s' if n_items != 1 else ''}", "items": items})
        def summarize(keys):
            items = [k for k in keys if k[0] == "item"]; rows = [k for k in keys if k[0] == "orphans"]; quest = [k for k in keys if k[0] == "quest"]
            chars = {k[1] for k in keys}
            bits = []
            if items: bits.append(f"remove {len(items)} item{'s' if len(items) != 1 else ''}")
            if rows: bits.append(f"clear leftover rows on {len(rows)} character{'s' if len(rows) != 1 else ''}")
            if quest: bits.append(f"fix {len(quest)} quest flag{'s' if len(quest) != 1 else ''}")
            return f"Apply: {', '.join(bits)} across {len(chars)} character{'s' if len(chars) != 1 else ''}. Removed items are gone from this file; the mods give them back."
        dlg = ChoiceDialog("Restore vanilla", WRITE_WARNING, groups, self, apply_text="Apply selected", summarize=summarize)
        if not dlg.exec():
            return
        selection = {}
        for key in dlg.selected():
            sel = selection.setdefault(key[1], {"items": set(), "orphans": False, "quest": []})
            if key[0] == "item": sel["items"].add(key[2])
            elif key[0] == "orphans": sel["orphans"] = True
            elif key[0] == "quest": sel["quest"].append(key[2])
        def job(_setup):
            common = core.common
            common.start_log(f"launcher: restore vanilla {path.name}")
            try:
                out = restore_vanilla(path, selection=selection)
                n = sum(d.get("removed", 0) for d in out.get("done") or [])
                kept = len(out.get("blocked") or [])
                common.log(f"done: removed {n} item(s) across {len(out.get('done') or [])} character(s) in {path.name}" + (f"; kept {kept} worn piece(s)" if kept else ""))
            except Exception as e:
                common.log(f"error: {e}"); raise SystemExit(1) from e
        self.start(job, f"Restoring vanilla in {path.name}...", need_setup=False)
    def _fix_quest_one(self, path, plan):
        if self.busy or self.game_running:
            self._toast("Cannot fix now", "Close Elden Ring first." if self.game_running else "Wait for the current job.", error=True); return
        path = Path(path)
        groups = []
        for p in plan:
            who = p.get("name") or f"slot {p['slot'] + 1}"
            items = [{"key": (p["slot"], k), "label": label, "sub": action} for k, label, action in zip(p["issues"], p.get("labels") or [], p.get("actions") or [])]
            groups.append({"title": who, "subtitle": f"{len(items)} flag fix{'es' if len(items) != 1 else ''}", "items": items})
        def summarize(keys):
            chars = {k[0] for k in keys}
            return f"Apply {len(keys)} flag fix{'es' if len(keys) != 1 else ''} on {len(chars)} character{'s' if len(chars) != 1 else ''}. Only those flags change; the character is re-signed."
        dlg = ChoiceDialog("Fix quest flags", WRITE_WARNING, groups, self, apply_text="Fix selected", summarize=summarize)
        if not dlg.exec():
            return
        selection = {}
        for slot, key in dlg.selected():
            selection.setdefault(slot, []).append(key)
        def job(_setup):
            common = core.common
            common.start_log(f"launcher: fix quest flags {path.name}")
            try:
                out = fix_quest_flags(path, selection=selection)
                n = len(out.get("fixed") or [])
                common.log(f"done: fixed {n} character{'s' if n != 1 else ''} in {path.name}")
            except Exception as e:
                common.log(f"error: {e}"); raise SystemExit(1) from e
        self.start(job, f"Fixing quest flags in {path.name}...", need_setup=False)
    def _fix_checksums_one(self, path, plan):
        if self.busy or self.game_running:
            self._toast("Cannot fix now", "Close Elden Ring first." if self.game_running else "Wait for the current job.", error=True); return
        path = Path(path)
        bits = [f"character slot {i + 1}" for i in (plan.get("slots") or [])]
        if plan.get("ud10"): bits.append("profile summary")
        msg = WRITE_WARNING + "\n\nWhat changes:\nRecompute the checksum for " + ", ".join(bits) + ". Nothing else changes."
        if not MessageBox("Fix checksums? This changes the save", msg, self).exec():
            return
        def job(_setup):
            common = core.common
            common.start_log(f"launcher: fix checksums {path.name}")
            try:
                out = fix_checksums(path)
                common.log(f"done: recomputed {len(out.get('slots') or []) + (1 if out.get('ud10') else 0)} checksum(s) in {path.name}")
            except Exception as e:
                common.log(f"error: {e}"); raise SystemExit(1) from e
        self.start(job, f"Fixing checksums in {path.name}...", need_setup=False)

    def _repair_one(self, path):
        if self.busy or self.game_running:
            self._toast("Cannot repair now", "Close Elden Ring first." if self.game_running else "Wait for the current job.", error=True); return
        def job(_setup):
            common = core.common
            common.start_log(f"launcher: repair {Path(path).name}")
            try:
                wrote = repair_save(path)
                common.log(f"done: {'rewrote' if wrote else 'already healthy'} {Path(path).name}")
            except Exception as e:
                common.log(f"error: {e}"); raise SystemExit(1) from e
        self.start(job, f"Repairing {Path(path).name}...", need_setup=False)

    def _on_dlc(self, idx):
        v = {1: "yes", 2: "no"}.get(idx, "auto"); save_settings(dlc_owned=v); self.settings["dlc_owned"] = v; self.refresh_saves()

    def _on_tarnished(self, idx):
        v = {1: "yes", 2: "no"}.get(idx, "auto"); save_settings(tarnished_owned=v); self.settings["tarnished_owned"] = v; self.refresh_saves()

    def _open_place(self, key, label):
        p = places(self.setup).get(key)
        if not p:
            why = {"me3": "me3 was not found on this PC. Set it under Locations, or install it.",
                   "game": "The game folder is unknown: Steam did not report Elden Ring, and no game exe is set under Locations.",
                   "saves": "No Elden Ring save folder in this Windows account yet.",
                   "profile": "Pick a setup on Play first.", "mods": "Pick a setup on Play first."}.get(key, "Unknown folder.")
            self._toast(f"No {label.lower()} folder", why, error=True); return
        os.startfile(str(p))

    def _folder_btn(self, key, label, icon=FI.FOLDER, tip=""):
        b = ghost_btn(label, icon); b.setToolTip(tip or f"Open the {label.lower()} folder in Explorer."); b.clicked.connect(lambda _=False, k=key, l=label: self._open_place(k, l)); return b

    def _pick_location(self, key, is_dir, filt):
        if is_dir:
            p = QFileDialog.getExistingDirectory(self, "Pick the folder", str(self.settings.get(key) or ""))
        else:
            p, _ = QFileDialog.getOpenFileName(self, "Pick the file", str(self.settings.get(key) or ""), filt + ";;All files (*)")
        if p: self._set_location(key, p)

    def _set_location(self, key, value):
        save_settings(**{key: value}); self.settings[key] = value
        apply_overrides(self.settings)
        self.loc[key].setText(value or "detected"); self.loc[key].setToolTip(value)
        self.setups = discover(self.settings.get("setup")); self._fill_setups(); self._refresh_me3(); self._fill_mods(); self._update_plan()
        self._toast("Location updated", "Detecting again." if not value else Path(value).name)

    def _refresh_me3(self):
        setup = self.setup
        def work():
            try: self.bus.me3.emit(me3_facts(setup))
            except Exception as e: self.bus.me3.emit({"error": str(e)})
        threading.Thread(target=work, daemon=True).start()

    def _on_me3(self, f):
        self._me3 = f
        if f.get("error"):
            self.me3_line.setText(f"me3: {f['error']}"); return
        v = f.get("version"); latest = (f.get("latest") or {}).get("version")
        text = f"me3 {v}" if v else "me3 version unknown"
        if f.get("update") and latest: text += f"  \u00b7  {latest} is available"
        elif v and latest: text += "  \u00b7  up to date"
        self.me3_line.setText(text); tone_label(self.me3_line, "accent" if f.get("update") else "muted")
        self.me3_line.setToolTip(f.get("path") or "")
        info = f.get("info") or {}
        where = info.get("install_prefix") or (str(Path(f["path"]).parent) if f.get("path") else "")
        self.me3_dir_btn.setEnabled(bool(where and Path(where).is_dir())); self.me3_dir_btn.setToolTip(where or "me3 was not found")
        self.me3_logs_btn.setEnabled(bool(info.get("logs_dir"))); self.me3_prof_btn.setEnabled(bool(info.get("profile_dir")))
        self.me3_logs_btn.setToolTip(info.get("logs_dir") or "me3 info did not report a logs folder"); self.me3_prof_btn.setToolTip(info.get("profile_dir") or "")
        self._update_plan()

    def _remember_play(self, key, checked):
        save_settings(**{key: bool(checked)}); self.settings[key] = bool(checked)
        if key == "warn_dead_shells": self._on_shells(dead_shells_count())

    # ---------------------------------------------------------------- Backups card (Saves page)
    def _fill_backups(self):
        for i in reversed(range(self.backups_rows.count())):
            it = self.backups_rows.takeAt(i); w = it.widget()
            if w: w.setParent(None); w.deleteLater()
        try: rows = list_backups()
        except Exception: rows = []
        shown = rows if self._backups_all else rows[:6]
        for b in shown:
            row = QWidget(); rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(10)
            when = CaptionLabel(b["when"][:16]); when.setFixedWidth(118); tone_label(when, "muted"); rl.addWidget(when)
            what = BodyLabel(f"{b['save_name']}  \u00b7  {b['action']}"); what.setWordWrap(True)
            detail = "\n".join(b["changes"][:12]) + ("\n..." if len(b["changes"]) > 12 else "")
            what.setToolTip(detail or "No change list recorded."); rl.addWidget(what, 1)
            if b["changes"]:
                first = b["changes"][0] + (f" (+{len(b['changes']) - 1})" if len(b["changes"]) > 1 else "")
                ch = hint(first); ch.setToolTip(detail); ch.setMaximumWidth(360); rl.addWidget(ch, 1)
            r = ghost_btn("Restore", FI.RETURN); r.setEnabled(not self.game_running and not self.busy)
            r.setToolTip("Close Elden Ring first." if self.game_running else "Put this copy back over the live save. The current file is copied first."); r.clicked.connect(lambda _=False, bk=b: self._restore_backup(bk)); rl.addWidget(r)
            d = ghost_btn("", FI.DELETE); d.setToolTip("Delete this backup."); d.clicked.connect(lambda _=False, bk=b: self._delete_backup(bk)); rl.addWidget(d)
            self.backups_rows.addWidget(row)
        n = len(rows)
        self.backups_note.setText("No backups yet. One is made the first time a save is repaired or fixed." if not n else count_label(n, "backup") + ("" if self._backups_all or n <= 6 else f", newest {len(shown)} shown"))
        self.backups_more.setVisible(n > 6); self.backups_more.setText("Show fewer" if self._backups_all else "Show all")

    def _toggle_backups(self):
        self._backups_all = not self._backups_all; self._fill_backups()

    def _open_backups_folder(self):
        rows = list_backups()
        if rows: os.startfile(str(rows[0]["path"].parent))
        else: self._toast("No backups yet", "A backup is made the first time a save is repaired or fixed.")

    def _restore_backup(self, b):
        if self.busy or self.game_running:
            self._toast("Cannot restore now", "Close Elden Ring first." if self.game_running else "Wait for the current job.", error=True); return
        save = core.save_for_backup(b["path"])
        if not confirm(self, f"Restore {save.name} from {b['when'][:16]}",
                       changes=[f"{save.name} becomes the copy taken before: {b['action']}"] + [f"That copy predates: {c}" for c in b["changes"][:6]],
                       warning=WRITE_WARNING, safety="The file as it is now is copied into save-fix-backups first, so this restore can itself be undone from the Backups list.",
                       apply_text="Restore"): return
        def job(_setup):
            common = core.common; common.start_log(f"launcher: restore backup {b['path'].name}")
            try:
                safety = restore_backup(b["path"], save)
                self._undo = (save, safety) if safety else None
                common.log(f"done: restored {b['path'].name} over {save.name}")
            except Exception as e:
                common.log(f"error: {e}"); raise SystemExit(1) from e
        self.start(job, f"Restoring {save.name}...", need_setup=False)

    def _delete_backup(self, b):
        if not confirm(self, "Delete this backup", changes=[f"{b['path'].name}", f"Taken {b['when'][:16]} before: {b['action']}"],
                       warning="Deleting a backup cannot be undone. The live save is not touched.", apply_text="Delete"): return
        try: delete_backup(b["path"]); self._fill_backups(); self._toast("Backup deleted", b["path"].name)
        except Exception as e: self._toast("Could not delete", str(e), error=True)

    def _undo_last(self, undo):
        save, bak = undo
        if self.busy or self.game_running:
            self._toast("Cannot undo now", "Close Elden Ring first." if self.game_running else "Wait for the current job.", error=True); return
        if not confirm(self, f"Undo the last change to {save.name}", changes=[f"{save.name} goes back to the copy taken just before the last change ({bak.name})"],
                       warning=WRITE_WARNING, safety="The file as it is now is copied first, so the undo can be undone from the Backups list.", apply_text="Undo"): return
        def job(_setup):
            common = core.common; common.start_log(f"launcher: undo {bak.name}")
            try:
                safety = restore_backup(bak, save)
                self._undo = (save, safety) if safety else None
                common.log(f"done: {save.name} is back as it was")
            except Exception as e:
                common.log(f"error: {e}"); raise SystemExit(1) from e
        self.start(job, f"Undoing in {save.name}...", need_setup=False)

    # ---------------------------------------------------------------- Save workshop (review one save, tick fixes, apply once)
    def _build_workshop(self):
        root = QWidget(); root.setObjectName("workshopPage"); outer = QVBoxLayout(root); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        head = QWidget(); hl = QVBoxLayout(head); hl.setContentsMargins(40, 20, 40, 8); hl.setSpacing(4)
        top = QHBoxLayout(); back = ghost_btn("Back to Saves", FI.LEFT_ARROW); back.clicked.connect(lambda: self.switchTo(self.saves_page)); top.addWidget(back); top.addStretch(); hl.addLayout(top)
        self.ws_title = TitleLabel(""); hl.addWidget(self.ws_title)
        self.ws_sub = hint(""); hl.addWidget(self.ws_sub)
        self.ws_chips = QHBoxLayout(); self.ws_chips.setSpacing(12); self.ws_chips.setContentsMargins(0, 2, 0, 0); hl.addLayout(self.ws_chips)
        outer.addWidget(head)
        body = QWidget(); bl = QHBoxLayout(body); bl.setContentsMargins(40, 8, 40, 4); bl.setSpacing(16)
        rail = QWidget(); rail.setFixedWidth(236); self.ws_rail = QVBoxLayout(rail); self.ws_rail.setContentsMargins(0, 0, 0, 0); self.ws_rail.setSpacing(8); self.ws_rail.setAlignment(Qt.AlignTop)
        bl.addWidget(rail, 0, Qt.AlignTop)
        self.ws_scroll, self.ws_lay = page("workshopScroll"); self.ws_lay.setContentsMargins(0, 0, 8, 16); self.ws_lay.setSpacing(14); bl.addWidget(self.ws_scroll, 1)
        outer.addWidget(body, 1)
        wrap = QWidget(); wl = QVBoxLayout(wrap); wl.setContentsMargins(40, 4, 40, 20)
        self.ws_bar = SaveBar(); box = QBoxLayout(QBoxLayout.LeftToRight, self.ws_bar); box.setContentsMargins(20, 12, 16, 12); box.setSpacing(12)
        self.ws_note = BodyLabel("Nothing selected."); self.ws_note.setWordWrap(True); box.addWidget(self.ws_note, 1)
        self.ws_reset = ghost_btn("Reset", FI.CANCEL); self.ws_reset.setToolTip("Put every tick box back to its default."); self.ws_reset.clicked.connect(self._ws_reset); box.addWidget(self.ws_reset)
        self.ws_apply = primary_btn("Apply"); self.ws_apply.setMinimumHeight(40); self.ws_apply.setMinimumWidth(150); self.ws_apply.clicked.connect(self._ws_apply); box.addWidget(self.ws_apply)
        wl.addWidget(self.ws_bar); outer.addWidget(wrap)
        self.workshop_page = root; self.ws_apply.setEnabled(False)          # joins the page stack on first open, never at startup
        self.ws_info = None; self.ws_slot = None; self.ws_state = {}; self.ws_boxes = {}; self.ws_item_rows = []; self.ws_search = None; self.ws_filter = None

    def open_workshop(self, info):
        self.ws_info = info; self.ws_slot = None; self.ws_state = {}
        if self.stackedWidget.indexOf(self.workshop_page) < 0: self.stackedWidget.addWidget(self.workshop_page)
        self._ws_head(); self._ws_build_rail(); self._ws_build_content(); self.switchTo(self.workshop_page)

    def _ws_refresh(self, infos):
        if not self.ws_info: return
        new = next((i for i in infos if i["path"] == self.ws_info["path"]), None)
        if new is None: return
        self.ws_info = new; self.ws_state = {}
        if self.ws_slot is not None and not any(c["slot"] - 1 == self.ws_slot for c in new.get("characters") or []): self.ws_slot = None
        self._ws_head(); self._ws_build_rail(); self._ws_build_content()

    def _ws_head(self):
        s = self.ws_info
        self.ws_title.setText(f"{s['kind']} save"); self.ws_sub.setText(f"{s['name']}  \u00b7  {s['modified']}  \u00b7  {s['path'].parent}")
        for i in reversed(range(self.ws_chips.count())):
            it = self.ws_chips.takeAt(i); w = it.widget()
            if w: w.setParent(None); w.deleteLater()
        for text, tone in save_summary(s):
            c_lab = CaptionLabel(("\u2713  " if tone == "success" else "\u26a0  " if tone == "warn" else "\u2022  ") + text)
            tone_label(c_lab, "success" if tone == "success" else "error" if tone == "warn" else "muted"); self.ws_chips.addWidget(c_lab)
        self.ws_chips.addStretch()

    def _ws_rail_entry(self, title, sub, slot):
        b = primary_btn(title) if self.ws_slot == slot else ghost_btn(title); b.setMinimumHeight(36)
        b.clicked.connect(lambda _=False, sl=slot: self._ws_pick(sl))
        self.ws_rail.addWidget(b)
        if sub: self.ws_rail.addWidget(hint(sub))

    def _ws_build_rail(self):
        for i in reversed(range(self.ws_rail.count())):
            it = self.ws_rail.takeAt(i); w = it.widget()
            if w: w.setParent(None); w.deleteLater()
        s = self.ws_info
        self.ws_rail.addWidget(hint("Characters"))
        n_fix = sum(1 for _ in self._ws_fix_keys(None))
        self._ws_rail_entry("All characters", f"{len(s.get('characters') or [])} on this file" + (f"  \u00b7  {n_fix} possible fixes" if n_fix else ""), None)
        for u in s.get("unreadable") or []:
            lab = ghost_btn((u.get("name") or f"Slot {u['slot']}") + "  (old layout)"); lab.setEnabled(False); lab.setMinimumHeight(36); self.ws_rail.addWidget(lab)
            self.ws_rail.addWidget(hint(f"Lv {u['level']}  \u00b7  save version {u['ver']}  \u00b7  not touched"))
        for ch in s.get("characters") or []:
            d = character_detail(s, ch["slot"] - 1)
            bits = [f"Lv {ch['level']}"]
            if d.get("loading"): bits.append("may not load")
            n_mod = sum((d.get("mods") or {}).values())
            if n_mod: bits.append(f"{n_mod} mod item{'s' if n_mod != 1 else ''}")
            if d.get("quest"): bits.append("quest flag")
            if not ch.get("ok"): bits.append("checksum")
            self._ws_rail_entry(ch["name"] or f"Slot {ch['slot']}", "  \u00b7  ".join(bits), ch["slot"] - 1)

    def _ws_pick(self, slot):
        self.ws_slot = slot; self._ws_build_rail(); self._ws_build_content()

    def _ws_fix_keys(self, slot):
        """Every possible fix key on this save (or one character), with its default tick and section."""
        s = self.ws_info
        want = lambda sl: slot is None or sl == slot
        for p in s.get("loading_plan") or []:
            if want(p["slot"]):
                for k in p["issues"]: yield ("loading", p["slot"], k), True
        for p in s.get("vanilla_plan") or []:
            if not want(p["slot"]): continue
            for e in p.get("strip") or []: yield ("item", p["slot"], e["handle"]), False
            if p.get("orphans"): yield ("orphans", p["slot"]), False
            for k in p.get("quest") or []: yield ("quest", p["slot"], k), True
        cs = s.get("checksum_fixes") or {}
        for sl in cs.get("slots") or []:
            if want(sl): yield ("checksum", sl), True
        if cs.get("ud10") and slot is None: yield ("checksum", "ud10"), True
        if s.get("needs_repair") and slot is None: yield ("regulation",), True

    def _ws_box(self, key, label, default, sub="", enabled=True, note="", section=None, source=None):
        cb = CheckBox(label); cb.setEnabled(enabled); cb.setChecked(bool(self.ws_state.get(key, default)) if enabled else False)
        cb.stateChanged.connect(lambda st, k=key: (self.ws_state.__setitem__(k, bool(st)), self._ws_recount()))
        row = QWidget(); rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(10); rl.addWidget(cb)
        side = note or sub
        if side:
            sl = hint(side)
            if note: sl.setTextColor("#963C48", "#E08A7A")
            rl.addWidget(sl, 1)
        else: rl.addStretch()
        self.ws_boxes[key] = cb
        return row, cb

    def _ws_build_content(self):
        for i in reversed(range(self.ws_lay.count())):
            it = self.ws_lay.takeAt(i); w = it.widget()
            if w: w.setParent(None); w.deleteLater()
        self.ws_boxes = {}; self.ws_item_rows = []
        s = self.ws_info; slot = self.ws_slot
        chars = [c for c in s.get("characters") or [] if slot is None or c["slot"] - 1 == slot]
        name_of = {c["slot"] - 1: (c["name"] or f"Slot {c['slot']}") for c in s.get("characters") or []}
        any_section = False

        if slot is not None and chars:
            ch = chars[0]; d = character_detail(s, slot)
            c, cl = card(ch["name"] or f"Slot {ch['slot']}", FI.PEOPLE)
            grid = QGridLayout(); grid.setHorizontalSpacing(18); grid.setVerticalSpacing(4)
            st = ch.get("stats") or {}
            facts = [("Level", str(ch["level"])), ("Body", ch["body"]), ("Max HP", f"{ch['hp']:,}"), ("Runes held", f"{ch['runes']:,}"),
                     ("Where", ch.get("where", "?")), ("Torrent", ch.get("torrent", "?")),
                     ("Stats", "  ".join(f"{k.upper()} {v}" for k, v in st.items()) if st else "?"),
                     ("Mod items", ", ".join(f"{k} {v}" for k, v in (d.get("mods") or {}).items()) or "none"),
                     ("Tarnished Edition", (f"{d.get('pack_items', 0)} piece{'s' if d.get('pack_items', 0) != 1 else ''}" + (" (counts as vanilla)" if s.get("tarnished_owned") else " (treated as mod items)")) if d.get("pack_items") else "none"),
                     ("Checksum", "OK" if ch.get("ok") else "mismatch")]
            for r, (k, v) in enumerate(facts):
                lab = hint(k); grid.addWidget(lab, r, 0); val = BodyLabel(v); val.setWordWrap(True); grid.addWidget(val, r, 1)
            grid.setColumnStretch(1, 1); cl.addLayout(grid); self.ws_lay.addWidget(c)

        loading = [p for p in s.get("loading_plan") or [] if slot is None or p["slot"] == slot]
        if loading:
            any_section = True
            c, cl = card("May not load", FI.POWER_BUTTON)
            cl.addWidget(hint("These states hang the loading screen. Ticked by default; the same repair the save editors apply."))
            for p in loading:
                who = name_of.get(p["slot"], f"slot {p['slot'] + 1}")
                for k, label, action in zip(p["issues"], p["labels"], p["actions"]):
                    row, _ = self._ws_box(("loading", p["slot"], k), (f"{who}: " if slot is None else "") + label, True, sub=action); cl.addWidget(row)
            self.ws_lay.addWidget(c)

        vplan = [p for p in s.get("vanilla_plan") or [] if (slot is None or p["slot"] == slot) and (p.get("strip") or p.get("blocked"))]
        if vplan:
            any_section = True
            c, cl = card("Remove mod items", FI.BROOM)
            cl.addWidget(hint("Items outside the vanilla + DLC list. Off by default: tick what to remove. The mods give them back in co-op; a standard .sl2 should not carry them."))
            tools = QHBoxLayout(); tools.setSpacing(8)
            self.ws_search = SearchLineEdit(); self.ws_search.setPlaceholderText("Search items"); self.ws_search.setMaximumWidth(280); self.ws_search.textChanged.connect(self._ws_filter_items); tools.addWidget(self.ws_search)
            self.ws_filter = ComboBox(); sources = sorted({(e.get("source") or "Other mod") for p in vplan for e in list(p.get("strip") or []) + list(p.get("blocked") or [])})
            self.ws_filter.addItems(["All mods"] + sources); self.ws_filter.setMinimumWidth(160); self.ws_filter.currentIndexChanged.connect(self._ws_filter_items); tools.addWidget(self.ws_filter)
            tools.addStretch(); cl.addLayout(tools)
            for p in vplan:
                who = name_of.get(p["slot"], f"slot {p['slot'] + 1}")
                if slot is None:
                    cl.addWidget(StrongBodyLabel(who))
                by_src = {}
                for e in p.get("strip") or []: by_src.setdefault(e.get("source") or "Other mod", []).append(e)
                for src, entries in by_src.items():
                    head = QHBoxLayout(); head.setSpacing(6); lab = hint(f"{src}  \u00b7  {len(entries)}"); head.addWidget(lab); head.addStretch()
                    keys = [("item", p["slot"], e["handle"]) for e in entries]
                    b_all = TransparentPushButton("All"); b_all.clicked.connect(lambda _=False, ks=keys: self._ws_set(ks, True)); head.addWidget(b_all)
                    b_none = TransparentPushButton("None"); b_none.clicked.connect(lambda _=False, ks=keys: self._ws_set(ks, False)); head.addWidget(b_none)
                    cl.addLayout(head)
                    for e in entries:
                        where = "chest" if e["box"] == "storage" else "held"
                        if e.get("pouch"): where += ", in the pouch"
                        elif e.get("quick"): where += ", in a quick slot"
                        row, cb = self._ws_box(("item", p["slot"], e["handle"]), e["name"] + (f"  x{e['qty']}" if e["qty"] > 1 else ""), False, sub=where)
                        self.ws_item_rows.append((row, e["name"].lower(), src)); cl.addWidget(row)
                for b in p.get("blocked") or []:
                    row, cb = self._ws_box(("blocked", p["slot"], b.get("handle")), b["name"], False, enabled=False,
                                           note="worn: take it off in-game first" if b.get("why") == "worn" else "remove the ash in-game first")
                    self.ws_item_rows.append((row, b["name"].lower(), b.get("source") or "Other mod")); cl.addWidget(row)
            self.ws_lay.addWidget(c)

        orphans = [p for p in s.get("vanilla_plan") or [] if (slot is None or p["slot"] == slot) and p.get("orphans")]
        if orphans:
            any_section = True
            c, cl = card("Cleanup", FI.DELETE)
            cl.addWidget(hint("Leftover item rows nothing holds or wears, usually from co-op partners' gear. Invisible in play. Off by default."))
            for p in orphans:
                who = name_of.get(p["slot"], f"slot {p['slot'] + 1}")
                names = ", ".join(o["name"] for o in p["orphans"][:6]) + (f", +{len(p['orphans']) - 6} more" if len(p["orphans"]) > 6 else "")
                row, _ = self._ws_box(("orphans", p["slot"]), f"{who}: clear {len(p['orphans'])} leftover row{'s' if len(p['orphans']) != 1 else ''}", False, sub=names); cl.addWidget(row)
            self.ws_lay.addWidget(c)

        quest = [p for p in s.get("quest_fixes") or [] if slot is None or p["slot"] == slot]
        if quest:
            any_section = True
            c, cl = card("Quest flags", FI.CHECKBOX)
            cl.addWidget(hint("Known soft-lock patterns. Ticked by default; only those flags change, the way a save editor would set them."))
            for p in quest:
                who = name_of.get(p["slot"], f"slot {p['slot'] + 1}")
                for k, label, action in zip(p["issues"], p.get("labels") or [], p.get("actions") or []):
                    row, _ = self._ws_box(("quest", p["slot"], k), (f"{who}: " if slot is None else "") + label, True, sub=action); cl.addWidget(row)
            self.ws_lay.addWidget(c)

        cs = s.get("checksum_fixes") or {}
        ed = [sl for sl in cs.get("slots") or [] if slot is None or sl == slot]
        if ed or (slot is None and (cs.get("ud10") or s.get("needs_repair"))):
            any_section = True
            c, cl = card("For save editors", FI.CERTIFICATE)
            cl.addWidget(hint("The game loads the file either way; save editors refuse it. Ticked by default."))
            for sl in ed:
                row, _ = self._ws_box(("checksum", sl), f"Recompute the checksum: {name_of.get(sl, 'slot ' + str(sl + 1))}", True, sub="stale character MD5"); cl.addWidget(row)
            if slot is None and cs.get("ud10"):
                row, _ = self._ws_box(("checksum", "ud10"), "Recompute the profile summary checksum", True); cl.addWidget(row)
            if slot is None and s.get("needs_repair"):
                row, _ = self._ws_box(("regulation",), "Repair the regulation block", True, sub="puts the game's regulation.bin back; me3 dirties it every session"); cl.addWidget(row)
            self.ws_lay.addWidget(c)

        damaged = [f for f in s.get("findings") or [] if f.get("code") in ("layout", "read") and f.get("level") == "error"]
        if damaged and slot is None:
            c, cl = card("This file could not be read fully", FI.INFO)
            for f in damaged:
                lab = BodyLabel(f.get("title") or "Damaged"); lab.setWordWrap(True); cl.addWidget(lab)
                cl.addWidget(hint(f.get("detail") or ""))
            cl.addWidget(hint("Nothing here is written to a damaged file. Restore a backup from the Saves page, or run er-save-manager's deep scan."))
            self.ws_lay.addWidget(c)
        elif not any_section:
            c, cl = card("Nothing to fix here", FI.ACCEPT)
            cl.addWidget(hint("No loading risk, no mod items, no quest soft-lock, no stale checksum" + (" on this character." if slot is not None else " on this file.")))
            self.ws_lay.addWidget(c)
        self._ws_recount()

    def _ws_set(self, keys, value):
        for k in keys:
            cb = self.ws_boxes.get(k)
            if cb is not None and cb.isEnabled(): cb.setChecked(value)

    def _ws_filter_items(self, *_):
        text = (self.ws_search.text() if self.ws_search else "").strip().lower()
        src = self.ws_filter.currentText() if self.ws_filter else "All mods"
        for row, name, source in self.ws_item_rows:
            row.setVisible((not text or text in name) and (src == "All mods" or src == source))

    def _ws_reset(self):
        self.ws_state = {}; self._ws_build_content()

    def _ws_selected(self):
        if self.ws_info is None: return []
        keys = [k for k, dflt in self._ws_fix_keys(None) if self.ws_state.get(k, dflt)]
        return keys

    def _ws_recount(self):
        if self.ws_info is None: return                       # workshop never opened yet
        keys = self._ws_selected()
        kinds = {}
        for k in keys: kinds[k[0]] = kinds.get(k[0], 0) + 1
        chars = {k[1] for k in keys if len(k) > 1 and isinstance(k[1], int)}
        if not keys:
            self.ws_note.setText("Nothing selected. Tick the fixes to apply; loading, quest and checksum fixes start ticked, removals start off.")
        else:
            bits = []
            if kinds.get("loading"): bits.append(f"{kinds['loading']} loading fix{'es' if kinds['loading'] != 1 else ''}")
            if kinds.get("item"): bits.append(f"remove {kinds['item']} item{'s' if kinds['item'] != 1 else ''}")
            if kinds.get("orphans"): bits.append(f"clear leftover rows on {kinds['orphans']} character{'s' if kinds['orphans'] != 1 else ''}")
            if kinds.get("quest"): bits.append(f"{kinds['quest']} quest flag fix{'es' if kinds['quest'] != 1 else ''}")
            if kinds.get("checksum"): bits.append(f"{kinds['checksum']} checksum{'s' if kinds['checksum'] != 1 else ''}")
            if kinds.get("regulation"): bits.append("regulation block repair")
            self.ws_note.setText(f"Apply {len(keys)} change{'s' if len(keys) != 1 else ''}: " + ", ".join(bits) + (f" on {len(chars)} character{'s' if len(chars) != 1 else ''}" if chars else "") + ". A backup is made first; Undo appears afterwards.")
        if self.game_running:
            self.ws_note.setText("Elden Ring is running. You can review and tick, but nothing is written until you quit the game." + (f"  ({len(keys)} ticked)" if keys else ""))
        elif self.busy:
            self.ws_note.setText("A job is running. Apply unlocks when it finishes.")
        self.ws_bar.pending = bool(keys) and not self.game_running; self.ws_bar.update()
        self.ws_apply.setEnabled(bool(keys) and not self.busy and not self.game_running)
        self.ws_apply.setText("Apply" if not keys else f"Apply {len(keys)}")
        self.ws_apply.setToolTip("Close Elden Ring first." if self.game_running else ("Wait for the current job." if self.busy else "Write the ticked changes, after one more confirm."))

    def _ws_apply(self):
        if self.busy or self.game_running:
            self._toast("Cannot apply now", "Close Elden Ring first." if self.game_running else "Wait for the current job.", error=True); return
        keys = self._ws_selected()
        if not keys: return
        path = self.ws_info["path"]
        loading = {}; vanilla = {}; checksums = False; regulation = False
        for k in keys:
            if k[0] == "loading": loading.setdefault(k[1], []).append(k[2])
            elif k[0] == "item": vanilla.setdefault(k[1], {"items": set(), "orphans": False, "quest": []})["items"].add(k[2])
            elif k[0] == "orphans": vanilla.setdefault(k[1], {"items": set(), "orphans": False, "quest": []})["orphans"] = True
            elif k[0] == "quest": vanilla.setdefault(k[1], {"items": set(), "orphans": False, "quest": []})["quest"].append(k[2])
            elif k[0] == "checksum": checksums = True
            elif k[0] == "regulation": regulation = True
        n_items = sum(len(v["items"]) for v in vanilla.values())
        names = {c["slot"] - 1: (c["name"] or f"slot {c['slot']}") for c in self.ws_info.get("characters") or []}
        lines = []
        for sl, keys_l in loading.items():
            lines.append(f"{names.get(sl, sl)}: {len(keys_l)} loading fix{'es' if len(keys_l) != 1 else ''}")
        for sl, v in vanilla.items():
            bits = []
            if v["items"]: bits.append(f"remove {len(v['items'])} item{'s' if len(v['items']) != 1 else ''}")
            if v["orphans"]: bits.append("clear leftover rows")
            if v["quest"]: bits.append(f"fix {len(v['quest'])} quest flag{'s' if len(v['quest']) != 1 else ''}")
            lines.append(f"{names.get(sl, sl)}: " + ", ".join(bits))
        if checksums: lines.append("Recompute the stale checksums")
        if regulation: lines.append("Repair the regulation block")
        if not confirm(self, f"Apply {len(keys)} change{'s' if len(keys) != 1 else ''} to {path.name}", changes=lines,
                       warning=WRITE_WARNING, safety=WRITE_SAFETY,
                       detail=(f"{n_items} item{'s' if n_items != 1 else ''} will be gone from this file. The mods give them back in co-op." if n_items else ""),
                       apply_text=f"Apply {len(keys)}"): return
        def job(_setup):
            common = core.common; common.start_log(f"launcher: apply {len(keys)} change(s) to {path.name}")
            backups = []
            try:
                if loading:
                    out = fix_loading(path, selection=loading); backups.append(out.get("backup"))
                if vanilla:
                    out = restore_vanilla(path, selection=vanilla); backups.append(out.get("backup"))
                if checksums:
                    out = fix_checksums(path); backups.append(out.get("backup"))
                if regulation:
                    repair_save(path)
                first = next((b for b in backups if b), None)
                self._undo = (path, first) if first else None
                common.log(f"done: applied {len(keys)} change(s) to {path.name}")
            except Exception as e:
                common.log(f"error: {e}"); raise SystemExit(1) from e
        self.start(job, f"Applying changes to {path.name}...", need_setup=False)

    # ---------------------------------------------------------------- jobs
    def _log(self, msg): self.bus.line.emit(str(msg))

    def _on_line(self, msg):
        self.log_pane.add(msg)
        if self.log_pane.last_level() == "error": self.log_exp.setExpand(True)
        shown = tidy_log_line(str(msg))
        low = shown.lstrip().lower()
        if low.startswith(("steam:", "launching", "game ", "regulation", "done:", "password", "no dead", "dead ", "scaling", "applied")): self.status.setText(shown.splitlines()[0][:120])

    def _pill(self, text, level):
        self.ready.setText(text); tone_label(self.ready, level)

    def set_busy(self, busy, status=None):
        if busy: self._pill("Running", "accent")
        self.busy = busy; self.play_btn.setEnabled(not busy and not self.game_running and self.setup is not None and not self.setup.problems()); self.play_btn.setText("Running..." if busy else "Play")
        self.setup_box.setEnabled(not busy); self.ring.setVisible(busy)
        if getattr(self, "ws_apply", None) is not None: self._ws_recount()
        if status: self.status.setText(status)
        self.setWindowTitle(f"{TITLE} {VERSION}" + (f" - {status}" if busy and status else ""))

    def _on_done(self, ok, status):
        self.set_busy(False, f"{status} at {datetime.datetime.now():%H:%M}"); self._pill("Finished" if ok else "Stopped", "success" if ok else "error"); self.refresh_saves()
        detail = "Open Launch log on the Play page." if not ok else ("Done." if any(w in (status or "") for w in ("Repairing", "Clearing", "Fixing", "Converting", "Restoring", "Installing")) else "Saves repaired and cleanup done.")
        if "Installing" in (status or ""): self._load_profile_editor(force=True); self._fill_mods(); self._update_plan()
        undo = self._undo if ok else None
        bar = (InfoBar.success if ok else InfoBar.error)(status, detail + (" Undo puts the file back as it was." if undo else ""), duration=-1 if (undo or not ok) else 6000, position=InfoBarPosition.TOP, parent=self)
        if undo:
            b = ghost_btn("Undo", FI.RETURN); b.clicked.connect(lambda _=False, u=undo, bar=bar: (bar.close(), self._undo_last(u))); bar.addWidget(b)
        self._undo = None

    def start(self, job, status, need_setup=True):
        if self.busy: return
        s = self.setup
        if need_setup:
            if not s: self._toast("Pick a setup first", "", error=True); return
            probs = s.problems()
            if probs: self._toast("Cannot launch", "\n".join(probs), error=True); return
            save_settings(setup=s.source)
        if self.game_running and job is not job_clear: self._toast("Elden Ring is already running", "Close it first.", error=True); return
        self.set_busy(True, status); self.log_pane.banner(status); route_logs(self._log)
        threading.Thread(target=run_job, args=(job, s, self._log, lambda ok, st: self.bus.done.emit(ok, st)), daemon=True).start()

    def launch(self):
        if self.busy or not self.setup: return
        wrote = self.save_seamless()
        if wrote is None or not self._announce_saved(wrote, "play"): return
        self.start(job_play, "Starting...")

    def _watch_game(self):
        def work():
            while True:
                try:
                    self.bus.running.emit(core.common.game_running())
                    self.bus.steam.emit(*steam_state())
                    self.bus.shells.emit(dead_shells_count())
                except Exception: pass
                time.sleep(5)
        threading.Thread(target=work, daemon=True).start()

    def _on_running(self, r):
        changed = r != self.game_running; self.game_running = r
        if changed: self.refresh_saves()                      # the save-block badge wording depends on it
        if getattr(self, "ws_apply", None) is not None: self._ws_recount()
        if changed and getattr(self, "backups_rows", None) is not None: self._fill_backups()
        if not self.busy:
            self.play_btn.setEnabled(not r and self.setup is not None and not self.setup.problems())
            if changed: self._pill("Game running" if r else "Ready", "warning" if r else "success"); self.status.setText("Elden Ring is running, Play is off until you quit." if r else "")

    def _on_steam(self, running, signed):
        """Steam running but not signed in for 20 s: say why Play would hang, and offer offline play."""
        bad = running and not signed
        if bad and self.steam_bad_since is None: self.steam_bad_since = time.time()
        if not bad: self.steam_bad_since = None
        show = bad and time.time() - self.steam_bad_since >= 20 and not self.busy
        if show and self.steam_bar is None:
            bar = InfoBar.warning("Steam is not signed in", "Steam's login network may be down, so Play would wait and co-op cannot start. You can still play solo on the standard save.", isClosable=False, duration=-1, position=InfoBarPosition.TOP, parent=self)
            b = ghost_btn("Play offline"); b.clicked.connect(self.launch_offline); bar.addWidget(b); self.steam_bar = bar
        elif not show and self.steam_bar is not None:
            try: self.steam_bar.close()
            except Exception: pass
            self.steam_bar = None

    def _on_shells(self, n):
        """Dead eldenring.exe shells make Steam and Discord think the game is still open."""
        show = n > 0 and not self.game_running and not self.busy and bool(self.settings.get("warn_dead_shells", True))
        if show and self.shells_bar is None:
            msg = f"{n} leftover eldenring.exe process{'es' if n != 1 else ''} with no game window. Steam may refuse to launch."
            bar = InfoBar.warning("Dead game process", msg, isClosable=True, duration=-1, position=InfoBarPosition.TOP, parent=self)
            b = ghost_btn("Clear"); b.clicked.connect(lambda: self.start(job_clear, "Clearing leftover processes...", need_setup=False)); bar.addWidget(b)
            self.shells_bar = bar
        elif not show and self.shells_bar is not None:
            try: self.shells_bar.close()
            except Exception: pass
            self.shells_bar = None

    def _remember_offline(self, *_):
        strip = self.off_revive.isChecked(); steam = self.off_steam.isChecked(); quiet = self.off_quiet.isChecked()
        save_settings(offline_strip_revive=strip, offline_start_steam=steam, offline_skip_confirm=quiet)
        self.settings.update(offline_strip_revive=strip, offline_start_steam=steam, offline_skip_confirm=quiet)

    def launch_offline(self):
        if self.busy or not self.setup: return
        strip = self.off_revive.isChecked(); steam = self.off_steam.isChecked(); quiet = self.off_quiet.isChecked()
        self._remember_offline()
        if not quiet:
            bits = ["Seamless stays off, so the game uses the standard save"]
            if strip: bits.append("Revive stays off too")
            if steam: bits.append("Steam is started if it is not running")
            if not confirm(self, "Play offline", changes=bits, safety="A temporary .offline.me3 copy is used; your real profile is not changed.",
                           detail="Skip this prompt with the switch on Tools.", apply_text="Play offline"): return
        def job(setup):
            job_play_offline(setup, strip_revive=strip, start_steam=steam)
        self.start(job, "Starting offline...")

    # ---------------------------------------------------------------- misc
    def _toast(self, title, msg, error=False, info=False):
        if self._toast_bar is not None:
            try: self._toast_bar.close()
            except Exception: pass
        kind = InfoBar.error if error else (InfoBar.info if info else InfoBar.success)
        self._toast_bar = kind(title, msg, duration=-1 if error else 4500, position=InfoBarPosition.TOP, parent=self)

    def _on_theme(self, dark):
        save_settings(theme="dark" if dark else "light"); self.settings["theme"] = "dark" if dark else "light"
        setTheme(Theme.DARK if dark else Theme.LIGHT); setThemeColor(ACCENT if dark else ACCENT_LIGHT)
        self._restyle()

    def _on_logo(self, index):
        mode = ("auto", "dark", "light")[index] if 0 <= index < 3 else "auto"
        save_settings(logo=mode); self.settings["logo"] = mode; self._apply_logo()

    def _apply_logo(self):
        mode = self.settings.get("logo", "auto")
        path = logo_path(isDarkTheme(), mode)
        ico = ASSETS_DIR / "icon.ico"
        if core.logo_kind(isDarkTheme(), mode) == "dark" and ico.is_file():
            icon = QIcon(str(ico))
        else:
            icon = QIcon(str(path))
        self.setWindowIcon(icon)
        app = QApplication.instance()
        if app is not None: app.setWindowIcon(icon)
        if hasattr(self, "logo_preview"):
            self.logo_preview.setPixmap(QPixmap(str(path)).scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _restyle(self):
        for b in self.findChildren(QPushBtn):
            if b.objectName() == "cta": style_primary(b)
            elif b.metaObject().className() == "PushButton": style_ghost(b)
        tone_label(self.ready); tone_label(self.status); tone_label(self.plan, "accent" if self.ini and self._coop_pending() else "muted")
        self.hero.update(); self.save_bar.update()
        for w in self.findChildren(GlassCard): w.update()
        for w in self.findChildren(ExpandGroupSettingCard):
            w._paint_view(); w.update(); w.card.update(); w.borderWidget.update()
        self.log_pane.restyle(); style_editor(self.profile_edit); style_editor(self.share)
        self._apply_logo(); self._frost()

    def showEvent(self, e):
        super().showEvent(e); self._frost()

    def _onThemeChangedFinished(self):
        super()._onThemeChangedFinished(); self._frost()

    def _frost(self):
        """Solid canvas. Mica made dark type vanish on a light desktop; Tailwind-style apps paint their own ground."""
        try: self.setMicaEffectEnabled(False)
        except Exception: pass
        self.setCustomBackgroundColor(BG_LIGHT, BG_DARK)

    def closeEvent(self, e):
        if self.busy and not MessageBox("Close anyway?", "A job is still running. Closing now leaves the game alone but skips the save repair and the cleanup afterwards.", self).exec(): e.ignore(); return
        coop = self._coop_pending()
        profile = self._profile_file is not None and self.profile_edit.toPlainText() != self._profile_disk
        if coop or profile:
            bits = (["Co-op settings"] if coop else []) + (["the me3 profile"] if profile else [])
            box = MessageBox("Save before closing?", " and ".join(bits) + (" have" if len(bits) > 1 else " has") + " unsaved changes.", self)
            box.yesButton.setText("Save"); box.cancelButton.setText("Cancel")
            if not box.exec(): e.ignore(); return
            if coop and self.save_seamless() is None: e.ignore(); return
            if profile and not self._save_profile(): e.ignore(); return
        e.accept()

    def _shortcut_save(self):
        page = self.stackedWidget.currentWidget()
        if page is self.coop_page and self._coop_pending(): self._announce_saved(self.save_seamless(), "next")
        elif page is self.mods_page and self.profile_save.isEnabled(): self._save_profile()


def main():
    app = QApplication(sys.argv); app.setApplicationName(TITLE)
    dark = load_settings().get("theme", "dark") == "dark"; setTheme(Theme.DARK if dark else Theme.LIGHT); setThemeColor(ACCENT if dark else ACCENT_LIGHT)
    w = Launcher()
    if "--shots" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--shots") + 1]); out.mkdir(parents=True, exist_ok=True); w.show()
        def shoot():
            w.log_pane.banner("Starting..."); w.log_pane.add("launching me3"); w.log_pane.add("steam: running"); w.log_pane.add("warning: example only"); w.log_exp.setExpand(True)
            w.profile_exp.setExpand(True); w.offline_exp.setExpand(True)
            t0 = time.time()
            while time.time() - t0 < 2.5 and not getattr(w, "saves", None): QApplication.processEvents()
            for name, pg in (("play", w.play_page), ("coop", w.coop_page), ("mods", w.mods_page), ("saves", w.saves_page), ("tools", w.tools_page)):
                w.switchTo(pg); t0 = time.time()
                while time.time() - t0 < 0.6: QApplication.processEvents()      # let the page-switch animation finish
                w.grab().save(str(out / f"{name}.png"))
                if name == "play":
                    w.resize(740, 720); QApplication.processEvents(); w._relayout(); QApplication.processEvents()
                    w.grab().save(str(out / "play-narrow.png")); w.resize(1080, 760); QApplication.processEvents(); w._relayout(); QApplication.processEvents()
                if name == "coop":                                        # second frame: the All-settings groups, opened and scrolled into view
                    scroll = w.coop_scroll
                    for exp in pg.findChildren(ExpandGroupSettingCard): exp.setExpand(True)
                    t0 = time.time()
                    while time.time() - t0 < 0.6: QApplication.processEvents()
                    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum() * 55 // 100); QApplication.processEvents(); w.grab().save(str(out / "coop-all.png"))
                    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum()); QApplication.processEvents(); w.grab().save(str(out / "coop-share.png"))
                    scroll.verticalScrollBar().setValue(0)
                if name == "mods":
                    w.pack_exp.setExpand(False); w.nat_exp.setExpand(False); w.profile_exp.setExpand(True)
                    t0 = time.time()
                    while time.time() - t0 < 0.5: QApplication.processEvents()
                    w.grab().save(str(out / "mods-edit.png"))
                    w.pack_exp.setExpand(True)
                if name == "saves":
                    # scroll to show both cards if tall
                    if hasattr(w.saves_page, "verticalScrollBar"):
                        w.saves_page.verticalScrollBar().setValue(0); QApplication.processEvents()
                        w.grab().save(str(out / "saves.png"))
                        w.saves_page.verticalScrollBar().setValue(w.saves_page.verticalScrollBar().maximum()); QApplication.processEvents()
                        w.grab().save(str(out / "saves-bottom.png"))
                        w.saves_page.verticalScrollBar().setValue(0)
            setTheme(Theme.LIGHT); setThemeColor(ACCENT_LIGHT); w._restyle()
            for name, pg in (("play-light", w.play_page), ("coop-light", w.coop_page)):
                w.switchTo(pg); t0 = time.time()
                while time.time() - t0 < 0.6: QApplication.processEvents()
                w.grab().save(str(out / f"{name}.png"))
            print("shots in", out); app.quit()
        QTimer.singleShot(2500, shoot); return app.exec()
    w.show(); return app.exec()

