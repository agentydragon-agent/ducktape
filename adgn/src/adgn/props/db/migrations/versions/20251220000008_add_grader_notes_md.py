"""add_grader_notes_md

Add notes_md column to grader_runs table to store grader summary/notes.

Similar to critic_runs.completion_summary, this provides a place to store
freeform markdown notes from the grader agent. This allows grader summary
to be stored independently of the output JSONB field.

Revision ID: 20251220000008
Revises: 20251220000007
Create Date: 2025-12-16

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251220000008"
down_revision: str | Sequence[str] | None = "20251220000007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add notes_md column to grader_runs table."""
    op.execute("""
        ALTER TABLE grader_runs
        ADD COLUMN notes_md TEXT
    """)


def downgrade() -> None:
    """Remove notes_md column from grader_runs table."""
    op.execute("""
        ALTER TABLE grader_runs
        DROP COLUMN notes_md
    """)
