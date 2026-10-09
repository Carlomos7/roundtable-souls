"""--self-test (technical specification §8.5): its list of required QML modules matches what pyside6-qmlimportscanner
finds in ui/qml, every listed file exists in the source tree, a missing one fails, and the whole self-test passes when
run from source (off-screen, in its own temporary data folder)."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from roundtable_souls.resources import PACKAGE_DIR
from roundtable_souls.ui import self_test

QML = PACKAGE_DIR / "ui" / "qml"


def scanner() -> str | None:
    found = shutil.which("pyside6-qmlimportscanner")
    if found:
        return found
    beside = Path(sys.executable).parent / ("pyside6-qmlimportscanner" + (".exe" if os.name == "nt" else ""))
    return str(beside) if beside.is_file() else None


def test_the_qml_module_list_is_what_the_scanner_finds():
    exe = scanner()
    if exe is None:
        pytest.skip("pyside6-qmlimportscanner is not installed")
    out = subprocess.run([exe, "-rootPath", str(QML), "-importPath", str(QML)], capture_output=True, check=True)
    found = sorted({e["name"] for e in json.loads(out.stdout) if e.get("type") == "module"})
    assert self_test.requirements()["qml_modules"] == found


def test_the_build_collects_only_the_qml_modules_the_launcher_needs():
    """scripts/pyinstaller_hooks/hook-PySide6.QtQml.py: every Qt module in the list and what it depends on, nothing
    like Qt WebEngine or Qt 3D (PyInstaller's own hook takes every QML module Qt ships: about 290 MB more)."""
    import runpy

    pytest.importorskip("PyInstaller")
    hook = runpy.run_path(str(PACKAGE_DIR.parents[1] / "scripts" / "pyinstaller_hooks" / "hook-PySide6.QtQml.py"))
    modules = hook["closure"](hook["WANTED"])
    shipped_by_qt = [m for m in self_test.requirements()["qml_modules"] if m.startswith("Qt")]
    assert set(shipped_by_qt) <= set(modules)
    assert {"QtQuick.Templates", "QtQml.Models"} <= set(modules)  # dependencies, found through the qmldir files
    assert not any(m.startswith(("QtWebEngine", "Qt3D", "QtQuick3D", "QtCharts", "QtMultimedia")) for m in modules)


def test_every_listed_file_is_in_the_source_tree():
    for spec in self_test.requirements()["files"]:
        self_test._files(spec)


def test_a_missing_file_is_a_failure_not_a_skip():
    lines = []
    report = self_test.Report(lines.append)
    report.check("file nope.txt", lambda: self_test._files({"path": "nope.txt"}))
    report.check("file none/*.png", lambda: self_test._files({"glob": "none/*.png", "min": 1}))
    assert report.failed == 2 and report.passed == 0
    assert lines[0].startswith("FAIL  file nope.txt: FileNotFoundError")


def test_compiled_qml_is_cached_inside_this_runs_data_folder(monkeypatch, tmp_path):
    """Qt names its QML cache folder after the program, which for the packaged build is the real data folder's name;
    use_qml_cache_folder() keeps it inside the data folder this run uses (the conftest's temporary one here)."""
    from roundtable_souls.platform import data_folder
    from roundtable_souls.ui import page_window

    for name in ("QML_DISK_CACHE_PATH", "QML_DISABLE_DISK_CACHE"):  # registered, so the test puts them back
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    folder = page_window.use_qml_cache_folder()
    root = data_folder.data_root()
    assert folder is not None and folder.is_relative_to(root)
    assert Path(os.environ["QML_DISK_CACHE_PATH"]) == folder
    assert root.is_relative_to(tmp_path)  # never the user's data folder

    def unset():
        raise RuntimeError("the data folder was not set")

    monkeypatch.delenv("QML_DISK_CACHE_PATH", raising=False)
    monkeypatch.setattr(data_folder, "data_root", unset)
    assert page_window.use_qml_cache_folder() is None
    assert os.environ["QML_DISABLE_DISK_CACHE"] == "1" and "QML_DISK_CACHE_PATH" not in os.environ


def test_the_self_test_passes_from_source(tmp_path):
    report = tmp_path / "report.txt"
    env = {k: v for k, v in os.environ.items() if k != "ROUNDTABLE_SOULS_DATA"}
    done = subprocess.run(
        [sys.executable, "-m", "roundtable_souls", "--self-test", str(report)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=300,
        check=False,
    )
    text = report.read_text(encoding="utf-8")
    assert done.returncode == 0, text
    assert "ok    database opens at the current schema" in text
    assert "ok    page activity in the light theme" in text
    assert ", 0 failed" in text
    data = next(line for line in text.splitlines() if line.startswith("ok    isolated data folder"))
    assert not Path(data.split("(", 1)[1].rstrip(")")).exists()  # the temporary data folder is gone
