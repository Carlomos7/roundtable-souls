"""Recovery in the save library: a swap that happened stays reported as happened when only its history line could
not be written (the line waits on disk and is added once, later), and a removal that stopped halfway can be put
back or finished from the launcher, after a restart too, only when nothing changed since. Also the lock order."""

import json
import shutil

import pytest

from roundtable_souls.game import catalog as games
from roundtable_souls.saves import backups as save_backups
from roundtable_souls.saves import library as Lib
from roundtable_souls.saves import regulation

ER = games.ELDEN_RING


def _save(path, fill):
    data = bytearray(regulation.FILE_SIZE)
    data[:4] = b"BND4"
    data[4] = fill
    path.write_bytes(bytes(data))
    return path


@pytest.fixture
def acct(tmp_path):
    a = tmp_path / "EldenRing" / "7656"
    a.mkdir(parents=True)
    return a


def _fail_manifest_writes(monkeypatch, after=0, everything=False):
    """Manifest writes fail once `after` of them have succeeded (everything: every write in the library fails)."""
    real = Lib.atomic_write
    done = []

    def write(path, data, backup=False):
        if everything and len(done) >= after:
            raise OSError("disk full")
        if path.name == Lib.MANIFEST:
            if len(done) >= after:
                raise OSError("disk full")
            done.append(path)
        return real(path, data, backup)

    monkeypatch.setattr(Lib, "atomic_write", write)


def _history(acct, action):
    return [h for h in Lib.load(acct)["history"] if h["action"] == action]


def test_a_swap_whose_history_cannot_be_written_still_reports_the_swap_and_keeps_the_record(acct, monkeypatch):
    live = _save(acct / "ER0000.sl2", 1)
    other = Lib.add(acct, _save(acct / "other.sl2", 2), "second run", ER)
    with monkeypatch.context() as m:
        _fail_manifest_writes(m, after=1)  # the outgoing save is added; the swap's own history line fails
        out = Lib.swap_in(acct, other["id"], live, "first run", ER)
    assert live.read_bytes()[4] == 2  # the swap happened, and nothing said otherwise
    assert out["outgoing"]["name"] == "first run" and out["backup"].is_file()
    assert "could not be updated" in out["warning"] and Lib.PENDING_HISTORY in out["warning"]
    pending = list((Lib.folder_for(acct) / Lib.PENDING_HISTORY).iterdir())
    assert len(pending) == 1 and _history(acct, "swap in") == []
    saved = pending[0].read_bytes()
    Lib.rename(acct, other["id"], "renamed")  # the next change (after a restart too: it is all on disk) adds it
    swaps = _history(acct, "swap in")
    assert len(swaps) == 1 and swaps[0]["target"] == "ER0000.sl2" and swaps[0]["backup"] == out["backup"].name
    assert not any((Lib.folder_for(acct) / Lib.PENDING_HISTORY).iterdir())
    pending[0].write_bytes(saved)  # as if removing the waiting file had failed: the line is still added only once
    Lib.rename(acct, other["id"], "again")
    assert len(_history(acct, "swap in")) == 1


def test_a_swap_that_cannot_record_anything_still_says_it_happened(acct, monkeypatch):
    live = _save(acct / "ER0000.sl2", 1)
    other = Lib.add(acct, _save(acct / "other.sl2", 2), "second run", ER)
    _fail_manifest_writes(monkeypatch, after=1)
    real = Lib.atomic_write
    monkeypatch.setattr(
        Lib,
        "atomic_write",
        lambda path, data, backup=False: (
            (_ for _ in ()).throw(OSError("read-only"))
            if Lib.PENDING_HISTORY in str(path)
            else real(path, data, backup)
        ),
    )
    out = Lib.swap_in(acct, other["id"], live, "first run", ER)
    assert live.read_bytes()[4] == 2 and "nor kept for later" in out["warning"]


def _stranded(acct, monkeypatch):
    """A removal that could neither finish nor move the copy back, then a 'restart' (the patches gone)."""
    e = Lib.add(acct, _save(acct / "ER0000.sl2", 1), "first run", ER)
    real_move, moves = shutil.move, []

    def move(src, dst):
        moves.append(src)
        if len(moves) > 1:
            raise PermissionError("in use")
        return real_move(src, dst)

    with monkeypatch.context() as m:
        _fail_manifest_writes(m, after=0)
        m.setattr(Lib.shutil, "move", move)
        with pytest.raises(Lib.LibraryError):
            Lib.remove(acct, e["id"])
    folder = Lib.folder_for(acct)
    moved = folder / save_backups.LIBRARY_REMOVED / e["file"]
    entry = Lib.load(acct)["entries"][0]
    assert entry["in_removed"] == str(moved)
    return e, folder, moved


def test_a_stranded_removal_can_be_put_back(acct, monkeypatch):
    e, folder, moved = _stranded(acct, monkeypatch)
    assert Lib.restore_removed(acct, e["id"]) is None
    assert (
        (folder / e["file"]).is_file() and not moved.exists() and not (moved.parent / (moved.name + ".json")).exists()
    )
    entry = Lib.load(acct)["entries"][0]
    assert not entry["missing"] and "in_removed" not in entry
    assert _history(acct, "restore")[0]["moved_from"] == str(moved)


def test_a_stranded_removal_can_be_finished(acct, monkeypatch):
    e, folder, moved = _stranded(acct, monkeypatch)
    Lib.finish_removal(acct, e["id"])
    assert Lib.load(acct)["entries"] == [] and moved.is_file()  # as after any removal
    assert json.loads((moved.parent / (moved.name + ".json")).read_text(encoding="utf-8"))["id"] == e["id"]
    assert _history(acct, "delete")[-1]["finished_later"] is True


@pytest.mark.parametrize("change", ["copy edited", "copy back home", "note about another copy", "note unreadable"])
def test_nothing_is_touched_when_something_changed_since(acct, monkeypatch, change):
    e, folder, moved = _stranded(acct, monkeypatch)
    note = moved.parent / (moved.name + ".json")
    if change == "copy edited":
        moved.write_bytes(b"edited by hand")
    elif change == "copy back home":
        shutil.copy2(moved, folder / e["file"])
    elif change == "note about another copy":
        note.write_text(json.dumps({**json.loads(note.read_text(encoding="utf-8")), "id": "someone-else"}))
    else:
        note.write_bytes(b"{damaged")
    before = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    for act in (Lib.restore_removed, Lib.finish_removal):
        with pytest.raises(Lib.LibraryError, match="nothing was changed"):
            act(acct, e["id"])
    assert {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()} == before


def test_the_library_lock_is_never_taken_inside_a_backups_lock(acct):
    with save_backups.account_lock(acct / "backups"):
        with pytest.raises(Lib.LockOrderError):
            with Lib.library_lock(acct):
                pass
    with Lib.library_lock(acct):  # the documented order works: library, then backups
        with save_backups.account_lock(acct / "backups"):
            pass
