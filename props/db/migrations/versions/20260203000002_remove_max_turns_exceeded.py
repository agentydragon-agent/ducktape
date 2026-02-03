"""Remove max_turns_exceeded status, use timed_out instead.

MAX_TURNS_EXCEEDED was a misnomer - props agents don't use turn limits,
they use timeout_seconds. The status was set when containers timed out,
which is what TIMED_OUT already represents.

Revision ID: 20260203000002
Revises: 20260203000000
Create Date: 2026-02-03
"""

from alembic import op

revision = "20260203000002"
down_revision = "20260203000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Update all existing max_turns_exceeded rows to timed_out
    op.execute("UPDATE agent_runs SET status = 'timed_out' WHERE status = 'max_turns_exceeded'")

    # Remove max_turns_exceeded from the enum
    # PostgreSQL doesn't support removing enum values directly, so we:
    # 1. Create a new enum without max_turns_exceeded
    # 2. Update the column to use the new enum
    # 3. Drop the old enum

    # Create new enum type
    op.execute("""
        CREATE TYPE agent_run_status_enum_new AS ENUM (
            'in_progress',
            'completed',
            'context_length_exceeded',
            'timed_out',
            'reported_failure'
        )
    """)

    # Update column to use new enum (via text cast)
    op.execute("""
        ALTER TABLE agent_runs
        ALTER COLUMN status TYPE agent_run_status_enum_new
        USING status::text::agent_run_status_enum_new
    """)

    # Drop old enum and rename new one
    op.execute("DROP TYPE agent_run_status_enum")
    op.execute("ALTER TYPE agent_run_status_enum_new RENAME TO agent_run_status_enum")

    # Update column comment
    op.execute(
        "COMMENT ON COLUMN agent_runs.status IS "
        "'Run status: in_progress, completed, context_length_exceeded, timed_out, or reported_failure'"
    )


def downgrade() -> None:
    # Re-add max_turns_exceeded to enum
    op.execute("""
        CREATE TYPE agent_run_status_enum_old AS ENUM (
            'in_progress',
            'completed',
            'max_turns_exceeded',
            'context_length_exceeded',
            'timed_out',
            'reported_failure'
        )
    """)

    op.execute("""
        ALTER TABLE agent_runs
        ALTER COLUMN status TYPE agent_run_status_enum_old
        USING status::text::agent_run_status_enum_old
    """)

    op.execute("DROP TYPE agent_run_status_enum")
    op.execute("ALTER TYPE agent_run_status_enum_old RENAME TO agent_run_status_enum")

    # Restore old comment
    op.execute(
        "COMMENT ON COLUMN agent_runs.status IS "
        "'Run status: in_progress, completed, max_turns_exceeded, context_length_exceeded, or reported_failure'"
    )
