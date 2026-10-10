"""The Activity presenter without Qt: the list grouped by day, the summary row, filters, a job's log, Undo plans, and
every string through tr()."""

import datetime
import gettext
import re
import subprocess
import sys

import pytest

from roundtable_souls.platform import logging as run_logging
from roundtable_souls.ui import text
from roundtable_souls.ui.pages.activity import presenter as act

NOW = datetime.datetime(2026, 10, 9, 12, 0)


def rec(id, start, title="Job", kind="task", outcome="done", game="eldenring", **more):
    return {
        "id": id,
        "title": title,
        "kind": kind,
        "game": game,
        "start": start,
        "seconds": more.pop("seconds", 4.0),
        "outcome": outcome,
        "log": f"{id}.log",
        "attachments": more.pop("attachments", []),
        **more,
    }


JOBS = [  # the index is newest first
    rec("p2", "2026-10-09T11:00:00", "Play Elden Ring", "play", seconds=7800),
    rec("i1", "2026-10-09T09:30:00", "install mod Grand Merchant", "install", undo={"type": "install"}),
    rec("r1", "2026-10-08T21:03:00", "rebuild combined parameters", "rebuild", "failed", problem="regulation clash"),
    rec("x1", "2026-10-01T08:00:00", "repair saves", "repair", "interrupted", game="nightreign"),
]


def presenter(jobs=JOBS, available=lambda u: bool(u)):
    return act.ActivityPresenter(read_jobs=lambda: list(jobs), now=lambda: NOW, undo_available=available)


