"""Add RLS policy for events table

Revision ID: 20251215000005
Revises: 20251215000004
Create Date: 2025-12-15 00:00:05

Note:
- snapshots, true_positives, false_positives, examples RLS implemented in migration 20251215000000
- critic_runs, grader_runs, critiques RLS implemented in migration 20251215000003
This migration adds the missing table: events.
"""

from alembic import op
from sqlalchemy import text

revision = "20251215000005"
down_revision = "20251215000004"


def upgrade() -> None:
    """Enable RLS and create TRAIN-only policy for events."""

    # Enable RLS on events table
    op.execute("ALTER TABLE events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE events FORCE ROW LEVEL SECURITY")

    # Create admin bypass policy for events
    op.execute(
        """
        CREATE POLICY admin_full_access_events ON events
        FOR ALL TO postgres
        USING (true)
        WITH CHECK (true)
    """
    )

    # events: TRAIN only (via transcript linkage to critic_runs and grader_runs)
    op.execute(
        text(
            """
        CREATE POLICY prompt_optimizer_events ON events
          FOR SELECT
          USING (
            current_prompt_optimizer_run_id() IS NOT NULL
            AND transcript_id IN (
              SELECT transcript_id FROM critic_runs WHERE snapshot_slug IN (
                SELECT slug FROM snapshots WHERE split = 'train'::split_enum
              )
              UNION
              SELECT transcript_id FROM grader_runs WHERE snapshot_slug IN (
                SELECT slug FROM snapshots WHERE split = 'train'::split_enum
              )
            )
          )
    """
        )
    )


def downgrade() -> None:
    """Drop RLS policy for events."""
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_events ON events")
    op.execute("DROP POLICY IF EXISTS admin_full_access_events ON events")

    op.execute("ALTER TABLE events DISABLE ROW LEVEL SECURITY")
