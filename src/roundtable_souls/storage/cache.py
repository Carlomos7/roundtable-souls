"""The file-hash cache in the database (it was cache/hashes.json).

An entry is valid while the file's size and modification time (ns) are exactly what they were when it was hashed,
the rule the file cache always used. The cache is only a shortcut: every failure here is a miss (the caller hashes
the file), never an answer, so a broken cache can make a check slower but never make it say a build is current.

hashes.json is imported, not moved: it stays as it is, so an older version restored by an update's watchdog keeps
using it. When that version has changed it, the next import here takes its entries; where both have an entry for a
path, the one made from the later modification time of the file wins. The database is used only once an import of
the file has been verified (every entry found); until then callers keep their old file cache.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from roundtable_souls.storage.db import Database
from roundtable_souls.storage.models import FileHash, ImportState, utc_now

SOURCE = "hashes.json"


class HashCache:
    def __init__(self, db: Database, log: Callable[[str], None] = lambda line: None):
        self.db = db
        self.log = log
        self.active = _verified(db, SOURCE)  # the database is used only after a verified import
        self._warned = False

    def get(self, key: str, size: int, mtime_ns: int) -> str | None:
        """The remembered SHA-256 when size and modification time still match; None otherwise or on any failure."""
        if not self.active:
            return None
        try:
            with self.db.unit_of_work() as s:
                row = s.get(FileHash, key)
                if row is not None and row.size == size and row.mtime_ns == mtime_ns:
                    return row.sha256
        except Exception as e:
            self._failed(e)
        return None

    def put(self, key: str, size: int, mtime_ns: int, sha256: str) -> None:
        """Remember a hash just computed (outside any transaction); a failure only means it is not remembered."""
        if not self.active:
            return
        try:
            with self.db.unit_of_work() as s:
                s.merge(FileHash(path=key, size=size, mtime_ns=mtime_ns, sha256=sha256, hashed_at=utc_now()))
        except Exception as e:
            self._failed(e)

    def _failed(self, e: Exception) -> None:
        if not self._warned:
            self._warned = True
            self.log(f"warning: the hash cache in the database failed ({e}); files are hashed again instead")

    def import_file(self, path: Path) -> bool:
        """Take hashes.json's entries (once per content of the file), verify them, and switch to the database when
        they are all there. Returns whether the cache is now active. Idempotent; safe in several processes."""
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            data = b"{}"
        content = hashlib.sha256(data).hexdigest()
        try:
            entries = json.loads(data.decode("utf-8"))
        except ValueError as e:
            self.log(f"warning: {path} can't be read ({e}); it is left as it is and not imported")
            entries = {}
        valid = {
            str(k): (int(v[0]), int(v[1]), str(v[2]))
            for k, v in (entries.items() if isinstance(entries, dict) else [])
            if isinstance(v, list | tuple) and len(v) == 3
        }
        with self.db.unit_of_work() as s:
            state = s.get(ImportState, SOURCE)
            if state is None or state.content_sha256 != content:
                for key, (size, mtime_ns, sha) in valid.items():
                    row = s.get(FileHash, key)
                    if row is None or mtime_ns > row.mtime_ns:
                        s.merge(FileHash(path=key, size=size, mtime_ns=mtime_ns, sha256=sha, hashed_at=utc_now()))
                state = s.merge(ImportState(source=SOURCE, content_sha256=content, position=len(data)))
            complete = all(
                (row := s.get(FileHash, k)) is not None and row.mtime_ns >= m for k, (_z, m, _h) in valid.items()
            )
            if complete:
                state.verified_at = utc_now()
        self.active = complete or self.active
        return self.active


def _verified(db: Database, source: str) -> bool:
    try:
        with db.unit_of_work() as s:
            state = s.get(ImportState, source)
            return state is not None and state.verified_at is not None
    except Exception:
        return False
