"""The Play session on a fake machine (fakehost.py): Steam started and waited for, me3 launched with the right
command, the game waited for whichever way me3 behaves, leftover game processes cleared, saves repaired after, and
every way it can go wrong. Nothing real is started; time only passes when the code sleeps."""

import json

import pytest
from fakehost import STEAM_EXE, FakeHost, setup_for

from roundtable_souls.game import catalog as games
from roundtable_souls.game.locate import Locations
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.platform import session
from roundtable_souls.services import jobs
from roundtable_souls.services import play as core
from support import er

EXE = "eldenring.exe"


@pytest.fixture
def me3(tmp_path):
    exe = tmp_path / "me3.exe"
    exe.write_bytes(b"not really me3")
    return exe


@pytest.fixture
def lines(monkeypatch):
    got = []
    real = run_logging.log

    def log(text, *a, **k):
        got.append(str(text))
        return real(text, *a, **k)

    real_fail = session.fail

    def fail(text, code=1):
        got.append(f"error: {text}")
        real_fail(text, code)

    monkeypatch.setattr(session, "log", log)
    monkeypatch.setattr(session, "fail", fail)
    monkeypatch.setattr(core.run_logging, "log", log)
    return got


# ----------------------------------------------------------------------------- Steam
def test_steam_already_running_and_signed_in_is_left_alone(monkeypatch, lines):
    host = FakeHost(monkeypatch, steam_running=True, signed_in=True)
    session.ensure_steam(120)
    assert "steam started" not in host.happened() and "steam: running and signed in" in lines


def test_steam_is_started_and_waited_for_until_signed_in(monkeypatch, lines):
    host = FakeHost(monkeypatch, steam_running=False, steam_starts_after=6, sign_in_after=10)
    started = host.clock.now
    session.ensure_steam(120)
    assert host.happened()[0] == "steam started" and "steam: signed in" in lines
    assert any(line.startswith("steam: starting") and STEAM_EXE in line for line in lines)
    assert 16 <= host.clock.now - started <= 30  # up after 6 s, signed in 10 s later, then a short settle


def test_steam_running_but_signed_out_is_waited_for_not_restarted(monkeypatch, lines):
    host = FakeHost(monkeypatch, steam_running=True, signed_in=False)
    host.signed_in_at = host.clock.now + 20
    session.ensure_steam(120)
    assert "steam started" not in host.happened() and "steam: running, waiting for sign-in" in lines


def test_steam_that_never_signs_in_fails_after_the_timeout(monkeypatch, lines):
    host = FakeHost(monkeypatch, steam_running=False, sign_in_after=None)
    started = host.clock.now
    with pytest.raises(SystemExit) as stop:
        session.ensure_steam(120)
    assert stop.value.code == 1 and 120 <= host.clock.now - started <= 125
    assert any("did not sign in within 120s" in line for line in lines)


def test_steam_that_is_not_installed_fails_at_once_without_starting_anything(monkeypatch, lines):
    host = FakeHost(monkeypatch, steam_installed=False, steam_running=False)
    with pytest.raises(SystemExit):
        session.ensure_steam(120)
    assert host.events == [] and any("steam is not running and could not be found" in line for line in lines)


def test_offline_play_starts_steam_but_does_not_wait_for_a_sign_in(monkeypatch, lines):
    host = FakeHost(monkeypatch, steam_running=False, sign_in_after=None)
    started = host.clock.now
    session.ensure_steam_running(60)
    assert host.happened() == ["steam started"] and host.clock.now - started < 60
    assert any("NOT signed in (offline play" in line for line in lines)


# ----------------------------------------------------------------------------- me3 and the game
def test_me3_attached_launches_with_the_profile_and_waits_for_the_game(monkeypatch, lines, me3):
    host = FakeHost(monkeypatch, me3="attached", game_starts_after=8, game_runs_for=60)
    assert session.launch("eldenring", "p.me3", me3, EXE, extra_args=["--no-boot-boost"]) is True
    command = next(e for e in host.events if e[0] == "me3")[2]
    assert command == [str(me3), "launch", "--game", "eldenring", "--profile", "p.me3", "--no-boot-boost"]
    assert host.happened() == ["me3", "game up", "game down", "me3 exit"]
    assert "game closed" in lines and "me3 exited with code 0" in lines


def test_a_bundled_runtime_launches_the_exe_instead_of_the_game_key(monkeypatch, me3, tmp_path):
    host = FakeHost(monkeypatch, me3="attached")
    game_exe = tmp_path / "nightreign.exe"
    session.launch("nightreign", "p.me3", me3, "nightreign.exe", exe=game_exe)
    command = next(e for e in host.events if e[0] == "me3")[2]
    assert command[1:4] == ["launch", "--exe", str(game_exe)] and "--game" not in command


