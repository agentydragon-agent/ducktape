"""Persist explicit-Agent temporary Kubernetes grants and their provenance.

Grant rules stay in JSONB because the Kubernetes API resource vocabulary is open-ended. The
application domain validates the RBAC-like rule shape before insertion; PostgreSQL enforces the
lifecycle and provenance invariants here.

Revision ID: 0089
Revises: 0088
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0089"
down_revision: str | None = "0088"
branch_labels: str | None = None
depends_on: str | None = None


_STATUS = "'active','released','revoked','expired'"


def upgrade() -> None:
    op.create_table(
        "kubernetes_grants",
        sa.Column("grant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_tool_call_id", sa.Text(), nullable=False),
        sa.Column("rules", JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("grant_id", name="kubernetes_grants_pkey"),
        sa.UniqueConstraint("source_tool_call_id", name="uq_kubernetes_grants_source_tool_call"),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.agent_id"], name="kubernetes_grants_agent_id_fkey", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_tool_call_id"],
            ["mcp_tool_calls.tool_call_id"],
            name="kubernetes_grants_source_tool_call_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("btrim(source_tool_call_id) <> ''", name="ck_kubernetes_grants_source_tool_call_nonempty"),
        sa.CheckConstraint(
            "jsonb_typeof(rules) = 'array' AND jsonb_array_length(rules) > 0",
            name="ck_kubernetes_grants_rules_nonempty",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_kubernetes_grants_expiration_after_creation"),
        sa.CheckConstraint(
            f"(status IN ({_STATUS})) AND ((status = 'active' AND ended_at IS NULL AND end_reason IS NULL) OR "
            "(status IN ('released', 'revoked', 'expired') AND ended_at IS NOT NULL "
            "AND end_reason IS NOT NULL AND btrim(end_reason) <> ''))",
            name="ck_kubernetes_grants_status_shape",
        ),
    )
    op.create_index(
        "idx_kubernetes_grants_agent_status_expiry", "kubernetes_grants", ["agent_id", "status", "expires_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_kubernetes_grants_agent_status_expiry", table_name="kubernetes_grants")
    op.drop_table("kubernetes_grants")
