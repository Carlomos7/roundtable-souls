"""The activity log in the database (it was logs/jobs.jsonl): one row per job, what it was, when, how it ended.

jobs.jsonl is imported, not moved. It stays where it is and keeps three roles:
- the fallback: a record the database could not take (storage off for the run, or a failed write) is appended
  there and imported by the next run that has storage, so nothing is lost;
- the home of undo: a job's "undo" and "undone" stay in the file (undo records are protective and move later, on
  their own terms), so the rows here have neither and retention never touches them;
- what an older version restored by an update's watchdog reads and appends to. The next import here takes what it
  appended, and reads the whole file again if it was rewritten or cut (older versions prune it).

The import is incremental and idempotent: rows are keyed by the job's id (a hash of the line when it has none), and
the bytes imported so far and their SHA-256 are saved in the same transaction as each batch, so an interrupted import
resumes and a repeated one adds nothing. Writers and readers switch to the database only after an import has been
verified (every job in the file found here).

Retention: completed rows (done, warnings, failed, stopped) whose job ended more than RETENTION_DAYS ago are removed,
only after the file has been imported. A row still running (or interrupted: its process died while it ran) is never
removed by age.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import delete, select

from roundtable_souls.platform import logging as run_logging
from roundtable_souls.storage.db import Database
from roundtable_souls.storage.models import ImportState, Job, utc_now

SOURCE = "jobs.jsonl"
RETENTION_DAYS = run_logging.ACTIVITY_DAYS  # the file reader applies the same rule to records waiting in jobs.jsonl
COMPLETED = run_logging.COMPLETED
BATCH = 500  # lines per import transaction


# ----------------------------------------------------------------------------- records <-> rows
def _local(text: str | None) -> datetime.datetime | None:
    if not text:
        return None
    try:
        when = datetime.datetime.fromisoformat(str(text))
    except ValueError:
        return None
    return when.astimezone(datetime.UTC)  # a naive time in the file is the launcher's local time


def import_key(rec: dict) -> str:
    if rec.get("id"):
        return str(rec["id"])
    shape = json.dumps([rec.get(k) for k in ("kind", "start", "end", "outcome")], ensure_ascii=False)
    return "line:" + hashlib.sha256(shape.encode("utf-8")).hexdigest()


def to_row(rec: dict) -> dict:
    """The columns for one record as platform.logging writes it (undo and undone are left to the file)."""
    started = (
        datetime.datetime.fromtimestamp(float(rec["t"]), datetime.UTC)
        if rec.get("t") not in (None, "")
        else _local(rec.get("start"))
    ) or datetime.datetime(1970, 1, 1, tzinfo=datetime.UTC)
    ended = None
    if rec.get("seconds") not in (None, "") and rec.get("outcome") != "running":
        ended = started + datetime.timedelta(seconds=float(rec["seconds"]))
    elif rec.get("end"):
        ended = _local(rec.get("end"))
    return {
        "import_key": import_key(rec),
        "job_id": str(rec["id"]) if rec.get("id") else None,
        "title": str(rec.get("title") or ""),
        "kind": str(rec.get("kind") or ""),
        "game": str(rec.get("game") or ""),
        "profile": str(rec.get("profile") or ""),
        "started_at": started,
        "ended_at": ended,
        "outcome": str(rec.get("outcome") or "running"),
        "warnings": int(rec.get("warnings") or 0),
        "errors": int(rec.get("errors") or 0),
        "log_name": rec.get("log") or None,
        "attachments": list(rec.get("attachments") or []),
        "summary": str(rec.get("summary") or ""),
        "problem": str(rec.get("problem") or ""),
        "pid": int(rec["pid"]) if rec.get("pid") not in (None, "") else None,
    }


def from_row(row: Job) -> dict:
    """A row as the record platform.logging.read_jobs returns (without undo, which comes from the file)."""
    start_local = row.started_at.astimezone().replace(tzinfo=None)
    rec = {
        "id": row.job_id or row.import_key,
        "title": row.title,
        "kind": row.kind,
        "game": row.game,
        "profile": row.profile,
        "start": start_local.isoformat(timespec="seconds"),
        "t": round(row.started_at.timestamp(), 6),
        "end": None,
        "seconds": None,
        "outcome": row.outcome,
        "warnings": row.warnings,
        "errors": row.errors,
        "log": row.log_name,
        "attachments": list(row.attachments or []),
        "summary": row.summary,
        "problem": row.problem,
        "undo": None,
        "pid": row.pid,
    }
    if row.ended_at is not None:
        rec["end"] = row.ended_at.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")
        rec["seconds"] = round((row.ended_at - row.started_at).total_seconds(), 1)
    return rec


def _upsert(s, values: dict) -> None:
    """Insert, or update unless the stored row is finished and this record is an older, still-running state."""
    row = s.scalar(select(Job).where(Job.import_key == values["import_key"]))
    if row is None:
        s.add(Job(**values))
    elif not (row.outcome != "running" and values["outcome"] == "running"):
        for k, v in values.items():
            setattr(row, k, v)


# ----------------------------------------------------------------------------- the repository
class ActivityLog:
    def __init__(self, db: Database, log: Callable[[str], None] = lambda line: None):
        self.db = db
        self.log = log
        self.active = _verified(db)
        self._warned = False

    def save(self, record: dict) -> bool:
        """Store one job record in one short unit of work. False when it was not stored (not switched over yet, or
        the write failed): the caller keeps it in the file."""
        if not self.active:
            return False
        try:
            values = to_row(record)
            with self.db.unit_of_work() as s:
                _upsert(s, values)
            return True
        except Exception as e:
            if not self._warned:
                self._warned = True
                self.log(f"warning: the activity log in the database failed ({e}); records go to jobs.jsonl")
            return False

    def records(self) -> list[dict] | None:
        """Every row as a record, or None when the database is not in use or can't be read."""
        if not self.active:
            return None
        try:
            with self.db.unit_of_work() as s:
                return [from_row(r) for r in s.scalars(select(Job))]
        except Exception as e:
            self.log(f"warning: the activity log in the database can't be read ({e})")
            return None

    def import_file(self, path: Path, stop_after: int | None = None) -> bool:
        """Import the lines of jobs.jsonl not imported yet (all of them when the file was rewritten), verify, and
        switch over when every job in the file is here. Returns whether the log is now active. stop_after (tests):
        stop after that many batches, as an interrupted import would."""
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            data = b""
        end = data.rfind(b"\n") + 1  # complete lines only: a line still being written waits for the next import
        with self.db.unit_of_work() as s:
            state = s.get(ImportState, SOURCE)
            pos = state.position if state else 0
            prefix = state.prefix_sha256 if state else ""
        if pos > end or hashlib.sha256(data[:pos]).hexdigest() != (prefix or hashlib.sha256(b"").hexdigest()):
            self.log("storage: jobs.jsonl was rewritten since the last import; reading all of it again")
            pos = 0
        lines = data[pos:end].splitlines(keepends=True)
        done_batches = 0
        for i in range(0, len(lines), BATCH):
            if stop_after is not None and done_batches >= stop_after:
                return self.active
            chunk = lines[i : i + BATCH]
            batch_end = pos + sum(len(x) for x in chunk)
            with self.db.unit_of_work() as s:
                for raw in chunk:
                    rec = _parse(raw)
                    if rec is not None:
                        _upsert(s, to_row(rec))
                s.merge(
                    ImportState(
                        source=SOURCE, position=batch_end, prefix_sha256=hashlib.sha256(data[:batch_end]).hexdigest()
                    )
                )
            pos = batch_end
            done_batches += 1
        if end == 0:  # nothing in the file yet: record the empty prefix so the state exists
            with self.db.unit_of_work() as s:
                if s.get(ImportState, SOURCE) is None:
                    s.add(ImportState(source=SOURCE, position=0, prefix_sha256=hashlib.sha256(b"").hexdigest()))
        wanted = {import_key(r) for r in (_parse(x) for x in data[:end].splitlines()) if r is not None}
        with self.db.unit_of_work() as s:
            have = set(s.scalars(select(Job.import_key)))
            complete = wanted <= have
            if complete:
                state = s.get(ImportState, SOURCE)
                if state is not None:
                    state.verified_at = utc_now()
        if not complete:
            self.log(f"warning: {len(wanted - have)} jobs from jobs.jsonl are not in the database yet")
        self.active = complete or self.active
        return self.active

    def prune_completed(self, now: datetime.datetime | None = None) -> int:
        """Remove completed rows that ended more than RETENTION_DAYS ago. Never a running or interrupted row, and
        nothing of undo (that is in the file). Returns how many were removed."""
        if not self.active:
            return 0
        cutoff = (now or utc_now()) - datetime.timedelta(days=RETENTION_DAYS)
        with self.db.unit_of_work() as s:
            result = s.execute(delete(Job).where(Job.outcome.in_(COMPLETED), Job.ended_at < cutoff))
            return int(getattr(result, "rowcount", 0) or 0)


def _parse(raw: bytes) -> dict | None:
    try:
        rec = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return None  # an unreadable line is skipped, as the file reader does
    return rec if isinstance(rec, dict) else None


def _verified(db: Database) -> bool:
    try:
        with db.unit_of_work() as s:
            state = s.get(ImportState, SOURCE)
            return state is not None and state.verified_at is not None
    except Exception:
        return False
