"""drop_match_type_from_grading_decisions

Revision ID: 20251220000007
Revises: 20251220000006
Create Date: 2025-12-20 17:08:59.029516

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20251220000007"
down_revision: str | Sequence[str] | None = "20251220000006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop match_type column from grading_decisions.

    This field was documented in grader prompts but never read/used by Python code.
    The grader agent can use the rationale field to explain match quality instead.
    """
    op.drop_column("grading_decisions", "match_type")


def downgrade() -> None:
    """Re-add match_type column."""
    op.add_column("grading_decisions", sa.Column("match_type", sa.String(), nullable=True))
