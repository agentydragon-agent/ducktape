"""Materialize the latest model-originated event for each Thread's sidebar snapshot.

The event log remains the source of truth. This backfill keeps existing Threads from
appearing unknown until their next model output; future events update the projection
in the same ingestion transaction as the fold.
"""

from alembic import op

revision = "0018_thread_model_activity"
down_revision = "0017_event_turn_completed_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Earlier-migration replay tests can stamp an older head on an otherwise current schema.
    op.execute("ALTER TABLE event_log ADD COLUMN IF NOT EXISTS last_model_activity_at timestamptz")
    # jsonb cannot represent escaped NULs retained by the raw json archive. Replace
    # them only in this predicate's scratch value: a NUL is nonempty model output,
    # and neither it nor a literal escape can equal an item-kind enum name. Never
    # rewrite the stored payload. Use the (thread_id, cursor) index to find each
    # Thread's latest activity instead of sorting/aggregating the entire archive.
    op.execute(
        r"""
        UPDATE event_log AS log SET last_model_activity_at = (
            SELECT at
            FROM event
            CROSS JOIN LATERAL (
                SELECT replace(payload::text, E'\\u0000', E'\\ufffd')::jsonb AS activity
            ) AS decoded
            WHERE thread_id = log.id AND (
                (kind = 'text_delta' AND coalesce(activity #>> '{event,textDelta,text}', '') <> '')
                OR (kind = 'tool_arguments_delta' AND coalesce(activity #>> '{event,toolArgumentsDelta,partialJson}', '') <> '')
                OR (kind = 'tool_arguments' AND coalesce(activity #>> '{event,toolArguments,argumentsJson}', '') <> '')
                OR (kind = 'item_started' AND activity #>> '{event,itemStarted,kind}' IN
                    ('ITEM_KIND_ASSISTANT_TEXT', 'ITEM_KIND_REASONING', 'ITEM_KIND_TOOL_CALL'))
                OR (kind = 'item_completed' AND coalesce(activity #>> '{event,itemCompleted,text}', '') <> '')
            )
            ORDER BY cursor DESC
            LIMIT 1
        )
        """
    )


def downgrade() -> None:
    op.drop_column("event_log", "last_model_activity_at")
