"""The Activity page: what the launcher did, one entry per job (Play, a repair, an install, a rebuild...), newest
first and grouped by day, with how each ended. Opening an entry shows its log, the fine detail on request, and the
output of other programs kept with it (me3's for a Play). Background housekeeping is not listed; it is in
launcher.log for when something needs tracking down.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import CaptionLabel, CheckBox, ComboBox, StrongBodyLabel, TextEdit, TransparentToolButton
from qfluentwidgets import FluentIcon as FI

from roundtable_souls import games
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.ui.theme import ghost_btn, hint, style_editor
from roundtable_souls.ui.widgets import ElideLabel, GlassCard, StatusPill, action_row, dispose, log_html, tone_label

SHOWN = 100  # entries listed at most (retention keeps about this many anyway)

OUTCOME = {  # outcome -> (pill text, pill level)
    "running": ("Running", "busy"),
    "done": ("Done", "ok"),
    "warnings": ("Done, with warnings", "warn"),
    "failed": ("Failed", "bad"),
    "interrupted": ("Interrupted", "bad"),
    "stopped": ("Stopped", "muted"),
}


def _when(rec: dict) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(rec.get("start") or "")
    except ValueError:
        return None


def day_label(day: datetime.date, today: datetime.date) -> str:
    if day == today:
        return "Today"
    if day == today - datetime.timedelta(days=1):
        return "Yesterday"
    return day.strftime("%A %d %B %Y").replace(" 0", " ")


def duration_text(seconds) -> str:
    if seconds is None:
        return ""
    s = int(round(float(seconds)))
    if s < 1:
        return "under a second"
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {s % 3600 // 60:02d}m"


def title_text(rec: dict) -> str:
    t = str(rec.get("title") or "Job").strip()
    return t[:1].upper() + t[1:]


def game_name(key: str) -> str:
    try:
        return games.resolve(key).name if key else ""
    except Exception:
        return key


def matches(rec: dict, game: str, group: str, failed_only: bool) -> bool:
    if game and rec.get("game") and rec.get("game") != game:
        return False
    if group and run_logging.group_of(rec.get("kind") or "") != group:
        return False
    return not failed_only or rec.get("outcome") in ("failed", "interrupted")


def _row(e: dict) -> tuple[str, str, str]:
    """A log entry for the viewer. The job's own start and end lines read as quiet notes, not as output."""
    text = e["text"]
    if e["source"] == "job" and text.startswith("=== ") and text.endswith(" ==="):
        return (e["time"], "debug", text[4:-4])
    return (e["time"], e["level"], text)


