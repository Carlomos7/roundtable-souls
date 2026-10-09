"""The Activity page's presenter (technical specification §8.10, Activity): what the launcher did, one entry per job
(Play, a repair, an install, a rebuild...), newest first and grouped by day, with how each ended; a summary row (last
Play, last install, last failure); filters by game, kind and failure; a job's log one click down; Undo where the job
can still be taken back.

Plain Python, no Qt: the adapter (adapter.py) hands what this returns to QML, and the Widgets window uses the same
Undo plans. Every string goes through tr(). Background housekeeping is not listed; it is in launcher.log."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from roundtable_souls.game import catalog as games
from roundtable_souls.mods import undo as mod_undo
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.platform import trash
from roundtable_souls.ui.text import plural, tr

SHOWN = 100  # entries listed at most (retention keeps about this many anyway)
FAILED = ("failed", "interrupted")

# outcome -> (pill text, pill level); levels are the QML Pill's (success | warning | danger | info | muted)
OUTCOMES = {
    "running": ("Running", "info"),
    "done": ("Done", "success"),
    "warnings": ("Done, with warnings", "warning"),
    "failed": ("Failed", "danger"),
    "interrupted": ("Interrupted", "danger"),
    "stopped": ("Stopped", "muted"),
}


# ----------------------------------------------------------------------------- what the page shows
@dataclass(frozen=True)
class Choice:
    """One entry of a filter drop-down: the value it filters by ("" for all) and its label."""

    key: str
    label: str


@dataclass(frozen=True)
class SummaryCard:
    label: str
    value: str
    level: str  # success | danger | muted


@dataclass(frozen=True)
class JobItem:
    """One job's row."""

    id: str
    when: str  # HH:MM
    title: str
    outcome: str  # the pill's text
    level: str  # the pill's level
    meta: str  # duration and game
    line: str  # the one-line result (the problem, for a failure)
    failed: bool
    undo_label: str  # "" when it cannot be taken back
    undo_tip: str
    sources: tuple[Choice, ...]  # the log, then other programs' output kept with it


@dataclass(frozen=True)
class Day:
    label: str
    jobs: tuple[JobItem, ...]


@dataclass(frozen=True)
class ActivityState:
    summary: tuple[SummaryCard, ...]
    days: tuple[Day, ...]
    empty: str  # what to say when no job is shown ("" when some are)


@dataclass(frozen=True)
class LogText:
    """A job's log (or an attachment) as shown: rows of (time, level, text), the plain text Copy takes, and a note
    (lines hidden, only the end shown, the file gone)."""

    rows: tuple[tuple[str, str, str], ...]
    plain: str
    note: str = ""
    missing: bool = False


@dataclass(frozen=True)
class Refusal:
    """Why Undo cannot run now: a toast's title and body."""

    title: str
    body: str


@dataclass(frozen=True)
class UndoPlan:
    """What taking a job back does, for the confirmation, and the job that does it."""

    title: str
    changes: tuple[str, ...]
    safety: str
    apply_text: str
    progress: str  # the status while it runs
    undo: dict = field(default_factory=dict)
    job_id: str = ""
    name: str = ""

    def job(self, locations) -> Callable:
        """The job for the window's runner (job(setup, loc)): it takes the job back and records that it did."""
        u, job_id, name = dict(self.undo), self.job_id, self.name

        def job(_setup, loc):
            run_logging.start_log(
                f"launcher: {'redo' if u.get('redo') else 'undo'} the rebuild"
                if u.get("type") == "rebuild"
                else f"launcher: {mod_undo.label(u).lower()} {name}"
                if u.get("type") in mod_undo.OPERATIONS
                else f"launcher: restore {name}",
                loc.game.key,
            )
            try:
                said = mod_undo.run(u, run_logging.log, loc=locations)
            except (mod_undo.UndoError, OSError) as e:
                run_logging.log(f"error: {e}")
                raise SystemExit(1) from e
            if job_id:
                run_logging.mark_undone(job_id)
            if u.get("type") == "rebuild":  # the same swap, the other way
                run_logging.set_undo({**u, "redo": not u.get("redo")})
            run_logging.log(f"done: {said}")

        return job


