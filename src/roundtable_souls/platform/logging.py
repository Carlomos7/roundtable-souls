"""Logging for the launcher, built on the standard logging module.

Where lines go:

    logs/launcher.log      everything worth keeping from any part of the launcher (INFO and up) and every crash with
                           its traceback; rotated at 2 MB, five older files kept
    logs/jobs/<when>_<what>.log
                           one file per job (Play, a repair, an install, a rebuild...), every line of that job
                           including DEBUG detail, with a header and a footer saying how it ended
    logs/jobs/<...>.<name>.log
                           a job's attachments: another program's own output (me3's launch output)
    logs/jobs.jsonl        one line per job start and end: what it was, when, how long, how it ended, its files
    the window             the running job's lines, and warnings and errors from anywhere

A job's file only gets lines logged while that job is the current one in the logging thread's context, so background
threads (update checks, the game watcher) never leak into it. Jobs and their files are kept for 14 days, or the newest
50, whichever keeps more.

Every path is worked out when it is used, from the launcher's data folder, so tests (which point that folder at a
temporary one) never write to the real logs. When the folder cannot be written, logging carries on without files.
"""

from __future__ import annotations

import atexit
import contextvars
import datetime
import itertools
import json
import logging
import logging.handlers
import os
import re
import shutil
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

LOGGER_NAME = "roundtable_souls"
APP_LOG = "launcher.log"
APP_LOG_BYTES = 2 * 1024 * 1024
APP_LOG_BACKUPS = 5
JOBS_DIR = "jobs"
JOBS_INDEX = "jobs.jsonl"
KEEP_JOBS = 50
KEEP_DAYS = 14
OLD_DIR = "old"  # files older launcher versions wrote, kept for a while
LEGACY_FILES = ("last_run.log", "me3_launch.log", "launcher-errors.log")
LINE_FORMAT = "%(asctime)s.%(msecs)03d  %(levelname)-7s  %(short)s  %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

OUTCOMES = ("running", "done", "warnings", "failed", "stopped", "interrupted")

_lock = threading.RLock()
_current: contextvars.ContextVar[Job | None] = contextvars.ContextVar("roundtable_job", default=None)
_app_handler: logging.Handler | None = None
_sink_handler: logging.Handler | None = None
_standalone: Job | None = None  # a job started outside run_job (the command line): closed at exit
_dir_override: Path | None = None
_serial = itertools.count(1)  # job ids stay unique within a process, however fast jobs follow each other


# ----------------------------------------------------------------------------- where
def log_dir() -> Path:
    """The logs folder in the launcher's data folder (worked out on each call)."""
    if _dir_override is not None:
        return _dir_override
    from roundtable_souls.platform import data_folder

    return data_folder.data_root() / "logs"


def get_logger(module: str | None = None) -> logging.Logger:
    if module and module.startswith(LOGGER_NAME):
        return logging.getLogger(module)
    return logging.getLogger(f"{LOGGER_NAME}.{module}" if module else LOGGER_NAME)


# The launcher's logger lets every level through to its handlers, which each keep what they want, whether or not
# setup_logging has run (tests, or code imported by another program).
logging.getLogger(LOGGER_NAME).setLevel(logging.DEBUG)


class _Short(logging.Filter):
    """record.short: the logger name without the package prefix (mods.rebuild, not roundtable_souls.mods.rebuild)."""

    def filter(self, record: logging.LogRecord) -> bool:
        name = record.name
        record.short = name[len(LOGGER_NAME) + 1 :] if name.startswith(LOGGER_NAME + ".") else name
        return True


def _formatter() -> logging.Formatter:
    return logging.Formatter(LINE_FORMAT, DATE_FORMAT)


class _SafeRotatingHandler(logging.handlers.RotatingFileHandler):
    """Rotation fails on Windows while another copy of the launcher has the file open; keep writing to the current
    file instead of printing a traceback for every line."""

    def doRollover(self) -> None:  # noqa: N802 - logging's name
        try:
            super().doRollover()
        except OSError:
            if self.stream is None:
                self.stream = self._open()

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802
        pass  # a full disk or a locked file must never break the launcher


def _file_handler(path: Path, level: int) -> logging.Handler | None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        h = logging.FileHandler(path, mode="a", encoding="utf-8", errors="backslashreplace", delay=False)
    except OSError:
        return None
    h.setLevel(level)
    h.setFormatter(_formatter())
    h.addFilter(_Short())
    h.handleError = lambda record: None  # type: ignore[method-assign]
    return h


