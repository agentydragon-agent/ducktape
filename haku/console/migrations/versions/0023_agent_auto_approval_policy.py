"""Persist each Agent's selected auto-approval policy.

Revision ID: 0023
Revises: 0022
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing Agents remain NULL during rollout. Runtime authorization treats an absent assignment
    # as manual-approval-only; every new enrollment/reconnect/update must choose a configured policy.
    op.add_column("agents", sa.Column("auto_approval_policy", sa.Text(), nullable=True))
    op.add_column("enrollment_interactions", sa.Column("auto_approval_policy", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("enrollment_interactions", "auto_approval_policy")
    op.drop_column("agents", "auto_approval_policy")
