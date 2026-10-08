"""Durable source health and per-subscription transition identities."""

import sqlalchemy as sa
from alembic import op

revision = "0007_subscription_health"
down_revision = "0006_stale_inbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("subscription", sa.Column("health", sa.String(), nullable=False, server_default="healthy"))
    op.add_column("subscription", sa.Column("health_sequence", sa.BigInteger(), nullable=False, server_default="0"))
    op.execute("UPDATE subscription SET health = 'backing_off' WHERE error IS NOT NULL")
    op.alter_column("subscription", "health", server_default=None)
    op.alter_column("subscription", "health_sequence", server_default=None)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM entry WHERE event->>'provider' = 'notifications' LIMIT 1")).first():
        raise RuntimeError("refusing downgrade with retained subscription health events")
    op.drop_column("subscription", "health_sequence")
    op.drop_column("subscription", "health")
