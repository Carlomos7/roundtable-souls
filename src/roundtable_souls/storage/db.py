"""Opening the launcher's database (roundtable.db in the data folder).

open_database() is the only way in:

1. The SQLite library Python carries is checked against MIN_SQLITE (the storage decision record says why that
   version); below it, storage is refused for the run (StorageUnavailable) and the launcher runs on without it.
2. roundtable.db.lock beside the database is held shared by every process that has the database open, and
   exclusively by a migration. A migration therefore waits for the others to close; after a bounded wait it is
   postponed (StorageUnavailable, the launcher runs on without storage) rather than blocking start-up.
3. Before an existing database is upgraded, a consistent snapshot is taken with SQLite's backup API (never a file
   copy, which can catch a WAL database mid-write): roundtable.db.<revision>.<time>.snapshot in the data folder, the
   newest KEEP_SNAPSHOTS kept. When the upgrade fails, every connection is closed and, still under the exclusive
   lock, the snapshot is restored if it passes PRAGMA integrity_check (otherwise it is kept for diagnosis and the
   database left as found); a database that did not exist before is removed. Then MigrationFailed is raised: the
   launcher must not report itself ready, so an update's watchdog rolls back to the version that worked.
4. WAL is set once, when the schema is created or upgraded, and the mode SQLite actually set is checked and
   reported. A database whose schema is newer than this build knows (a later version ran, then was rolled back) is
   left untouched and storage is refused.

Which failures roll an update back. Only MigrationFailed stops start-up (no ready report, so the update watchdog puts
the previous version back): this version's own migration code failed, and the previous version, which never ran
it, is the remedy. Everything else is StorageUnavailable (its .reason says which) and the launcher runs normally
without storage, because a rollback would not help and would only repeat at the next update:
  "old-sqlite"    the SQLite in this Python is below MIN_SQLITE
  "busy"          another process has the database open while it needs upgrading, or is upgrading it (contention)
  "newer-schema"  a later version upgraded it
  "damaged"       the file exists but is not a readable SQLite database; it is left untouched
  "environment"   the filesystem refused (no space, read-only, locked by another program, cannot open or create);
                  an upgrade interrupted this way is restored first, as for MigrationFailed
Without storage, the hash cache is bypassed (files are hashed every time) and activity records go to their old
file, logs/jobs.jsonl, from which a later run with storage imports them: nothing is lost and nothing claims to be in
the database.

Connections: a bounded busy_timeout, foreign_keys on, synchronous FULL, and write transactions started with BEGIN
IMMEDIATE (a writer waits at the start instead of failing at commit). Database.unit_of_work() is one short unit of
work: one session, committed once when the block ends (rolled back on an error); never held across long file work.
"""

from __future__ import annotations

import contextlib
import datetime
import sqlite3
import weakref
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from roundtable_souls.platform import logging as run_logging
from roundtable_souls.platform.filelock import ReadWriteLock
from roundtable_souls.resources import MIGRATIONS_DIR

# migrations/env.py imports models by name at run time; importing it here is what puts it in a packaged build (the
# migration scripts are loaded by path, so the bundler never sees their imports).
from roundtable_souls.storage import models  # noqa: F401

DB_NAME = "roundtable.db"
LOCK_NAME = DB_NAME + ".lock"
MIN_SQLITE = (3, 51, 3)  # docs/decisions/0005-storage.md: the WAL-reset corruption fix
BUSY_TIMEOUT_MS = 5000
LOCK_WAIT = 10.0  # seconds to wait for the database lock at start-up
SYNCHRONOUS = "FULL"
KEEP_SNAPSHOTS = 3
SIDE_FILES = ("-wal", "-shm", "-journal")


class StorageError(Exception):
    pass


class StorageUnavailable(StorageError):
    """Storage is off for this run; the launcher runs on without it (the module docstring lists the reasons).
    Nothing was changed, or an interrupted upgrade was put back first."""

    def __init__(self, message: str, reason: str = "busy"):
        super().__init__(message)
        self.reason = reason


class MigrationFailed(StorageError):
    """The schema upgrade failed (the database was restored or left as found, as the message says). The launcher
    must not report itself ready."""


