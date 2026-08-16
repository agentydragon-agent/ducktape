"""Durable Console authority for temporary Kubernetes RoleBinding leases.

Revision ID: 0043
Revises: 0042
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    state = sa.Enum("pending", "active", "revoked", "expired", name="kubernetes_access_grant_state")
    state.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "kubernetes_access_grants",
        sa.Column("lease_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("policy_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("policy_hash", sa.Text(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", state, nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_kubernetes_access_grants_active", "kubernetes_access_grants", ["state", "expires_at"])


def downgrade() -> None:
    op.drop_index("idx_kubernetes_access_grants_active", table_name="kubernetes_access_grants")
    op.drop_table("kubernetes_access_grants")
    sa.Enum(name="kubernetes_access_grant_state").drop(op.get_bind(), checkfirst=True)
