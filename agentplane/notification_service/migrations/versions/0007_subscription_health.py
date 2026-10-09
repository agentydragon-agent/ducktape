"""Persist current source-processing observations, not a health summary."""

import sqlalchemy as sa
from alembic import op

revision = "0007_subscription_health"
down_revision = "0006_stale_inbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("subscription", sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("subscription", sa.Column("error_kind", sa.String(), nullable=True))
    op.add_column("subscription", sa.Column("error_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column("subscription", sa.Column("error_observed_at", sa.DateTime(timezone=True), nullable=True))
    # Existing opaque errors have no recorded observation time or typed cause. Adopt them as-is
    # at migration time; do not infer a historical success or parse messages to guess a cause.
    op.execute(
        "UPDATE subscription SET error_kind = 'processing_error', error_since = now(), error_observed_at = now() "
        "WHERE error IS NOT NULL"
    )
    op.create_check_constraint(
        "subscription_error_kind",
        "subscription",
        "error_kind IN ('rate_limited', 'unavailable', 'access_denied', 'source_changed', 'processing_error')",
    )
    op.create_check_constraint(
        "subscription_error_state",
        "subscription",
        "(error IS NULL AND error_kind IS NULL AND error_since IS NULL AND error_observed_at IS NULL) OR "
        "(error IS NOT NULL AND error_kind IS NOT NULL AND error_since IS NOT NULL AND error_observed_at IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("subscription_error_state", "subscription", type_="check")
    op.drop_constraint("subscription_error_kind", "subscription", type_="check")
    for column in ("error_observed_at", "error_since", "error_kind", "last_success_at"):
        op.drop_column("subscription", column)
