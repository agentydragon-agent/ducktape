"""Persist current subscription health separately from lifecycle and delivery."""

import sqlalchemy as sa
from alembic import op

revision = "0007_subscription_health"
down_revision = "0006_stale_inbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("subscription", sa.Column("health", sa.String(), nullable=False, server_default="healthy"))
    op.execute("UPDATE subscription SET health = 'backing_off' WHERE error IS NOT NULL")
    op.alter_column("subscription", "health", server_default=None)


def downgrade() -> None:
    op.drop_column("subscription", "health")
