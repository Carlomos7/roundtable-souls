"""The Activity page and what it reads: job summaries, logs read back, filters, day grouping, unseen failures."""

import datetime
import json
import os

import pytest

from roundtable_souls.platform import logging as rl
from roundtable_souls.platform import paths as common
from roundtable_souls.ui import activity as act

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def make_job(title, lines=(), outcome=None, game="eldenring", attach=None):
    job = rl.begin_job(title, game=game)
    for line in lines:
        common.log(line)
    if attach:
        rl.attachment(attach[0]).write_text(attach[1], encoding="utf-8")
    rl.end_job(job, outcome)
    return job


# ----------------------------------------------------------------------------- what the index says
def test_a_job_keeps_its_summary_and_first_problem():
    make_job("install mod goblins", ["copying", "done: installed goblins (readme left out)"])
    make_job("repair", ["error: ER0000.co2 is locked by another program", "error: second problem"], "failed")
    recs = {r["title"]: r for r in rl.read_jobs()}
    assert recs["install mod goblins"]["summary"] == "installed goblins (readme left out)"
    assert recs["repair"]["problem"] == "ER0000.co2 is locked by another program"


def test_set_summary_wins_over_the_done_line():
    job = rl.begin_job("rebuild")
    common.log("done: rebuilt")
    rl.set_summary("Combined 2 packs; 1 overlapping row")
    rl.end_job(job)
    assert rl.read_jobs()[0]["summary"] == "Combined 2 packs; 1 overlapping row"


def test_a_log_reads_back_as_entries_with_levels_and_continuations():
    job = make_job("check", ["first line", "warning: careful"])
    rl.begin_job("crash")
    try:
        raise ValueError("boom")
    except ValueError:
        rl.get_logger("job").exception("it broke")
    crash = rl.current_job()
    rl.end_job(crash, "failed")
    got = rl.read_job_log(job.path.name)
    levels = [(e["level"], e["text"]) for e in got["entries"]]
    assert ("info", "first line") in levels and ("warning", "warning: careful") in levels
    assert all(e["time"].count(":") == 2 and "." in e["time"] for e in got["entries"])
    tb = next(e for e in rl.read_job_log(crash.path.name)["entries"] if e["text"].startswith("it broke"))
    assert tb["level"] == "error" and "Traceback" in tb["text"] and "ValueError: boom" in tb["text"]


def test_only_the_end_of_a_huge_log_is_read():
    job = make_job("play", [f"line {i} " + "x" * 80 for i in range(400)])
    got = rl.read_job_log(job.path.name, limit=4000)
    assert got["cut"] and got["entries"][-1]["text"].startswith("=== play")
    assert all(e["time"] for e in got["entries"])  # the partial first line was dropped, not shown as garbage


def test_names_outside_the_jobs_folder_are_refused():
    assert rl.job_file("../launcher.log") is None and rl.job_file("") is None
    assert rl.read_job_log("..\\..\\x.log")["missing"] and rl.read_attachment("/etc/passwd")["missing"]


def test_unseen_failures_count_only_after_the_last_look():
    make_job("repair", ["error: x"], "failed")
    first = rl.read_jobs()[0]
    assert len(rl.unseen_failures(0)) == 1
    assert rl.unseen_failures(float(first["t"])) == []
    make_job("play", ["fine"])
    make_job("install mod y", ["error: z"], "failed")
    assert [r["title"] for r in rl.unseen_failures(float(first["t"]))] == ["install mod y"]


def test_kinds_fall_into_the_filter_groups():
    assert rl.group_of("play") == "Play" and rl.group_of("repair") == "Saves"
    assert rl.group_of("rebuild") == "Mods" and rl.group_of("install") == "Mods"
    assert rl.group_of("check") == "Other" and rl.group_of("anything") == "Other"


# ----------------------------------------------------------------------------- how the page words things
def test_day_labels_and_durations():
    today = datetime.date(2026, 9, 29)
    assert act.day_label(today, today) == "Today"
    assert act.day_label(datetime.date(2026, 9, 28), today) == "Yesterday"
    assert act.day_label(datetime.date(2026, 9, 1), today) == "Tuesday 1 September 2026"
    assert act.duration_text(None) == "" and act.duration_text(0.2) == "under a second"
    assert act.duration_text(42) == "42s" and act.duration_text(125) == "2m 05s" and act.duration_text(3725) == "1h 02m"


