"""make_grader_output_nullable

Make grader_runs.output column nullable to support creating the row before
running the agent (matching critic workflow pattern).

This allows us to create the grader_run row with status='in_progress' before
the agent starts, enabling proper RLS scoping and status-based flow control.

Revision ID: 20251220000009
Revises: 20251220000008
Create Date: 2025-12-16

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251220000009"
down_revision: str | Sequence[str] | None = "20251220000008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Make output column nullable."""
    op.execute("""
        ALTER TABLE grader_runs
        ALTER COLUMN output DROP NOT NULL
    """)


def downgrade() -> None:
    """Make output column non-nullable again."""
    # First set any NULL values to a placeholder (shouldn't happen in practice)
    op.execute("""
        UPDATE grader_runs
        SET output = '{"tag": "max_turns_exceeded"}'::jsonb
        WHERE output IS NULL
    """)

    op.execute("""
        ALTER TABLE grader_runs
        ALTER COLUMN output SET NOT NULL
    """)
