"""The account lock on a backups folder: shared by processes and threads, entered again by the same thread, never
skipped on timeout, released by a process that dies, and held by every change to backups and their notes."""

import json
import os
import subprocess
import sys
import textwrap
import threading
import time

import pytest

from roundtable_souls.saves import backups as save_backups
from roundtable_souls.saves import fix as save_fix
from roundtable_souls.services import saves as saves_service

HOLDER = textwrap.dedent(
    """
    import sys, time
    from pathlib import Path
    from roundtable_souls.saves import backups as save_backups

    folder, mode = Path(sys.argv[1]), sys.argv[2]
    with save_backups.account_lock(folder):
        print("held", flush=True)
        if mode == "until-stdin-closes":
            sys.stdin.read()
        elif mode == "keep-then-release":  # a keep set by this process while another waits to prune
            time.sleep(0.5)
            save_backups.set_keep(Path(sys.argv[3]), True)
        elif mode == "hang":
            time.sleep(60)
    """
)


def _hold(folder, mode, *extra):
    """Another process holding the lock on folder; returns once it has it."""
    proc = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(folder), mode, *map(str, extra)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "held"
    return proc


def _aged_out(folder, n=save_backups.KEEP_NEWEST + 3):
    folder.mkdir(parents=True, exist_ok=True)
    now = time.time()
    made = []
    for i in range(n):
        f = folder / f"ER0000.co2.20260101-0000{i:02d}.bak"
        f.write_bytes(b"x")
        age = (save_backups.KEEP_DAYS + 1 + i) * 86400
        os.utime(f, (now - age, now - age))
        made.append(f)
    return made, now


@pytest.fixture
def short_timeout(monkeypatch):
    monkeypatch.setattr(save_backups, "LOCK_TIMEOUT", 0.3)


def test_another_process_holding_the_lock_blocks_every_change_and_none_runs_unlocked(tmp_path, short_timeout):
    folder = tmp_path / "backups"
    made, now = _aged_out(folder)
    save = tmp_path / "ER0000.co2"
    save.write_bytes(b"live")
    save_backups.set_keep(made[0], True)
    before = sorted(p.name for p in folder.iterdir())
    proc = _hold(folder, "until-stdin-closes")
    try:
        with pytest.raises(save_backups.BackupsBusy):
            save_backups.set_keep(made[0], False)
        with pytest.raises(save_backups.BackupsBusy):
            saves_service.delete_backup(made[1])
        with pytest.raises(save_backups.BackupsBusy):
            save_fix.write_manifest(made[2], {"action": "x"})
        assert save_backups.prune(folder, "ER0000.co2", now=now) == []  # busy: nothing is removed
        assert sorted(p.name for p in folder.iterdir()) == before
        assert save_backups.read_note(made[0]) == {"keep": True}
    finally:
        assert proc.stdin is not None
        proc.stdin.close()
        proc.wait(10)
    save_backups.set_keep(made[0], False)  # free again
    assert save_backups.read_note(made[0]) == {"keep": False}
    assert len(save_backups.prune(folder, "ER0000.co2", now=now)) == 3


def test_a_backup_is_refused_while_another_process_holds_the_lock(tmp_path, short_timeout, monkeypatch):
    save = tmp_path / "EldenRing" / "7656" / "ER0000.co2"
    save.parent.mkdir(parents=True)
    save.write_bytes(b"live")
    folder = save_backups.backups(save.parent)
    proc = _hold(folder, "until-stdin-closes")
    try:
        with pytest.raises(save_backups.BackupsBusy):
            save_fix.backup(save)
        assert not folder.exists() or not any(folder.iterdir())  # nothing half-made
    finally:
        assert proc.stdin is not None
        proc.stdin.close()
        proc.wait(10)
    bak = save_fix.backup(save)
    assert bak.read_bytes() == b"live" and (save_backups.read_note(bak) or {}).get("save") == str(save)


def test_prune_waits_and_reads_a_keep_set_by_another_process_under_the_lock(tmp_path):
    folder = tmp_path / "backups"
    made, now = _aged_out(folder)
    oldest = made[-1]
    proc = _hold(folder, "keep-then-release", oldest)
    removed = save_backups.prune(folder, "ER0000.co2", now=now)  # waits for the other process, then reads its keep
    proc.wait(10)
    assert oldest not in removed and oldest.is_file() and save_backups.read_note(oldest) == {"keep": True}
    assert sorted(removed) == sorted(made[save_backups.KEEP_NEWEST : -1])


def test_a_process_that_dies_holding_the_lock_releases_it(tmp_path, short_timeout):
    folder = tmp_path / "backups"
    made, _ = _aged_out(folder, 1)
    proc = _hold(folder, "hang")
    with pytest.raises(save_backups.BackupsBusy):
        save_backups.set_keep(made[0], True)
    proc.kill()
    proc.wait(10)
    save_backups.set_keep(made[0], True)
    assert save_backups.read_note(made[0]) == {"keep": True}


def test_an_error_inside_the_lock_releases_it(tmp_path, short_timeout):
    folder = tmp_path / "backups"
    with pytest.raises(RuntimeError):
        with save_backups.account_lock(folder):
            raise RuntimeError("a write failed")
    with save_backups.account_lock(folder):  # free for this thread
        pass
    got = []

    def other():
        with save_backups.account_lock(folder):
            got.append(True)

    t = threading.Thread(target=other)
    t.start()
    t.join()
    assert got == [True]  # and for another thread


def test_the_same_thread_enters_again_but_another_thread_waits(tmp_path, short_timeout):
    folder = tmp_path / "backups"
    made, now = _aged_out(folder)
    with save_backups.account_lock(folder):
        with save_backups.account_lock(folder):  # nested: no wait, no deadlock
            pass
        assert len(save_backups.prune(folder, "ER0000.co2", now=now)) == 3  # prune inside the lock still prunes
        errors = []

        def other():
            try:
                save_backups.set_keep(made[0], True)
            except save_backups.BackupsBusy as e:
                errors.append(e)

        t = threading.Thread(target=other)
        t.start()
        t.join()
        assert len(errors) == 1  # another thread of this process is shut out like another process
    save_backups.set_keep(made[0], True)


def test_a_backup_prunes_inside_its_own_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(save_backups, "LOCK_TIMEOUT", 0.3)
    save = tmp_path / "EldenRing" / "7656" / "ER0000.co2"
    save.parent.mkdir(parents=True)
    save.write_bytes(b"live")
    folder = save_backups.backups(save.parent)
    made, _now = _aged_out(folder)
    bak = save_fix.backup(save, {"action": "Before a change"})
    left = [p for p in folder.iterdir() if p.suffix == ".bak"]
    assert bak in left and len(left) == save_backups.KEEP_NEWEST  # the nested prune ran (busy would remove none)
    assert json.loads((folder / (bak.name + ".json")).read_text())["action"] == "Before a change"


def test_the_lock_file_never_lists_as_a_backup(tmp_path):
    save = tmp_path / "EldenRing" / "7656" / "ER0000.co2"
    save.parent.mkdir(parents=True)
    save.write_bytes(b"live")
    bak = save_fix.backup(save)
    lock = bak.parent.with_name(bak.parent.name + ".lock")
    assert lock.is_file() and lock.parent != bak.parent  # beside the backups folder, not in it
    assert sorted(p.name for p in bak.parent.iterdir()) == [bak.name, bak.name + ".json"]
