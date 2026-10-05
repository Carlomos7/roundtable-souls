"""The job runner (services/jobs.py): work runs on a thread of its own and reports progress, then its result, as
events in order; a failure reaches threading.excepthook and posts no result."""

import threading

from roundtable_souls.game import catalog
from roundtable_souls.game.locate import Locations
from roundtable_souls.services import jobs


def collect():
    events, finished = [], threading.Event()

    def post(event):
        events.append(event)
        if event.kind == jobs.RESULT:
            finished.set()

    return events, finished, post


def test_progress_then_the_result_in_order():
    events, finished, post = collect()

    def work(progress):
        progress("one")
        progress("two")
        return 42

    task = jobs.Runner(post).start(work)
    assert finished.wait(5)
    assert [(e.task, e.kind, e.value) for e in events] == [
        (task, jobs.PROGRESS, "one"),
        (task, jobs.PROGRESS, "two"),
        (task, jobs.RESULT, 42),
    ]


def test_threads_are_named_like_threading_names_them(monkeypatch):
    names, finished = [], threading.Event()

    def work(_progress):
        names.append(threading.current_thread().name)

    runner = jobs.Runner(lambda e: finished.set() if e.kind == jobs.RESULT else None)
    runner.start(work, name="launcher-update")
    assert finished.wait(5)
    finished.clear()
    runner.start(work)
    assert finished.wait(5)
    assert names[0] == "launcher-update" and names[1].endswith("(work)")  # crash reports name the thread


def test_a_failure_reaches_the_excepthook_and_posts_no_result(monkeypatch):
    events, seen = [], threading.Event()
    caught = []
    monkeypatch.setattr(threading, "excepthook", lambda a: (caught.append(a.exc_type), seen.set()))

    def work(_progress):
        raise ValueError("boom")

    jobs.Runner(events.append).start(work)
    assert seen.wait(5)
    assert caught == [ValueError] and events == []


def test_a_logged_job_posts_its_outcome():
    events, finished, post = collect()
    jobs.Runner(post).start_job(lambda setup, loc: None, None, Locations(catalog.ELDEN_RING), "Testing...")
    assert finished.wait(5)
    assert events[-1].value == jobs.Outcome(True, "Finished")
