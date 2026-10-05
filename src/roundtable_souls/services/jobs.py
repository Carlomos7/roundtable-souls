"""Background work, without Qt. A Runner starts each piece of work on a thread of its own and reports what happens as
events: progress while it runs, then its result. The window's adapter (ui/jobs.py) delivers the events on the UI
thread, so work never touches the window itself.

A logged job (run_job) is one the Activity page lists: its lines go to a log file of its own and the jobs index
records how it ended; its result is an Outcome, what the window's status line shows.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from roundtable_souls.game.locate import Locations
from roundtable_souls.platform import logging as run_logging

PROGRESS = "progress"
RESULT = "result"


@dataclass(frozen=True)
class Event:
    task: int  # what Runner.start returned
    kind: str  # PROGRESS or RESULT
    value: Any = None


@dataclass(frozen=True)
class Outcome:
    """How a logged job ended: ok, and the status the window shows ("Finished", "Stopped (see details)", ...)."""

    ok: bool
    status: str


class Progress:
    """Handed to the work: progress(value) reports a step (a line of text, a value the window shows)."""

    def __init__(self, post: Callable[[Event], None], task: int):
        self._post, self._task = post, task

    def __call__(self, value: Any) -> None:
        self._post(Event(self._task, PROGRESS, value))


class Runner:
    """post receives every event, on the worker's thread (the adapter passes them on to the UI thread)."""

    def __init__(self, post: Callable[[Event], None]):
        self._post = post
        self._ids = itertools.count(1)

    def start(self, work: Callable[[Progress], Any], name: str | None = None) -> int:
        """Run work(progress) on a daemon thread and post its return value as the result. An exception is not caught
        here: it reaches threading.excepthook (the window reports it) and no result is posted. name: the thread's
        (crash reports show it); without one the thread is named after the work, as threading names it."""
        task = next(self._ids)
        progress = Progress(self._post, task)

        def run():
            self._post(Event(task, RESULT, work(progress)))

        run.__name__ = getattr(work, "__name__", run.__name__)
        threading.Thread(target=run, daemon=True, name=name).start()
        return task

    def start_job(self, job: Callable[[Any, Locations], None], setup, loc: Locations, title: str = "Job") -> int:
        """A logged job (run_job) on a thread of its own; its result is the job's Outcome."""

        def logged(_progress: Progress) -> Outcome:
            return run_job(job, setup, loc, title)

        logged.__name__ = "run_job"  # the thread's name, as when run_job itself was the thread's target
        return self.start(logged)


def run_job(job: Callable[[Any, Locations], None], setup, loc: Locations, title: str = "Job") -> Outcome:
    """Run job(setup, loc) on this (worker) thread as a logged job of its own: its lines go to its log file and the
    window, and the jobs index records how it ended. A job stops early with SystemExit (130: the user stopped it)."""
    profile = str(getattr(setup, "profile", "") or "")
    record = run_logging.begin_job(title.rstrip(". "), game=loc.game.key, profile=profile)
    log = run_logging.get_logger("job")
    try:
        job(setup, loc)
    except SystemExit as e:
        stopped = e.code == 130
        run_logging.end_job(record, "stopped" if stopped else "failed" if e.code not in (0, None) else None)
        return Outcome(e.code in (0, None), "Finished" if e.code in (0, None) else "Stopped (see details)")
    except Exception:
        log.exception("the job failed with an unexpected error")
        run_logging.end_job(record, "failed")
        return Outcome(False, "Error (see details)")
    run_logging.end_job(record)
    return Outcome(True, "Finished")
