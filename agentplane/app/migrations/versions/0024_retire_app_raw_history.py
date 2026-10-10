"""Delete obsolete app raw history; Sandbox Service remains the archive authority.

This intentionally deletes retained app event/feed_state rows. Stop old app Pods
before migration: they still map the fence column. No service data is touched.
"""

from alembic import op

revision = "0024_retire_app_raw_history"
down_revision = "0023_drop_app_runner_locator"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No CASCADE: unexpected dependencies must stop the rollout, not be erased.
    # Dropping each table removes its obsolete write-rejection trigger and indexes.
    op.execute("DROP TABLE IF EXISTS event")
    op.execute("DROP TABLE IF EXISTS feed_state")
    op.execute("DROP FUNCTION IF EXISTS reject_fenced_app_ingestion()")
    op.execute("ALTER TABLE event_log DROP COLUMN IF EXISTS raw_ingestion_fenced_at_cursor")


def downgrade() -> None:
    raise RuntimeError("app raw-history retirement is irreversible; restore a pre-retirement backup for rollback")