# ----------------------------------------------------------------------------- small words
def when_of(rec: dict) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(rec.get("start") or "")
    except ValueError:
        return None


def day_label(day: datetime.date, today: datetime.date) -> str:
    if day == today:
        return tr("Today")
    if day == today - datetime.timedelta(days=1):
        return tr("Yesterday")
    return day.strftime("%A %d %B %Y").replace(" 0", " ")


def day_word(day: datetime.date, today: datetime.date) -> str:
    """The day inside a sentence: today, yesterday, or Mon 5 Oct."""
    if day == today:
        return tr("today")
    if day == today - datetime.timedelta(days=1):
        return tr("yesterday")
    return day.strftime("%a %d %b").replace(" 0", " ")


def duration_text(seconds) -> str:
    if seconds is None:
        return ""
    s = int(round(float(seconds)))
    if s < 1:
        return tr("under a second")
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {s % 3600 // 60:02d}m"


def title_text(rec: dict) -> str:
    t = str(rec.get("title") or tr("Job")).strip()
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
    return not failed_only or rec.get("outcome") in FAILED


def result_line(rec: dict) -> str:
    """The one line under a job: its problem when it failed, else its summary."""
    line = rec.get("problem") if rec.get("outcome") in FAILED else ""
    line = line or rec.get("summary") or ""
    if rec.get("outcome") == "interrupted" and not line:
        line = tr("The launcher closed before this job finished.")
    return line


def log_row(e: dict) -> tuple[str, str, str]:
    """A log entry for the viewer. The job's own start and end lines read as quiet notes, not as output."""
    text = e["text"]
    if e["source"] == "job" and text.startswith("=== ") and text.endswith(" ==="):
        return (e["time"], "debug", text[4:-4])
    return (e["time"], e["level"], text)


# ----------------------------------------------------------------------------- the presenter
class ActivityPresenter:
    """The page's state from the jobs index. refresh() reads it again; the filters are its arguments."""

    def __init__(
        self,
        read_jobs: Callable[[], list[dict]] | None = None,
        now: Callable[[], datetime.datetime] = datetime.datetime.now,
        undo_available: Callable[[dict], bool] | None = None,
    ):
        self._read_jobs = read_jobs or (lambda: run_logging.read_jobs())
        self._now = now
        self._undo_available = undo_available or (lambda u: mod_undo.available(u))  # looked up per call
        self._records: dict[str, dict] = {}

    # ---- text the page and its window carry
    title = property(lambda self: tr("Activity"))
    subtitle = property(
        lambda self: tr("What the launcher did: every Play, repair, install and rebuild, with how it went and its log.")
    )
    open_window_text = property(lambda self: tr("Open new Activity window"))
    open_window_tip = property(
        lambda self: tr("The new Activity page, in a window of its own: a preview of the launcher's new look.")
    )
    failed_only_text = property(lambda self: tr("Failed only"))

    @property
    def games(self) -> tuple[Choice, ...]:
        return (Choice("", tr("All games")), *(Choice(g.key, g.name) for g in games.GAMES))

    @property
    def kinds(self) -> tuple[Choice, ...]:
        return (Choice("", tr("All kinds")), *(Choice(g, tr(g)) for g in run_logging.GROUPS))

    # ---- the list
    def refresh(self, game: str = "", group: str = "", failed_only: bool = False) -> ActivityState:
        recs = self._read_jobs()
        self._records = {str(r.get("id")): r for r in recs if r.get("id")}
        today = self._now().date()
        shown = [r for r in recs if matches(r, game, group, failed_only)][:SHOWN]
        days: list[Day] = []
        current: list[JobItem] = []
        label = None
        for rec in shown:
            when = when_of(rec)
            this = day_label(when.date(), today) if when else tr("Unknown date")
            if this != label:
                if current:
                    days.append(Day(label or "", tuple(current)))
                label, current = this, []
            current.append(self._item(rec))
        if current:
            days.append(Day(label or "", tuple(current)))
        if not recs:
            empty = tr(
                "Nothing yet. Play, repairs, installs and rebuilds show up here with how they went, and each keeps "
                "its full log."
            )
        elif not shown:
            empty = tr("Nothing matches these filters.")
        else:
            empty = ""
        return ActivityState(self._summary(recs, today), tuple(days), empty)

    def _item(self, rec: dict) -> JobItem:
        when = when_of(rec)
        outcome = rec.get("outcome") or ""
        text, level = OUTCOMES.get(outcome, (str(outcome or "?").capitalize(), "muted"))
        meta = [duration_text(rec.get("seconds")), game_name(rec.get("game") or "")]
        undo = rec.get("undo")
        can_undo = bool(undo) and outcome in ("done", "warnings") and self._undo_available(undo or {})
        sources = [Choice(rec.get("log") or "", tr("Log"))]
        for name in rec.get("attachments") or []:
            label = name.rsplit(".", 2)[-2] if name.count(".") >= 2 else name
            sources.append(Choice(name, tr("{program} output").format(program=label)))
        return JobItem(
            id=str(rec.get("id") or ""),
            when=when.strftime("%H:%M") if when else "",
            title=title_text(rec),
            outcome=tr(text),
            level=level,
            meta="  ·  ".join(m for m in meta if m),
            line=result_line(rec),
            failed=outcome in FAILED,
            undo_label=tr(mod_undo.label(undo)) if can_undo else "",
            undo_tip=tr("Take this back: {what}").format(what=rec.get("summary") or title_text(rec))
            if can_undo
            else "",
            sources=tuple(sources),
        )

    def _summary(self, recs: list[dict], today: datetime.date) -> tuple[SummaryCard, ...]:
        """Last Play, last install, last failure (the index is newest first)."""

        def first(test) -> dict | None:
            return next((r for r in recs if test(r)), None)

        def when(rec: dict) -> str:
            w = when_of(rec)
            return day_word(w.date(), today) if w else ""

        play = first(lambda r: r.get("kind") == "play")
        install = first(lambda r: r.get("kind") == "install")
        failure = first(lambda r: r.get("outcome") in FAILED)
        none = tr("None yet")
        cards = []
        if play:
            w = when_of(play)
            bits = [f"{day_word(w.date(), today).capitalize()} {w.strftime('%H:%M')}" if w else ""]
            bits.append(duration_text(play.get("seconds")))
            level = "danger" if play.get("outcome") in FAILED else "success"
            cards.append(SummaryCard(tr("Last Play"), "  ·  ".join(b for b in bits if b), level))
        else:
            cards.append(SummaryCard(tr("Last Play"), none, "muted"))
        if install:
            value = "  ·  ".join(b for b in (title_text(install), when(install)) if b)
            cards.append(SummaryCard(tr("Last install"), value, "muted"))
        else:
            cards.append(SummaryCard(tr("Last install"), none, "muted"))
        if failure:
            value = "  ·  ".join(b for b in (title_text(failure), when(failure)) if b)
            cards.append(SummaryCard(tr("Last failure"), value, "danger"))
        else:
            cards.append(SummaryCard(tr("Last failure"), none, "muted"))
        return tuple(cards)

    def record(self, job_id: str) -> dict | None:
        """The job as the last refresh() read it."""
        return self._records.get(job_id)

    # ---- one job's log
    def log(self, job_id: str, source: str = "", detail: bool = False) -> LogText:
        """The job's log (information and up, or every line with detail), or another program's output kept with
        it (source: an attachment's name)."""
        rec = self.record(job_id) or {}
        main = rec.get("log") or ""
        source = source or main
        notes: list[str] = []
        if source == main:
            got = run_logging.read_job_log(source)
            if got["missing"]:
                return LogText((("", "warning", tr("This job's log file is no longer there.")),), "", missing=True)
            rows = tuple(log_row(e) for e in got["entries"] if detail or e["level"] != "debug")
            hidden = 0 if detail else sum(1 for e in got["entries"] if e["level"] == "debug")
            if hidden:
                notes.append(
                    plural(
                        "{n} detail line hidden; turn on Show details to see it.",
                        "{n} detail lines hidden; turn on Show details to see them.",
                        hidden,
                    ).format(n=hidden)
                )
            plain = "\n".join(f"{t}  {lvl.upper():7}  {x}" for t, lvl, x in rows)
        else:
            got = run_logging.read_attachment(source)
            if got["missing"]:
                return LogText((("", "warning", tr("This output file is no longer there.")),), "", missing=True)
            plain = got["text"]
            rows = (("", "info", plain),)
        if got.get("cut"):
            notes.insert(0, tr("Only the end of a long file is shown; Open file has all of it."))
        return LogText(rows, plain, " ".join(notes))

    @staticmethod
    def copy_text(log: LogText, for_support: bool = False) -> str:
        """What Copy puts on the clipboard; for support, with the user name and Steam IDs masked."""
        return run_logging.redact(log.plain) if for_support else log.plain

    @staticmethod
    def log_path(source: str) -> Path | None:
        """The file behind a log or attachment, for Open file (None when it is gone)."""
        path = run_logging.job_file(source)
        return path if path is not None and path.is_file() else None

    # ---- Undo
    def undo_plan(self, rec: dict, busy: bool, game_running: bool) -> UndoPlan | Refusal:
        """What taking rec back would do, or why it cannot be done now."""
        u = dict(rec.get("undo") or {})
        if busy:
            return Refusal(tr("Wait for the current job"), tr("Undo runs as a job of its own."))
        if not self._undo_available(u):
            return Refusal(tr("It cannot be taken back any more"), tr("What it needs is gone."))
        if u.get("type") == "rebuild" and game_running:
            return Refusal(tr("Close the game first"), tr("The rebuild's files are in use while it runs."))
        prof = Path(u.get("profile") or "")
        job_id = str(rec.get("id") or "")
        if u.get("type") == "rebuild":
            redo = bool(u.get("redo"))
            title = tr("Redo the rebuild") if redo else tr("Undo the rebuild")
            changes = (
                tr("The rebuild tool's output is swapped with the backup it kept") if u.get("tool_restore") else "",
                tr("The combined parameters are swapped with the ones kept before") if u.get("combined_before") else "",
                (
                    tr("{profile} goes back as it was after the rebuild")
                    if redo
                    else tr("{profile} goes back as it was before the rebuild")
                ).format(profile=prof.name)
                if u.get("profile_before")
                else "",
            )
            return UndoPlan(
                title,
                tuple(c for c in changes if c),
                tr(
                    "Nothing is deleted: each is swapped with its copy, so this can be done again the other way. "
                    "Load order will say the parameters are out of date until you rebuild."
                ),
                title,
                tr("Redoing the rebuild...") if redo else tr("Undoing the rebuild..."),
                u,
                job_id,
                "the rebuild",
            )
        if u.get("type") in mod_undo.OPERATIONS:
            name = u.get("name") or tr("the mod")
            fresh = u.get("type") == "install"
            changes = (
                tr("{profile} goes back to exactly what it was before the install").format(profile=prof.name)
                if fresh
                else tr("{name}'s folder and its entries go back to the version before").format(name=name),
                tr("The files the install added are removed; any you changed since stay, and are listed")
                if fresh
                else tr("The version it replaces is kept aside, with any changes you made to it"),
                tr("The merged mods are rebuilt for it") if u.get("rebuild") and not fresh else "",
            )
            return UndoPlan(
                (tr("Undo the install of {name}") if fresh else tr("Roll {name} back")).format(name=name),
                tuple(c for c in changes if c),
                tr(
                    "Seamless Co-op and your other mods are not touched. If the profile changed since, only {name}'s "
                    "entries are taken out of it."
                ).format(name=name),
                tr("Undo install") if fresh else tr("Roll back"),
                tr("Restoring {name}...").format(name=name),
                u,
                job_id,
                name,
            )
        name = u.get("name") or tr("it")
        changes = (
            tr("Its entry goes back into {profile}, where it was").format(profile=prof.name),
            tr("Its folder comes back from the Recycle Bin") if trash.exists(u.get("trash")) else "",
            tr("Play rebuilds the merged mods with it before the game starts (or Rebuild on the Mods page)")
            if u.get("merged")
            else "",
        )
        return UndoPlan(
            tr("Restore {name}").format(name=name),
            tuple(c for c in changes if c),
            tr("The profile as it is now is kept in its versions."),
            tr("Restore"),
            tr("Restoring {name}...").format(name=name),
            u,
            job_id,
            name,
        )
