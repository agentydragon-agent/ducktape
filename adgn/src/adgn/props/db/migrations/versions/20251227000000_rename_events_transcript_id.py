"""Rename events.transcript_id to agent_run_id and add FK.

Revision ID: 20251227000000
Revises: 20251226000003
Create Date: 2025-12-27

This migration:
1. Renames events.transcript_id column to agent_run_id
2. Updates unique constraint and index names
3. Adds FK constraint to agent_runs.agent_run_id
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20251227000000"
down_revision = "20251226000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Rename the column
    op.alter_column("events", "transcript_id", new_column_name="agent_run_id")

    # 2. Drop old unique constraint and index
    # Constraint name from initial schema is uq_events_transcript_sequence
    op.drop_constraint("uq_events_transcript_sequence", "events", type_="unique")
    op.drop_index("ix_events_transcript_id", table_name="events")

    # 3. Create new unique constraint and index with updated names
    op.create_unique_constraint("uq_events_agent_run_id_seq", "events", ["agent_run_id", "sequence_num"])
    op.create_index("ix_events_agent_run_id_seq", "events", ["agent_run_id", "sequence_num"])

    # 4. Add FK constraint to agent_runs
    op.create_foreign_key(
        "fk_events_agent_run_id", "events", "agent_runs", ["agent_run_id"], ["agent_run_id"], ondelete="CASCADE"
    )


def downgrade() -> None:
    # 1. Drop FK constraint
    op.drop_constraint("fk_events_agent_run_id", "events", type_="foreignkey")

    # 2. Drop new unique constraint and index
    op.drop_constraint("uq_events_agent_run_id_seq", "events", type_="unique")
    op.drop_index("ix_events_agent_run_id_seq", table_name="events")

    # 3. Rename column back (must do before recreating constraint with old column name)
    op.alter_column("events", "agent_run_id", new_column_name="transcript_id")

    # 4. Create old unique constraint and index with original names
    op.create_unique_constraint("uq_events_transcript_sequence", "events", ["transcript_id", "sequence_num"])
    op.create_index("ix_events_transcript_id", "events", ["transcript_id"])
