"""Shared fixtures: an isolated settings file and data folder so tests never read or write the developer's own
(backups, the save library, deleted profiles), and no item names from whatever mods happen to be installed on the
machine running the tests (tests that read names build their own).

The write guard (writes_stay_in_temporary_folders, an audit hook): while a test runs, file changes made through
Python in the test process itself outside pytest's temporary folders and the system temporary folder raise
PermissionError, so a patch undone too early fails the test instead of touching the developer's files.
  Covered: open() and os.open() for writing (so Path.write_*, touch, tempfile), rename, replace, remove/unlink,
  rmdir, mkdir/makedirs, truncate, utime, chmod, link, symlink, shutil's copyfile, copytree, rmtree (and move,
  which is made of these), and sqlite3.connect (a read-only "mode=ro" URI excepted).
  Not covered: child processes the test starts; native code writing without Python's audit events (ctypes and
  Win32 calls such as the Recycle Bin's SHFileOperation, Qt's own file I/O such as QSettings or QSaveFile, writes
  SQLite makes after a connection is open); files opened before the test started (session- or module-scoped
  fixtures) and writes to already-open file descriptors; paths given relative to a dir_fd.
  Allowed besides the temporary folders: named pipes, __pycache__ folders, and the Recycle Bin items a test itself
  created (recycle_bin_left_clean restores and purges them). Reading is never refused."""

import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import pytest

from roundtable_souls.config import settings
from roundtable_souls.game import catalog as games
from roundtable_souls.game.locate import Locations
from roundtable_souls.mods import locations as mod_locations
from roundtable_souls.platform import data_folder, instance
from roundtable_souls.platform import paths as common
from roundtable_souls.saves import backups as save_backups
from roundtable_souls.saves import item_names

_WRITABLE: list[str] = []  # while a test runs: the folders it may write in; empty = not guarding
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC


def _refuse_outside(path) -> None:
    if not _WRITABLE or path is None or isinstance(path, int):
        return
    try:
        text = os.fsdecode(path)
    except TypeError:
        return
    if text.startswith("\\\\.\\pipe\\"):  # a named pipe (platform.instance talking to the window), not a file
        return
    for candidate in (os.path.abspath(text), os.path.realpath(text)):
        p = os.path.normcase(candidate)
        if "__pycache__" in p or any(p == root or p.startswith(root + os.sep) for root in _WRITABLE):
            return
    raise PermissionError(f"a test tried to write outside its temporary folders: {text}")


def _audit(event: str, args: tuple) -> None:
    """The audit events listed in the module docstring as covered."""
    if not _WRITABLE:
        return
    if event == "open":
        path, mode, flags = args
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (mode is None and flags & _WRITE_FLAGS):
            _refuse_outside(path)
    elif event in ("os.remove", "os.rmdir", "os.mkdir", "os.truncate", "os.utime", "os.chmod", "shutil.rmtree"):
        _refuse_outside(args[0])
    elif event in ("os.rename", "os.replace", "os.link", "os.symlink"):
        _refuse_outside(args[0])
        _refuse_outside(args[1])
    elif event in ("shutil.copyfile", "shutil.copytree"):
        _refuse_outside(args[1])
    elif event == "sqlite3.connect":
        target = os.fsdecode(args[0]) if isinstance(args[0], (str, bytes, os.PathLike)) else ""
        if target and target != ":memory:" and "mode=ro" not in target:
            if target.startswith("file:"):
                target = url2pathname(urlparse(target).path)
            _refuse_outside(target)


sys.addaudithook(_audit)  # audit hooks can't be removed; _WRITABLE switches it on per test


