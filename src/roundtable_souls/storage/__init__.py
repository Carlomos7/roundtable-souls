"""The launcher's own records in one SQLite database (roundtable.db in the data folder), through SQLAlchemy 2 with
Alembic migrations run in code at start-up.

  db.py          opening the database: the SQLite version check, the cross-process lock, migrations with a snapshot
                 first and recovery when they fail, connection settings, units of work
  models.py      the typed tables, and the UTC timestamp type every date column uses
  migrations/    Alembic's env.py and versions/, shipped as files beside the package (Alembic loads them by path)

Only files that belong to the launcher itself move here, area by area; settings, saves, profiles, mods and the
records that protect files beside them stay files. Nothing outside this package writes SQL.
"""
