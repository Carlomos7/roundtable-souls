"""'Back up saves before Play': when it is on, a failed backup never starts the game silently. The window asks
(Retry, Launch without backup, Cancel); --play without the window stops unless --allow-without-backup was given."""

import uuid

import pytest

from roundtable_souls.config.settings import LauncherSettings
from roundtable_souls.game.locate import Locations
from roundtable_souls.platform import instance
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.services import play as core
from support import er


@pytest.fixture
def session(tmp_path, monkeypatch):
    """Two saves, the second of which can't be backed up, and a Play session that records instead of launching."""
    saves = [tmp_path / "ER0000.sl2", tmp_path / "ER0000.co2"]
    for p in saves:
        p.write_bytes(b"save")
    monkeypatch.setattr(Locations, "save_files", lambda self: saves)
    real_backup = core.save_fix.backup

    def backup(p, manifest=None):
        if p.suffix == ".co2":
            raise PermissionError("in use")
        return real_backup(p, manifest)

    monkeypatch.setattr(core.save_fix, "backup", backup)
    launched = []
    opts = {k: False for k in core.PLAY_DEFAULTS} | {"play_backup_before": True}
    monkeypatch.setattr(core, "play_options", lambda settings=None: opts)
    monkeypatch.setattr(core.me3_session, "ensure_steam", lambda *a: None)
    monkeypatch.setattr(core.me3_session, "ensure_steam_running", lambda *a: None)
    monkeypatch.setattr(core.me3_session, "launch", lambda *a, **k: launched.append(a[0]))
    monkeypatch.setattr(core.me3_info, "me3_version", lambda *a: None)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    monkeypatch.setattr(core.run_logging, "start_log", lambda *a, **k: None)
    monkeypatch.setattr(core, "_after_play", lambda opts, loc: None)
    monkeypatch.setattr(core, "offline_profile_for", lambda *a, **k: "p.offline.me3")
    setup = type(
        "S",
        (),
        {
            "profile": "p.me3",
            "source": "x",
            "game": core.games.ELDEN_RING,
            "problems": lambda self: [],
            "me3_path": lambda self: "me3.exe",
            "launch_exe": lambda self: None,
            "locations": lambda self: er(),
        },
    )()
    return {"setup": setup, "launched": launched, "opts": opts, "saves": saves}


def test_a_failed_backup_stops_play_and_offline_play(session):
    with pytest.raises(core.BackupBeforePlayFailed) as err:
        core.job_play(session["setup"], er())
    assert [p.name for p, _why in err.value.failed] == ["ER0000.co2"]
    with pytest.raises(core.BackupBeforePlayFailed):
        core.job_play_offline(session["setup"], er())
    assert session["launched"] == []


def test_the_saves_that_could_be_backed_up_still_are(session):
    from roundtable_souls.saves import backups as save_backups

    with pytest.raises(core.BackupBeforePlayFailed):
        core.backup_saves_before_play(er(), required=True)
    made = [p for p in save_backups.backups(session["saves"][0].parent).iterdir() if p.suffix == ".bak"]
    assert [p.name.split(".")[1] for p in made] == ["sl2"]
    assert len(core.backup_saves_before_play(er())) == 1  # not required: as before, the failure is only logged


def test_play_starts_only_when_asked_to_go_without_or_the_backup_was_handled(session):
    core.job_play(session["setup"], er(), backup=core.BACKUP_ALLOW_FAILURE)
    core.job_play(session["setup"], er(), backup=core.BACKUP_SKIP)
    core.job_play_offline(session["setup"], er(), backup=core.BACKUP_SKIP)
    assert len(session["launched"]) == 3
    session["opts"]["play_backup_before"] = False  # off: nothing to back up, nothing to stop
    core.job_play(session["setup"], er())
    assert len(session["launched"]) == 4


def test_headless_play_fails_clearly_unless_bypass_was_asked_for(session, monkeypatch):
    setup = session["setup"]
    monkeypatch.setattr(core, "discover", lambda remembered, loc: [setup])
    monkeypatch.setattr(core, "same_source", lambda a, b: True)
    monkeypatch.setattr(core, "update_merge_headless", lambda s, automatic=True: None)
    logged, shown = [], []
    monkeypatch.setattr(run_logging, "log", logged.append)
    s = LauncherSettings.from_raw({})
    notice = lambda game, why, headline=None: shown.append((headline, why))  # noqa: E731
    assert core.play_headless(s, er(), notice=notice) == 1
    assert session["launched"] == []
    assert shown and "a backup before Play failed" in shown[0][0] and "--allow-without-backup" in shown[0][1]
    assert any("error: the game was not started" in line for line in logged)
    assert core.play_headless(s, er(), notice=notice, allow_without_backup=True) == 0
    assert len(session["launched"]) == 1
    assert any("starting without a backup" in line for line in logged)


def test_the_shortcut_flag_reaches_headless_play_and_an_open_window(monkeypatch):
    from roundtable_souls import cli
    from roundtable_souls.game import catalog as games

    played, sent = [], []
    monkeypatch.setattr(
        core,
        "play_headless",
        lambda settings, loc, notice=None, allow_without_backup=False: played.append(allow_without_backup) or 0,
    )
    monkeypatch.setattr(instance, "WINDOW", f"RoundtableSouls.Test.{uuid.uuid4().hex}")
    monkeypatch.setattr(instance, "PLAY", f"RoundtableSouls.Test.{uuid.uuid4().hex}")
    monkeypatch.setattr(instance, "send", lambda msg, name=None: sent.append(msg) or True)
    er_game = games.get("eldenring")
    assert cli.play_from_shortcut(er_game) == 0 and cli.play_from_shortcut(er_game, allow_without_backup=True) == 0
    assert played == [False, True]
    window = instance.acquire(instance.WINDOW)
    assert window is not None
    try:
        cli.play_from_shortcut(er_game, allow_without_backup=True)
        cli.play_from_shortcut(er_game)
        assert sent == ["play eldenring allow-without-backup", "play eldenring"]
    finally:
        window.release()
