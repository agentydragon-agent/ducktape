"""Add reported_failure to grader_run_status_enum.

Adds the 'reported_failure' value to the grader_run_status_enum PostgreSQL type.
This allows grader agents to explicitly report that they cannot complete grading
(e.g., malformed critic output, missing data, access issues).

Revision ID: 20251222000003
Revises: 20251222000002
Create Date: 2025-12-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20251222000003"
down_revision: str | Sequence[str] | None = "20251222000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add 'reported_failure' value to grader_run_status_enum.

    PostgreSQL requires ALTER TYPE ... ADD VALUE for adding enum values.
    This is safe and doesn't require recreating the type.
    """
    op.execute("ALTER TYPE grader_run_status_enum ADD VALUE 'reported_failure'")


def downgrade() -> None:
    """Cannot remove enum value in PostgreSQL.

    PostgreSQL doesn't support removing enum values. The only options are:
    1. Recreate the type (requires migrating all data)
    2. Leave the value (harmless if unused)

    We choose option 2 for simplicity. If a full downgrade is needed,
    run the database recreation command.
    """
    # Cannot remove enum values in PostgreSQL - would need to recreate type
