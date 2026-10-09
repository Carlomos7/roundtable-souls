"""--self-test (technical specification §8.5): proves that a build, as packaged, starts and initializes: the modules,
data and QML the bundler had to collect are there, the database opens at the current schema, and every registered
QML page loads in every theme with no QML warning. It runs off-screen in a temporary data folder (cli.py points
ROUNDTABLE_SOULS_DATA there before anything else runs) with a fake host: nothing of the user's is read or written,
no game or me3 is started, no update feed is contacted.

What it does not verify: visual correctness, behaviour against a real game, saves or me3, or native integration
(window manager, high-DPI, file dialogs, shortcuts, the installer, the updater). Until the QML shell (S9) it covers
the QML page windows only, not the Widgets window, which the release workflow's --shots step still exercises.

One line per check, then a summary; exit code 0 only when every check passed."""

from __future__ import annotations

import importlib
import json
import os
from collections.abc import Callable
from pathlib import Path

from roundtable_souls.resources import DATA_DIR, PACKAGE_DIR

THEMES = ("dark", "tarnished", "light")
LIST_FILE = DATA_DIR / "self-test.json"


class SelfTestHost:
    """The host a page sees during the self-test: idle, no game, jobs refused, background work run at once."""

    busy = False
    game_running = False
    locations = None

    def run_job(self, job, status: str) -> None:
        raise RuntimeError("the self-test runs no jobs")

    def mark_seen(self) -> None:
        pass

    def run_in_background(self, work, on_result) -> None:
        on_result(work())


class Report:
    def __init__(self, out: Callable[[str], None] = print):
        self.out = out
        self.failed = 0
        self.passed = 0

    def check(self, name: str, test: Callable[[], str | None]) -> None:
        """Run test(); it returns None (or a note) when the check passed and raises when it did not."""
        try:
            note = test()
        except Exception as e:  # every failure is reported, none stops the others
            self.failed += 1
            self.out(f"FAIL  {name}: {type(e).__name__}: {e}")
            return
        self.passed += 1
        self.out(f"ok    {name}" + (f" ({note})" if note else ""))


def requirements() -> dict:
    return json.loads(LIST_FILE.read_text(encoding="utf-8"))


def run(data_dir: Path, out: Callable[[str], None] = print) -> int:
    """All checks; 0 when every one passed."""
    report = Report(out)
    out(f"Roundtable Souls self-test, data folder {data_dir}")
    report.check("isolated data folder", lambda: _isolated(data_dir))
    try:
        need = requirements()
    except (OSError, ValueError) as e:
        problem = e
        report.check("the self-test list", lambda: _raise(problem))
        need = {"python_modules": [], "qml_modules": [], "files": []}
    for name in need["python_modules"]:
        report.check(f"module {name}", lambda name=name: _import(name))
    for spec in need["files"]:
        report.check(f"file {spec.get('path') or spec.get('glob')}", lambda spec=spec: _files(spec))
    report.check("SQLite version", _sqlite)
    report.check("database opens at the current schema", lambda: _database(data_dir))
    _qml(report, need["qml_modules"])
    out(f"{report.passed} passed, {report.failed} failed")
    out(
        "Limits: packaging and initialization only; not visual correctness, real games, saves or me3, native "
        "integration, the installer or the updater; the Widgets window is not covered until the QML shell (S9)."
    )
    return 1 if report.failed else 0


def _raise(e: Exception):
    raise e


def _isolated(data_dir: Path) -> str:
    from roundtable_souls.config.settings import data_dir as settings_data_dir

    data_dir = data_dir.resolve()
    if Path(os.environ.get("ROUNDTABLE_SOULS_DATA", "")).resolve() != data_dir or settings_data_dir() != data_dir:
        raise RuntimeError(f"the data folder is {settings_data_dir()}, not the temporary {data_dir}")
    return str(data_dir)


def _import(name: str) -> None:
    importlib.import_module(name)


def _files(spec: dict) -> str | None:
    if "path" in spec:
        path = PACKAGE_DIR / spec["path"]
        if not path.is_file():
            raise FileNotFoundError(path)
        return None
    found = list(PACKAGE_DIR.glob(spec["glob"]))
    if len(found) < int(spec.get("min", 1)):
        raise FileNotFoundError(f"{len(found)} found, {spec.get('min', 1)} needed")
    return f"{len(found)}"


def _sqlite() -> str:
    import sqlite3

    from roundtable_souls.storage.db import sqlite_problem

    problem = sqlite_problem()
    if problem:
        raise RuntimeError(problem)
    return sqlite3.sqlite_version


def _database(data_dir: Path) -> None:
    from roundtable_souls.storage import db

    database = db.open_database(data_dir)
    database.close()


def _qml(report: Report, modules: list[str]) -> None:
    """The QML modules import, and every registered page loads in its window in every theme with no warning."""
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
    from PySide6.QtWidgets import QApplication

    from roundtable_souls.ui.page_window import PageWindow, use_qml_cache_folder
    from roundtable_souls.ui.pages.registry import QML_PAGES

    cache = use_qml_cache_folder()  # before the first engine: Qt's compiled QML stays in the temporary data folder
    if QCoreApplication.instance() is None:
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Software)
    app = QApplication.instance() or QApplication([])
    for name in modules:
        report.check(f"QML module {name}", lambda name=name: _qml_module(name))

    for entry in QML_PAGES:
        for theme in THEMES:

            def page(entry=entry, theme=theme) -> None:
                w = PageWindow(entry, SelfTestHost(), theme)
                try:
                    if not w.build():
                        raise RuntimeError("the window did not load: " + "; ".join(w.warnings))
                    win = w.window
                    if win is None:
                        raise RuntimeError("no window")
                    win.show()
                    for _ in range(10):
                        app.processEvents()
                    if w.page_item() is None:
                        raise RuntimeError("the page did not load: " + "; ".join(w.warnings))
                    if w.warnings:
                        raise RuntimeError(f"{len(w.warnings)} QML warning(s): " + "; ".join(w.warnings))
                finally:
                    w.dispose()
                    app.processEvents()

            report.check(f"page {entry.name} in the {theme} theme", page)

    def cache_stays_in_the_data_folder() -> str:
        if os.environ.get("QML_DISABLE_DISK_CACHE"):
            return "the disk cache is off for this run"
        if cache is None or not any(cache.glob("*.qmlc")):
            raise RuntimeError(f"no compiled QML in {cache}: Qt's cache went somewhere else")
        return str(cache)

    report.check("QML cache in the temporary data folder", cache_stays_in_the_data_folder)


def _qml_module(name: str) -> None:
    from PySide6.QtQml import QQmlComponent, QQmlEngine

    from roundtable_souls.ui.page_window import QML_DIR

    engine = QQmlEngine()
    engine.addImportPath(str(QML_DIR))
    component = QQmlComponent(engine)
    component.setData(f"import QtQuick\nimport {name}\nQtObject {{}}\n".encode(), QML_DIR.as_uri() + "/probe.qml")
    if component.isError():
        raise RuntimeError("; ".join(e.toString() for e in component.errors()))
    obj = component.create()
    if obj is None:
        raise RuntimeError("; ".join(e.toString() for e in component.errors()) or "it did not instantiate")
