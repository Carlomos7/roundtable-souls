"""The launcher keeps its own files in its data folder: older folders beside the saves and profiles move in, backups
carry notes, and old backups age out unless kept."""

import json
import os
import time

import pytest

from roundtable_souls.platform import data_folder
from roundtable_souls.saves import backups as save_backups


def _account(tmp_path):
    acct = tmp_path / "Roaming" / "EldenRing" / "76561198000000000"
    acct.mkdir(parents=True)
    (acct / "ER0000.co2").write_bytes(b"save")
    return acct


def test_older_folders_beside_the_saves_move_in_with_notes(tmp_path):
    acct = _account(tmp_path)
    for legacy, name in (
        ("regulation-fix-backups", "ER0000.co2.20260924-140632.bak"),
        ("co2-to-sl2-backups", "ER0000.sl2.20260925-101010.bak"),
        ("save-fix-backups", "ER0000.co2.20260925-191753.bak"),
    ):
        (acct / legacy).mkdir()
        (acct / legacy / name).write_bytes(b"old")
    (acct / "roundtable-saves" / "deleted").mkdir(parents=True)
    (acct / "roundtable-saves" / "library.json").write_text("{}")
    (acct / "roundtable-saves" / "deleted" / "x.co2").write_bytes(b"gone")
    (acct / "ER0000.co2.bak").write_bytes(b"the game's own")
    backups = save_backups.backups(acct)
    assert backups == tmp_path / "launcher-data" / "saves" / "eldenring" / acct.name / "backups"
    assert sorted(p.name for p in acct.iterdir()) == ["ER0000.co2", "ER0000.co2.bak"]  # only the game's files stay
    note = save_backups.note_of(backups / "ER0000.co2.20260924-140632.bak")
    assert note["action"] == "Before repairing for save editors" and note["save"] == str(acct / "ER0000.co2")
    assert (
        save_backups.note_of(backups / "ER0000.sl2.20260925-101010.bak")["action"]
        == "Before copying the co-op save over it"
    )
    lib = save_backups.library(acct)
    assert (lib / "library.json").is_file() and (lib / "removed" / "x.co2").read_bytes() == b"gone"


def test_clashing_names_keep_their_extension_and_note_and_dotted_saves_are_named_right(tmp_path):
    acct = _account(tmp_path)
    same = "ER0000.co2.20260924-140632.bak"
    for legacy in ("save-fix-backups", "regulation-fix-backups"):
        (acct / legacy).mkdir()
        (acct / legacy / same).write_bytes(legacy.encode())
    (acct / "save-fix-backups" / (same + ".json")).write_text(json.dumps({"action": "Fix checksums"}))
    backups = save_backups.backups(acct)
    names = sorted(p.name for p in backups.iterdir() if p.suffix == ".bak")
    assert names == ["ER0000.co2.20260924-140632-2.bak", same]  # both still list as backups
    assert {save_backups.note_of(backups / n)["action"] for n in names} == {
        "Fix checksums",
        "Before repairing for save editors",
    }
    assert save_backups._saved_name("My.Run.sl2.20260924-140632-3.bak") == "My.Run.sl2"


def test_a_folder_an_older_tool_writes_again_is_picked_up_on_refresh(tmp_path):
    acct = _account(tmp_path)
    save_backups.backups(acct)
    (acct / "regulation-fix-backups").mkdir()
    (acct / "regulation-fix-backups" / "ER0000.co2.20260930-000000.bak").write_bytes(b"new")
    save_backups.adopt_legacy_save_folders(acct, again=True)
    assert (save_backups.backups(acct) / "ER0000.co2.20260930-000000.bak").is_file()
    assert not (acct / "regulation-fix-backups").exists()


def test_old_backups_age_out_unless_recent_or_kept(tmp_path):
    folder = tmp_path / "b"
    folder.mkdir()
    now = time.time()
    made = []
    for i in range(save_backups.KEEP_NEWEST + 5):
        f = folder / f"ER0000.co2.2026010{i // 10}-00000{i % 10}.{i}.bak"
        f.write_bytes(b"x")
        age = (save_backups.KEEP_DAYS + 1 + i) * 86400  # all older than the recent window, newest first
        os.utime(f, (now - age, now - age))
        made.append(f)
    save_backups.set_keep(made[-1], True)  # the oldest, kept by hand
    other = folder / "ER0000.sl2.20200101-000000.bak"
    other.write_bytes(b"x")
    os.utime(other, (now - 900 * 86400, now - 900 * 86400))
    removed = save_backups.prune(folder, "ER0000.co2", now=now)
    assert sorted(removed) == sorted(made[save_backups.KEEP_NEWEST : -1])  # beyond the newest 20, except the kept one
    assert made[-1].is_file() and other.is_file()  # another save's backups are its own business
    assert json.loads((folder / (made[-1].name + ".json")).read_text())["keep"] is True


