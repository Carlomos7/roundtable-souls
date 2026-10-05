"""platform.files.atomic_write: a write either lands whole or leaves the file as it was, and writers of the same
file never share a temp file."""

import os
import threading

import pytest

from roundtable_souls.platform.files import atomic_write


def test_a_failed_write_leaves_the_file_and_no_temp_file(tmp_path, monkeypatch):
    p = tmp_path / "note.json"
    atomic_write(p, "before")

    def cut(src, dst):
        raise OSError("power cut before the rename")

    monkeypatch.setattr(os, "replace", cut)
    with pytest.raises(OSError):
        atomic_write(p, "after")
    assert p.read_text() == "before" and [f.name for f in tmp_path.iterdir()] == ["note.json"]


def test_each_write_has_its_own_temp_file(tmp_path, monkeypatch):
    seen = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda src, dst: (seen.append(os.fspath(src)), real(src, dst)))
    for text in ("one", "two"):
        atomic_write(tmp_path / "f.txt", text)
    assert len(set(seen)) == 2 and all(s.endswith(".tmp") for s in seen)


def test_a_second_writer_between_write_and_rename_does_not_take_the_first_ones_temp_file(tmp_path, monkeypatch):
    # With one shared <name>.tmp, B's rename would carry A's temp file away and A's rename would fail (or land B's
    # bytes as A's). Each writer must rename exactly what it wrote.
    p = tmp_path / "library.json"
    real = os.replace
    calls = []

    def replace(src, dst):
        calls.append(os.fspath(src))
        if len(calls) == 1:  # A has written its temp file and is about to rename it: B writes in full now
            atomic_write(p, "B")
            assert p.read_text() == "B"
        real(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    atomic_write(p, "A")
    assert p.read_text() == "A" and calls[0] != calls[1]
    assert [f.name for f in tmp_path.iterdir()] == ["library.json"]


def test_threads_writing_one_file_leave_it_whole(tmp_path):
    p = tmp_path / "library.json"
    payloads = [(str(i) * 200_000) for i in range(6)]
    errors: list[BaseException] = []

    def writer(text):
        for _ in range(15):
            try:
                atomic_write(p, text)
            except PermissionError:
                pass  # Windows refuses a rename onto a file another writer is renaming; the file stays whole
            except BaseException as e:
                errors.append(e)

    threads = [threading.Thread(target=writer, args=(t,)) for t in payloads]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and p.read_text() in payloads
    assert [f.name for f in tmp_path.iterdir()] == ["library.json"]
