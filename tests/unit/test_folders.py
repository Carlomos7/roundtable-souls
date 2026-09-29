"""The launcher keeps its own files in its data folder: older folders beside the saves and profiles move in, backups
carry notes, and old backups age out unless kept."""

import json
import os
import time

from roundtable_souls import folders


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
    backups = folders.backups(acct)
    assert backups == tmp_path / "launcher-data" / "saves" / "eldenring" / acct.name / "backups"
    assert sorted(p.name for p in acct.iterdir()) == ["ER0000.co2", "ER0000.co2.bak"]  # only the game's files stay
    note = folders.note_of(backups / "ER0000.co2.20260924-140632.bak")
    assert note["action"] == "Before repairing for save editors" and note["save"] == str(acct / "ER0000.co2")
    assert (
        folders.note_of(backups / "ER0000.sl2.20260925-101010.bak")["action"] == "Before copying the co-op save over it"
    )
    lib = folders.library(acct)
    assert (lib / "library.json").is_file() and (lib / "removed" / "x.co2").read_bytes() == b"gone"


def test_clashing_names_keep_their_extension_and_note_and_dotted_saves_are_named_right(tmp_path):
    acct = _account(tmp_path)
    same = "ER0000.co2.20260924-140632.bak"
    for legacy in ("save-fix-backups", "regulation-fix-backups"):
        (acct / legacy).mkdir()
        (acct / legacy / same).write_bytes(legacy.encode())
    (acct / "save-fix-backups" / (same + ".json")).write_text(json.dumps({"action": "Fix checksums"}))
    backups = folders.backups(acct)
    names = sorted(p.name for p in backups.iterdir() if p.suffix == ".bak")
    assert names == ["ER0000.co2.20260924-140632-2.bak", same]  # both still list as backups
    assert {folders.note_of(backups / n)["action"] for n in names} == {
        "Fix checksums",
        "Before repairing for save editors",
    }
    assert folders._saved_name("My.Run.sl2.20260924-140632-3.bak") == "My.Run.sl2"


def test_a_folder_an_older_tool_writes_again_is_picked_up_on_refresh(tmp_path):
    acct = _account(tmp_path)
    folders.backups(acct)
    (acct / "regulation-fix-backups").mkdir()
    (acct / "regulation-fix-backups" / "ER0000.co2.20260930-000000.bak").write_bytes(b"new")
    folders.adopt_legacy_save_folders(acct, again=True)
    assert (folders.backups(acct) / "ER0000.co2.20260930-000000.bak").is_file()
    assert not (acct / "regulation-fix-backups").exists()


def test_old_backups_age_out_unless_recent_or_kept(tmp_path):
    folder = tmp_path / "b"
    folder.mkdir()
    now = time.time()
    made = []
    for i in range(folders.KEEP_NEWEST + 5):
        f = folder / f"ER0000.co2.2026010{i // 10}-00000{i % 10}.{i}.bak"
        f.write_bytes(b"x")
        age = (folders.KEEP_DAYS + 1 + i) * 86400  # all older than the recent window, newest first
        os.utime(f, (now - age, now - age))
        made.append(f)
    folders.set_keep(made[-1], True)  # the oldest, kept by hand
    other = folder / "ER0000.sl2.20200101-000000.bak"
    other.write_bytes(b"x")
    os.utime(other, (now - 900 * 86400, now - 900 * 86400))
    removed = folders.prune(folder, "ER0000.co2", now=now)
    assert sorted(removed) == sorted(made[folders.KEEP_NEWEST : -1])  # beyond the newest 20, except the kept one
    assert made[-1].is_file() and other.is_file()  # another save's backups are its own business
    assert json.loads((folder / (made[-1].name + ".json")).read_text())["keep"] is True


def test_deleted_profiles_and_install_leftovers_leave_the_profile_folder(tmp_path):
    prof = tmp_path / "profiles" / "eldenring-mods"
    (prof / "deleted-profiles").mkdir(parents=True)
    (prof / "deleted-profiles" / "old.20260101-000000.me3").write_text("x")
    (prof / ".roundtable-staging" / "abc").mkdir(parents=True)
    dest = folders.deleted_profiles(prof)
    assert (dest / "old.20260101-000000.me3").is_file() and sorted(p.name for p in prof.iterdir()) == []
    stale = folders.temp("installing") / "stale"
    stale.mkdir()
    os.utime(stale, (time.time() - 7200, time.time() - 7200))
    fresh = folders.temp("installing") / "fresh"
    fresh.mkdir()
    folders.clear_temp()
    assert not stale.exists() and fresh.exists()  # a recent one may belong to another running copy


def test_tests_never_move_folders_outside_their_own(tmp_path):
    outside = tmp_path.parent / f"outside-{tmp_path.name}" / "EldenRing" / "76561198000000001"
    (outside / "regulation-fix-backups").mkdir(parents=True)
    (outside / "regulation-fix-backups" / "ER0000.co2.20260101-000000.bak").write_bytes(b"real")
    try:
        folders.adopt_legacy_save_folders(outside, again=True)
        folders.backups(outside)
        assert (outside / "regulation-fix-backups" / "ER0000.co2.20260101-000000.bak").read_bytes() == b"real"
    finally:
        import shutil

        shutil.rmtree(outside.parent.parent, ignore_errors=True)
