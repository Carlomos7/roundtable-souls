"""The update watchdog scripts themselves, run for real against a fake install (short timeouts): a version that
reports ready is kept; one that does not is undone (its packages removed, the kept version re-applied, a rollback
record written); an update that was never applied leaves everything alone."""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from roundtable_souls import updates

SCRIPTS = Path(updates.__file__).resolve().parent / "data"
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="PowerShell watchdog")
linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="sh watchdog")


def _sq(root: Path, version: str):
    (root / "current").mkdir(parents=True, exist_ok=True)
    (root / "current" / "sq.version").write_text(f"<package><version>{version}</version></package>", encoding="utf-8")


def _windows_install(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    _sq(root, "1.0.0")
    (root / "packages").mkdir()
    (root / "packages" / "X-2.0.0-full.nupkg").write_bytes(b"new")
    (root / "packages" / "X-1.0.0-full.nupkg").write_bytes(b"old")
    # any harmless program stands in for Update.exe: the script only runs it and logs its exit code
    shutil.copy(Path(shutil.which("where.exe") or r"C:\Windows\System32\where.exe"), root / "Update.exe")
    return root


def _start_ps(root: Path, state: Path, apply_s=4, ready_s=3):
    state.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
         str(SCRIPTS / "update-watchdog.ps1"), "-Root", str(root), "-Version", "2.0.0", "-Package",
         str(root / "kept.nupkg"), "-State", str(state), "-WaitApply", str(apply_s), "-WaitReady", str(ready_s)],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )  # fmt: skip


@windows_only
def test_windows_watchdog_keeps_a_version_that_reports_ready(tmp_path):
    root, state = _windows_install(tmp_path), tmp_path / "state"
    proc = _start_ps(root, state)
    time.sleep(1.5)
    _sq(root, "2.0.0")  # Velopack applied it
    (state / "ready-2.0.0").write_text("window")
    assert proc.wait(30) == 0
    log = (state / "watchdog.log").read_text(encoding="utf-8")
    assert "2.0.0 is ready" in log and not (state / "rollback.json").exists()
    assert (root / "packages" / "X-2.0.0-full.nupkg").exists()


@windows_only
def test_windows_watchdog_undoes_a_version_that_does_not_start(tmp_path):
    root, state = _windows_install(tmp_path), tmp_path / "state"
    proc = _start_ps(root, state)
    time.sleep(1.5)
    _sq(root, "2.0.0")
    assert proc.wait(30) == 0
    record = json.loads((state / "rollback.json").read_text(encoding="utf-8-sig"))
    assert record["version"] == "2.0.0" and "did not finish starting" in record["reason"]
    assert not (root / "packages" / "X-2.0.0-full.nupkg").exists()  # Velopack cannot apply it again
    assert (root / "packages" / "X-1.0.0-full.nupkg").exists()
    log = (state / "watchdog.log").read_text(encoding="utf-8")
    assert "putting the previous version back" in log and "Update.exe apply exited" in log


@windows_only
def test_windows_watchdog_leaves_an_update_that_never_applied(tmp_path):
    root, state = _windows_install(tmp_path), tmp_path / "state"
    assert _start_ps(root, state, apply_s=2).wait(30) == 0
    assert "nothing to undo" in (state / "watchdog.log").read_text(encoding="utf-8")
    assert not (state / "rollback.json").exists() and (root / "packages" / "X-2.0.0-full.nupkg").exists()


def _start_sh(app: Path, kept: Path, state: Path, apply_s=4, ready_s=3):
    state.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(["/bin/sh", str(SCRIPTS / "update-watchdog.sh"), str(app), "2.0.0", str(kept), str(state),
                             str(apply_s), str(ready_s), "Test.Pack.NotInstalled"])  # fmt: skip


def _appimage(tmp_path: Path, body: bytes) -> Path:
    app = tmp_path / "Test.AppImage"
    app.write_bytes(body)
    app.chmod(0o755)
    return app


def _replace(app: Path, body: bytes):
    new = app.with_name("new.tmp")
    new.write_bytes(body)
    new.chmod(0o755)
    new.replace(app)  # a new inode, as Velopack's move does


@linux_only
def test_linux_watchdog_keeps_a_version_that_reports_ready(tmp_path):
    app = _appimage(tmp_path, b"#!/bin/sh\nexit 0\n")
    kept = tmp_path / "kept.AppImage"
    kept.write_bytes(b"#!/bin/sh\nexit 0\n# old\n")
    state = tmp_path / "state"
    proc = _start_sh(app, kept, state)
    time.sleep(1)
    _replace(app, b"#!/bin/sh\nexit 0\n# new\n")
    (state / "ready-2.0.0").write_text("window")
    assert proc.wait(30) == 0
    assert "2.0.0 is ready" in (state / "watchdog.log").read_text() and b"# new" in app.read_bytes()


@linux_only
def test_linux_watchdog_puts_the_kept_appimage_back(tmp_path):
    app = _appimage(tmp_path, b"#!/bin/sh\nexit 0\n")
    kept = tmp_path / "kept.AppImage"
    kept.write_bytes(b"#!/bin/sh\nexit 0\n# old\n")
    state = tmp_path / "state"
    proc = _start_sh(app, kept, state)
    time.sleep(1)
    _replace(app, b"#!/bin/sh\nexit 3\n# broken\n")
    assert proc.wait(30) == 0
    assert app.read_bytes() == kept.read_bytes()
    assert json.loads((state / "rollback.json").read_text())["version"] == "2.0.0"
