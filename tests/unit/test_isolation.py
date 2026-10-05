"""The test run itself: while a test runs, files can be written only in the temporary folders (tests/conftest.py,
writes_stay_in_temporary_folders), so a test can never touch the developer's saves, settings or data folder."""

import contextlib
import os
import shutil
import uuid
from pathlib import Path

import pytest

OUTSIDE = Path.home() / f"roundtable-souls-test-probe-{uuid.uuid4().hex}"


@pytest.fixture
def leaves_nothing_outside():
    yield
    for p in (OUTSIDE, OUTSIDE.with_suffix(".txt")):
        with contextlib.suppress(OSError):
            if p.is_dir():
                p.rmdir()
            else:
                p.unlink()
    assert not OUTSIDE.exists() and not OUTSIDE.with_suffix(".txt").exists()


def test_writing_outside_the_temporary_folders_is_refused(tmp_path, leaves_nothing_outside):
    target = OUTSIDE.with_suffix(".txt")
    with pytest.raises(PermissionError, match="outside its temporary folders"):
        target.write_text("x")
    with pytest.raises(PermissionError):
        os.open(target, os.O_WRONLY | os.O_CREAT)
    inside = tmp_path / "a.txt"
    inside.write_text("x")  # inside is fine
    with pytest.raises(PermissionError):
        os.replace(inside, target)
    with pytest.raises(PermissionError):
        shutil.copyfile(inside, target)
    with pytest.raises(PermissionError):
        OUTSIDE.mkdir()
    with pytest.raises(PermissionError):
        os.remove(target)
    assert inside.read_text() == "x"


def test_a_database_outside_the_temporary_folders_is_refused_but_reading_one_is_not(tmp_path, leaves_nothing_outside):
    import sqlite3

    target = OUTSIDE.with_suffix(".txt")
    with pytest.raises(PermissionError):
        sqlite3.connect(target)
    with pytest.raises(PermissionError):
        sqlite3.connect(target.as_uri(), uri=True)
    inside = tmp_path / "x.db"
    sqlite3.connect(inside).close()
    sqlite3.connect(f"{inside.as_uri()}?mode=ro", uri=True).close()  # reading is never refused
    sqlite3.connect(":memory:").close()


def test_reading_outside_is_still_allowed(tmp_path):
    assert Path(__file__).read_text(encoding="utf-8").startswith('"""')
