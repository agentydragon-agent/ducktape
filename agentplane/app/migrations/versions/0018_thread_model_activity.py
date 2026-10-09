"""Materialize the latest model-originated event for each Thread's sidebar snapshot.

The event log remains the source of truth. This backfill keeps existing Threads from
appearing unknown until their next model output; future events update the projection
in the same ingestion transaction as the fold.
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_thread_model_activity"
down_revision = "0017_event_turn_completed_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("event_log", sa.Column("last_model_activity_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        """
        UPDATE event_log AS log SET last_model_activity_at = latest.at
        FROM (
            SELECT DISTINCT ON (thread_id) thread_id, at
            FROM event
            WHERE (kind = 'text_delta' AND coalesce(payload::jsonb #>> '{event,textDelta,text}', '') <> '')
               OR (kind = 'tool_arguments_delta' AND coalesce(payload::jsonb #>> '{event,toolArgumentsDelta,partialJson}', '') <> '')
               OR (kind = 'tool_arguments' AND coalesce(payload::jsonb #>> '{event,toolArguments,argumentsJson}', '') <> '')
               OR (kind = 'item_started' AND payload::jsonb #>> '{event,itemStarted,kind}' IN
                   ('ITEM_KIND_ASSISTANT_TEXT', 'ITEM_KIND_REASONING', 'ITEM_KIND_TOOL_CALL'))
               OR (kind = 'item_completed' AND coalesce(payload::jsonb #>> '{event,itemCompleted,text}', '') <> '')
            ORDER BY thread_id, cursor DESC
        ) AS latest
        WHERE log.id = latest.thread_id
        """
    )


def downgrade() -> None:
    op.drop_column("event_log", "last_model_activity_at")