# ----------------------------------------------------------------------------- setup
def setup_logging(level: str = "INFO", console: bool = True, directory: Path | None = None) -> logging.Logger:
    """Configure the launcher's logger: launcher.log (rotated) and, when there is one, the console. Safe to call
    again: earlier handlers are replaced. Moves the files older versions wrote into logs/old once."""
    global _app_handler, _dir_override
    if directory is not None:
        _dir_override = Path(directory)
    root = get_logger()
    root.setLevel(logging.DEBUG)  # handlers decide what they keep
    root.propagate = False
    for h in list(root.handlers):
        if h is not _sink_handler and not isinstance(h, _JobHandler):
            root.removeHandler(h)
            h.close()
    if console and sys.stderr is not None:  # a windowed exe has no console
        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(logging.WARNING)
        ch.setFormatter(_formatter())
        ch.addFilter(_Short())
        root.addHandler(ch)
    _app_handler = None
    try:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        _adopt_legacy(d)
        h = _SafeRotatingHandler(
            d / APP_LOG,
            maxBytes=APP_LOG_BYTES,
            backupCount=APP_LOG_BACKUPS,
            encoding="utf-8",
            errors="backslashreplace",
        )
        h.setLevel(getattr(logging, level.upper(), logging.INFO))
        h.setFormatter(_formatter())
        h.addFilter(_Short())
        root.addHandler(h)
        _app_handler = h
    except OSError:
        pass  # logs folder not writable: the window and the console still get every line
    return root


def shutdown() -> None:
    """Close the current standalone job and every file handler (so the files can be moved or deleted)."""
    global _app_handler, _standalone
    if _standalone is not None:
        end_job(_standalone)
        _standalone = None
    root = get_logger()
    for h in list(root.handlers):
        if h is not _sink_handler:
            root.removeHandler(h)
            h.close()
    _app_handler = None


atexit.register(shutdown)


def _adopt_legacy(d: Path) -> None:
    """Move the log files older versions kept at the top of logs/ into logs/old (dated), and drop old ones after
    30 days."""
    old = d / OLD_DIR
    for name in LEGACY_FILES:
        f = d / name
        if f.is_file():
            try:
                old.mkdir(exist_ok=True)
                stamp = datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y%m%d-%H%M%S")
                f.replace(old / f"{f.stem}.{stamp}{f.suffix}")
            except OSError:
                pass
    if old.is_dir():
        cutoff = time.time() - 30 * 86400
        for f in old.iterdir():
            try:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass


# ----------------------------------------------------------------------------- levels
_ERROR_WORDS = ("error", "traceback", "exception", "failed")
_WARNING_WORDS = ("warning", "warn:", "warn ")


def level_of(text: str) -> int:
    """The level a line written the old way means: 'error: ...' is an error, 'warning: ...' a warning."""
    low = str(text).lstrip().lower()
    if low.startswith(_ERROR_WORDS):
        return logging.ERROR
    if low.startswith(_WARNING_WORDS):
        return logging.WARNING
    return logging.INFO


def log_line(text: object = "", module: str | None = None, level: int | None = None) -> None:
    """One line, at the level its wording says unless given (see level_of), under module's logger."""
    msg = "" if text is None else str(text)
    get_logger(module).log(level if level is not None else level_of(msg), "%s", msg)


def log(msg=""):
    """One line for the current job's log (and the window), under the calling module's logger. Its level follows
    its wording: 'error: ...' is an error, 'warning: ...' a warning, anything else information."""
    caller = sys._getframe(1).f_globals.get("__name__", "")
    log_line(msg, caller or None)


def fail(msg, code=1):
    log_line(f"error: {msg}", sys._getframe(1).f_globals.get("__name__", "") or None)
    sys.exit(code)


# ----------------------------------------------------------------------------- jobs
@dataclass
class Job:
    id: str
    title: str
    kind: str
    started: float
    path: Path | None
    game: str = ""
    profile: str = ""
    warnings: int = 0
    errors: int = 0
    attachments: list[str] = field(default_factory=list)
    outcome: str = "running"
    ended: float | None = None
    kind_given: bool = False  # kind named by the caller, not guessed from the title
    summary: str = ""  # what it did, in a line: its last "done: ..." line, or set_summary()
    problem: str = ""  # its first error, in a line
    undo: dict | None = None  # how to take it back (see mods.undo), when it can be
    handler: logging.Handler | None = None


