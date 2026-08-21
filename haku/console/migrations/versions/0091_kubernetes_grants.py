"""Persist explicit-Agent temporary Kubernetes grants and their provenance.

Grant scope and rules stay in JSONB because the Kubernetes API resource vocabulary is open-ended.
The application domain validates the namespace scope and RBAC-like rule shape before insertion;
PostgreSQL enforces their basic shape plus the lifecycle and provenance invariants here.

Revision ID: 0091
Revises: 0090
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0091"
down_revision: str | None = "0090"
branch_labels: str | None = None
depends_on: str | None = None


_STATUS = "'active','released','revoked','expired'"


def upgrade() -> None:
    op.create_table(
        "kubernetes_grants",
        sa.Column("grant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_tool_call_id", sa.Text(), nullable=False),
        sa.Column("scope", JSONB(), nullable=False),
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
        sa.CheckConstraint(
            "jsonb_typeof(scope) = 'object' "
            "AND scope ? 'kind' AND scope ? 'namespaces' "
            "AND scope->>'kind' IN ('namespaces', 'all_namespaces', 'cluster', 'non_resource') "
            "AND jsonb_typeof(scope->'namespaces') = 'array' "
            "AND ((scope->>'kind' = 'namespaces' AND jsonb_array_length(scope->'namespaces') > 0) "
            "OR (scope->>'kind' <> 'namespaces' AND jsonb_array_length(scope->'namespaces') = 0))",
            name="ck_kubernetes_grants_scope_shape",
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
    op.execute(
        """
        CREATE FUNCTION public.haku_0091_kubernetes_grant_source_invariants()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM public.mcp_tool_calls AS call
                JOIN public.mcp_tool_call_principals AS principal
                  ON principal.tool_call_id = call.tool_call_id
                JOIN public.credential_bindings AS binding
                  ON binding.binding_id = principal.binding_id
                JOIN public.agents AS agent
                  ON agent.agent_id = binding.agent_id
                WHERE call.tool_call_id = NEW.source_tool_call_id
                  AND binding.agent_id = NEW.agent_id
                  AND agent.status NOT IN ('abandoned', 'deleted')
                  AND call.server_id = 'kubernetes'
                  AND call.tool_name = 'create_grant'
                  AND call.status IN ('running', 'ok')
                  AND call.approved_at IS NOT NULL
                  AND call.approval_policy_id IS NULL
            ) THEN
                RAISE EXCEPTION 'invalid Kubernetes grant source provenance'
                    USING ERRCODE = 'check_violation',
                          CONSTRAINT = 'ck_kubernetes_grants_source_provenance';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_haku_0091_kubernetes_grant_source_invariants
        BEFORE INSERT OR UPDATE OF agent_id, source_tool_call_id ON public.kubernetes_grants
        FOR EACH ROW EXECUTE FUNCTION public.haku_0091_kubernetes_grant_source_invariants()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_haku_0091_kubernetes_grant_source_invariants ON public.kubernetes_grants")
    op.execute("DROP FUNCTION public.haku_0091_kubernetes_grant_source_invariants()")
    op.drop_index("idx_kubernetes_grants_agent_status_expiry", table_name="kubernetes_grants")
    op.drop_table("kubernetes_grants")