def test_me3_that_hands_off_is_followed_until_the_game_closes(monkeypatch, lines, me3):
    host = FakeHost(monkeypatch, me3="handoff", game_starts_after=12, game_runs_for=90)
    assert session.launch("eldenring", "p.me3", me3, EXE) is True
    happened = host.happened()
    assert happened.index("me3 exit") < happened.index("game up") < happened.index("game down")
    assert host.clock.now >= host.game_down_at and "game closed" in lines  # type: ignore[operator]


def test_a_game_that_outlives_me3_is_still_waited_for(monkeypatch, lines, me3):
    host = FakeHost(monkeypatch, me3="handoff", game_starts_after=0.5, game_runs_for=300)
    session.launch("eldenring", "p.me3", me3, EXE)
    assert host.clock.now >= host.game_down_at  # type: ignore[operator]


def test_a_game_that_never_appears_returns_false_after_a_grace_period(monkeypatch, lines, me3):
    host = FakeHost(monkeypatch, me3="fails", me3_exit_code=1, game_starts_after=None)
    started = host.clock.now
    assert session.launch("eldenring", "p.me3", me3, EXE) is False
    assert "game up" not in host.happened() and 20 <= host.clock.now - started <= 30
    assert "me3 exited with code 1" in lines
    assert any("the game never appeared" in line for line in lines)


def test_me3_that_is_missing_fails_without_starting_anything(monkeypatch, lines, tmp_path):
    host = FakeHost(monkeypatch)
    with pytest.raises(SystemExit) as stop:
        session.launch("eldenring", "p.me3", tmp_path / "missing" / "me3.exe", EXE)
    assert stop.value.code == 1 and host.events == []
    with pytest.raises(SystemExit):
        session.launch("eldenring", "p.me3", None, EXE)
    assert any("me3 was not found" in line for line in lines)


def test_stopping_while_the_game_runs_leaves_it_running_and_says_so(monkeypatch, lines, me3):
    host = FakeHost(monkeypatch, me3="attached", game_starts_after=5, interrupt_after=30)
    with pytest.raises(SystemExit) as stop:
        session.launch("eldenring", "p.me3", me3, EXE)
    assert stop.value.code == 130 and "game down" not in host.happened()
    assert any("leaving the game running" in line for line in lines)


def test_me3_output_goes_to_the_jobs_attachment(monkeypatch, me3):
    host = FakeHost(monkeypatch, me3="attached")
    host.me3_output = "me3 0.13.0: profile loaded\n"
    job = run_logging.begin_job("Play")
    try:
        session.launch("eldenring", "p.me3", me3, EXE)
    finally:
        run_logging.end_job(job)
    attached = [run_logging.job_file(name) for name in job.attachments]
    assert attached and attached[0] is not None and "profile loaded" in attached[0].read_text(encoding="utf-8")


def test_waiting_for_a_game_that_never_starts_gives_up(monkeypatch, lines):
    host = FakeHost(monkeypatch, game_starts_after=None)
    started = host.clock.now
    assert session.wait_for_game(EXE, appear_timeout=40) is False
    assert 40 <= host.clock.now - started <= 45 and "game never appeared; nothing to wait for" in lines


# ----------------------------------------------------------------------------- leftover game processes
def test_dead_shells_are_cleared_and_none_means_no_prompt(monkeypatch, lines):
    host = FakeHost(monkeypatch, dead_shells=[301, 302])
    session.clear_dead_shells(EXE, "before launch")
    assert ("shells killed", host.clock.now, [301, 302]) in host.events and host.dead_shells == []
    host.events.clear()
    session.clear_dead_shells(EXE, "after exit")
    assert host.events == []  # nothing to clear: no administrator prompt


def test_shells_that_survive_are_reported(monkeypatch, lines):
    FakeHost(monkeypatch, dead_shells=[301], shells_survive_kill=True)
    session.clear_dead_shells(EXE, "after exit")
    assert any("1 dead shell(s) could not be removed" in line for line in lines)


def test_a_dead_shell_is_not_taken_for_a_running_game(monkeypatch, me3):
    host = FakeHost(monkeypatch, dead_shells=[301], game_starts_after=None)
    assert session.launch("eldenring", "p.me3", me3, EXE) is False  # only a zero-memory shell: not the game
    assert "game up" not in host.happened()


# ----------------------------------------------------------------------------- the Play job
@pytest.fixture
def play(monkeypatch, me3):
    """The Play job on the fake host, for Elden Ring with no saves to back up, every option on."""
    monkeypatch.setattr(Locations, "save_files", lambda self: [])
    opts = dict.fromkeys(core.PLAY_DEFAULTS, False) | {
        "play_clear_before": True,
        "play_clear_after": True,
        "play_repair_after": True,
        "play_boot_boost": True,
    }
    monkeypatch.setattr(core, "play_options", lambda settings=None: opts)
    monkeypatch.setattr(core.me3_info, "me3_version", lambda path: "0.13.0")
    repaired = []
    monkeypatch.setattr(core.save_repair, "repair_all", lambda loc: repaired.append(loc.game.key))
    host = FakeHost(monkeypatch, steam_running=False, dead_shells=[301], me3="attached")
    return {
        "host": host,
        "opts": opts,
        "repaired": repaired,
        "setup": setup_for(games.ELDEN_RING, me3=str(me3), loc=er()),
    }


