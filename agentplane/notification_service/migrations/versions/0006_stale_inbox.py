"""Persist the confirmation deadline for UID-pinned stale destinations."""

import sqlalchemy as sa
from alembic import op

revision = "0006_stale_inbox"
down_revision = "0005_github"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("inbox", sa.Column("stale_check_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("inbox", "stale_check_at")
