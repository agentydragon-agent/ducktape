"""Add improvement agent type to agent_type_enum.

Revision ID: 20251231000000
Revises: 20251230000000
Create Date: 2025-12-31

Adds the 'improvement' value to agent_type_enum, which was missing
from the original enum creation in 20251223000000.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20251231000000"
down_revision: str | Sequence[str] | None = "20251230000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add 'improvement' to agent_type_enum."""
    op.execute("""
        DO $$
        BEGIN
            -- Check if 'improvement' is not already in the enum
            IF NOT EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumtypid = 'agent_type_enum'::regtype
                AND enumlabel = 'improvement'
            ) THEN
                ALTER TYPE agent_type_enum ADD VALUE 'improvement';
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    """Cannot remove enum values in PostgreSQL without recreating the type.

    This is a one-way migration. If you need to remove 'improvement',
    you'd need to recreate the enum type and update all references.
    """