class _JobHandler(logging.Handler):
    """Writes the lines logged while its job is current in the logging context, and counts warnings and errors."""

    def __init__(self, job: Job, inner: logging.Handler | None):
        super().__init__(logging.DEBUG)
        self.job, self.inner = job, inner

    def emit(self, record: logging.LogRecord) -> None:
        if _current.get() is not self.job:
            return
        if record.levelno >= logging.ERROR:
            self.job.errors += 1
        elif record.levelno >= logging.WARNING:
            self.job.warnings += 1
        try:
            first = (record.getMessage().strip().splitlines() or [""])[0].strip()
        except Exception:  # noqa: BLE001 - a message that cannot be formatted still goes to the file below
            first = ""
        if first.lower().startswith("done:"):
            self.job.summary = first.split(":", 1)[1].strip()
        if record.levelno >= logging.ERROR and not self.job.problem and first:
            self.job.problem = re.sub(r"(?i)^(error|failed)\s*:?\s*", "", first) or first
        if self.inner is not None:
            self.inner.handle(record)

    def close(self) -> None:
        if self.inner is not None:
            self.inner.close()
        super().close()


_KIND_WORDS = (
    ("rebuild", "rebuild"),
    ("combin", "rebuild"),
    ("install mod", "install"),
    ("play", "play"),
    ("repair", "repair"),
    ("restore", "restore"),
    ("undo", "restore"),
    ("clear", "cleanup"),
    ("library", "library"),
    ("swap", "library"),
    ("copy", "copy"),
    ("apply", "settings"),
    ("check", "check"),
)


def kind_of(title: str) -> str:
    low = title.lower()
    return next((kind for word, kind in _KIND_WORDS if word in low), "task")


def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", text.lower()).strip("-")
    return s[:40] or "job"


def _clean_title(title: str) -> str:
    return re.sub(r"^launcher:\s*", "", str(title)).strip() or "Job"


def begin_job(title: str, kind: str | None = None, game: str = "", profile: str = "") -> Job:
    """Start a job: its own log file and an index record, current in this context. Returns the Job."""
    title = _clean_title(title)
    now = time.time()
    stamp = datetime.datetime.fromtimestamp(now).strftime("%Y-%m-%d_%H%M%S")
    jid = f"{stamp}-{os.getpid()}-{next(_serial)}"
    path = None
    try:
        jobs = log_dir() / JOBS_DIR
        jobs.mkdir(parents=True, exist_ok=True)
        path = jobs / f"{stamp}_{_slug(title)}.log"
        n = 2
        while path.exists():
            path = jobs / f"{stamp}_{_slug(title)}-{n}.log"
            n += 1
    except OSError:
        path = None
    job = Job(jid, title, kind or kind_of(title), now, path, game, profile, kind_given=kind is not None)
    inner = _file_handler(path, logging.DEBUG) if path is not None else None
    if inner is None:
        job.path = None
    job.handler = _JobHandler(job, inner)
    get_logger().addHandler(job.handler)
    _current.set(job)
    _write_index(job)
    get_logger("job").info("=== %s ===", title)
    return job


def current_job() -> Job | None:
    return _current.get()


def is_standalone(job: Job | None) -> bool:
    """A job the command line started for itself (not one the window's run_job opened)."""
    return job is not None and job is _standalone


def rename_job(title: str) -> None:
    """Give the current job its real name (a job started as "Installing x..." names itself when it begins)."""
    job = _current.get()
    if job is None:
        return
    new = _clean_title(title)
    if new != job.title:
        job.title = new
        if not job.kind_given:
            job.kind = kind_of(new)
        get_logger("job").info("=== %s ===", new)
        _write_index(job)


