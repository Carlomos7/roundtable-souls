"""Alembic's environment for the launcher's database. storage.db runs it in code, handing over the connection it
opened (config.attributes["connection"]); there is no alembic.ini and no command line. render_as_batch because
SQLite cannot alter most columns in place."""

from alembic import context

from roundtable_souls.storage.models import Base

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("the launcher's migrations run through roundtable_souls.storage.db, which passes a connection")

context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
with context.begin_transaction():
    context.run_migrations()
