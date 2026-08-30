"""Persist operator abort requests across runner reconnects.

Revision ID: 0127
Revises: 0126
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0127"
down_revision: str | None = "0126"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("abort_requested_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "abort_requested_at")
