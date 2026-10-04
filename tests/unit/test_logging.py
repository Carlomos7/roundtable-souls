"""The logging layer: jobs with their own files and index records, levels, the window's sink, crashes, retention,
the legacy files, redaction, and what happens when the logs folder cannot be written."""

import json
import logging
import os
import threading
import time
from pathlib import Path

import pytest

from roundtable_souls.game import catalog as games
from roundtable_souls.game.locate import Locations
from roundtable_souls.platform import logging as rl
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.services import jobs
from roundtable_souls.services import play as core


@pytest.fixture
def logs(tmp_path):
    return tmp_path / "launcher-data" / "logs"  # conftest points the data folder here


def job_text(job) -> str:
    return job.path.read_text(encoding="utf-8")


def index(logs: Path) -> list[dict]:
    return [json.loads(line) for line in (logs / rl.JOBS_INDEX).read_text(encoding="utf-8").splitlines()]


# ----------------------------------------------------------------------------- where logs go
def test_logs_follow_the_data_folder_so_tests_never_touch_the_real_one(logs):
    assert rl.log_dir() == logs


def test_setup_writes_launcher_log_and_moves_older_files_aside(logs):
    logs.mkdir(parents=True)
    (logs / "last_run.log").write_text("old run")
    (logs / "launcher-errors.log").write_text("old crash")
    rl.setup_logging(console=False)
    rl.get_logger("mods.merge").info("hello")
    rl.get_logger("mods.merge").debug("too detailed for launcher.log")
    rl.shutdown()
    text = (logs / rl.APP_LOG).read_text(encoding="utf-8")
    assert "INFO     mods.merge  hello" in text and "too detailed" not in text
    moved = sorted(p.name for p in (logs / rl.OLD_DIR).iterdir())
    assert len(moved) == 2 and moved[0].startswith("last_run.") and moved[1].startswith("launcher-errors.")
    assert not (logs / "last_run.log").exists()


def test_setup_twice_keeps_one_file_handler(logs):
    rl.setup_logging(console=False)
    rl.setup_logging(console=False)
    files = [h for h in rl.get_logger().handlers if isinstance(h, logging.FileHandler)]
    rl.shutdown()
    assert len(files) == 1


def test_launcher_log_rotates_and_a_failed_rotation_is_not_fatal(logs, monkeypatch):
    monkeypatch.setattr(rl, "APP_LOG_BYTES", 400)
    rl.setup_logging(console=False)
    for i in range(40):
        rl.get_logger().info("line %d %s", i, "x" * 40)
    assert (logs / f"{rl.APP_LOG}.1").is_file()

    def refuse(*a, **k):
        raise PermissionError("another copy has it open")

    monkeypatch.setattr(os, "rename", refuse)
    monkeypatch.setattr(os, "replace", refuse)
    for i in range(20):
        rl.get_logger().info("still logging %d %s", i, "y" * 40)  # no exception, keeps writing
    rl.shutdown()
    assert "still logging 19" in (logs / rl.APP_LOG).read_text(encoding="utf-8")