def end_job(job: Job | None = None, outcome: str | None = None) -> Job | None:
    """Finish a job: a footer line, its handler closed, the index updated, old jobs pruned. outcome defaults to
    done, or warnings when it logged any."""
    job = job or _current.get()
    if job is None or job.ended is not None:
        return job
    if outcome is None:
        outcome = "failed" if job.errors else "warnings" if job.warnings else "done"
    job.outcome = outcome
    job.ended = time.time()
    token_job = _current.get()
    if token_job is not job:
        _current.set(job)  # so the footer reaches the job's own file
    counts = [
        f"{n} {word}{'s' if n != 1 else ''}" for n, word in ((job.warnings, "warning"), (job.errors, "error")) if n
    ]
    get_logger("job").info(
        "=== %s: %s in %s%s ===",
        job.title,
        outcome,
        _duration(job.ended - job.started),
        (", " + ", ".join(counts)) if counts else "",
    )
    if job.handler is not None:
        get_logger().removeHandler(job.handler)
        job.handler.close()
        job.handler = None
    _current.set(token_job if token_job is not job else None)
    _write_index(job)
    prune()
    return job


def set_undo(data: dict | None) -> None:
    """How the current job can be taken back (Activity offers it while it still can be; see mods.undo)."""
    job = _current.get()
    if job is not None:
        job.undo = dict(data) if data else None
        _write_index(job)


def mark_undone(job_id: str) -> None:
    """A job was taken back (from Activity): its record no longer offers to, and says so."""
    with _lock:
        rec = next((r for r in read_jobs() if r.get("id") == job_id), None)
        if rec is None:
            return
        rec = {**rec, "undo": None, "undone": datetime.datetime.now().isoformat(timespec="seconds")}
        try:
            with (log_dir() / JOBS_INDEX).open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass


def set_summary(text: str) -> None:
    """What the current job did, in a line, for the Activity page (otherwise its last "done: ..." line)."""
    job = _current.get()
    if job is not None:
        job.summary = str(text).strip()


def attachment(name: str) -> Path | None:
    """A file for another program's output that belongs to the current job (logs/jobs/<job>.<name>.log), or None
    without a job or a writable logs folder."""
    job = _current.get()
    if job is None or job.path is None:
        return None
    p = job.path.with_name(f"{job.path.stem}.{_slug(name)}.log")
    if p.name not in job.attachments:
        job.attachments.append(p.name)
        _write_index(job)
    return p


def _duration(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600}h {s % 3600 // 60}m" if s >= 3600 else f"{s // 60}m {s % 60}s" if s >= 60 else f"{s}s"


def _record(job: Job) -> dict:
    return {
        "id": job.id,
        "title": job.title,
        "kind": job.kind,
        "game": job.game,
        "profile": job.profile,
        "start": datetime.datetime.fromtimestamp(job.started).isoformat(timespec="seconds"),
        "t": round(job.started, 6),  # exact start, for ordering jobs within one second
        "end": datetime.datetime.fromtimestamp(job.ended).isoformat(timespec="seconds") if job.ended else None,
        "seconds": round(job.ended - job.started, 1) if job.ended else None,
        "outcome": job.outcome,
        "warnings": job.warnings,
        "errors": job.errors,
        "log": job.path.name if job.path else None,
        "attachments": list(job.attachments),
        "summary": job.summary,
        "problem": job.problem,
        "undo": job.undo,
        "pid": os.getpid(),
    }


def _write_index(job: Job) -> None:
    with _lock:
        try:
            d = log_dir()
            d.mkdir(parents=True, exist_ok=True)
            with (d / JOBS_INDEX).open("a", encoding="utf-8") as f:
                f.write(json.dumps(_record(job), ensure_ascii=False) + "\n")
        except OSError:
            pass


def _pid_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    try:
        import psutil  # type: ignore[import-not-found]

        return psutil.pid_exists(pid)
    except Exception:
        pass
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_jobs() -> list[dict]:
    """Every job the index knows, newest first, one record each (its last state). A job still marked running by a
    launcher that is no longer running is reported as interrupted. Unreadable lines are skipped."""
    with _lock:
        try:
            lines = (log_dir() / JOBS_INDEX).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
    by_id: dict[str, dict] = {}
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("id"):
            by_id[rec["id"]] = rec
    out = list(by_id.values())
    alive: dict[int, bool] = {}
    for rec in out:
        if rec.get("outcome") == "running":
            pid = int(rec.get("pid") or 0)
            if pid not in alive:
                alive[pid] = _pid_alive(pid)
            if not alive[pid]:
                rec["outcome"] = "interrupted"
    out.sort(key=lambda r: (r.get("start") or "", r.get("t") or 0), reverse=True)
    return out


def recent_jobs(limit: int = 50) -> list[dict]:
    return read_jobs()[:limit]


def prune(keep: int = KEEP_JOBS, days: int = KEEP_DAYS, now: float | None = None) -> list[str]:
    """Drop jobs beyond the newest `keep` that are also older than `days`, with their files; rewrite the index with
    one line per kept job; remove job files the index no longer knows once they are that old too. Returns the ids
    dropped. Never touches a running job."""
    now = time.time() if now is None else now
    cutoff = now - days * 86400
    with _lock:
        jobs = read_jobs()
        keep_ids, drop = set(), []
        for i, rec in enumerate(jobs):
            try:
                started = datetime.datetime.fromisoformat(rec["start"]).timestamp()
            except KeyError, TypeError, ValueError:
                started = 0
            if i < keep or started >= cutoff or rec.get("outcome") == "running":
                keep_ids.add(rec["id"])
            else:
                drop.append(rec)
        d = log_dir()
        jdir = d / JOBS_DIR
        kept_files = set()
        for rec in jobs:
            if rec["id"] in keep_ids:
                kept_files.update(x for x in [rec.get("log"), *(rec.get("attachments") or [])] if x)
        for rec in drop:
            for name in [rec.get("log"), *(rec.get("attachments") or [])]:
                if name:
                    try:
                        (jdir / name).unlink(missing_ok=True)
                    except OSError:
                        pass
        if jdir.is_dir():
            for f in jdir.iterdir():
                try:
                    if f.is_file() and f.name not in kept_files and f.stat().st_mtime < cutoff:
                        f.unlink()
                except OSError:
                    pass
        if drop or len(jobs) != sum(1 for _ in _index_lines(d)):
            kept = [r for r in reversed(jobs) if r["id"] in keep_ids]
            try:
                tmp = d / (JOBS_INDEX + ".tmp")
                tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept), encoding="utf-8")
                tmp.replace(d / JOBS_INDEX)
            except OSError:
                pass
        return [r["id"] for r in drop]


