"""The first schema: the file-hash cache, the activity log and the rebuild run log (empty; nothing is imported here).

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_hashes",
        sa.Column("path", sa.String(), primary_key=True),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("mtime_ns", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("hashed_at", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_key", sa.String(), nullable=False, unique=True),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("game", sa.String(), nullable=False),
        sa.Column("profile", sa.Text(), nullable=False),
        sa.Column("started_at", sa.BigInteger(), nullable=False),
        sa.Column("ended_at", sa.BigInteger(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("warnings", sa.Integer(), nullable=False),
        sa.Column("errors", sa.Integer(), nullable=False),
        sa.Column("log_name", sa.String(), nullable=True),
        sa.Column("attachments", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("problem", sa.Text(), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=True),
    )
    op.create_index("ix_jobs_started_at", "jobs", ["started_at"])
    op.create_table(
        "rebuild_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_key", sa.String(), nullable=False, unique=True),
        sa.Column("profile", sa.Text(), nullable=False),
        sa.Column("ran_at", sa.BigInteger(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
    )
    op.create_index("ix_rebuild_runs_profile", "rebuild_runs", ["profile"])


def downgrade() -> None:
    op.drop_index("ix_rebuild_runs_profile", "rebuild_runs")
    op.drop_table("rebuild_runs")
    op.drop_index("ix_jobs_started_at", "jobs")
    op.drop_table("jobs")
    op.drop_table("file_hashes")