def _aged_out(folder, n=save_backups.KEEP_NEWEST + 4):
    """n backups of ER0000.co2 older than KEEP_DAYS, newest first; those past KEEP_NEWEST are prunable."""
    now = time.time()
    made = []
    for i in range(n):
        f = folder / f"ER0000.co2.20260101-0000{i:02d}.bak"
        f.write_bytes(b"x")
        age = (save_backups.KEEP_DAYS + 1 + i) * 86400
        os.utime(f, (now - age, now - age))
        made.append(f)
    return made, now


def test_a_damaged_or_half_written_note_is_never_pruned(tmp_path):
    made, now = _aged_out(tmp_path)
    damaged = {
        made[-1]: b'{"keep": tr',  # cut off mid-write
        made[-2]: b"\xff\xfe not utf-8",
        made[-3]: b"[true]",  # JSON, but not a note
        made[-4]: b"",
    }
    for bak, data in damaged.items():
        (tmp_path / (bak.name + ".json")).write_bytes(data)
    removed = save_backups.prune(tmp_path, "ER0000.co2", now=now)
    assert removed == []
    for bak, data in damaged.items():
        assert bak.is_file() and (tmp_path / (bak.name + ".json")).read_bytes() == data
        assert save_backups.is_kept(bak) and save_backups.note_of(bak) == {}
    assert save_backups.read_note(made[0]) is None  # no note is not an unreadable one


def test_missing_and_normal_notes_prune_as_before(tmp_path):
    made, now = _aged_out(tmp_path)
    save_backups.set_keep(made[-1], True)
    save_backups.set_keep(made[-2], False)
    (tmp_path / (made[-3].name + ".json")).write_text(json.dumps({"action": "Before a change"}))
    removed = save_backups.prune(tmp_path, "ER0000.co2", now=now)
    assert sorted(removed) == sorted(made[save_backups.KEEP_NEWEST : -1])
    assert made[-1].is_file() and not (tmp_path / (made[-2].name + ".json")).exists()
    assert sorted(p.name for p in tmp_path.iterdir() if not p.name.endswith((".bak", ".bak.json"))) == []


def test_an_interrupted_note_write_leaves_the_previous_note(tmp_path, monkeypatch):
    bak = tmp_path / "ER0000.co2.20260101-000000.bak"
    bak.write_bytes(b"x")
    save_backups.set_keep(bak, True)
    before = (tmp_path / (bak.name + ".json")).read_bytes()

    def cut(src, dst):
        raise OSError("power cut before the rename")

    monkeypatch.setattr(os, "replace", cut)
    for write in (lambda: save_backups.set_keep(bak, False), lambda: save_backups.write_note(bak, {"keep": False})):
        try:
            write()
        except OSError:
            pass
        else:
            raise AssertionError("the write should have failed")
    assert (tmp_path / (bak.name + ".json")).read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == [bak.name, bak.name + ".json"]  # no .tmp left behind
    assert save_backups.is_kept(bak)


def test_set_keep_copies_an_unreadable_note_aside_and_delete_takes_it_along(tmp_path):
    from roundtable_souls.services import saves as saves_service

    bak = tmp_path / "ER0000.co2.20260101-000000.bak"
    bak.write_bytes(b"x")
    note = tmp_path / (bak.name + ".json")
    note.write_bytes(b'{"action": "Fix check')
    save_backups.set_keep(bak, False)
    assert (tmp_path / (note.name + ".unreadable")).read_bytes() == b'{"action": "Fix check'
    assert save_backups.read_note(bak) == {"keep": False} and not save_backups.is_kept(bak)
    note.write_bytes(b"also damaged")
    save_backups.set_keep(bak, True)
    assert (tmp_path / (note.name + ".unreadable-2")).read_bytes() == b"also damaged"
    assert (tmp_path / (note.name + ".unreadable")).is_file()
    saves_service.delete_backup(bak)
    assert list(tmp_path.iterdir()) == []


def test_a_failed_set_keep_on_an_unreadable_note_leaves_the_backup_protected(tmp_path, monkeypatch):
    made, now = _aged_out(tmp_path)
    bak = made[-1]
    note = tmp_path / (bak.name + ".json")
    note.write_bytes(b'{"keep": tr')
    real = os.replace

    def cut_the_note(src, dst):  # the copy aside lands; the note's own replacement is cut off
        if os.fspath(dst) == str(note):
            raise OSError("power cut before the rename")
        real(src, dst)

    monkeypatch.setattr(os, "replace", cut_the_note)
    with pytest.raises(OSError):
        save_backups.set_keep(bak, False)
    monkeypatch.setattr(os, "replace", real)
    assert note.read_bytes() == b'{"keep": tr'  # the primary note is still there, as it was
    assert (tmp_path / (note.name + ".unreadable")).read_bytes() == b'{"keep": tr'
    assert save_backups.protection(bak) == save_backups.UNREADABLE
    assert bak not in save_backups.prune(tmp_path, "ER0000.co2", now=now) and bak.is_file()
    assert not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]