def test_filters():
    rec = {"game": "nightreign", "kind": "play", "outcome": "done"}
    assert act.matches(rec, "", "", False)
    assert not act.matches(rec, "eldenring", "", False)
    assert act.matches({"game": "", "kind": "check", "outcome": "done"}, "eldenring", "", False)  # launcher-wide
    assert not act.matches(rec, "", "Mods", False)
    assert not act.matches(rec, "", "", True)
    assert act.matches(rec | {"outcome": "interrupted"}, "", "Play", True)


# ----------------------------------------------------------------------------- the page itself
@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_the_page_lists_jobs_by_day_with_outcomes_and_opens_one(app):
    make_job("repair", ["done: repaired 2 saves"])
    make_job("install mod goblins", ["error: archive is damaged"], "failed")
    make_job("play", ["launching"], attach=("me3", "me3 says: game started"))
    view = act.ActivityView(now=datetime.datetime.now)
    view.resize(900, 600)
    view.refresh()
    rows = view.rows_shown()
    assert [r.title.full_text() for r in rows] == ["Play", "Install mod goblins", "Repair"]
    assert [r.pill.text() for r in rows] == ["Done", "Failed", "Done"]
    assert rows[1].summary.full_text() == "archive is damaged" and rows[2].summary.full_text() == "repaired 2 saves"
    assert "3 jobs kept" in view.note.text() and "1 failed" in view.note.text()
    play = rows[0]
    play.flip()
    d = play.details
    assert d is not None and play.expanded and d.isVisibleTo(play) and "launching" in d._plain
    assert d.sources.count() == 2 and d.sources.isVisibleTo(play)
    d.sources.setCurrentIndex(1)
    assert "me3 says: game started" in d._plain and not d.detail.isVisibleTo(play)
    view.refresh()  # an opened entry stays open across a refresh
    assert view.rows_shown()[0].expanded


def test_show_details_reveals_debug_lines(app):
    job = rl.begin_job("rebuild")
    rl.get_logger("mods.merge").debug("hash cache hit for regulation.bin")
    common.log("done: rebuilt")
    rl.end_job(job)
    view = act.ActivityView()
    view.refresh()
    row = view.rows_shown()[0]
    row.flip()
    assert "hash cache hit" not in row.details._plain and "1 detail line hidden" in row.details.note.text()
    row.details.detail.setChecked(True)
    assert "hash cache hit" in row.details._plain


def test_filters_and_empty_states(app):
    view = act.ActivityView()
    view.refresh()
    assert "Nothing yet" in view.empty.text() and view.empty.isVisibleTo(view)
    make_job("play", game="nightreign")
    make_job("repair", ["error: x"], "failed")
    view.refresh()
    view.failed_only.setChecked(True)
    assert [r.title.full_text() for r in view.rows_shown()] == ["Repair"]
    view.failed_only.setChecked(False)
    view.game_box.setCurrentIndex(view.game_box.findData("nightreign"))
    assert [r.title.full_text() for r in view.rows_shown()] == ["Play"]
    view.kind_box.setCurrentIndex(view.kind_box.findData("Mods"))
    assert view.rows_shown() == [] and "Nothing matches" in view.empty.text()


def test_copy_for_support_masks_the_user(app, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("USERNAME", "player1")
    make_job("check", [r"profile C:\Users\player1\p.me3 for 76561190000000001"])
    view = act.ActivityView()
    view.refresh()
    row = view.rows_shown()[0]
    row.flip()
    row.details._copy(True)
    text = QApplication.clipboard().text()
    assert "player1" not in text and "<user>" in text and "<steam id>" in text
    row.details._copy(False)
    assert "player1" in QApplication.clipboard().text()


def test_a_missing_log_file_is_said_not_shown_as_an_error(app):
    job = make_job("play", ["x"])
    job.path.unlink()
    view = act.ActivityView()
    view.refresh()
    row = view.rows_shown()[0]
    row.flip()
    assert row.details._plain == ""


def test_an_interrupted_job_explains_itself(app):
    job = make_job("play", ["launching"])
    idx = rl.log_dir() / rl.JOBS_INDEX
    lines = idx.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[-1]) | {"id": "ghost", "outcome": "running", "pid": 999999, "summary": ""}
    idx.write_text("\n".join(lines + [json.dumps(rec)]) + "\n", encoding="utf-8")
    view = act.ActivityView()
    view.refresh()
    ghost = next(r for r in view.rows_shown() if r.rec["id"] == "ghost")
    assert ghost.pill.text() == "Interrupted" and "closed before this job finished" in ghost.summary.full_text()
    assert job.path.exists()
