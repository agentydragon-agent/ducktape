"""add_input_issue_existence_check

Revision ID: 20251220000005
Revises: 20251220000004
Create Date: 2025-12-20 17:30:00.000000

Add CHECK constraint to validate that input_issue_id in grading_decisions
corresponds to an actual reported issue in the critique being graded.

Uses a database function to traverse grader_run -> critic_run -> reported_issues
without denormalizing critic_run_id into grading_decisions.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251220000005"
down_revision: str | Sequence[str] | None = "20251220000004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add function and CHECK constraint to validate input_issue_id exists."""

    # Create validation function
    op.execute("""
        CREATE FUNCTION validate_input_issue_exists(grader_run_id UUID, input_issue_id TEXT)
        RETURNS BOOLEAN AS $$
            SELECT EXISTS (
                SELECT 1
                FROM reported_issues ri
                JOIN grader_runs gr ON gr.critic_run_id = ri.critic_run_id
                WHERE gr.id = $1 AND ri.issue_id = $2
            )
        $$ LANGUAGE SQL STABLE;
    """)

    # Add CHECK constraint
    op.execute("""
        ALTER TABLE grading_decisions
        ADD CONSTRAINT check_input_issue_exists
        CHECK (validate_input_issue_exists(grader_run_id, input_issue_id));
    """)


def downgrade() -> None:
    """Remove CHECK constraint and validation function."""

    # Drop CHECK constraint
    op.execute("""
        ALTER TABLE grading_decisions
        DROP CONSTRAINT check_input_issue_exists;
    """)

    # Drop validation function
    op.execute("""
        DROP FUNCTION validate_input_issue_exists(UUID, TEXT);
    """)