@pytest.mark.parametrize("keep", ["yes", 1, 0, None, [], {}])
def test_a_keep_that_is_not_true_or_false_fails_closed(tmp_path, keep):
    made, now = _aged_out(tmp_path)
    bak = made[-1]
    note = tmp_path / (bak.name + ".json")
    raw = json.dumps({"action": "Fix checksums", "keep": keep, "custom": 7})
    note.write_text(raw)
    assert save_backups.protection(bak) == save_backups.UNREADABLE and save_backups.is_kept(bak)
    assert bak not in save_backups.prune(tmp_path, "ER0000.co2", now=now)
    assert save_backups.note_of(bak)["action"] == "Fix checksums"  # the rest still shows
    save_backups.set_keep(bak, False)  # the user's explicit choice replaces it; nothing else in the note changes
    assert save_backups.read_note(bak) == {"action": "Fix checksums", "keep": False, "custom": 7}
    assert (tmp_path / (note.name + ".unreadable")).read_text() == raw


def test_set_keep_on_a_readable_note_keeps_its_other_fields_and_sets_nothing_aside(tmp_path):
    bak = tmp_path / "ER0000.co2.20260101-000000.bak"
    bak.write_bytes(b"x")
    doc = {"action": "Before playing", "when": "2026-01-01 00:00:00", "save": "C:/x", "changes": ["a"], "extra": 1}
    (tmp_path / (bak.name + ".json")).write_text(json.dumps(doc))
    save_backups.set_keep(bak, True)
    assert save_backups.read_note(bak) == {**doc, "keep": True}
    assert save_backups.protection(bak) == save_backups.KEPT
    assert sorted(p.name for p in tmp_path.iterdir()) == [bak.name, bak.name + ".json"]


def test_the_backup_list_says_when_protection_is_unreadable_without_calling_it_kept(tmp_path):
    from roundtable_souls.services import saves as saves_service
    from support import er

    acct = _account(tmp_path)
    folder = save_backups.backups(acct)
    folder.mkdir(parents=True)
    rows = {}
    for name, note in (("a", b"{broken"), ("b", b'{"keep": true}'), ("c", b'{"keep": false}'), ("d", None)):
        bak = folder / f"ER0000.co2.2026010{ord(name) - 96}-000000.bak"
        bak.write_bytes(b"x")
        if note is not None:
            (folder / (bak.name + ".json")).write_bytes(note)
        rows[name] = bak
    listed = {r["path"]: r for r in saves_service.list_backups(acct / "ER0000.co2", loc=er())}
    flags = {k: (listed[p]["keep"], listed[p]["protected"], listed[p]["metadata_unreadable"]) for k, p in rows.items()}
    assert flags == {
        "a": (False, True, True),
        "b": (True, True, False),
        "c": (False, False, False),
        "d": (False, False, False),
    }


def test_deleted_profiles_and_install_leftovers_leave_the_profile_folder(tmp_path):
    prof = tmp_path / "profiles" / "eldenring-mods"
    (prof / "deleted-profiles").mkdir(parents=True)
    (prof / "deleted-profiles" / "old.20260101-000000.me3").write_text("x")
    (prof / ".roundtable-staging" / "abc").mkdir(parents=True)
    dest = data_folder.deleted_profiles(prof)
    assert (dest / "old.20260101-000000.me3").is_file() and sorted(p.name for p in prof.iterdir()) == []
    stale = data_folder.temp("installing") / "stale"
    stale.mkdir()
    os.utime(stale, (time.time() - 7200, time.time() - 7200))
    fresh = data_folder.temp("installing") / "fresh"
    fresh.mkdir()
    data_folder.clear_temp()
    assert not stale.exists() and fresh.exists()  # a recent one may belong to another running copy


def test_tests_never_move_folders_outside_their_own(tmp_path):
    outside = tmp_path.parent / f"outside-{tmp_path.name}" / "EldenRing" / "76561198000000001"
    (outside / "regulation-fix-backups").mkdir(parents=True)
    (outside / "regulation-fix-backups" / "ER0000.co2.20260101-000000.bak").write_bytes(b"real")
    try:
        save_backups.adopt_legacy_save_folders(outside, again=True)
        save_backups.backups(outside)
        assert (outside / "regulation-fix-backups" / "ER0000.co2.20260101-000000.bak").read_bytes() == b"real"
    finally:
        import shutil

        shutil.rmtree(outside.parent.parent, ignore_errors=True)
