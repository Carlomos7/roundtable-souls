"""Import progress for the old record files (jobs.jsonl, hashes.json).

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_state",
        sa.Column("source", sa.String(), primary_key=True),
        sa.Column("position", sa.BigInteger(), nullable=False),
        sa.Column("prefix_sha256", sa.String(64), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("verified_at", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("import_state")
