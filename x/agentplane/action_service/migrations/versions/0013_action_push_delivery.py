"""Coordinate Action Web Push delivery across replicas."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013_action_push_delivery"
down_revision = "0012_action_push_subscription"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_push_delivery",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("request_id", "kind"),
    )


def downgrade() -> None:
    op.drop_table("action_push_delivery")
