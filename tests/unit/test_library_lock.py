"""The save library's lock and recovery: every change is one locked read-change-write shared by processes, the
manifest is read again once the lock is held, unknown fields survive, and a removal whose manifest write fails puts
the copy back or leaves a record of where it is."""

import json
import shutil
import subprocess
import sys
import textwrap

import pytest

from roundtable_souls.game import catalog as games
from roundtable_souls.saves import backups as save_backups
from roundtable_souls.saves import library as Lib
from roundtable_souls.saves import regulation

ER = games.ELDEN_RING

WORKER = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    from roundtable_souls.platform import data_folder
    from roundtable_souls.saves import library as Lib

    root, save_dir, entry_id, tag, mode = sys.argv[1:6]
    data_folder.data_root = lambda: Path(root)  # the test's data folder, never the real one
    if mode == "rename":
        for i in range(20):
            Lib.rename(Path(save_dir), entry_id, f"{tag} {i}")
        print("done", flush=True)
    elif mode == "hold":
        with Lib.library_lock(Path(save_dir)):
            print("held", flush=True)
            sys.stdin.read()
    """
)


def _save(path, fill):
    data = bytearray(regulation.FILE_SIZE)
    data[:4] = b"BND4"
    data[4] = fill
    path.write_bytes(bytes(data))
    return path


def _worker(tmp_path, acct, entry_id, tag, mode):
    return subprocess.Popen(
        [sys.executable, "-c", WORKER, str(tmp_path / "launcher-data"), str(acct), entry_id, tag, mode],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )


@pytest.fixture
def acct(tmp_path):
    a = tmp_path / "EldenRing" / "7656"
    a.mkdir(parents=True)
    return a


def test_two_processes_changing_the_library_at_once_lose_nothing(tmp_path, acct):
    e = Lib.add(acct, _save(acct / "ER0000.sl2", 1), "start", ER)
    procs = [_worker(tmp_path, acct, e["id"], tag, "rename") for tag in ("a", "b")]
    for p in procs:
        assert p.stdout is not None
        assert p.stdout.readline().strip() == "done"
        p.wait(60)
    doc = Lib.load(acct)
    renames = [h for h in doc["history"] if h["action"] == "rename"]
    assert len(renames) == 40  # each read-change-write saw the one before it
    assert len(doc["entries"]) == 1 and doc["entries"][0]["name"] in ("a 19", "b 19")


def test_a_change_waits_for_the_lock_and_reads_the_manifest_after_it(tmp_path, acct, monkeypatch):
    e = Lib.add(acct, _save(acct / "ER0000.sl2", 1), "start", ER)
    monkeypatch.setattr(save_backups, "LOCK_TIMEOUT", 0.3)
    holder = _worker(tmp_path, acct, e["id"], "", "hold")
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
        before = (Lib.folder_for(acct) / Lib.MANIFEST).read_bytes()
        with pytest.raises(Lib.LibraryBusy):
            Lib.rename(acct, e["id"], "blocked")
        with pytest.raises(Lib.LibraryBusy):
            Lib.remove(acct, e["id"])
        assert (Lib.folder_for(acct) / Lib.MANIFEST).read_bytes() == before
        assert Lib.entry_path(acct, e).is_file()
        # what another process writes while it holds the lock is what this one reads once it gets it
        manifest = Lib.folder_for(acct) / Lib.MANIFEST
        raw = json.loads(before)
        raw["entries"][0]["name"] = "renamed elsewhere"
        manifest.write_text(json.dumps(raw), encoding="utf-8")
    finally:
        assert holder.stdin is not None
        holder.stdin.close()
        holder.wait(10)
    Lib.rename(acct, e["id"], "after")
    doc = Lib.load(acct)
    assert doc["history"][-1]["was"] == "renamed elsewhere" and doc["entries"][0]["name"] == "after"


def test_unknown_top_level_fields_survive_a_change(acct):
    e = Lib.add(acct, _save(acct / "ER0000.sl2", 1), "a", ER)
    manifest = Lib.folder_for(acct) / Lib.MANIFEST
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    raw["future"] = {"kept": True}
    raw["version"] = 1
    manifest.write_text(json.dumps(raw), encoding="utf-8")
    Lib.rename(acct, e["id"], "b")
    after = json.loads(manifest.read_text(encoding="utf-8"))
    assert after["future"] == {"kept": True} and after["version"] == 1
    assert "missing" not in after["entries"][0] and "unreadable" not in after


def _fail_manifest_writes(monkeypatch):
    real = Lib.atomic_write

    def write(path, data, backup=False):
        if path.name == Lib.MANIFEST:
            raise OSError("disk full")
        return real(path, data, backup)

    monkeypatch.setattr(Lib, "atomic_write", write)


def test_a_removal_whose_manifest_write_fails_puts_the_copy_back(acct, monkeypatch):
    e = Lib.add(acct, _save(acct / "ER0000.sl2", 1), "a", ER)
    folder = Lib.folder_for(acct)
    manifest_before = (folder / Lib.MANIFEST).read_bytes()
    _fail_manifest_writes(monkeypatch)
    with pytest.raises(OSError, match="disk full"):
        Lib.remove(acct, e["id"])
    assert Lib.entry_path(acct, e).is_file()  # back where it was
    assert (folder / Lib.MANIFEST).read_bytes() == manifest_before
    removed = folder / save_backups.LIBRARY_REMOVED
    assert not removed.exists() or not any(removed.iterdir())
    doc = Lib.load(acct)
    assert [x["id"] for x in doc["entries"]] == [e["id"]] and not doc["entries"][0]["missing"]


def test_a_removal_that_can_neither_finish_nor_move_back_leaves_a_record(acct, monkeypatch):
    e = Lib.add(acct, _save(acct / "ER0000.sl2", 1), "a", ER)
    folder = Lib.folder_for(acct)
    _fail_manifest_writes(monkeypatch)
    real_move = shutil.move
    moves = []

    def move(src, dst):
        moves.append(src)
        if len(moves) > 1:  # the move back fails too
            raise PermissionError("in use")
        return real_move(src, dst)

    monkeypatch.setattr(Lib.shutil, "move", move)
    with pytest.raises(Lib.LibraryError, match="could not be put back") as err:
        Lib.remove(acct, e["id"])
    moved = folder / save_backups.LIBRARY_REMOVED / e["file"]
    assert str(moved) in str(err.value) and moved.is_file()
    note = json.loads((moved.parent / (moved.name + ".json")).read_text(encoding="utf-8"))
    assert note["id"] == e["id"] and note["library_path"] == str(Lib.entry_path(acct, e))
    entry = Lib.load(acct)["entries"][0]  # still listed, and says where its file is
    assert entry["id"] == e["id"] and entry["missing"] and entry["in_removed"] == str(moved)


def test_an_add_whose_manifest_write_fails_leaves_no_copy_behind(acct, monkeypatch):
    Lib.add(acct, _save(acct / "ER0000.sl2", 1), "a", ER)
    folder = Lib.folder_for(acct)
    before = sorted(p.name for p in folder.iterdir())
    _fail_manifest_writes(monkeypatch)
    with pytest.raises(OSError, match="disk full"):
        Lib.add(acct, acct / "ER0000.sl2", "b", ER)
    assert sorted(p.name for p in folder.iterdir()) == before


def test_the_lock_file_sits_beside_the_library_folder(acct):
    Lib.add(acct, _save(acct / "ER0000.sl2", 1), "a", ER)
    folder = Lib.folder_for(acct)
    assert (folder.parent / (folder.name + ".lock")).is_file()
    assert not [p for p in folder.iterdir() if p.suffix == ".lock"]