# ----------------------------------------------------------------------------- one entry
class JobDetails(QWidget):
    """An entry opened: its log (information and up, or every line with Show details), the output of other programs
    kept with it, and ways to copy or open them."""

    def __init__(self, rec: dict, parent=None):
        super().__init__(parent)
        self.rec = rec
        self._source = rec.get("log") or ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(8)
        row, bar = action_row()
        self.detail = CheckBox("Show details")
        self.detail.setToolTip("Every line, including the fine detail kept for tracking down problems.")
        self.detail.stateChanged.connect(self._show)
        bar.addWidget(self.detail)
        self.sources = ComboBox()
        self.sources.addItem("Log", userData=rec.get("log") or "")
        for name in rec.get("attachments") or []:
            label = name.rsplit(".", 2)[-2] if name.count(".") >= 2 else name
            self.sources.addItem(f"{label} output", userData=name)
        self.sources.currentIndexChanged.connect(self._pick)
        bar.addWidget(self.sources)
        self.sources.setVisible(self.sources.count() > 1)
        self.copy_btn = ghost_btn("Copy", FI.COPY)
        self.copy_btn.setToolTip("Copy what is shown.")
        self.copy_btn.clicked.connect(lambda: self._copy(False))
        self.support_btn = ghost_btn("Copy for support", FI.SHARE)
        self.support_btn.setToolTip(
            "Copy what is shown with your user name and Steam IDs masked, to paste in a report."
        )
        self.support_btn.clicked.connect(lambda: self._copy(True))
        self.open_btn = ghost_btn("Open file", FI.DOCUMENT)
        self.open_btn.clicked.connect(self._open)
        for b in (self.copy_btn, self.support_btn, self.open_btn):
            bar.addWidget(b)
        lay.addWidget(row)
        self.note = hint("")
        self.note.setVisible(False)
        lay.addWidget(self.note)
        self.view = TextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(TextEdit.LineWrapMode.WidgetWidth)
        self.view.setMinimumHeight(180)
        self.view.setMaximumHeight(420)
        style_editor(self.view)
        lay.addWidget(self.view)
        self._plain = ""
        self._show()

    def _pick(self, *_):
        self._source = self.sources.currentData() or ""
        self.detail.setVisible(self._source == (self.rec.get("log") or ""))
        self._show()

    def _show(self, *_):
        is_log = self._source == (self.rec.get("log") or "")
        notes = []
        if is_log:
            got = run_logging.read_job_log(self._source)
            if got["missing"]:
                self.view.setHtml(log_html([("", "warning", "This job's log file is no longer there.")]))
                self._plain = ""
                self.note.setVisible(False)
                return
            rows = [_row(e) for e in got["entries"] if self.detail.isChecked() or e["level"] != "debug"]
            hidden = sum(1 for e in got["entries"] if e["level"] == "debug") if not self.detail.isChecked() else 0
            if hidden:
                notes.append(f"{hidden} detail line{'s' if hidden != 1 else ''} hidden; tick Show details to see them.")
            self._plain = "\n".join(f"{t}  {lvl.upper():7}  {x}" for t, lvl, x in rows)
            self.view.setHtml(log_html(rows, "00:00:00.000"))
        else:
            got = run_logging.read_attachment(self._source)
            text = got["text"] if not got["missing"] else "This output file is no longer there."
            self._plain = text
            self.view.setHtml(log_html([("", "info", text)], ""))
        if got.get("cut"):
            notes.insert(0, "Only the end of a long file is shown; Open file has all of it.")
        self.note.setText(" ".join(notes))
        self.note.setVisible(bool(notes))

    def _copy(self, redacted: bool):
        text = run_logging.redact(self._plain) if redacted else self._plain
        QApplication.clipboard().setText(text)

    def _open(self):
        from roundtable_souls.platform import paths as common

        path = run_logging.job_file(self._source)
        if path is not None and path.is_file():
            common.open_path(str(path))


