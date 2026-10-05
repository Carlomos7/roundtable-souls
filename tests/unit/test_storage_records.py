"""The hash cache and the activity log in the database: imported from their old files (idempotent, resumable,
re-read when an older version rewrote them), switched over only once verified, lossless without storage, undo kept
in its file, retention after import, short transactions, and several processes at once. Real temporary databases;
child processes for concurrency."""

import datetime
import hashlib
import json
import os
import subprocess
import sys
import textwrap
import time

import pytest
from sqlalchemy import select

from roundtable_souls.mods import rebuild
from roundtable_souls.platform import logging as rl
from roundtable_souls.storage import activity as act
from roundtable_souls.storage import db, models
from roundtable_souls.storage.cache import HashCache
from roundtable_souls.storage.imports import run_imports

pytestmark = pytest.mark.skipif(db.sqlite_problem() is not None, reason=str(db.sqlite_problem()))


@pytest.fixture
def data(tmp_path):
    return tmp_path / "launcher-data"  # conftest points the data folder here


@pytest.fixture
def database(data):
    data.mkdir(parents=True, exist_ok=True)
    d = db.open_database(data, log=lambda line: None)
    yield d
    d.close()


@pytest.fixture(autouse=True)
def fresh_hash_memory(monkeypatch):
    monkeypatch.setattr(rebuild, "_HASHES", {})
    monkeypatch.setattr(rebuild, "_HASHES_LOADED", False)


def _jobs_file():
    return rl.log_dir() / rl.JOBS_INDEX


