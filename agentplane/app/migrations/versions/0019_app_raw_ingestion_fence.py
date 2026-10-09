"""Fence legacy app raw writers even when they do not understand service projection."""

from alembic import op

revision = "0019_app_raw_ingestion_fence"
down_revision = "0018_thread_model_activity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Earlier-revision replay tests retain newer columns/functions. No data rewrite.
    op.execute("ALTER TABLE event_log ADD COLUMN IF NOT EXISTS raw_ingestion_fenced_at_cursor bigint")
    op.execute("""
        CREATE OR REPLACE FUNCTION reject_fenced_app_ingestion() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE destination uuid; barrier bigint;
        BEGIN
            IF TG_OP = 'DELETE' THEN destination := OLD.thread_id;
            ELSE destination := NEW.thread_id; END IF;
            -- SHARE conflicts with the handoff's UPDATE lock and lasts until commit.
            -- The fence therefore waits for an admitted raw+fold transaction, or the
            -- old transaction observes the committed fence before writing anything.
            SELECT raw_ingestion_fenced_at_cursor INTO barrier
              FROM event_log WHERE id = destination FOR SHARE;
            IF barrier IS NOT NULL THEN
                RAISE EXCEPTION 'app raw ingestion fenced for Thread %', destination
                  USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
        END
        $$
    """)
    for table in ("event", "feed_state"):
        op.execute(f"""
            CREATE OR REPLACE TRIGGER reject_fenced_app_ingestion
            BEFORE INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_fenced_app_ingestion()
        """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM event_log WHERE raw_ingestion_fenced_at_cursor IS NOT NULL) THEN
                RAISE EXCEPTION 'cannot remove active app raw ingestion fences';
            END IF;
        END $$
    """)
    for table in ("event", "feed_state"):
        op.execute(f"DROP TRIGGER reject_fenced_app_ingestion ON {table}")
    op.execute("DROP FUNCTION reject_fenced_app_ingestion()")
    op.execute("ALTER TABLE event_log DROP COLUMN raw_ingestion_fenced_at_cursor")