@pytest.fixture(autouse=True)
def writes_stay_in_temporary_folders(tmp_path_factory):
    """Switch the write guard on for the whole test (module docstring): pytest's temporary folders (every tmp_path)
    and the system temporary folder (where pytest and Qt keep their own scratch files) stay writable."""
    roots = {tmp_path_factory.getbasetemp(), Path(tempfile.gettempdir())}
    _WRITABLE[:] = sorted(
        {os.path.normcase(os.path.realpath(r)) for r in roots} | {os.path.normcase(str(r)) for r in roots}
    )
    yield
    _WRITABLE.clear()


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "settings_path", lambda: tmp_path / "launcher_settings.json")
    monkeypatch.setattr(data_folder, "data_root", lambda: tmp_path / "launcher-data")
    # Moving older folders into the data folder only ever happens inside this test's own folder: a test that builds
    # the real window sees the developer's real saves and profiles, and must never move anything out of them.
    for module, name in ((save_backups, "adopt_legacy_save_folders"), (data_folder, "adopt_legacy_profile_folders")):
        real = getattr(module, name)

        def guarded(folder, *args, _real=real, **kwargs):
            if tmp_path.resolve() in Path(folder).resolve().parents:
                return _real(folder, *args, **kwargs)
            return None

        monkeypatch.setattr(module, name, guarded)
    save_backups._adopted.clear()
    yield
    save_backups._adopted.clear()


@pytest.fixture(autouse=True)
def installed_me3_not_asked(monkeypatch):
    """A rebuild records the installed me3's version by running it: tests never run the developer's me3."""
    from roundtable_souls.mods.backends import builtin

    monkeypatch.setattr(builtin, "_me3_version", lambda: "0.13.0")


@pytest.fixture(autouse=True)
def run_in_a_temporary_folder(tmp_path, monkeypatch):
    """Every test runs from its own temporary folder, never the repository: a relative path gone wrong (an empty path
    is the current folder) can then only reach that folder."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def recycle_bin_left_clean(monkeypatch):
    """Removing a mod sends its folder to the real Recycle Bin: every item a test sends there is purged after it,
    so the bin is left as it was."""
    from roundtable_souls.platform import trash

    made = []
    real = trash.send

    def send(path):
        rec = real(path)
        made.append(rec)
        for p in (rec.get("item"), rec.get("info")):  # this test's own bin items may be restored and purged
            if p:
                _WRITABLE.append(os.path.normcase(os.path.abspath(p)))
        return rec

    monkeypatch.setattr(trash, "send", send)
    yield
    for rec in made:
        trash.purge(rec)


@pytest.fixture(autouse=True)
def clean_logging():
    """No job, sink or standalone run survives a test, so one test's lines never reach another's files."""
    from roundtable_souls.platform import logging as run_logging

    yield
    job = run_logging.current_job()
    if job is not None:
        run_logging.end_job(job)
    if run_logging._standalone is not None:
        run_logging.end_job(run_logging._standalone)
        run_logging._standalone = None
    run_logging.detach_sink()
    run_logging._dir_override = None


@pytest.fixture(autouse=True)
def no_installed_mod_names(request, monkeypatch):
    if request.module.__name__.endswith("test_gamefiles"):
        return
    monkeypatch.setattr(item_names, "item_names", lambda *a, **k: item_names.ItemNames({}))


@pytest.fixture(autouse=True)
def records_back_to_their_files():
    """create_app points the hash cache and the activity log at its database; every test ends with them back on their
    files, so no test writes through another test's (closed) database."""
    from roundtable_souls.mods import rebuild
    from roundtable_souls.platform import logging as run_logging

    yield
    rebuild.use_hash_store(None)
    run_logging.use_job_store(None)


@pytest.fixture(autouse=True)
def elden_ring_is_the_active_game(tmp_path):
    """Every test starts on Elden Ring (the rebuild code's locations, as create_app would give them), with no detection
    cached from a prior test that used a different environment, and instance names scoped to its own folder."""
    mod_locations.use(Locations(games.DEFAULT))
    instance.use_scope("RoundtableSouls.Test", tmp_path)
    common.clear_detection_cache()
    common._PROFILE_GAMES_CACHE.clear()
    yield
    mod_locations.use(None)
    common.clear_detection_cache()
    common._PROFILE_GAMES_CACHE.clear()