def _index_lines(d: Path):
    try:
        with (d / JOBS_INDEX).open(encoding="utf-8", errors="replace") as f:
            yield from f
    except OSError:
        return


# ----------------------------------------------------------------------------- reading jobs back
KIND_GROUPS = {
    "play": "Play",
    "cleanup": "Play",
    "repair": "Saves",
    "restore": "Saves",
    "library": "Saves",
    "copy": "Saves",
    "install": "Mods",
    "rebuild": "Mods",
}
GROUPS = ("Play", "Saves", "Mods", "Other")
_LINE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)(?:\.(\d{3}))?  (DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+(\S+)  (.*)$"
)
READ_LIMIT = 2 * 1024 * 1024  # a job log or attachment is shown from its last 2 MB


def group_of(kind: str) -> str:
    return KIND_GROUPS.get(kind, "Other")


def job_file(name: str) -> Path | None:
    """A file in logs/jobs by its bare name (as the index lists it), or None for anything else."""
    if not name or Path(name).name != name or name in (".", ".."):
        return None
    return log_dir() / JOBS_DIR / name


def _tail(path: Path, limit: int) -> tuple[str, bool]:
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - limit))
        data = f.read()
    text = data.decode("utf-8", errors="replace")
    if size > limit:
        text = text.split("\n", 1)[-1]  # drop the partial first line
    return text, size > limit


def read_job_log(name: str, limit: int = READ_LIMIT) -> dict:
    """A job's log as entries {time, level, source, text} (lines that continue an entry, such as a traceback, are
    part of its text). {entries, cut (only the end was read), missing}."""
    path = job_file(name)
    if path is None or not path.is_file():
        return {"entries": [], "cut": False, "missing": True}
    try:
        text, cut = _tail(path, limit)
    except OSError:
        return {"entries": [], "cut": False, "missing": True}
    entries: list[dict] = []
    for line in text.splitlines():
        m = _LINE.match(line)
        if m:
            entries.append(
                {
                    "time": m.group(1)[11:] + (f".{m.group(2)}" if m.group(2) else ""),
                    "level": m.group(3).lower().replace("critical", "error"),
                    "source": m.group(4),
                    "text": m.group(5),
                }
            )
        elif entries:
            entries[-1]["text"] += "\n" + line
        elif line.strip():
            entries.append({"time": "", "level": "info", "source": "", "text": line})
    return {"entries": entries, "cut": cut, "missing": False}


