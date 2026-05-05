"""Initial Y.Doc state table.

Revision ID: 0001
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "doc",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("update_blob", sa.LargeBinary(), nullable=False),
        sa.CheckConstraint("id = 1", name="doc_single_row"),
    )


def downgrade() -> None:
    op.drop_table("doc")