def sqlite_problem(version: str | None = None) -> str | None:
    """Why this SQLite can't be used, or None."""
    version = version or sqlite3.sqlite_version
    try:
        found = tuple(int(x) for x in version.split(".")[:3])
    except ValueError:
        return f"SQLite {version} can't be checked"
    if found < MIN_SQLITE:
        need = ".".join(map(str, MIN_SQLITE))
        return f"SQLite {version} is older than {need}, which the launcher's database needs; storage is off"
    return None


# ----------------------------------------------------------------------------- migrations
def alembic_config(connection=None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def head_revision() -> str:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    if head is None:
        raise StorageError(f"no migrations found in {MIGRATIONS_DIR}")
    return head


def known_revisions() -> set[str]:
    return {s.revision for s in ScriptDirectory.from_config(alembic_config()).walk_revisions()}


_ENVIRONMENT = ("locked", "busy", "disk i/o", "unable to open", "readonly", "read-only", "full", "permission")


def _environmental(error: BaseException) -> bool:
    """Whether a failure came from the filesystem or another program, not from the migration code itself."""
    todo: list[BaseException] = [error]
    visited: set[int] = set()
    while todo:
        seen = todo.pop()
        if id(seen) in visited:
            continue
        visited.add(id(seen))
        if isinstance(seen, OSError) and not isinstance(seen, sqlite3.Error):
            return True
        if isinstance(seen, sqlite3.OperationalError) and any(w in str(seen).lower() for w in _ENVIRONMENT):
            return True
        todo += [
            e for e in (getattr(seen, "orig", None), seen.__cause__, seen.__context__) if isinstance(e, BaseException)
        ]
    return False


def read_revision(path: Path) -> str | None:
    """The schema revision a database file is at (read-only, without creating it); None when there is none yet.
    Raises StorageUnavailable ("damaged" or "environment") when the file can't be read as a database."""
    if not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        try:
            query = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'"
            if not conn.execute(query).fetchone():
                return None
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
            return row[0] if row else None
        finally:
            conn.close()
    except sqlite3.Error as e:
        if _environmental(e):
            raise StorageUnavailable(
                f"The database can't be read now ({e}); storage is off for this run", "environment"
            ) from e
        raise StorageUnavailable(
            f"{path} is not a readable database ({e}). It was left as it is and storage is off; moving it aside "
            "lets Roundtable Souls start a new one",
            "damaged",
        ) from e


def _snapshot(path: Path, revision: str | None) -> Path:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    out = path.with_name(f"{path.name}.{revision or 'none'}.{stamp}.snapshot")
    src, dst = sqlite3.connect(path), sqlite3.connect(out)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    old = sorted(path.parent.glob(f"{path.name}.*.snapshot"), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in old[KEEP_SNAPSHOTS:]:
        with contextlib.suppress(OSError):
            stale.unlink()
    return out


def _intact(path: Path) -> bool:
    try:
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        try:
            return conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def _recover(path: Path, snapshot: Path | None) -> str:
    """After a failed upgrade, with every connection closed and the exclusive lock held: what was done."""
    if snapshot is None:  # created by this upgrade: remove what it left
        for p in [path, *(path.with_name(path.name + s) for s in SIDE_FILES)]:
            with contextlib.suppress(FileNotFoundError):
                p.unlink()
        return "the new database was removed"
    if not _intact(snapshot):
        return f"the snapshot {snapshot.name} failed its integrity check; it was kept and the database left as found"
    src, dst = sqlite3.connect(snapshot), sqlite3.connect(path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return f"the database was restored from {snapshot.name}"


def _set_wal(path: Path) -> str:
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        return str(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
    finally:
        conn.close()


def _migrate(path: Path, log: Callable[[str], None]) -> str:
    """Bring the database to the head revision (under the exclusive lock). Returns the journal mode set."""
    before = read_revision(path)
    existed = path.is_file() and path.stat().st_size > 0
    snapshot = _snapshot(path, before) if existed else None
    engine = make_engine(path, pooled=False)
    try:
        with engine.begin() as conn:
            command.upgrade(alembic_config(conn), "head")
    except Exception as e:
        engine.dispose()
        outcome = _recover(path, snapshot)
        log(f"error: the database upgrade from {before or 'nothing'} failed ({e}); {outcome}")
        if _environmental(e):  # the disk or another program, not this version: a rollback would not help
            raise StorageUnavailable(
                f"The database upgrade was stopped by the system ({e}); {outcome}; storage is off for this run",
                "environment",
            ) from e
        raise MigrationFailed(f"The database upgrade failed ({e}); {outcome}.") from e
    engine.dispose()
    log(f"storage: database {'upgraded from ' + before if before else 'created'} at {head_revision()}")
    mode = _set_wal(path)
    if mode != "wal":
        log(f"warning: the database could not use WAL (journal mode {mode}); it works, with less concurrency")
    return mode


# ----------------------------------------------------------------------------- connections
def make_engine(path: Path, pooled: bool = True) -> Engine:
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"timeout": BUSY_TIMEOUT_MS / 1000, "check_same_thread": False},
        **({} if pooled else {"poolclass": NullPool}),
    )

    @event.listens_for(engine, "connect")
    def _connected(dbapi_connection, _record):
        dbapi_connection.isolation_level = None  # transactions start in _begin below, not in the sqlite3 module
        cur = dbapi_connection.cursor()
        cur.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        cur.execute("PRAGMA foreign_keys = ON")
        cur.execute(f"PRAGMA synchronous = {SYNCHRONOUS}")
        cur.close()

    @event.listens_for(engine, "begin")
    def _begin(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


@dataclass
class Database:
    path: Path
    engine: Engine
    revision: str
    journal_mode: str
    lock: ReadWriteLock
    sessions: sessionmaker[Session] = field(init=False)

    def __post_init__(self):
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self._finalizer = weakref.finalize(self, _close, self.engine, self.lock)

    @contextlib.contextmanager
    def unit_of_work(self) -> Iterator[Session]:
        """One short unit of work: committed once when the block ends, rolled back if it raises."""
        with self.sessions() as session, session.begin():
            yield session

    def close(self) -> None:
        """Close every connection and let go of the lock (a waiting migration may then run)."""
        self._finalizer()


def _close(engine: Engine, lock: ReadWriteLock) -> None:
    engine.dispose()
    lock.release()


def open_database(data_dir: Path, wait: float = LOCK_WAIT, log: Callable[[str], None] = run_logging.log) -> Database:
    """The database in data_dir at the current schema, held open (shared) until close(). Raises StorageUnavailable
    (storage off for this run, nothing changed) or MigrationFailed (see the module docstring)."""
    problem = sqlite_problem()
    if problem:
        raise StorageUnavailable(problem, "old-sqlite")
    path = Path(data_dir) / DB_NAME
    head, known = head_revision(), known_revisions()
    lock = ReadWriteLock(path.with_name(LOCK_NAME))

    def refuse_newer(rev: str | None) -> None:
        if rev is not None and rev not in known:
            raise StorageUnavailable(
                f"The database is at schema {rev}, newer than this version of Roundtable Souls knows; it was left "
                "as it is and storage is off for this run",
                "newer-schema",
            )

    def take(exclusive: bool) -> bool:
        try:
            return lock.acquire(exclusive, wait)
        except OSError as e:
            raise StorageUnavailable(f"The database lock can't be used ({e}); storage is off", "environment") from e

    current = read_revision(path)
    refuse_newer(current)
    if current != head:
        if not take(True):
            raise StorageUnavailable(
                "Other Roundtable Souls windows or Plays have the database open, so its update for this version "
                "waits until they close; storage is off for this run",
                "busy",
            )
        try:
            current = read_revision(path)  # another process may have done it meanwhile
            refuse_newer(current)
            if current != head:
                _migrate(path, log)
        finally:
            lock.release()
    if not take(False):
        raise StorageUnavailable(
            "Another Roundtable Souls is updating the database; storage is off for this run", "busy"
        )
    try:
        current = read_revision(path)
        refuse_newer(current)
        if current != head:
            raise StorageUnavailable("The database changed while it was opened; storage is off for this run", "busy")
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)  # a read: no write transaction for it
        try:
            mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        finally:
            conn.close()
        engine = make_engine(path)
        if mode != "wal":
            log(f"warning: the database is in journal mode {mode}, not WAL")
        return Database(path, engine, head, mode, lock)
    except BaseException:
        lock.release()
        raise
