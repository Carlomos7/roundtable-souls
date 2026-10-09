"""Off-screen QML view tests (technical specification §8.5, "screenshots and UI tests"): pages render in a real
QQuickWindow on the offscreen platform with the software scene graph, over synthetic data and a fake host.

Set S5_SHOTS (or RS_VIEW_SHOTS) to a folder to keep every render as a PNG for review; otherwise renders go to the
test's temporary folder."""

import datetime
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtQuick")
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from roundtable_souls.ui.pages.activity.adapter import ActivityAdapter  # noqa: E402
from roundtable_souls.ui.pages.activity.presenter import ActivityPresenter  # noqa: E402
from roundtable_souls.ui.pages.registry import QmlPage  # noqa: E402

NOW = datetime.datetime(2026, 10, 9, 12, 0)

JOBS = [
    {
        "id": "p2",
        "title": "Play Elden Ring",
        "kind": "play",
        "game": "eldenring",
        "start": "2026-10-09T11:00:00",
        "seconds": 7800,
        "outcome": "done",
        "log": "p2.log",
        "summary": "finished after 2h 10m",
        "attachments": ["p2.me3.log"],
    },
    {
        "id": "i1",
        "title": "install mod Grand Merchant",
        "kind": "install",
        "game": "eldenring",
        "start": "2026-10-09T09:30:00",
        "seconds": 12,
        "outcome": "done",
        "log": "i1.log",
        "summary": "done, merged mods rebuilt",
        "undo": {"type": "install", "name": "Grand Merchant", "profile": "eldenring.me3"},
    },
    {
        "id": "r1",
        "title": "rebuild combined parameters",
        "kind": "rebuild",
        "game": "eldenring",
        "start": "2026-10-08T21:03:00",
        "seconds": 3,
        "outcome": "failed",
        "log": "r1.log",
        "problem": "regulation.bin clash, see log",
    },
]


class FakeHost:
    """The window that hosts a page, without one: jobs are recorded, background work runs at once."""

    def __init__(self):
        self.busy = False
        self.game_running = False
        self.locations = "LOCATIONS"
        self.jobs: list[str] = []
        self.seen = 0

    def run_job(self, job, status):
        self.jobs.append(status)

    def mark_seen(self):
        self.seen += 1

    def run_in_background(self, work, on_result):
        on_result(work())


@pytest.fixture(scope="session")
def qt_app():
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Software)
    return QApplication.instance() or QApplication([])


@pytest.fixture
def activity_entry():
    presenter = ActivityPresenter(read_jobs=lambda: list(JOBS), now=lambda: NOW, undo_available=bool)
    return QmlPage("activity", "Pages/ActivityPage.qml", lambda host, n: ActivityAdapter(host, n, presenter=presenter))


@pytest.fixture
def host() -> FakeHost:
    return FakeHost()


@pytest.fixture
def shots(tmp_path) -> Path:
    where = os.environ.get("S5_SHOTS") or os.environ.get("RS_VIEW_SHOTS")
    out = Path(where) if where else tmp_path / "shots"
    out.mkdir(parents=True, exist_ok=True)
    return out