def _run(job, setup):
    return jobs.run_job(job, setup, er(), "Starting...")


def _record(job_id=None):
    recs = run_logging.read_jobs()
    return recs[0] if job_id is None else next(r for r in recs if r["id"] == job_id)


def test_play_runs_every_step_in_order_and_records_a_finished_job(play):
    host = play["host"]
    outcome = _run(core.job_play, play["setup"])
    assert outcome.ok and outcome.status == "Finished"
    assert host.happened() == ["steam started", "shells killed", "me3", "game up", "game down", "me3 exit"]
    assert play["repaired"] == ["eldenring"]
    rec = _record()
    assert rec["outcome"] == "done" and rec["title"] == "play"


def test_play_options_that_are_off_are_skipped_and_said(play, lines):
    play["opts"].update(play_clear_before=False, play_clear_after=False, play_repair_after=False)
    _run(core.job_play, play["setup"])
    assert "shells killed" not in play["host"].happened() and play["repaired"] == []
    assert any("repair after quitting is off" in line for line in lines)
    assert any("clearing leftover processes after quitting is off" in line for line in lines)


def test_play_that_cannot_get_steam_fails_and_launches_nothing(play):
    play["host"].sign_in_after = None
    outcome = _run(core.job_play, play["setup"])
    assert not outcome.ok and outcome.status == "Stopped (see details)"
    assert "me3" not in play["host"].happened() and play["repaired"] == []
    assert _record()["outcome"] == "failed"


def test_play_with_me3_missing_fails_before_launching(play, tmp_path):
    setup = setup_for(games.ELDEN_RING, me3=str(tmp_path / "nowhere" / "me3.exe"), loc=er())
    outcome = _run(core.job_play, setup)
    assert not outcome.ok and "me3" not in play["host"].happened() and play["repaired"] == []
    assert _record()["outcome"] == "failed"


def test_a_game_that_never_starts_still_repairs_and_clears_after(play):
    host = play["host"]
    host.me3, host.me3_exit_code, host.game_starts_after = "fails", 1, None
    outcome = _run(core.job_play, play["setup"])
    assert outcome.ok  # nothing failed in the launcher; the log says the game never appeared
    assert play["repaired"] == ["eldenring"]


def test_stopping_play_marks_the_job_stopped_and_skips_the_after_steps(play):
    play["host"].interrupt_after = 20
    outcome = _run(core.job_play, play["setup"])
    assert not outcome.ok and _record()["outcome"] == "stopped" and play["repaired"] == []


def test_play_passes_the_play_options_to_me3_by_version(play):
    play["opts"].update(play_boot_boost=False, play_show_logos=True)
    _run(core.job_play, play["setup"])
    command = next(e for e in play["host"].events if e[0] == "me3")[2]
    assert "--no-boot-boost" in command and "--show-logos" in command


def test_offline_play_uses_the_offline_profile_and_skips_steams_sign_in(play, monkeypatch, tmp_path):
    offline = tmp_path / "p.offline.me3"
    monkeypatch.setattr(core, "offline_profile_for", lambda profile, **k: offline)
    host = play["host"]
    host.sign_in_after = None  # offline: never signs in, and must not be waited for

    def job(setup, loc):
        core.job_play_offline(setup, loc, start_steam=True)

    outcome = _run(job, play["setup"])
    assert outcome.ok
    command = next(e for e in host.events if e[0] == "me3")[2]
    assert command[command.index("--profile") + 1] == str(offline)
    assert command[command.index("--skip-steam-init") + 1] == "true"  # offline: me3 does not wait for Steam
    assert host.happened()[0] == "steam started"


def test_offline_play_without_starting_steam_never_starts_it(play, monkeypatch, tmp_path):
    monkeypatch.setattr(core, "offline_profile_for", lambda profile, **k: tmp_path / "p.offline.me3")

    def job(setup, loc):
        core.job_play_offline(setup, loc, start_steam=False)

    _run(job, play["setup"])
    assert "steam started" not in play["host"].happened()


def test_a_game_without_a_regulation_block_is_not_repaired(play, monkeypatch):
    ds3 = games.get("darksouls3")  # no regulation block me3 leaves dirty (Elden Ring and Nightreign have one)
    assert not ds3.regulation_repair
    loc = Locations(ds3)
    monkeypatch.setattr(Locations, "save_files", lambda self: [])
    setup = setup_for(ds3, me3=play["setup"].me3_path(), loc=loc)
    outcome = jobs.run_job(core.job_play, setup, loc, "Starting...")
    assert outcome.ok and play["repaired"] == []


def test_the_job_index_line_is_readable_json(play):
    _run(core.job_play, play["setup"])
    lines_in_index = (run_logging.log_dir() / run_logging.JOBS_INDEX).read_text(encoding="utf-8").splitlines()
    assert lines_in_index and all(isinstance(json.loads(x), dict) for x in lines_in_index)
