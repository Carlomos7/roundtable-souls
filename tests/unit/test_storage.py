"""The launcher's database (storage/): created fresh, upgraded with a snapshot first, put back when an upgrade fails,
coordinated across processes, never touched when its schema is newer than the build, and refused on an old SQLite.
Every test uses a real SQLite file in its own temporary folder."""

import datetime
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import textwrap
import time

import pytest

from roundtable_souls.platform.filelock import ReadWriteLock
from roundtable_souls.storage import db, models

HEAD = db.head_revision()  # the newest real revision; test revisions (9xxx) are added after it

needs_sqlite = pytest.mark.skipif(
    db.sqlite_problem() is not None, reason=f"this Python's SQLite is too old for storage: {db.sqlite_problem()}"
)

HOLDER = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    from roundtable_souls.platform.filelock import ReadWriteLock
    from roundtable_souls.storage import db

    folder, mode = Path(sys.argv[1]), sys.argv[2]
    if mode == "open":
        held = db.open_database(folder, log=lambda line: None)
    else:  # a migration in progress elsewhere
        held = ReadWriteLock(folder / db.LOCK_NAME)
        assert held.acquire(True, 5)
    print("held", flush=True)
    sys.stdin.read()
    """
)


def _hold(folder, mode):
    proc = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(folder), mode], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    assert proc.stdout is not None and proc.stdout.readline().strip() == "held"
    return proc


def _let_go(proc):
    assert proc.stdin is not None
    proc.stdin.close()
    proc.wait(10)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def lines():
    return []


@pytest.fixture
def migrations(tmp_path, monkeypatch):
    """A copy of the migrations this test may add revisions to."""
    copy = tmp_path / "migrations"
    shutil.copytree(db.MIGRATIONS_DIR, copy, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(db, "MIGRATIONS_DIR", copy)

    def add(body: str, revision="9001", down: str | None = None):
        down = down or HEAD
        (copy / "versions" / f"{revision}_test.py").write_text(
            "import sqlalchemy as sa\nfrom alembic import op\n\n"
            f"revision = {revision!r}\ndown_revision = {down!r}\nbranch_labels = None\ndepends_on = None\n\n\n"
            "def upgrade():\n" + textwrap.indent(textwrap.dedent(body).strip(), "    ") + "\n\n\n"
            "def downgrade():\n    pass\n",
            encoding="utf-8",
        )

    return add


def _a_run(database):
    with database.unit_of_work() as s:
        s.add(models.RebuildRun(import_key="p@1", profile="p", ran_at=models.utc_now(), ok=True, message="kept"))


def _runs(path):
    conn = sqlite3.connect(path)
    try:
        return [r[0] for r in conn.execute("SELECT message FROM rebuild_runs")]
    finally:
        conn.close()


# ----------------------------------------------------------------------------- creation and connections
@needs_sqlite
def test_a_fresh_database_is_created_at_the_current_schema_in_wal(tmp_path, lines):
    database = db.open_database(tmp_path, log=lines.append)
    try:
        assert database.revision == HEAD and database.journal_mode == "wal"
        assert db.read_revision(tmp_path / db.DB_NAME) == HEAD
        conn = sqlite3.connect(tmp_path / db.DB_NAME)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        conn.close()
        assert tables == {"alembic_version", "file_hashes", "jobs", "rebuild_runs", "import_state"}
        assert not list(tmp_path.glob("*.snapshot"))  # nothing to snapshot before the first schema
        with database.engine.connect() as c:
            assert c.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            assert c.exec_driver_sql("PRAGMA synchronous").scalar() == 2  # FULL
            assert c.exec_driver_sql("PRAGMA busy_timeout").scalar() == db.BUSY_TIMEOUT_MS
        assert any(f"created at {HEAD}" in line for line in lines)
    finally:
        database.close()


@needs_sqlite
def test_a_unit_of_work_writes_with_begin_immediate_and_commits_once(tmp_path):
    database = db.open_database(tmp_path, log=lambda line: None)
    try:
        other = sqlite3.connect(tmp_path / db.DB_NAME, timeout=0, isolation_level=None)
        with database.unit_of_work() as s:
            s.add(models.RebuildRun(import_key="a", profile="p", ran_at=models.utc_now(), ok=True, message=""))
            s.flush()
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("BEGIN IMMEDIATE")  # the unit of work holds the write lock from its start
        other.close()
        with pytest.raises(RuntimeError), database.unit_of_work() as s:
            s.add(models.RebuildRun(import_key="b", profile="p", ran_at=models.utc_now(), ok=True, message=""))
            raise RuntimeError("the job failed")
        with database.unit_of_work() as s:
            assert [r.import_key for r in s.query(models.RebuildRun)] == ["a"]  # rolled back, not half-written
    finally:
        database.close()


def test_times_are_utc_milliseconds_and_naive_ones_are_refused():
    from sqlalchemy.dialects import sqlite as sqlite_dialect

    t, dialect = models.UtcMillis(), sqlite_dialect.dialect()
    when = datetime.datetime(2026, 10, 5, 22, 30, 1, 123456, tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
    stored = t.process_bind_param(when, dialect)
    assert stored == 1791232201123  # 20:30:01.123 UTC
    back = t.process_result_value(stored, dialect)
    assert back is not None and back == when.replace(microsecond=123000) and back.tzinfo == datetime.UTC
    with pytest.raises(ValueError, match="timezone-aware"):
        t.process_bind_param(datetime.datetime(2026, 10, 5), dialect)


# ----------------------------------------------------------------------------- upgrades
@needs_sqlite
def test_an_upgrade_takes_a_consistent_snapshot_first_and_keeps_the_data(tmp_path, migrations, lines):
    first = db.open_database(tmp_path, log=lines.append)
    _a_run(first)
    first.close()
    migrations("op.add_column('rebuild_runs', sa.Column('note', sa.Text(), nullable=True))")
    second = db.open_database(tmp_path, log=lines.append)
    try:
        assert second.revision == "9001" and _runs(tmp_path / db.DB_NAME) == ["kept"]
        snaps = list(tmp_path.glob(f"{db.DB_NAME}.{HEAD}.*.snapshot"))
        assert len(snaps) == 1 and db.read_revision(snaps[0]) == HEAD and _runs(snaps[0]) == ["kept"]
        assert any(f"upgraded from {HEAD}" in line for line in lines)
    finally:
        second.close()


@needs_sqlite
def test_only_the_newest_snapshots_are_kept(tmp_path, migrations):
    db.open_database(tmp_path, log=lambda line: None).close()
    for n in range(2, 7):
        migrations(
            f"op.create_table('t{n}', sa.Column('id', sa.Integer(), primary_key=True))",
            f"90{n:02d}",
            HEAD if n == 2 else f"90{n - 1:02d}",
        )
        db.open_database(tmp_path, log=lambda line: None).close()
        time.sleep(0.02)
    names = sorted(p.name.split(".")[2] for p in tmp_path.glob("*.snapshot"))
    assert names == ["9003", "9004", "9005"]  # the revisions the last three upgrades started from


@needs_sqlite
def test_a_failed_upgrade_restores_the_snapshot_and_raises(tmp_path, migrations, lines):
    first = db.open_database(tmp_path, log=lines.append)
    _a_run(first)
    first.close()
    migrations(
        """
        op.execute("DELETE FROM rebuild_runs")
        op.create_table('half', sa.Column('id', sa.Integer(), primary_key=True))
        raise RuntimeError("a broken migration")
        """
    )
    with pytest.raises(db.MigrationFailed, match="restored from"):
        db.open_database(tmp_path, log=lines.append)
    path = tmp_path / db.DB_NAME
    assert db.read_revision(path) == HEAD and _runs(path) == ["kept"]
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'half'").fetchone()
    conn.close()
    assert any(f"upgrade from {HEAD} failed" in line for line in lines)


@needs_sqlite
def test_a_snapshot_that_fails_its_check_is_kept_and_the_database_left_as_found(tmp_path, migrations, monkeypatch):
    db.open_database(tmp_path, log=lambda line: None).close()
    migrations("raise RuntimeError('a broken migration')")
    monkeypatch.setattr(db, "_intact", lambda path: False)
    restores = []
    monkeypatch.setattr(db, "_recover", lambda path, snap, real=db._recover: restores.append(snap) or real(path, snap))
    with pytest.raises(db.MigrationFailed, match="left as found"):
        db.open_database(tmp_path, log=lambda line: None)
    assert len(restores) == 1 and restores[0].is_file()  # the snapshot that failed its check is kept
    assert db.read_revision(tmp_path / db.DB_NAME) == HEAD


@needs_sqlite
def test_a_failed_first_creation_leaves_no_database(tmp_path, migrations):
    (db.MIGRATIONS_DIR / "versions" / "0001_first_schema.py").write_text(
        "revision = '0001'\ndown_revision = None\nbranch_labels = None\ndepends_on = None\n\n\n"
        "def upgrade():\n    raise RuntimeError('broken')\n\n\ndef downgrade():\n    pass\n",
        encoding="utf-8",
    )
    with pytest.raises(db.MigrationFailed, match="new database was removed"):
        db.open_database(tmp_path, log=lambda line: None)
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(db.DB_NAME) and p.name != db.LOCK_NAME]


# ----------------------------------------------------------------------------- other processes
@needs_sqlite
def test_an_upgrade_waits_for_other_processes_and_is_postponed_while_they_hold_the_database(tmp_path, migrations):
    db.open_database(tmp_path, log=lambda line: None).close()
    before = _sha(tmp_path / db.DB_NAME)
    other = _hold(tmp_path, "open")  # another window with the database open, at the current schema
    try:
        migrations("op.create_table('later', sa.Column('id', sa.Integer(), primary_key=True))")
        with pytest.raises(db.StorageUnavailable, match="waits until they close") as busy:
            db.open_database(tmp_path, wait=0.3, log=lambda line: None)
        assert busy.value.reason == "busy"  # contention: normal operation, never a rollback
        assert db.read_revision(tmp_path / db.DB_NAME) == HEAD and not list(tmp_path.glob("*.snapshot"))
        assert _sha(tmp_path / db.DB_NAME) == before  # postponed: nothing was written
    finally:
        _let_go(other)
    upgraded = db.open_database(tmp_path, wait=0.3, log=lambda line: None)  # they closed: it runs now
    assert upgraded.revision == "9001"
    upgraded.close()


@needs_sqlite
def test_a_second_process_opens_a_current_database_without_waiting(tmp_path):
    db.open_database(tmp_path, log=lambda line: None).close()
    other = _hold(tmp_path, "open")
    try:
        started = time.monotonic()
        mine = db.open_database(tmp_path, wait=5, log=lambda line: None)
        assert time.monotonic() - started < 2 and mine.revision == HEAD  # shared with the other, no upgrade wait
        mine.close()
    finally:
        _let_go(other)


@needs_sqlite
def test_nothing_opens_the_database_while_another_process_migrates(tmp_path):
    db.open_database(tmp_path, log=lambda line: None).close()
    migrating = _hold(tmp_path, "exclusive")
    try:
        with pytest.raises(db.StorageUnavailable, match="updating the database") as busy:
            db.open_database(tmp_path, wait=0.3, log=lambda line: None)
        assert busy.value.reason == "busy"
    finally:
        _let_go(migrating)


@needs_sqlite
def test_the_shared_lock_is_let_go_on_close_and_when_a_holder_dies(tmp_path):
    database = db.open_database(tmp_path, log=lambda line: None)
    probe = ReadWriteLock(tmp_path / db.LOCK_NAME)
    assert not probe.acquire(True, 0.1)
    database.close()
    assert probe.acquire(True, 0.1)
    probe.release()
    other = _hold(tmp_path, "open")
    other.kill()
    other.wait(10)
    assert probe.acquire(True, 2)
    probe.release()


# ----------------------------------------------------------------------------- versions
@needs_sqlite
def test_a_newer_schema_than_this_build_knows_is_left_untouched(tmp_path):
    db.open_database(tmp_path, log=lambda line: None).close()
    path = tmp_path / db.DB_NAME
    conn = sqlite3.connect(path)
    conn.execute("UPDATE alembic_version SET version_num = '0099'")  # a later release ran, then was rolled back
    conn.commit()
    conn.close()
    before = _sha(path)
    with pytest.raises(db.StorageUnavailable, match="newer than this version") as newer:
        db.open_database(tmp_path, log=lambda line: None)
    assert newer.value.reason == "newer-schema"
    assert _sha(path) == before and not list(tmp_path.glob("*.snapshot"))


def test_ci_runs_the_storage_tests_rather_than_skipping_them():
    """On CI the storage tests must run: a Python whose SQLite is too old there (a runner's preinstalled one) would
    skip them silently and test a build without its database. Locally an old SQLite only skips them."""
    if os.environ.get("CI") and db.sqlite_problem():
        pytest.fail(f"CI's Python can't use storage: {db.sqlite_problem()} (UV_PYTHON_PREFERENCE=only-managed?)")


@pytest.mark.parametrize(
    ("version", "ok"), [("3.51.2", False), ("3.45.1", False), ("3.51.3", True), ("3.53.1", True), ("4.0.0", True)]
)
def test_sqlite_older_than_the_minimum_is_refused(version, ok):
    assert (db.sqlite_problem(version) is None) is ok


def test_an_old_sqlite_refuses_storage_before_touching_anything(tmp_path, monkeypatch):
    monkeypatch.setattr(db.sqlite3, "sqlite_version", "3.45.1")
    with pytest.raises(db.StorageUnavailable, match=r"older than 3\.51\.3") as old:
        db.open_database(tmp_path, log=lambda line: None)
    assert old.value.reason == "old-sqlite"
    assert list(tmp_path.iterdir()) == []


def test_everything_the_migration_scripts_import_is_imported_by_storage_db():
    """Alembic loads env.py and the revision scripts by path, so a bundler only packages what storage.db itself
    imports: a module only the scripts import is missing from a packaged build (found on one: storage.models)."""
    import ast

    wanted = set()
    for script in [db.MIGRATIONS_DIR / "env.py", *(db.MIGRATIONS_DIR / "versions").glob("*.py")]:
        for node in ast.walk(ast.parse(script.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                wanted |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                wanted.add(node.module)
    probe = (
        "import sys, roundtable_souls.storage.db\n"
        f"missing = [m for m in {sorted(wanted)!r} if m not in sys.modules]\n"
        "print(missing)\n"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]", f"imported only by the migration scripts: {out.strip()}"


# ----------------------------------------------------------------------------- what rolls an update back
@needs_sqlite
def test_a_damaged_database_file_is_left_alone_and_storage_is_off_without_a_rollback(tmp_path):
    path = tmp_path / db.DB_NAME
    path.write_bytes(b"not a database, " * 100)
    before = _sha(path)
    with pytest.raises(db.StorageUnavailable, match="moving it aside") as damaged:
        db.open_database(tmp_path, log=lambda line: None)
    assert damaged.value.reason == "damaged" and _sha(path) == before and not list(tmp_path.glob("*.snapshot"))


@needs_sqlite
def test_an_upgrade_stopped_by_the_disk_is_restored_and_does_not_roll_back(tmp_path, migrations):
    first = db.open_database(tmp_path, log=lambda line: None)
    _a_run(first)
    first.close()
    migrations(
        """
        op.create_table('half', sa.Column('id', sa.Integer(), primary_key=True))
        import sqlite3
        raise sqlite3.OperationalError("database or disk is full")
        """
    )
    with pytest.raises(db.StorageUnavailable, match="stopped by the system") as full:
        db.open_database(tmp_path, log=lambda line: None)
    assert full.value.reason == "environment" and not isinstance(full.value, db.MigrationFailed)
    assert db.read_revision(tmp_path / db.DB_NAME) == HEAD and _runs(tmp_path / db.DB_NAME) == ["kept"]


@needs_sqlite
def test_a_lock_file_that_cannot_be_used_turns_storage_off(tmp_path, monkeypatch):
    def refuse(self, exclusive, timeout):
        raise PermissionError("access denied")

    monkeypatch.setattr(db.ReadWriteLock, "acquire", refuse)
    with pytest.raises(db.StorageUnavailable) as locked:
        db.open_database(tmp_path, log=lambda line: None)
    assert locked.value.reason == "environment"


def test_only_a_failure_of_the_migration_code_stops_start_up():
    import sqlalchemy.exc

    full = sqlalchemy.exc.OperationalError("INSERT", {}, sqlite3.OperationalError("database or disk is full"))
    assert db._environmental(full) and db._environmental(PermissionError("denied"))
    assert db._environmental(sqlite3.OperationalError("database is locked"))
    assert not db._environmental(RuntimeError("a broken migration"))
    assert not db._environmental(sqlite3.OperationalError("no such column: nope"))  # a bug in the migration


# ----------------------------------------------------------------------------- the application
@needs_sqlite
def test_create_app_opens_the_database_in_the_data_folder(tmp_path):
    from roundtable_souls.app import create_app

    ctx = create_app()
    try:
        assert ctx.storage is not None and ctx.storage.path == tmp_path / "launcher-data" / db.DB_NAME
        assert ctx.storage_problem == ""
    finally:
        ctx.close()


def test_create_app_runs_on_without_storage_when_it_is_refused(monkeypatch):
    from roundtable_souls import app

    def refuse(_folder):
        raise db.StorageUnavailable("storage is off for this run")

    monkeypatch.setattr(app.storage_db, "open_database", refuse)
    ctx = app.create_app()
    assert ctx.storage is None and ctx.storage_problem == "storage is off for this run"


def test_a_failed_upgrade_stops_start_up_and_play_reports_nothing_ready(monkeypatch):
    from roundtable_souls import app, cli
    from roundtable_souls.game import catalog as games
    from roundtable_souls.platform import instance
    from roundtable_souls.updates import apply as updates

    def fail(_folder):
        raise db.MigrationFailed("The database upgrade failed (broken); the database was restored from x.")

    monkeypatch.setattr(app.storage_db, "open_database", fail)
    with pytest.raises(db.MigrationFailed):
        app.create_app()
    ready = []
    monkeypatch.setattr(updates, "mark_ready", lambda how="window", **k: ready.append(how))
    monkeypatch.setattr(instance, "held", lambda name: False)
    monkeypatch.setattr(cli, "storage_failed", lambda e, window: 1)
    assert cli.play_from_shortcut(games.ELDEN_RING) == 1 and ready == []


@needs_sqlite
def test_check_storage_reports_the_database_it_opened(capsys):
    from roundtable_souls import cli

    assert cli.check_storage() == 0
    out = capsys.readouterr().out
    assert (
        "0001_first_schema.py" in out and f"at {HEAD} (head {HEAD}), journal wal" in out and out.rstrip().endswith("OK")
    )