def test_importing_the_presenter_pulls_in_no_qt():
    code = (
        "import sys; import roundtable_souls.ui.pages.activity.presenter; "
        "print(sorted(m for m in sys.modules if m.split('.')[0] in ('PySide6', 'shiboken6', 'qfluentwidgets')))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "[]"


def test_jobs_are_grouped_by_day_newest_first():
    state = presenter().refresh()
    assert [d.label for d in state.days] == ["Today", "Yesterday", "Thursday 1 October 2026"]
    assert [j.id for j in state.days[0].jobs] == ["p2", "i1"]
    assert state.empty == ""


def test_a_row_says_when_how_it_ended_what_it_was_and_its_result():
    today = presenter().refresh().days[0].jobs
    play, install = today
    assert (play.when, play.title, play.outcome, play.level) == ("11:00", "Play Elden Ring", "Done", "success")
    assert play.meta == "2h 10m  ·  Elden Ring"
    assert install.title == "Install mod Grand Merchant"  # capitalised
    failed = presenter().refresh().days[1].jobs[0]
    assert (failed.outcome, failed.level, failed.failed, failed.line) == ("Failed", "danger", True, "regulation clash")
    interrupted = presenter().refresh().days[2].jobs[0]
    assert interrupted.line == "The launcher closed before this job finished."


def test_undo_is_offered_only_for_a_finished_job_that_can_still_be_taken_back():
    install = presenter().refresh().days[0].jobs[1]
    assert install.undo_label == "Undo install"
    assert install.undo_tip.startswith("Take this back: ")
    gone = presenter(available=lambda u: False).refresh().days[0].jobs[1]
    assert gone.undo_label == ""
    failed = presenter().refresh().days[1].jobs[0]
    assert failed.undo_label == ""


def test_the_summary_row_names_the_last_play_install_and_failure():
    cards = presenter().refresh().summary
    assert [(c.label, c.value, c.level) for c in cards] == [
        ("Last Play", "Today 11:00  ·  2h 10m", "success"),
        ("Last install", "Install mod Grand Merchant  ·  today", "muted"),
        ("Last failure", "Rebuild combined parameters  ·  yesterday", "danger"),
    ]
    empty = presenter(jobs=[]).refresh().summary
    assert [c.value for c in empty] == ["None yet", "None yet", "None yet"]


def test_filters_and_what_an_empty_list_says():
    p = presenter()
    assert [j.id for d in p.refresh(game="nightreign").days for j in d.jobs] == ["x1"]
    assert [j.id for d in p.refresh(group="Mods").days for j in d.jobs] == ["i1", "r1"]
    assert [j.id for d in p.refresh(failed_only=True).days for j in d.jobs] == ["r1", "x1"]
    assert p.refresh(game="sekiro", group="Play").empty == "Nothing matches these filters."
    assert presenter(jobs=[]).refresh().empty.startswith("Nothing yet.")
    assert [c.label for c in p.kinds] == ["All kinds", "Play", "Saves", "Mods", "Other"]
    assert p.games[0] == act.Choice("", "All games")


def test_a_jobs_log_hides_detail_lines_unless_asked(monkeypatch):
    entries = [
        {"time": "11:00:00.000", "level": "info", "source": "job", "text": "=== Play ==="},
        {"time": "11:00:01.000", "level": "debug", "source": "me3", "text": "fine detail"},
        {"time": "11:00:02.000", "level": "error", "source": "me3", "text": "it broke"},
    ]
    monkeypatch.setattr(run_logging, "read_job_log", lambda name: {"entries": entries, "cut": True, "missing": False})
    p = presenter()
    p.refresh()
    log = p.log("p2")
    assert log.rows == (("11:00:00.000", "debug", "Play"), ("11:00:02.000", "error", "it broke"))
    assert log.note == (
        "Only the end of a long file is shown; Open file has all of it. "
        "1 detail line hidden; turn on Show details to see it."
    )
    assert len(p.log("p2", detail=True).rows) == 3
    assert "ERROR    it broke" in log.plain


def test_a_missing_log_is_said_not_shown_as_an_error(monkeypatch):
    monkeypatch.setattr(run_logging, "read_job_log", lambda name: {"entries": [], "cut": False, "missing": True})
    p = presenter()
    p.refresh()
    log = p.log("p2")
    assert log.missing and log.rows[0][2] == "This job's log file is no longer there."


def test_other_programs_output_is_offered_beside_the_log():
    jobs = [rec("p", "2026-10-09T11:00:00", "Play", "play", attachments=["p.me3.log"])]
    item = presenter(jobs).refresh().days[0].jobs[0]
    assert [s.label for s in item.sources] == ["Log", "me3 output"]


def test_copy_for_support_masks_the_user(monkeypatch):
    monkeypatch.setattr(run_logging, "redact", lambda s: s.replace("carlos", "<user>"))
    log = act.LogText((), "C:/Users/carlos/x")
    assert act.ActivityPresenter.copy_text(log) == "C:/Users/carlos/x"
    assert act.ActivityPresenter.copy_text(log, for_support=True) == "C:/Users/<user>/x"


@pytest.mark.parametrize(
    ("busy", "running", "undo", "title"),
    [
        (True, False, {"type": "install"}, "Wait for the current job"),
        (False, False, {}, "It cannot be taken back any more"),
        (False, True, {"type": "rebuild"}, "Close the game first"),
    ],
)
def test_undo_says_why_it_cannot_run_now(busy, running, undo, title):
    plan = presenter().undo_plan({"id": "j", "undo": undo}, busy=busy, game_running=running)
    assert isinstance(plan, act.Refusal) and plan.title == title


def test_undo_plans_say_what_each_kind_of_undo_changes(tmp_path):
    p = presenter()
    rebuild = p.undo_plan(
        {"id": "r", "undo": {"type": "rebuild", "profile": "x/a.me3", "profile_before": "k"}}, False, False
    )
    assert isinstance(rebuild, act.UndoPlan)
    assert (rebuild.title, rebuild.apply_text, rebuild.progress) == (
        "Undo the rebuild",
        "Undo the rebuild",
        "Undoing the rebuild...",
    )
    assert rebuild.changes == ("a.me3 goes back as it was before the rebuild",)
    update = p.undo_plan({"id": "u", "undo": {"type": "update", "name": "GM", "rebuild": True}}, False, False)
    assert isinstance(update, act.UndoPlan)
    assert update.title == "Roll GM back" and update.apply_text == "Roll back"
    assert "The merged mods are rebuilt for it" in update.changes
    restore = p.undo_plan({"id": "m", "undo": {"type": "remove", "name": "GM", "profile": "a.me3"}}, False, False)
    assert isinstance(restore, act.UndoPlan)
    assert restore.title == "Restore GM" and restore.changes == ("Its entry goes back into a.me3, where it was",)


def test_the_undo_job_runs_the_undo_and_records_it(monkeypatch):
    calls = []
    from roundtable_souls.mods import undo as mod_undo

    monkeypatch.setattr(mod_undo, "run", lambda u, log, loc: calls.append(("run", u["type"], loc)) or "undid it")
    monkeypatch.setattr(run_logging, "start_log", lambda title, game: calls.append(("title", title)))
    monkeypatch.setattr(run_logging, "log", lambda m="": calls.append(("log", m)))
    monkeypatch.setattr(run_logging, "mark_undone", lambda i: calls.append(("undone", i)))
    monkeypatch.setattr(run_logging, "set_undo", lambda d: calls.append(("redo", d.get("redo"))))
    plan = presenter().undo_plan({"id": "r", "undo": {"type": "rebuild"}}, False, False)
    assert isinstance(plan, act.UndoPlan)
    loc = type("Loc", (), {"game": type("G", (), {"key": "eldenring"})()})()
    plan.job("LOCATIONS")(None, loc)
    assert calls == [
        ("title", "launcher: undo the rebuild"),
        ("run", "rebuild", "LOCATIONS"),
        ("undone", "r"),
        ("redo", True),
        ("log", "done: undid it"),
    ]


def test_every_string_goes_through_tr():
    class Shout(gettext.NullTranslations):
        def gettext(self, message):  # placeholders stay as they are
            return re.sub(
                r"\{[^}]*\}|[^{]+", lambda m: m.group(0) if m.group(0)[0] == "{" else m.group(0).upper(), message
            )

    text.install(Shout())
    try:
        p = presenter()
        state = p.refresh()
        assert state.days[0].label == "TODAY"
        assert state.summary[0].label == "LAST PLAY"
        assert p.open_window_text == "OPEN NEW ACTIVITY WINDOW"
        assert state.days[0].jobs[0].outcome == "DONE"
    finally:
        text.install(None)