def read_attachment(name: str, limit: int = READ_LIMIT) -> dict:
    """Another program's output kept with a job: {text, cut, missing}."""
    path = job_file(name)
    if path is None or not path.is_file():
        return {"text": "", "cut": False, "missing": True}
    try:
        text, cut = _tail(path, limit)
    except OSError:
        return {"text": "", "cut": False, "missing": True}
    return {"text": text, "cut": cut, "missing": False}


def unseen_failures(since: float) -> list[dict]:
    """Jobs that failed or were interrupted after `since` (a time; what the Activity page last showed)."""
    return [r for r in read_jobs() if r.get("outcome") in ("failed", "interrupted") and float(r.get("t") or 0) > since]


# ----------------------------------------------------------------------------- the command line
def start_standalone(title: str, game: str = "") -> Job:
    """A job for the command line (--play, --check): the previous one ends, this one ends at exit."""
    global _standalone
    if _standalone is not None:
        end_job(_standalone)
    _standalone = begin_job(title, game=game)
    return _standalone


def start_log(title: str, game: str) -> None:
    """Name the job that is running (the window starts each job as one), or, outside the window (--play, --check),
    start a job of its own for game (its key) that ends at exit."""
    job = current_job()
    if job is not None and not is_standalone(job):
        rename_job(title)
    else:
        start_standalone(title, game=game)


# ----------------------------------------------------------------------------- the window
class _SinkHandler(logging.Handler):
    """Lines for the window: the current job's, and warnings and errors from anywhere."""

    def __init__(self, sink: Callable[[str, str], None]) -> None:
        super().__init__(logging.INFO)
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "shown", False):
            return  # the window wrote it itself (see log_shown)
        if _current.get() is None and record.levelno < logging.WARNING:
            return
        level = (
            "error" if record.levelno >= logging.ERROR else "warning" if record.levelno >= logging.WARNING else "info"
        )
        try:
            text = record.getMessage()
            if record.exc_info:
                text += "\n" + logging.Formatter().formatException(record.exc_info)
            self.sink(text, level)
        except Exception:  # noqa: BLE001 - a broken sink must never stop a job
            pass


def attach_sink(sink: Callable[[str, str], None]) -> None:
    """Send lines to a callable (message, level) as well: the window's log pane. Replaces any earlier sink."""
    global _sink_handler
    root = get_logger()
    if _sink_handler is not None:
        root.removeHandler(_sink_handler)
    _sink_handler = _SinkHandler(sink)
    root.addHandler(_sink_handler)


def detach_sink() -> None:
    global _sink_handler
    if _sink_handler is not None:
        get_logger().removeHandler(_sink_handler)
        _sink_handler = None


def log_shown(text: object, module: str = "ui") -> None:
    """A line the window has already shown in its pane (a change made in the window itself): kept in the logs
    without being sent back to the pane."""
    msg = "" if text is None else str(text)
    get_logger(module).log(level_of(msg), "%s", msg, extra={"shown": True})


# ----------------------------------------------------------------------------- crashes
def log_crash(exc_type, exc, tb, where: str = "launcher") -> None:
    """An uncaught error: to launcher.log (and the current job's file) with its traceback."""
    get_logger("crash").critical("uncaught error in %s: %s", where, exc, exc_info=(exc_type, exc, tb))


# ----------------------------------------------------------------------------- sharing
_STEAM_ID = re.compile(r"\b7656119\d{10}\b")
_USERS = re.compile(r"(?i)([A-Z]:[\\/]+Users[\\/]+)([^\\/\s\"']+)")
_HOME_LINUX = re.compile(r"(/home/)([^/\s\"']+)")


def redact(text: str) -> str:
    """The same text with this PC's user name and Steam IDs masked, for sharing a log."""
    out = _STEAM_ID.sub("<steam id>", text)
    out = _USERS.sub(lambda m: m.group(1) + "<user>", out)
    out = _HOME_LINUX.sub(lambda m: m.group(1) + "<user>", out)
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    if len(user) >= 3:
        out = re.sub(rf"(?i)\b{re.escape(user)}\b", "<user>", out)
    return out


def copy_logs(dest: Path) -> Path:
    """Copy the logs folder (redacted) to dest, for attaching to a report. Returns the folder written."""
    src = log_dir()
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for f in src.rglob("*"):
        if f.is_file() and (f.suffix in (".log", ".jsonl") or f.name.startswith(APP_LOG)):
            target = dest / f.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                target.write_text(redact(f.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
            except OSError:
                shutil.copy2(f, target)
    return dest