def _write_lines(recs, mode="w"):
    _jobs_file().parent.mkdir(parents=True, exist_ok=True)
    with _jobs_file().open(mode, encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")


def _rec(n, outcome="done", t=None, **extra):
    t = time.time() - 3600 if t is None else t
    start = datetime.datetime.fromtimestamp(t).isoformat(timespec="seconds")
    return {
        "id": f"job{n}",
        "title": f"Job {n}",
        "kind": "repair",
        "game": "eldenring",
        "profile": "",
        "start": start,
        "t": t,
        "end": None if outcome == "running" else start,
        "seconds": None if outcome == "running" else 2.0,
        "outcome": outcome,
        "warnings": 0,
        "errors": 0,
        "log": f"job{n}.log",
        "attachments": [],
        "summary": "",
        "problem": "",
        "undo": None,
        "pid": os.getpid(),
        **extra,
    }


def _rows(database):
    with database.unit_of_work() as s:
        return {r.import_key: r for r in s.scalars(select(models.Job))}


# ----------------------------------------------------------------------------- the hash cache
def _hashes_json(data, entries):
    (data / "cache").mkdir(parents=True, exist_ok=True)
    (data / "cache" / "hashes.json").write_text(json.dumps(entries), encoding="utf-8")


def test_the_cache_switches_to_the_database_only_after_a_verified_import(data, database, tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"merged archive")
    st = f.stat()
    key = os.path.normcase(str(f.resolve()))
    _hashes_json(data, {key: [st.st_size, st.st_mtime_ns, "from-the-old-file"]})
    cache = HashCache(database)
    rebuild.use_hash_store(cache)
    assert not cache.active and rebuild.sha256(f) == "from-the-old-file"  # not verified yet: the old file, as before
    assert cache.import_file(data / "cache" / "hashes.json") and cache.active
    before = (data / "cache" / "hashes.json").read_bytes()
    rebuild._HASHES.clear()
    assert rebuild.sha256(f) == "from-the-old-file"  # now from the database
    g = tmp_path / "b.bin"
    g.write_bytes(b"another")
    assert rebuild.sha256(g) == hashlib.sha256(b"another").hexdigest()
    assert (data / "cache" / "hashes.json").read_bytes() == before  # the old file is preserved, no longer written
    assert cache.get(os.path.normcase(str(g.resolve())), g.stat().st_size, g.stat().st_mtime_ns) is not None


def test_the_cache_import_is_idempotent_and_the_later_file_state_wins(data, database):
    _hashes_json(data, {"x": [1, 100, "old"], "y": [2, 200, "y"]})
    cache = HashCache(database)
    assert cache.import_file(data / "cache" / "hashes.json")
    assert cache.import_file(data / "cache" / "hashes.json")  # again: nothing changes
    # an older version, after a rollback, hashed x again (newer modification time) and dropped y
    _hashes_json(data, {"x": [1, 300, "new"]})
    assert cache.import_file(data / "cache" / "hashes.json")
    assert cache.get("x", 1, 300) == "new" and cache.get("y", 2, 200) == "y"
    _hashes_json(data, {"x": [1, 50, "older"]})  # an entry from before what the database has: not taken
    cache.import_file(data / "cache" / "hashes.json")
    assert cache.get("x", 1, 300) == "new"


def test_a_changed_file_is_hashed_again_and_a_failing_cache_is_a_miss(data, database, tmp_path, monkeypatch):
    _hashes_json(data, {})
    cache = HashCache(database)
    cache.import_file(data / "cache" / "hashes.json")
    rebuild.use_hash_store(cache)
    f = tmp_path / "a.bin"
    f.write_bytes(b"one")
    assert rebuild.sha256(f) == hashlib.sha256(b"one").hexdigest()
    f.write_bytes(b"two!")  # size and time change: the remembered hash no longer counts
    rebuild._HASHES.clear()
    assert rebuild.sha256(f) == hashlib.sha256(b"two!").hexdigest()

    def broken():
        raise RuntimeError("database gone")

    monkeypatch.setattr(database, "unit_of_work", broken)
    rebuild._HASHES.clear()
    f.write_bytes(b"three")
    assert rebuild.sha256(f) == hashlib.sha256(b"three").hexdigest()  # a miss: hashed, never a stale answer


def test_without_storage_the_cache_is_bypassed_and_its_file_left_alone(data, tmp_path):
    _hashes_json(data, {"x": [1, 1, "x"]})
    before = (data / "cache" / "hashes.json").read_bytes()
    rebuild.use_hash_store(None, file_in_use=False)
    f = tmp_path / "a.bin"
    f.write_bytes(b"data")
    assert rebuild.sha256(f) == hashlib.sha256(b"data").hexdigest()
    assert (data / "cache" / "hashes.json").read_bytes() == before


def test_no_database_transaction_is_open_while_a_file_is_hashed(data, database, tmp_path, monkeypatch):
    _hashes_json(data, {})
    cache = HashCache(database)
    cache.import_file(data / "cache" / "hashes.json")
    rebuild.use_hash_store(cache)
    f = tmp_path / "big.bin"
    f.write_bytes(os.urandom(3 << 20))
    seen = []
    real_open = type(f).open

    def watched_open(self, *a, **k):
        if self == f:
            seen.append(database.engine.pool.checkedout())  # type: ignore[attr-defined]
        return real_open(self, *a, **k)

    monkeypatch.setattr(type(f), "open", watched_open)
    rebuild.sha256(f)
    assert seen == [0]


# ----------------------------------------------------------------------------- the activity log
def test_the_activity_import_is_incremental_idempotent_and_verified(database):
    _write_lines([_rec(1), _rec(2, outcome="running")])
    log = act.ActivityLog(database)
    assert not log.active and log.import_file(_jobs_file()) and log.active
    _write_lines([_rec(2), _rec(3)], mode="a")  # job 2 finished, job 3 new
    log.import_file(_jobs_file())
    log.import_file(_jobs_file())
    rows = _rows(database)
    assert sorted(rows) == ["job1", "job2", "job3"] and rows["job2"].outcome == "done"
    with database.unit_of_work() as s:
        state = s.get(models.ImportState, act.SOURCE)
        assert state is not None and state.position == _jobs_file().stat().st_size and state.verified_at


def test_an_interrupted_import_resumes_where_it_stopped(database, monkeypatch):
    monkeypatch.setattr(act, "BATCH", 2)
    _write_lines([_rec(n) for n in range(7)])
    log = act.ActivityLog(database)
    assert not log.import_file(_jobs_file(), stop_after=2)  # stopped after 4 lines, not verified
    assert len(_rows(database)) == 4 and not log.active
    assert log.import_file(_jobs_file())
    assert sorted(_rows(database)) == [f"job{n}" for n in range(7)]


def test_a_file_an_older_version_rewrote_or_cut_is_read_again_without_duplicates(database):
    _write_lines([_rec(n) for n in range(5)])
    log = act.ActivityLog(database)
    log.import_file(_jobs_file())
    _write_lines([_rec(3), _rec(4), _rec(9)])  # an older version pruned it and added a job
    log.import_file(_jobs_file())
    assert sorted(_rows(database)) == [f"job{n}" for n in (0, 1, 2, 3, 4, 9)]  # nothing lost, nothing twice
    _jobs_file().write_text("", encoding="utf-8")  # cut to nothing
    log.import_file(_jobs_file())
    assert len(_rows(database)) == 6


def test_old_build_and_new_build_take_turns_without_losing_a_job(database):
    _write_lines([_rec(1)])
    store = act.ActivityLog(database)
    store.import_file(_jobs_file())
    rl.use_job_store(store)
    rl.end_job(rl.begin_job("New build job"))  # into the database, not the file
    assert "New build job" not in _jobs_file().read_text(encoding="utf-8")
    rl.use_job_store(None)
    _write_lines([_rec(7, title="Old build job")], mode="a")  # after a rollback, the older version appends
    rl.use_job_store(store)
    assert {"Job 1", "New build job", "Old build job"} <= {r["title"] for r in rl.read_jobs()}  # before the import
    store.import_file(_jobs_file())
    assert "job7" in _rows(database)


def test_without_storage_or_when_a_write_fails_records_go_to_the_file_and_arrive_later(database, monkeypatch):
    rl.use_job_store(None)  # storage off for the run
    rl.end_job(rl.begin_job("While storage was off"))
    store = act.ActivityLog(database)
    store.import_file(_jobs_file())
    rl.use_job_store(store)
    with monkeypatch.context() as m:
        m.setattr(store, "save", lambda record: False)  # a write that did not happen is not claimed
        rl.end_job(rl.begin_job("A failed write"))
    lines = [json.loads(x)["title"] for x in _jobs_file().read_text(encoding="utf-8").splitlines()]
    assert "While storage was off" in lines and "A failed write" in lines
    store.import_file(_jobs_file())
    assert {r.title for r in _rows(database).values()} >= {"While storage was off", "A failed write"}


def test_undo_stays_in_the_file_and_retention_never_touches_it(database):
    store = act.ActivityLog(database)
    store.import_file(_jobs_file())
    rl.use_job_store(store)
    job = rl.begin_job("Remove a mod")
    rl.set_undo({"kind": "remove", "path": "x"})
    rl.end_job(job)
    file_recs = [json.loads(x) for x in _jobs_file().read_text(encoding="utf-8").splitlines()]
    assert any(r["id"] == job.id and r.get("undo") for r in file_recs)
    shown = next(r for r in rl.read_jobs() if r["id"] == job.id)
    assert shown["undo"] == {"kind": "remove", "path": "x"} and shown["outcome"] != "running"
    with database.unit_of_work() as s:  # make the row 100 days old, then apply retention
        row = s.scalar(select(models.Job).where(models.Job.job_id == job.id))
        assert row is not None
        row.ended_at = models.utc_now() - datetime.timedelta(days=100)
    assert store.prune_completed() == 1
    assert next(r for r in rl.read_jobs() if r["id"] == job.id)["undo"]  # still offered: undo is in its file
    rl.mark_undone(job.id)
    assert not next(r for r in rl.read_jobs() if r["id"] == job.id)["undo"]


def test_retention_runs_after_the_import_and_spares_running_and_recent_jobs(data, database):
    old = time.time() - 120 * 86400
    _write_lines([_rec(1, t=old), _rec(2, outcome="running", t=old), _rec(3), _rec(4, outcome="failed", t=old)])
    _hashes_json(data, {})
    cache, log = HashCache(database), act.ActivityLog(database)
    out = run_imports(data / "cache" / "hashes.json", _jobs_file(), cache, log, lambda line: None)
    assert out["activity log"] and out["hash cache"] and out["pruned"] == 2
    assert sorted(_rows(database)) == ["job2", "job3"]


def test_two_processes_importing_and_writing_at_once_lose_and_double_nothing(data, database, tmp_path):
    _write_lines([_rec(n) for n in range(300)])
    worker = textwrap.dedent(
        """
        import json, sys, time
        from pathlib import Path
        from roundtable_souls.storage import activity, db
        folder, jobs, tag = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
        d = db.open_database(folder, log=lambda line: None)
        log = activity.ActivityLog(d)
        log.import_file(jobs)
        for i in range(30):
            t = time.time()
            assert log.save({"id": f"{tag}-{i}", "title": tag, "t": t, "start": "2026-10-05T12:00:00",
                             "outcome": "done", "seconds": 1.0, "pid": 1})
        log.import_file(jobs)
        d.close()
        print("ok", flush=True)
        """
    )
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", worker, str(data), str(_jobs_file()), tag], stdout=subprocess.PIPE, text=True
        )
        for tag in ("a", "b")
    ]
    for p in procs:
        out, _ = p.communicate(timeout=120)
        assert out.strip() == "ok" and p.returncode == 0
    rows = _rows(database)
    assert len(rows) == 300 + 60 and len({r.import_key for r in rows.values()}) == 360


