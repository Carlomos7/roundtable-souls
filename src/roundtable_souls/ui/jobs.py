"""The window's side of services/jobs.py: events the worker threads post arrive here, on the UI thread, and go to the
callbacks given with each piece of work."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal

from roundtable_souls.services import jobs


class Jobs(QObject):
    _arrived = Signal(object)  # a jobs.Event, emitted on a worker thread; Qt queues it to this object's thread

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._calls: dict[int, tuple[Callable[[Any], None] | None, Callable[[Any], None] | None]] = {}
        self._arrived.connect(self._deliver)
        self.runner = jobs.Runner(self._arrived.emit)

    def start(
        self,
        work: Callable[[jobs.Progress], Any],
        on_result: Callable[[Any], None] | None = None,
        on_progress: Callable[[Any], None] | None = None,
        name: str | None = None,
    ) -> int:
        """Run work(progress) on a worker thread; on_progress gets each step and on_result the return value, both on
        the UI thread."""
        task = self.runner.start(work, name=name)
        # Events are delivered from the event loop, which cannot run before this method returns: none is missed.
        self._calls[task] = (on_progress, on_result)
        return task

    def start_job(self, job, setup, loc, title: str, on_done: Callable[[jobs.Outcome], None]) -> int:
        """A logged job (jobs.run_job); on_done gets its Outcome on the UI thread."""
        task = self.runner.start_job(job, setup, loc, title)
        self._calls[task] = (None, on_done)
        return task

    def _deliver(self, event: jobs.Event) -> None:
        on_progress, on_result = self._calls.get(event.task, (None, None))
        if event.kind == jobs.PROGRESS:
            if on_progress is not None:
                on_progress(event.value)
            return
        self._calls.pop(event.task, None)
        if on_result is not None:
            on_result(event.value)
