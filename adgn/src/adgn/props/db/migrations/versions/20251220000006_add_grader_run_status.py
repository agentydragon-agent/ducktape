"""add_grader_run_status

Add status column to grader_runs table to enable database-based abort mechanism.

This aligns grader with critic behavior - both now use database-based status
polling for agent loop termination. Enables HTTP mode where MCP server can
signal completion by updating database status.

Revision ID: 20251220000006
Revises: 20251220000005
Create Date: 2025-12-16 17:51:50

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251220000006"
down_revision: str | Sequence[str] | None = "20251220000005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add grader_run_status_enum type and migrate status column to use it.

    Note: The squashed migration already creates a status column with type TEXT.
    This migration converts it to use the enum type.
    """
    # Create enum type for grader run status
    op.execute("""
        CREATE TYPE grader_run_status_enum AS ENUM (
            'in_progress',
            'completed',
            'max_turns_exceeded'
        )
    """)

    # Update status values based on output tag BEFORE changing column type
    # This ensures all values are valid enum values
    op.execute("""
        UPDATE grader_runs
        SET status = CASE
            WHEN output->>'tag' = 'success' THEN 'completed'
            WHEN output->>'tag' = 'max_turns_exceeded' THEN 'max_turns_exceeded'
            ELSE 'in_progress'
        END
    """)

    # Drop the server default before type conversion (can't cast TEXT default to enum)
    op.execute("""
        ALTER TABLE grader_runs
        ALTER COLUMN status DROP DEFAULT
    """)

    # Convert status column from TEXT to enum
    # ALTER TYPE requires explicit USING clause for conversion
    op.execute("""
        ALTER TABLE grader_runs
        ALTER COLUMN status TYPE grader_run_status_enum USING status::grader_run_status_enum
    """)

    # Re-add the default with enum type
    op.execute("""
        ALTER TABLE grader_runs
        ALTER COLUMN status SET DEFAULT 'in_progress'::grader_run_status_enum
    """)


def downgrade() -> None:
    """Remove status column and grader_run_status_enum type."""
    op.execute("ALTER TABLE grader_runs DROP COLUMN status")
    op.execute("DROP TYPE grader_run_status_enum")