class JobRow(GlassCard):
    """One job: when, how it ended, what it was, its summary; click (or the chevron) to open it. When the job can
    still be taken back (mods.undo), a button does it."""

    elevated = False  # a row in a list, not a standalone card

    def __init__(self, rec: dict, expanded: bool = False, parent=None, on_undo=None):
        super().__init__(parent)
        self.rec = rec
        self.details: JobDetails | None = None
        self._open = False  # not isVisible(): that is false whenever the page itself is not on screen
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 10, 12, 10)
        lay.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(10)
        when = _when(rec)
        self.time = CaptionLabel(when.strftime("%H:%M") if when else "")
        self.time.setFixedWidth(40)
        tone_label(self.time, "muted")
        head.addWidget(self.time)
        text, level = OUTCOME.get(rec.get("outcome") or "", (str(rec.get("outcome") or "?").capitalize(), "muted"))
        self.pill = StatusPill(text, level)
        head.addWidget(self.pill)
        self.title = ElideLabel(title_text(rec))
        head.addWidget(self.title, 1)
        meta = [duration_text(rec.get("seconds")), game_name(rec.get("game") or "")]
        self.meta = CaptionLabel("  ·  ".join(m for m in meta if m))
        tone_label(self.meta, "muted")
        head.addWidget(self.meta)
        self.undo_btn = None
        undo = rec.get("undo")
        if on_undo is not None and undo and rec.get("outcome") in ("done", "warnings"):
            from roundtable_souls.mods import undo as undo_tools

            if undo_tools.available(undo):
                self.undo_btn = ghost_btn(undo_tools.label(undo), FI.RETURN)
                self.undo_btn.setToolTip("Take this back: " + (rec.get("summary") or title_text(rec)))
                self.undo_btn.clicked.connect(lambda _=False, r=rec: on_undo(r))
                head.addWidget(self.undo_btn)
        self.toggle = TransparentToolButton(FI.CHEVRON_RIGHT_MED)
        self.toggle.setFixedSize(28, 28)
        self.toggle.setToolTip("Show this job's log")
        self.toggle.clicked.connect(self.flip)
        head.addWidget(self.toggle)
        lay.addLayout(head)
        line = rec.get("problem") if rec.get("outcome") in ("failed", "interrupted") else ""
        line = line or rec.get("summary") or ""
        if rec.get("outcome") == "interrupted" and not line:
            line = "The launcher closed before this job finished."
        self.summary = ElideLabel(line)
        tone_label(self.summary, "error" if rec.get("outcome") in ("failed", "interrupted") else "muted")
        lay.addWidget(self.summary)
        self.summary.setVisible(bool(line))  # only once parented: shown before that, it is a window of its own
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(self.body)
        self.setCursor(Qt.PointingHandCursor)
        if expanded:
            self.flip()

    @property
    def expanded(self) -> bool:
        return self._open

    def flip(self):
        self._open = not self._open
        if self.details is None:
            self.details = JobDetails(self.rec, self)
            self.body.addWidget(self.details)
        self.details.setVisible(self._open)
        open_ = self._open
        self.toggle.setIcon(FI.CHEVRON_DOWN_MED if open_ else FI.CHEVRON_RIGHT_MED)
        self.toggle.setToolTip("Hide this job's log" if open_ else "Show this job's log")
        self.setCursor(Qt.ArrowCursor if open_ else Qt.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        # A click on the entry's own surface opens it; clicks inside the opened log (selecting text) do not.
        if e.button() == Qt.LeftButton and not self.expanded:
            self.flip()
        super().mouseReleaseEvent(e)


# ----------------------------------------------------------------------------- the list
class ActivityView(QWidget):
    """Filters and the list of jobs. refresh() reads the jobs index again."""

    refreshed = Signal(int)  # entries shown

    def __init__(self, parent=None, now: Callable[[], datetime.datetime] = datetime.datetime.now, on_undo=None):
        super().__init__(parent)
        self._now = now
        self._on_undo = on_undo
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        row, bar = action_row()
        self.game_box = ComboBox()
        self.game_box.addItem("All games", userData="")
        for g in games.GAMES:
            self.game_box.addItem(g.name, userData=g.key)
        self.kind_box = ComboBox()
        self.kind_box.addItem("Everything", userData="")
        for group in run_logging.GROUPS:
            self.kind_box.addItem(group, userData=group)
        self.failed_only = CheckBox("Failed only")
        for w in (self.game_box, self.kind_box):
            w.setMinimumWidth(150)
            w.currentIndexChanged.connect(self.refresh)
            bar.addWidget(w)
        self.failed_only.stateChanged.connect(self.refresh)
        bar.addWidget(self.failed_only)
        lay.addWidget(row)
        self.note = hint("")
        lay.addWidget(self.note)
        self.rows_box = QWidget()
        self.rows = QVBoxLayout(self.rows_box)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(8)
        lay.addWidget(self.rows_box)
        self.empty = hint("")
        lay.addWidget(self.empty)
        self._rows: list[JobRow] = []

    def rows_shown(self) -> list[JobRow]:
        return list(self._rows)

    def refresh(self, *_):
        opened = {r.rec.get("id") for r in self._rows if r.expanded}
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget() is not None:
                dispose(item.widget())
        self._rows = []
        recs = run_logging.read_jobs()
        game = self.game_box.currentData() or ""
        group = self.kind_box.currentData() or ""
        shown = [r for r in recs if matches(r, game, group, self.failed_only.isChecked())][:SHOWN]
        failed = sum(1 for r in recs if r.get("outcome") in ("failed", "interrupted"))
        running = sum(1 for r in recs if r.get("outcome") == "running")
        parts = [f"{len(recs)} job{'s' if len(recs) != 1 else ''} kept"]
        if running:
            parts.append(f"{running} running")
        if failed:
            parts.append(f"{failed} failed")
        parts.append(f"kept for {run_logging.KEEP_DAYS} days or the newest {run_logging.KEEP_JOBS}")
        self.note.setText("  ·  ".join(parts))
        today = self._now().date()
        day = None
        for rec in shown:
            when = _when(rec)
            d = when.date() if when else None
            if d != day:
                day = d
                label = StrongBodyLabel(day_label(d, today) if d else "Unknown date")
                self.rows.addWidget(label)
            row = JobRow(rec, expanded=rec.get("id") in opened, on_undo=self._on_undo)
            self.rows.addWidget(row)
            self._rows.append(row)
        if not recs:
            self.empty.setText(
                "Nothing yet. Play, repairs, installs and rebuilds show up here with how they went, and each keeps "
                "its full log."
            )
        elif not shown:
            self.empty.setText("Nothing matches these filters.")
        self.empty.setVisible(not shown)
        self.refreshed.emit(len(shown))
