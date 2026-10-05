# 0005 The launcher's own records go into one SQLite database, through SQLAlchemy and Alembic

**Status:** in use from the release after 3.15.0. The database is created and kept at the current schema; the
records move into it area by area, starting with the file-hash cache, the activity log and the rebuild run log.

## Decision

The launcher keeps the records that belong to it alone in `roundtable.db` in its data folder: SQLite, used through
SQLAlchemy 2 (synchronous; typed models with `DeclarativeBase`, `Mapped[]`, `mapped_column`), with the schema
managed by Alembic migrations that run in code at start-up. All of it is in `src/roundtable_souls/storage/`;
nothing else writes SQL.

What stays a file: the settings file (an older version restored after a failed update must read it), saves, me3
profiles, mod folders and game files, other programs' formats, and the records that protect files beside them (build
journals, a profile's `roundtable.json`). Records with that kind of job are classified before anything moves.

**Connections.** Every connection sets a bounded `busy_timeout` (5 s), `foreign_keys=ON` and `synchronous=FULL`,
and every write transaction starts with `BEGIN IMMEDIATE`, so a writer waits at the start instead of failing at
commit. `FULL` is used for the whole database: it holds few, small writes, and some of what will move into it
protects backups. A unit of work is one short session, committed once; none is held open across long file work.

**Journal mode.** WAL, set once when the schema is created or upgraded; the mode SQLite actually reports is checked,
and a filesystem that refuses WAL leaves the default journal mode, reported in the log rather than failing.

**Several processes.** The window, a Play started from a Steam shortcut and an update hand-off can run at once.
`roundtable.db.lock` beside the database is held shared by every process that has the database open and exclusively
by a migration. A migration therefore waits until the others have closed; after a bounded wait it is postponed and
that run goes on without storage. While a migration runs, nothing else opens the database.

**Upgrades.**
- Before an existing database is upgraded, a consistent snapshot is taken with SQLite's backup API (a file copy
  could catch a WAL database mid-write): `roundtable.db.<revision>.<time>.snapshot`, the newest three kept.
- If the upgrade fails, every connection is closed and, still under the exclusive lock, the snapshot is restored,
  but only if it passes `PRAGMA integrity_check`; otherwise it is kept for diagnosis and the database is left as
  found. A database created by the failed run is removed.
- The program then stops without reporting itself ready, so the update watchdog
  ([0004](0004-velopack.md)) puts the previous version back.
- A database whose schema is newer than the program knows (a later version ran, then was rolled back) is left
  untouched, and that run goes on without storage.

**What rolls an update back, and what does not.** Only a failure of the new version's own migration code stops
start-up (no ready report, so the watchdog restores the previous version, which never ran that code). Everything
else turns storage off for that run and the launcher works normally, because a rollback would not help and would
repeat at every update:
- the database is busy (another process has it open while it needs upgrading, or is upgrading it);
- its schema is newer than the version knows;
- the file is not a readable database (it is left untouched; moving it aside lets a new one be made);
- the filesystem or another program stopped it (no space, read-only, locked, cannot be opened); an upgrade
  interrupted this way is restored from its snapshot first;
- SQLite is below the minimum (builds refuse to package such a Python, so this happens only outside releases).

**Without storage**, records are never lost and never reported as stored: the file-hash cache is bypassed (files
are hashed every time, which is slower, never wrong), and activity records are written to the activity log's
original file, from which the next run with storage imports them.

**Minimum SQLite: 3.51.3.** The SQLite inside the packaged Python is checked at start-up; below the minimum,
storage is refused for the run with a message saying why. 3.51.3 (2026-03-13) fixes the *WAL-reset* bug, which can
corrupt a WAL database when two connections in different threads or processes write or checkpoint at the same
instant: exactly the launcher's situation. sqlite.org documents it as present from 3.7.0 through 3.51.2. That
version also covers the earlier fixes relevant here: frames written without checksums into the WAL after a
savepoint rollback (fixed in 3.50.2) and corruption from an application breaking POSIX advisory locks (resistance
added in 3.51.0). The features used (WAL, the backup API, `BEGIN IMMEDIATE`, foreign keys) are far older. sqlite.org
also lists backports of the WAL-reset fix in 3.44.6 and 3.50.7; one minimum is kept instead of a list of patch
releases. The 3.53.4 note that it fixes problems in 3.53.0–3.53.3 does not describe them, so it does not move the
minimum. Releases are built with Python 3.14.7 (`.python-version`), which carries SQLite 3.53.1 on Windows and Linux;
`scripts/build.py` refuses to build with a Python whose SQLite is below the minimum, and the release workflow opens
a database with each packaged program.

**Times** are stored as UTC milliseconds since the Unix epoch, through one column type that refuses a datetime
without a time zone.

**Snapshots are not backups.** They exist to undo a failed upgrade. The data they hold is the launcher's own
bookkeeping; saves and profiles are never inside the database.

**Retention of the activity log**, when it moves into the database: completed entries older than 90 days are
removed; entries still running, or interrupted, are not. Undo, recovery and backup-protection records are kept
apart from the activity log and are never removed by its retention.

## Why

The launcher had about twenty JSON formats of its own, each with its own write path, its own handling of older
versions and its own lock:
- growing files (`hashes.json`, `jobs.jsonl`) were read and rewritten whole;
- related changes could not succeed or fail together;
- nothing could be queried without scanning folders.

A shared JSON layer would have made the writes consistent, but would not have helped with growth, multi-record
changes, several processes or queries. SQLite does all four, and ships with Python. SQLAlchemy gives typed models and
a maintained SQLite dialect; Alembic gives versioned, testable schema changes (with batch mode, which SQLite needs to
alter most columns). Plain `sqlite3`, SQLModel and Peewee were considered and set aside: plain `sqlite3` would mean
writing the migration machinery, the other two add less than they cost.

## Reopen if

The records outgrow a single local file (several machines sharing one data folder, say), SQLite's WAL proves
unreliable on a filesystem users run the launcher from, or a SQLite release documents a correctness fix for WAL,
the backup API or locking (raise the minimum).