def test_the_reader_prefers_the_more_finished_state_and_takes_undo_from_the_file(database):
    store = act.ActivityLog(database)
    store.import_file(_jobs_file())
    rl.use_job_store(store)
    store.save(_rec(5, outcome="done"))
    _write_lines([_rec(5, outcome="running", undo={"kind": "x"})], mode="a")
    shown = next(r for r in rl.read_jobs() if r["id"] == "job5")
    assert shown["outcome"] == "done" and shown["undo"] == {"kind": "x"}


# ----------------------------------------------------------------------------- the application
def test_create_app_wires_both_areas_and_imports_after_ready(data):
    from roundtable_souls.app import create_app

    _write_lines([_rec(1)])
    ctx = create_app()
    try:
        assert ctx.hash_cache is not None and ctx.activity is not None and not ctx.activity.active
        thread = ctx.start_imports()
        assert thread is not None
        thread.join(30)
        assert ctx.activity.active and ctx.hash_cache.active
        rl.end_job(rl.begin_job("After the switch"))
        assert "After the switch" not in _jobs_file().read_text(encoding="utf-8")
    finally:
        ctx.close()


def test_create_app_without_storage_bypasses_the_cache_and_keeps_activity_in_the_file(data, monkeypatch, tmp_path):
    from roundtable_souls import app

    def refuse(_folder):
        raise db.StorageUnavailable("busy", "busy")

    monkeypatch.setattr(app.storage_db, "open_database", refuse)
    ctx = app.create_app()
    assert ctx.storage is None and ctx.start_imports() is None
    rl.end_job(rl.begin_job("No storage"))
    assert "No storage" in _jobs_file().read_text(encoding="utf-8")
    f = tmp_path / "a.bin"
    f.write_bytes(b"z")
    rebuild.sha256(f)
    assert not (data / "cache" / "hashes.json").exists()
