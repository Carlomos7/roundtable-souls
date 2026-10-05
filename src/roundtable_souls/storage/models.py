"""The database's tables, typed (SQLAlchemy 2: DeclarativeBase, Mapped[], mapped_column).

The first schema holds the file-hash cache, the activity log and the rebuild run log. They start empty: their old
files (cache/hashes.json, logs/jobs.jsonl, merges.json) are still what the launcher reads and writes until each
area moves. Undo, recovery and backup-protection records are not here; they stay independent of the activity log
and its retention.
"""

from __future__ import annotations

import datetime

from sqlalchemy import BigInteger, Boolean, Integer, String, Text, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


class UtcMillis(TypeDecorator[datetime.datetime]):
    """A moment, stored as whole milliseconds since the Unix epoch (UTC). Only timezone-aware datetimes are accepted
    (a naive one is refused: its zone would be a guess); values come back as UTC datetimes."""

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value: datetime.datetime | None, dialect) -> int | None:
        if value is None:
            return None
        if not isinstance(value, datetime.datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"a timezone-aware datetime is required, not {value!r}")
        delta = value - datetime.datetime(1970, 1, 1, tzinfo=datetime.UTC)
        return delta // datetime.timedelta(milliseconds=1)

    def process_result_value(self, value: int | None, dialect) -> datetime.datetime | None:
        if value is None:
            return None
        return datetime.datetime(1970, 1, 1, tzinfo=datetime.UTC) + datetime.timedelta(milliseconds=int(value))


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class Base(DeclarativeBase):
    pass


class FileHash(Base):
    """The hash cache: a file's SHA-256, valid while its size and modification time are the same."""

    __tablename__ = "file_hashes"

    path: Mapped[str] = mapped_column(String, primary_key=True)  # normalised: os.path.normcase of the full path
    size: Mapped[int] = mapped_column(BigInteger)
    mtime_ns: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    hashed_at: Mapped[datetime.datetime] = mapped_column(UtcMillis, default=utc_now, onupdate=utc_now)


class Job(Base):
    """The activity log: one row per job (what it was, when, how it ended, its log file)."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_key: Mapped[str] = mapped_column(String, unique=True)  # its job id, or a hash of an imported line
    job_id: Mapped[str | None] = mapped_column(String)
    title: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String, default="")
    game: Mapped[str] = mapped_column(String, default="")
    profile: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime.datetime] = mapped_column(UtcMillis, index=True)
    ended_at: Mapped[datetime.datetime | None] = mapped_column(UtcMillis)
    outcome: Mapped[str] = mapped_column(String, default="running")  # platform.logging.OUTCOMES
    warnings: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    log_name: Mapped[str | None] = mapped_column(String)
    attachments: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    problem: Mapped[str] = mapped_column(Text, default="")
    pid: Mapped[int | None] = mapped_column(Integer)


class RebuildRun(Base):
    """The rebuild run log: the last runs of the merged-mods rebuild, per profile."""

    __tablename__ = "rebuild_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_key: Mapped[str] = mapped_column(String, unique=True)  # the profile and its run time
    profile: Mapped[str] = mapped_column(Text, index=True)  # normalised like FileHash.path
    ran_at: Mapped[datetime.datetime] = mapped_column(UtcMillis)
    ok: Mapped[bool] = mapped_column(Boolean)
    message: Mapped[str] = mapped_column(Text, default="")


class ImportState(Base):
    """How far an old record file has been imported, so an import resumes where it stopped and notices when the file
    was rewritten (an older build ran after a rollback). position: bytes of the file imported; prefix_sha256: of
    those bytes; content_sha256: of the whole file at the last import (for files rewritten whole); verified_at: when
    every record of the file was last found in the database (the area switches to the database only after that)."""

    __tablename__ = "import_state"

    source: Mapped[str] = mapped_column(String, primary_key=True)  # "jobs.jsonl", "hashes.json"
    position: Mapped[int] = mapped_column(BigInteger, default=0)
    prefix_sha256: Mapped[str] = mapped_column(String(64), default="")
    content_sha256: Mapped[str] = mapped_column(String(64), default="")
    verified_at: Mapped[datetime.datetime | None] = mapped_column(UtcMillis)
    updated_at: Mapped[datetime.datetime] = mapped_column(UtcMillis, default=utc_now, onupdate=utc_now)
