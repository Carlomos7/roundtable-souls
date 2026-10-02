"""Removing a mod and taking it back: the entry where it was, the folder from the Recycle Bin, and knowing what a
removal leaves inside a combined result. Items a test puts in the real Recycle Bin are purged after it."""

import shutil
import sys

import pytest
from test_mod_merge import TALK, World

from roundtable_souls.mods import conflicts as overview
from roundtable_souls.mods import rebuild as merge
from roundtable_souls.mods import remove, undo
from roundtable_souls.platform import trash

PROFILE = """profileVersion = "v1"

# the base mod
[[packages]]
id = "base"
path = 'mod/base'

# voice pack: English lines
[[packages]]
id = "voice"
path = 'mod/voice'

# =====
#  UI
# =====

[[packages]]
id = "hud"
path = 'mod/hud'
"""

needs_trash = pytest.mark.skipif(not trash.available(), reason="no trash on this system")


@pytest.fixture
def sent():
    records = []
    yield records
    for rec in records:
        trash.purge(rec)  # only ever acts on a genuine bin item


@pytest.fixture
def prof(tmp_path, monkeypatch):
    if sys.platform != "win32":
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    base = tmp_path / "er"
    for name in ("base", "voice", "hud"):
        (base / "mod" / name / "sd").mkdir(parents=True)
        (base / "mod" / name / "sd" / f"{name}.bnk").write_bytes(name.encode())
    p = base / "p.me3"
    p.write_text(PROFILE, encoding="utf-8")
    return p


def removal(p, index, sent, delete=True):
    out = remove.uninstall(p, index, delete_folder=delete)
    if out.get("trash"):
        sent.append(out["trash"])
    rec = {
        "type": "remove",
        "profile": str(p),
        "name": out["name"],
        "path": out["path"],
        "entry_text": out["entry_text"],
        "where": out["where"],
        "trash": out.get("trash"),
    }
    return out, rec


@needs_trash
def test_a_removed_mod_comes_back_entry_and_folder(prof, sent):
    out, rec = removal(prof, 1, sent)
    folder = prof.parent / "mod" / "voice"
    assert out["removed_folder"] and not folder.exists() and trash.exists(out["trash"])
    assert undo.available(rec) and undo.label(rec) == "Restore"
    said = undo.run(rec, lambda s: None)
    assert said == "restored voice (its entry and its folder)"
    assert prof.read_text(encoding="utf-8") == PROFILE and (folder / "sd" / "voice.bnk").read_bytes() == b"voice"
    assert not undo.available(rec)  # done: nothing left to take back


def test_only_the_entry_comes_back_when_the_folder_was_kept(prof, sent):
    _out, rec = removal(prof, 1, sent, delete=False)
    assert rec["trash"] is None and undo.available(rec)
    assert undo.run(rec, lambda s: None) == "restored voice (its entry)"
    assert prof.read_text(encoding="utf-8") == PROFILE


@needs_trash
def test_an_emptied_bin_still_gives_the_entry_back(prof, sent):
    out, rec = removal(prof, 1, sent)
    trash.purge(out["trash"])
    lines = []
    assert undo.available(rec)
    undo.run(rec, lines.append)
    assert prof.read_text(encoding="utf-8") == PROFILE
    assert any("no longer in the Recycle Bin" in x for x in lines)


def test_a_folder_windows_deleted_for_good_leaves_the_entry_to_restore(prof, sent, monkeypatch):
    def gone(path):
        shutil.rmtree(path)
        return {"kind": "gone", "item": "", "info": "", "original": str(path), "deleted": 0}

    monkeypatch.setattr(trash, "send", gone)
    monkeypatch.setattr(trash, "available", lambda: True)
    out, rec = removal(prof, 1, sent)
    assert out["removed_folder"] and not trash.exists(out["trash"])
    assert undo.available(rec)
    undo.run(rec, lambda s: None)
    assert prof.read_text(encoding="utf-8") == PROFILE
    trash.purge(out["trash"])  # a "gone" record: nothing to purge, and nothing else touched
    assert prof.is_file() and (prof.parent / "mod" / "hud").is_dir()


@needs_trash
def test_a_folder_put_back_meanwhile_is_not_overwritten(prof, sent):
    out, rec = removal(prof, 1, sent)
    (prof.parent / "mod" / "voice").mkdir()  # reinstalled meanwhile
    with pytest.raises(FileExistsError):
        undo.run(rec, lambda s: None)
    assert trash.exists(out["trash"])  # still in the bin, nothing lost


def test_restore_is_not_offered_once_done_or_when_the_profile_is_gone(prof, sent):
    _out, rec = removal(prof, 1, sent, delete=False)
    undo.run(rec, lambda s: None)
    assert not undo.available(rec)
    prof.unlink()
    assert not undo.available(rec)
    with pytest.raises(undo.UndoError):
        undo.run(rec, lambda s: None)
    assert not undo.available(None) and not undo.available({"type": "nothing"})


def test_merged_from_names_what_stays_in_a_combined_result(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.pack("near", (TALK,))
    merge.rebuild(w.profile, lambda s: None, combine=False)
    assert overview.merged_from(w.profile, "near") == [TALK]
    assert overview.merged_from(w.profile, "parts") == []
