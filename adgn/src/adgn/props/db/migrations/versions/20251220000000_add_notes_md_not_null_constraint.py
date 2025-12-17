"""Add NOT NULL constraint on completion_summary when status='completed'

Revision ID: 20251220000000
Revises: 20251216000000
Create Date: 2025-12-20 00:00:00.000000

Adds a CHECK constraint to ensure completion_summary is NOT NULL when a critic run
has status='completed'. This prevents NULL completion summaries for
successful runs while allowing NULL for in-progress or failed runs.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251220000000"
down_revision: str | None = "20251216000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add CHECK constraint ensuring completion_summary is NOT NULL when status='completed'
    op.execute("""
        ALTER TABLE critic_runs
        ADD CONSTRAINT check_completion_summary_not_null_when_completed
        CHECK (status != 'completed' OR completion_summary IS NOT NULL)
    """)


def downgrade() -> None:
    # Remove the CHECK constraint
    op.execute("""
        ALTER TABLE critic_runs
        DROP CONSTRAINT IF EXISTS check_completion_summary_not_null_when_completed
    """)
