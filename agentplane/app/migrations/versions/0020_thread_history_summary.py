"""Create bounded projection metadata; existing Threads are seeded only at explicit handoff."""

from alembic import op

revision = "0020_thread_history_summary"
down_revision = "0019_app_raw_ingestion_fence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Older-revision replay tests keep newer tables. No archive backfill at startup.
    op.execute("""
        CREATE TABLE IF NOT EXISTS thread_history_summary (
            thread_id uuid PRIMARY KEY REFERENCES event_log(id) ON DELETE CASCADE,
            last_event_at timestamptz,
            last_turn_status bigint
        )
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM event_log WHERE raw_ingestion_fenced_at_cursor IS NOT NULL) THEN
                RAISE EXCEPTION 'cannot remove metadata for service-projected Threads';
            END IF;
        END $$
    """)
    op.drop_table("thread_history_summary")