def test_an_unwritable_logs_folder_never_breaks_anything(tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x")
    monkeypatch.setattr(rl, "_dir_override", blocker / "logs")
    rl.setup_logging(console=False)
    got = []
    rl.attach_sink(lambda m, lvl: got.append((m, lvl)))
    job = rl.begin_job("Play")
    run_logging.log("steam: running")
    rl.attachment("me3")
    rl.end_job(job)
    rl.shutdown()
    assert job.path is None and ("steam: running", "info") in got and job.outcome == "done"
    assert rl.read_jobs() == []


# ----------------------------------------------------------------------------- levels
def test_old_style_prefixes_become_real_levels():
    assert rl.level_of("error: no me3") == logging.ERROR
    assert rl.level_of("  Traceback (most recent call last)") == logging.ERROR
    assert rl.level_of("warning: slow disk") == logging.WARNING
    assert rl.level_of("done: installed") == logging.INFO
    assert rl.level_of("") == logging.INFO


def test_common_log_uses_the_callers_module_and_accepts_anything(logs):
    job = rl.begin_job("Check")
    run_logging.log(12345)
    run_logging.log(None)
    run_logging.log("multi\nline\ntext")
    run_logging.log("日本語のパス C:\\Users\\テスト\\file.me3")
    rl.end_job(job)
    text = job_text(job)
    assert "test_logging  12345" in text and "multi\nline\ntext" in text and "日本語のパス" in text


# ----------------------------------------------------------------------------- jobs
def test_a_job_has_its_own_file_header_footer_and_index_record(logs):
    job = rl.begin_job("launcher: install mod goblins", game="eldenring", profile="C:/p.me3")
    run_logging.log("copied 12 files")
    run_logging.log("warning: readme left out")
    rl.end_job(job)
    text = job_text(job)
    assert text.splitlines()[0].endswith("=== install mod goblins ===")
    assert "copied 12 files" in text and "WARNING" in text
    assert "install mod goblins: warnings in" in text.splitlines()[-1]
    recs = rl.read_jobs()
    assert len(recs) == 1
    r = recs[0]
    assert (r["title"], r["kind"], r["outcome"], r["warnings"], r["errors"], r["game"]) == (
        "install mod goblins",
        "install",
        "warnings",
        1,
        0,
        "eldenring",
    )
    assert r["log"] == job.path.name and r["seconds"] is not None


def test_lines_from_other_threads_stay_out_of_a_job(logs):
    job = rl.begin_job("Play")
    other = threading.Thread(target=lambda: run_logging.log("update check: nothing new"))
    other.start()
    other.join()
    run_logging.log("launching me3")
    rl.end_job(job)
    text = job_text(job)
    assert "launching me3" in text and "update check" not in text


def test_the_window_gets_the_jobs_lines_and_warnings_from_anywhere(logs):
    got = []
    rl.attach_sink(lambda m, lvl: got.append((m, lvl)))
    run_logging.log("background detail")  # no job: not for the pane
    run_logging.log("warning: Steam is offline")  # a warning from anywhere is
    job = rl.begin_job("Repair")
    run_logging.log("repaired 2 saves")
    run_logging.log("error: one save is locked")
    rl.end_job(job)
    assert ("background detail", "info") not in got
    assert ("warning: Steam is offline", "warning") in got
    assert ("repaired 2 saves", "info") in got and ("error: one save is locked", "error") in got


def test_a_broken_sink_never_stops_a_job(logs):
    rl.attach_sink(lambda m, lvl: 1 / 0)
    job = rl.begin_job("Play")
    run_logging.log("still fine")
    rl.end_job(job)
    assert "still fine" in job_text(job)


def test_a_job_named_inside_run_job_is_renamed_not_restarted(logs):
    job = rl.begin_job("Installing goblins...")
    rl.start_log("launcher: install mod goblins", "eldenring")
    run_logging.log("inside")
    rl.end_job(job)
    recs = rl.read_jobs()
    assert len(recs) == 1 and recs[0]["title"] == "install mod goblins" and recs[0]["kind"] == "install"
    assert "inside" in job_text(job)


def test_the_command_line_gets_a_job_that_ends_at_the_next_one_and_at_exit(logs):
    rl.start_log("launcher: check", "eldenring")
    run_logging.log("first")
    first = rl.current_job()
    rl.start_log("launcher: play (no window)", "eldenring")
    second = rl._standalone
    assert first is not second and first.outcome == "done"
    rl.shutdown()
    assert second.outcome == "done" and [r["title"] for r in rl.read_jobs()] == ["play (no window)", "check"]
    assert {r["game"] for r in rl.read_jobs()} == {"eldenring"}  # the game the command line runs for


def test_attachments_belong_to_the_job(logs):
    job = rl.begin_job("Play")
    me3 = rl.attachment("me3")
    me3.write_text("me3 says hi")
    assert rl.attachment("me3") == me3  # asked twice, listed once
    rl.end_job(job)
    rec = rl.read_jobs()[0]
    assert rec["attachments"] == [me3.name] and me3.name.startswith(job.path.stem)
    assert rl.attachment("me3") is None  # no job, no attachment


def test_job_files_close_so_they_can_be_deleted(logs):
    job = rl.begin_job("Play")
    run_logging.log("x")
    rl.end_job(job)
    job.path.unlink()  # Windows refuses while a handle is open
    assert not job.path.exists()


def test_two_jobs_in_one_second_get_their_own_files(logs):
    a = rl.begin_job("Repair")
    rl.end_job(a)
    b = rl.begin_job("Repair")
    rl.end_job(b)
    assert a.path != b.path and a.path.is_file() and b.path.is_file()


# ----------------------------------------------------------------------------- run_job
def test_run_job_records_how_each_job_ended(logs):
    results = []

    def done(ok, status):
        results.append((ok, status))

    def fine(setup, loc):
        run_logging.log("did it")

    def failing(setup, loc):
        run_logging.log("error: could not write the save")
        raise SystemExit(1)

    def interrupted(setup, loc):
        raise SystemExit(130)

    def crashing(setup, loc):
        raise ValueError("boom")

    for fn, title in (
        (fine, "Repairing..."),
        (failing, "Repairing..."),
        (interrupted, "Starting..."),
        (crashing, "Installing x..."),
    ):
        outcome = jobs.run_job(fn, None, Locations(games.ELDEN_RING), title)
        done(outcome.ok, outcome.status)
    outcomes = [r["outcome"] for r in reversed(rl.read_jobs())]
    assert outcomes == ["done", "failed", "stopped", "failed"]
    assert [r[0] for r in results] == [True, False, False, False]
    crash_log = next(r for r in rl.read_jobs() if r["title"] == "Installing x")["log"]
    text = (logs / rl.JOBS_DIR / crash_log).read_text(encoding="utf-8")
    assert "Traceback" in text and "ValueError: boom" in text


def test_run_job_names_the_game_and_profile(logs):
    class Setup:
        profile = "C:/profiles/er/p.me3"

    loc = Locations(games.NIGHTREIGN)
    jobs.run_job(lambda s, loc: None, Setup(), loc, "Starting...")
    r = rl.read_jobs()[0]
    assert r["game"] == "nightreign" and r["profile"].endswith("p.me3") and r["title"] == "Starting"


# ----------------------------------------------------------------------------- the index
def test_a_job_left_running_by_a_closed_launcher_reads_as_interrupted(logs):
    job = rl.begin_job("Play")
    rl.end_job(job)
    lines = (logs / rl.JOBS_INDEX).read_text(encoding="utf-8")
    ghost = json.loads(lines.splitlines()[0]) | {"id": "ghost", "outcome": "running", "pid": 999999}
    with (logs / rl.JOBS_INDEX).open("a", encoding="utf-8") as f:
        f.write(json.dumps(ghost) + "\n")
        f.write("{not json\n")
        f.write("[1, 2]\n")
    recs = {r["id"]: r for r in rl.read_jobs()}
    assert recs["ghost"]["outcome"] == "interrupted" and recs[job.id]["outcome"] == "done"


def test_retention_keeps_the_newest_or_the_last_days_and_removes_files(logs):
    jobs = []
    for i in range(6):
        j = rl.begin_job(f"Repair {i}")
        rl.end_job(j)
        jobs.append(j)
    # age the first four by 30 days in the index
    recs = index(logs)
    for r in recs:
        n = int(r["title"].split()[-1])
        if n < 4:
            r["start"] = "2020-01-01T00:00:00"
    (logs / rl.JOBS_INDEX).write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    dropped = rl.prune(keep=3, days=14)
    kept = {r["title"] for r in rl.read_jobs()}
    assert kept == {"Repair 3", "Repair 4", "Repair 5"} or kept == {"Repair 4", "Repair 5", "Repair 3"}
    assert len(dropped) == 3
    for j in jobs[:3]:
        assert not j.path.exists()
    assert len(index(logs)) == 3  # one line per job after compaction


def test_retention_never_drops_a_running_job(logs):
    running = rl.begin_job("Play")
    dropped = rl.prune(keep=0, days=0, now=time.time() + 86400 * 30)
    assert running.id not in dropped and running.path.exists()
    rl.end_job(running)


def test_old_orphan_files_are_cleaned_up_new_ones_kept(logs):
    j = rl.begin_job("Repair")
    rl.end_job(j)
    orphan_old = logs / rl.JOBS_DIR / "2020-01-01_000000_forgotten.log"
    orphan_new = logs / rl.JOBS_DIR / "fresh_orphan.log"
    orphan_old.write_text("x")
    orphan_new.write_text("y")
    os.utime(orphan_old, (0, 0))
    rl.prune()
    assert not orphan_old.exists() and orphan_new.exists() and j.path.exists()


# ----------------------------------------------------------------------------- crashes
def test_a_crash_goes_to_launcher_log_and_the_running_job(logs):
    rl.setup_logging(console=False)
    job = rl.begin_job("Play")
    try:
        raise RuntimeError("worker died")
    except RuntimeError as e:
        core.report_exception(type(e), e, e.__traceback__, "a worker")
    rl.end_job(job)
    rl.shutdown()
    app = (logs / rl.APP_LOG).read_text(encoding="utf-8")
    assert "CRITICAL" in app and "uncaught error in a worker: worker died" in app and "Traceback" in app
    assert "worker died" in job_text(job) and rl.read_jobs()[0]["outcome"] == "failed"


# ----------------------------------------------------------------------------- the window's own lines
def test_lines_the_window_shows_itself_are_kept_but_not_echoed(logs):
    rl.setup_logging(console=False)
    got = []
    rl.attach_sink(lambda m, lvl: got.append(m))
    rl.log_shown("warning: password changed in ersc_settings.ini")
    rl.shutdown()
    assert got == [] and "password changed" in (logs / rl.APP_LOG).read_text(encoding="utf-8")


# ----------------------------------------------------------------------------- sharing
def test_redact_masks_the_user_and_steam_ids(monkeypatch):
    monkeypatch.setenv("USERNAME", "player1")
    text = (
        r"C:\Users\player1\AppData\Local\x.me3 and c:/users/Someone/y and /home/deck/z "
        "76561190000000001 saved by player1, id 1234567890"
    )
    out = rl.redact(text)
    assert "player1" not in out and "Someone" not in out and "deck" not in out and "76561190000000001" not in out
    assert r"C:\Users\<user>\AppData" in out and "<steam id>" in out and "1234567890" in out


def test_copy_logs_writes_a_redacted_copy(logs, tmp_path, monkeypatch):
    monkeypatch.setenv("USERNAME", "player1")
    job = rl.begin_job("Play")
    run_logging.log(r"profile C:\Users\player1\p.me3 for 76561190000000001")
    rl.end_job(job)
    out = rl.copy_logs(tmp_path / "share")
    text = (out / rl.JOBS_DIR / job.path.name).read_text(encoding="utf-8")
    assert "<user>" in text and "<steam id>" in text and "player1" not in text
    assert (out / rl.JOBS_INDEX).is_file()


def test_kinds_are_read_from_titles():
    assert rl.kind_of("rebuild combined parameters") == "rebuild"
    assert rl.kind_of("Combining parameters...") == "rebuild"
    assert rl.kind_of("play offline") == "play"
    assert rl.kind_of("swap 'x' into ER0000.sl2") == "library"
    assert rl.kind_of("something new") == "task"
