"""The save library: named copies, swaps that never lose the replaced save, and the manifest that tracks them. Also
which save files a setup uses."""

import json

import pytest

from roundtable_souls.game import catalog as games
from roundtable_souls.platform import paths as common
from roundtable_souls.saves import library as Lib
from roundtable_souls.saves import regulation
from roundtable_souls.services import play as core
from roundtable_souls.services import saves as saves_service

ER = games.ELDEN_RING


def _save(path, fill):
    """A file the size and magic of a PC save; its characters do not parse, which the library tolerates."""
    data = bytearray(regulation.FILE_SIZE)
    data[:4] = b"BND4"
    data[4] = fill
    path.write_bytes(bytes(data))
    return path


def test_add_keeps_a_verified_copy_and_records_it(tmp_path):
    live = _save(tmp_path / "ER0000.sl2", 1)
    e = Lib.add(tmp_path, live, "  before   the DLC ", ER)
    assert e["name"] == "before the DLC" and e["from"] == "ER0000.sl2" and e["format"] == "sl2"
    assert Lib.entry_path(tmp_path, e).read_bytes() == live.read_bytes()
    doc = json.loads((Lib.folder_for(tmp_path) / Lib.MANIFEST).read_text(encoding="utf-8"))
    assert [x["id"] for x in doc["entries"]] == [e["id"]] and doc["history"][0]["action"] == "stash"
    with pytest.raises(Lib.LibraryError):
        Lib.add(tmp_path, live, "   ", ER)  # a copy needs a name
    (tmp_path / "junk.sl2").write_bytes(b"not a save")
    with pytest.raises(Lib.LibraryError):
        Lib.add(tmp_path, tmp_path / "junk.sl2", "junk", ER)


def test_swap_in_keeps_the_replaced_save_under_its_name_and_backs_it_up(tmp_path):
    live = _save(tmp_path / "ER0000.sl2", 1)
    other = Lib.add(tmp_path, _save(tmp_path / "other.sl2", 2), "second run", ER)
    out = Lib.swap_in(tmp_path, other["id"], live, "first run", ER)
    assert live.read_bytes()[4] == 2  # the copy is live now
    kept = Lib.entry_path(tmp_path, out["outgoing"])
    assert kept.read_bytes()[4] == 1 and out["outgoing"]["name"] == "first run"
    assert out["backup"].is_file()  # Undo works as for every other write
    doc = Lib.load(tmp_path)
    assert {e["name"] for e in doc["entries"]} == {"second run", "first run"}  # the swapped-in copy stays
    assert [h["action"] for h in doc["history"]] == ["stash", "swapped out", "swap in"]
    assert doc["history"][-1]["target"] == "ER0000.sl2"


def test_swap_into_a_file_that_does_not_exist_yet_creates_it(tmp_path):
    e = Lib.add(tmp_path, _save(tmp_path / "src.sl2", 3), "co-op start", ER)
    target = tmp_path / "ER0000.co2"
    out = Lib.swap_in(tmp_path, e["id"], target, None, ER)
    assert target.read_bytes()[4] == 3 and out["outgoing"] is None and out["backup"] is None


def test_rename_remove_and_outside_changes(tmp_path):
    e = Lib.add(tmp_path, _save(tmp_path / "ER0000.sl2", 1), "a", ER)
    assert Lib.rename(tmp_path, e["id"], "b")["name"] == "b"
    assert not Lib.changed_outside(tmp_path, e)
    Lib.entry_path(tmp_path, e).write_bytes(b"edited elsewhere")
    assert Lib.changed_outside(tmp_path, Lib.find(Lib.load(tmp_path), e["id"]))
    moved = Lib.remove(tmp_path, e["id"])
    assert moved.is_file() and moved.parent.name == "removed"  # moved aside, never erased
    doc = Lib.load(tmp_path)
    assert doc["entries"] == [] and [h["action"] for h in doc["history"]] == ["stash", "rename", "delete"]


def test_default_name_says_when_without_characters(tmp_path):
    assert Lib.default_name(_save(tmp_path / "ER0000.co2", 1), ER).startswith("ER0000.co2 · ")


def test_setup_saves_follow_me3_savefile_and_the_seamless_extension(tmp_path):
    prof = tmp_path / "p.me3"
    prof.write_text('profileVersion = "v1"\nsavefile = "run2.sl2"\n', encoding="utf-8")
    ini = tmp_path / "ersc_settings.ini"
    ini.write_text("[SAVE]\nsave_file_extension = co3\n", encoding="utf-8")
    names = core.setup_saves(core.Setup("me3", prof, ini=ini, game=ER))
    assert names["standard"] == "run2.sl2" and names["coop"] == "run2.co3" and names["active"] == "run2.co3"
    assert "save_file_extension" in names["why"]["coop"] and "savefile" in names["why"]["standard"]
    plain = core.setup_saves(core.Setup("me3", tmp_path / "missing.me3", game=ER))
    assert (plain["standard"], plain["coop"], plain["active"]) == ("ER0000.sl2", None, "ER0000.sl2")


def test_save_files_include_the_names_the_setup_uses(tmp_path, monkeypatch):
    acct = tmp_path / "EldenRing" / "7656"
    acct.mkdir(parents=True)
    for n in ("ER0000.sl2", "run2.co3", "unrelated.sl2"):
        (acct / n).write_bytes(b"x")
    monkeypatch.setattr(common, "save_roots", lambda game=None: [tmp_path / "EldenRing"])
    common.set_setup_save_names(ER, {})
    try:
        assert [p.name for p in common.save_files(ER)] == ["ER0000.sl2"]
        common.set_setup_save_names(ER, {"standard": "ER0000.sl2", "coop": "run2.co3"})
        assert [p.name for p in common.save_files(ER)] == ["ER0000.sl2", "run2.co3"]
        assert saves_service.save_kind(acct / "run2.co3", ER) == "Seamless Co-op"
    finally:
        common.set_setup_save_names(ER, {})
