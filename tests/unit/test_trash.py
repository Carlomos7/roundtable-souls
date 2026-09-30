"""The Recycle Bin / desktop trash, for real: every item a test sends is restored or purged before it ends, so the
bin is left as it was."""

import os
import sys

import pytest

from roundtable_souls.system import trash

pytestmark = pytest.mark.skipif(not trash.available(), reason="no trash on this system")


@pytest.fixture
def sent(monkeypatch, tmp_path):
    """Records sent in the test; purged afterwards if they are still in the bin. On Linux the trash is a
    temporary one (XDG_DATA_HOME), never the real one."""
    if not sys.platform == "win32":
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    records = []
    yield records
    for r in records:
        if trash.exists(r):
            trash.purge(r)


def make_mod(root, name="probe-mod"):
    d = root / name
    (d / "parts").mkdir(parents=True)
    (d / "parts" / "x.partsbnd.dcx").write_bytes(b"part" * 500)
    (d / "readme.txt").write_text("hello")
    return d


def test_a_folder_goes_to_the_trash_and_comes_back_whole(tmp_path, sent):
    mod = make_mod(tmp_path)
    rec = trash.send(mod)
    sent.append(rec)
    assert not mod.exists() and trash.exists(rec) and rec["kind"] in ("windows", "freedesktop")
    assert os.path.normcase(rec["original"]) == os.path.normcase(str(mod))
    back = trash.restore(rec)
    assert back == mod and (mod / "parts" / "x.partsbnd.dcx").read_bytes() == b"part" * 500
    assert not trash.exists(rec)  # its bin record is gone, as with Windows' own Restore


def test_two_deletions_of_the_same_path_are_told_apart(tmp_path, sent):
    first = trash.send(make_mod(tmp_path))
    sent.append(first)
    mod = make_mod(tmp_path)
    (mod / "readme.txt").write_text("second")
    second = trash.send(mod)
    sent.append(second)
    assert first["item"] != second["item"]
    trash.restore(second)
    assert (mod / "readme.txt").read_text() == "second"


def test_restore_never_overwrites_and_can_go_elsewhere(tmp_path, sent):
    mod = make_mod(tmp_path)
    rec = trash.send(mod)
    sent.append(rec)
    mod.mkdir()  # something new at the old place
    with pytest.raises(FileExistsError):
        trash.restore(rec)
    other = trash.restore(rec, tmp_path / "probe-mod (restored)")
    assert (other / "readme.txt").read_text() == "hello"


def test_an_item_gone_from_the_trash_is_said(tmp_path, sent):
    rec = trash.send(make_mod(tmp_path))
    trash.purge(rec)
    assert not trash.exists(rec)
    with pytest.raises(trash.TrashError):
        trash.restore(rec)


def test_a_missing_path_is_refused_and_nothing_is_recorded(tmp_path):
    with pytest.raises(trash.TrashError):
        trash.send(tmp_path / "nothing-here")
    assert not trash.exists(None) and not trash.exists({})


@pytest.mark.skipif(sys.platform == "win32", reason="freedesktop layout")
def test_linux_trash_writes_an_info_file(tmp_path, sent):
    mod = make_mod(tmp_path, "with space")
    rec = trash.send(mod)
    sent.append(rec)
    info = open(rec["info"], encoding="utf-8").read()
    assert info.startswith("[Trash Info]\nPath=") and "with%20space" in info and "DeletionDate=" in info


@pytest.mark.parametrize(
    "record",
    [
        {"kind": "gone", "item": "", "info": "", "original": "x"},  # deleted for good: empty paths
        {"kind": "windows", "item": "", "info": ""},
        {"kind": "windows", "item": ".", "info": "."},
        {"kind": "freedesktop", "item": "files", "info": "info"},
        None,
        {},
    ],
)
def test_purge_and_restore_never_touch_anything_but_a_real_trash_item(tmp_path, monkeypatch, record):
    here = tmp_path / "work"
    (here / "src").mkdir(parents=True)
    (here / "src" / "keep.py").write_text("keep")
    monkeypatch.chdir(here)  # an empty path is the current folder
    trash.purge(record)
    assert (here / "src" / "keep.py").read_text() == "keep"
    assert not trash.exists(record)
    with pytest.raises(trash.TrashError):
        trash.restore(record or {"kind": "gone"})


def test_purge_refuses_a_path_outside_a_trash(tmp_path):
    victim = tmp_path / "$R123456"
    victim.mkdir()
    info = tmp_path / "$I123456"
    info.write_text("x")
    trash.purge({"kind": "windows", "item": str(victim), "info": str(info)})  # not inside a $Recycle.Bin
    assert victim.exists() and info.exists()
