"""The Activity page's adapter: the thin QObject the QML page binds to (technical specification §8.6 D5). It holds
no decisions: what to show and what Undo does come from the presenter; reading the jobs index runs on the job
runner's worker thread; Undo runs as a logged job of the host (the window that owns the job runner and knows whether
a job or the game is running); results reach the user through the Notifier."""

from __future__ import annotations

from typing import Any, Protocol

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QGuiApplication

from roundtable_souls.ui.models import RowsModel
from roundtable_souls.ui.notifications import Notifier
from roundtable_souls.ui.pages.activity.presenter import ActivityPresenter, ActivityState, LogText, Refusal
from roundtable_souls.ui.text import tr


class ActivityHost(Protocol):
    """What the page needs from the window that hosts it (the Widgets launcher until the shell, S9)."""

    @property
    def busy(self) -> bool: ...
    @property
    def game_running(self) -> bool: ...
    @property
    def locations(self) -> Any: ...
    def run_job(self, job, status: str) -> None:
        """Start job(setup, loc) as a logged job; the host refreshes Activity when it ends."""

    def mark_seen(self) -> None:
        """The user looked at Activity: failures so far are no longer new."""

    def run_in_background(self, work, on_result) -> None:
        """work() on a worker thread, on_result(value) back on the UI thread (ui.jobs.Jobs.start)."""


