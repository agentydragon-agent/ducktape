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
        sa.Column(
            "tool_call_id", sa.Text(), sa.ForeignKey("mcp_tool_calls.tool_call_id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "operator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("operators.operator_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("requester", sa.Text(), nullable=False),
        sa.Column("profile_id", sa.Text(), nullable=False),
        sa.Column("profile_hash", sa.Text(), nullable=False),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("cluster_role", sa.Text(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", state, nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_kubernetes_access_grants_active", "kubernetes_access_grants", ["state", "expires_at"])
    op.create_index("idx_kubernetes_access_grants_tool_call", "kubernetes_access_grants", ["tool_call_id"])


def downgrade() -> None:
    op.drop_index("idx_kubernetes_access_grants_tool_call", table_name="kubernetes_access_grants")
    op.drop_index("idx_kubernetes_access_grants_active", table_name="kubernetes_access_grants")
    op.drop_table("kubernetes_access_grants")
    sa.Enum(name="kubernetes_access_grant_state").drop(op.get_bind(), checkfirst=True)