class ActivityAdapter(QObject):
    changed = Signal()  # summary, empty text, filters
    logChanged = Signal()
    loadingChanged = Signal()

    def __init__(self, host: ActivityHost, notifier: Notifier, presenter: ActivityPresenter | None = None, parent=None):
        super().__init__(parent)
        self.host = host
        self.notifier = notifier
        self.presenter = presenter or ActivityPresenter()
        self._state = ActivityState((), (), "")
        self._game = ""
        self._kind = ""
        self._failed_only = False
        self._loading = False
        self._again = False
        self._open_job = ""
        self._source = ""
        self._detail = False
        self._log = LogText((), "")
        self._summary = RowsModel(("label", "value", "level"), self)
        self._days = RowsModel(("label", "jobs"), self)
        self._games = RowsModel(("key", "label"), self)
        self._kinds = RowsModel(("key", "label"), self)
        self._games.set_rows(self.presenter.games)
        self._kinds.set_rows(self.presenter.kinds)

    # ---- the text the page carries (all from the presenter, through tr())
    title = Property(str, lambda self: self.presenter.title, constant=True)
    subtitle = Property(str, lambda self: self.presenter.subtitle, constant=True)
    failedOnlyText = Property(str, lambda self: self.presenter.failed_only_text, constant=True)
    words = Property(
        dict,
        lambda self: {
            "showDetails": tr("Show details"),
            "showDetailsTip": tr("Every line, including the fine detail kept for tracking down problems."),
            "copy": tr("Copy"),
            "copyTip": tr("Copy what is shown."),
            "copySupport": tr("Copy for support"),
            "copySupportTip": tr("Copy what is shown with your user name and Steam IDs masked, to paste in a report."),
            "openFile": tr("Open file"),
            "showLog": tr("Show this job's log"),
            "hideLog": tr("Hide this job's log"),
            "copied": tr("Copied"),
        },
        constant=True,
    )

    # ---- models
    summary = Property(QObject, lambda self: self._summary, constant=True)
    days = Property(QObject, lambda self: self._days, constant=True)
    games = Property(QObject, lambda self: self._games, constant=True)
    kinds = Property(QObject, lambda self: self._kinds, constant=True)
    empty = Property(str, lambda self: self._state.empty, notify=changed)
    loading = Property(bool, lambda self: self._loading, notify=loadingChanged)

    # ---- filters
    def _label(self, model: RowsModel, key: str) -> str:
        return next((r["label"] for r in model.rows() if r["key"] == key), "")

    game = Property(str, lambda self: self._game, notify=changed)
    gameLabel = Property(str, lambda self: self._label(self._games, self._game), notify=changed)
    kind = Property(str, lambda self: self._kind, notify=changed)
    kindLabel = Property(str, lambda self: self._label(self._kinds, self._kind), notify=changed)
    failedOnly = Property(bool, lambda self: self._failed_only, notify=changed)

    @Slot(str)
    def setGame(self, key: str) -> None:
        self._game = key
        self.refresh()

    @Slot(str)
    def setKind(self, key: str) -> None:
        self._kind = key
        self.refresh()

    @Slot(bool)
    def setFailedOnly(self, on: bool) -> None:
        self._failed_only = on
        self.refresh()

    # ---- reading the jobs again (on the job runner's worker thread)
    @Slot()
    def refresh(self) -> None:
        if self._loading:
            self._again = True  # one more read when this one lands, with the filters as they are then
            return
        self._loading = True
        self.loadingChanged.emit()
        game, kind, failed = self._game, self._kind, self._failed_only
        self.host.run_in_background(lambda: self.presenter.refresh(game, kind, failed), self._apply)

    def _apply(self, state: ActivityState) -> None:
        self._loading = False
        self.loadingChanged.emit()
        if self._again:
            self._again = False
            self.refresh()
            return
        self._state = state
        self._summary.set_rows(state.summary)
        self._days.set_rows(state.days)
        self.changed.emit()
        if self._open_job and self.presenter.record(self._open_job) is None:
            self.closeLog()
        elif self._open_job:
            self._read_log()

    def state(self) -> ActivityState:
        """What the page shows now (tests and the self-test)."""
        return self._state

    @Slot()
    def seen(self) -> None:
        self.host.mark_seen()

    # ---- one job's log (one open at a time)
    openJob = Property(str, lambda self: self._open_job, notify=logChanged)
    logText = Property(str, lambda self: self._log.plain or "\n".join(r[2] for r in self._log.rows), notify=logChanged)
    logNote = Property(str, lambda self: self._log.note, notify=logChanged)
    logSource = Property(str, lambda self: self._source, notify=logChanged)
    logDetail = Property(bool, lambda self: self._detail, notify=logChanged)
    logMissing = Property(bool, lambda self: self._log.missing, notify=logChanged)

    @Slot(str)
    def toggleLog(self, job_id: str) -> None:
        if job_id == self._open_job:
            self.closeLog()
            return
        self._open_job, self._source, self._detail = job_id, "", False
        self._read_log()

    @Slot()
    def closeLog(self) -> None:
        self._open_job, self._source, self._log = "", "", LogText((), "")
        self.logChanged.emit()

    @Slot(str)
    def setLogSource(self, source: str) -> None:
        self._source = source
        self._read_log()

    @Slot(bool)
    def setLogDetail(self, on: bool) -> None:
        self._detail = on
        self._read_log()

    def _read_log(self) -> None:
        self._log = self.presenter.log(self._open_job, self._source, self._detail)
        self.logChanged.emit()

    @Slot(bool)
    def copyLog(self, for_support: bool) -> None:
        QGuiApplication.clipboard().setText(self.presenter.copy_text(self._log, for_support))
        self.notifier.toast(tr("Copied with your user name and Steam IDs masked") if for_support else tr("Copied"))

    @Slot()
    def openLogFile(self) -> None:
        rec = self.presenter.record(self._open_job) or {}
        path = self.presenter.log_path(self._source or rec.get("log") or "")
        if path is None:
            self.notifier.toast(tr("That file is no longer there."), error=True)
            return
        from roundtable_souls.platform import desktop

        desktop.open_path(str(path))

    # ---- Undo
    @Slot(str)
    def undo(self, job_id: str) -> None:
        rec = self.presenter.record(job_id)
        if rec is None:
            return
        plan = self.presenter.undo_plan(rec, busy=self.host.busy, game_running=self.host.game_running)
        if isinstance(plan, Refusal):
            self.notifier.toast(f"{plan.title}. {plan.body}", error=True)
            self.refresh()
            return

        def answered(ok: bool) -> None:
            if ok:
                self.host.run_job(plan.job(self.host.locations), plan.progress)

        self.notifier.confirm(plan.title, plan.changes, plan.safety, plan.apply_text, answered)

    # ---- for tests and the self-test
    def snapshot(self) -> dict:
        return {"summary": self._summary.rows(), "days": self._days.rows(), "empty": self._state.empty}
