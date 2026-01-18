"""Add llm_requests table and container log columns.

Revision ID: 20260118_llm_requests_and_logs
Revises: 20260113_proxy_agent_definitions
Create Date: 2026-01-18

Combines:
- llm_requests table for LLM proxy logging
- container_stdout/container_stderr columns on agent_runs

The llm_requests table stores full request/response payloads. Token counts
are computed via the llm_request_costs view from response_body->'usage'.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision = "20260118_llm_requests_and_logs"
down_revision = "20260113_proxy_agent_definitions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create llm_requests table, views, and container log columns."""
    # Create llm_requests table (token columns computed via view from response_body)
    op.create_table(
        "llm_requests",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "agent_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.agent_run_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("model", sa.String, nullable=False, index=True),
        sa.Column("request_body", JSONB, nullable=False),
        sa.Column("response_body", JSONB, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP,
            nullable=False,
            server_default=sa.func.now(),
        ),
        comment="LLM API requests logged by the proxy. Token counts computed via llm_request_costs view.",
    )

    # Index for querying by agent run (most common access pattern)
    op.create_index(
        "ix_llm_requests_agent_run_created",
        "llm_requests",
        ["agent_run_id", "created_at"],
    )

    # Enable RLS
    op.execute("ALTER TABLE llm_requests ENABLE ROW LEVEL SECURITY")

    # Create function to check if ancestor_id is in the parent chain of descendant_id
    op.execute("""
        CREATE OR REPLACE FUNCTION is_agent_ancestor(ancestor_id UUID, descendant_id UUID)
        RETURNS BOOLEAN AS $$
        WITH RECURSIVE ancestors AS (
            -- Base case: the descendant itself
            SELECT agent_run_id, parent_agent_run_id
            FROM agent_runs
            WHERE agent_run_id = descendant_id

            UNION ALL

            -- Recursive case: walk up the parent chain
            SELECT ar.agent_run_id, ar.parent_agent_run_id
            FROM agent_runs ar
            JOIN ancestors a ON ar.agent_run_id = a.parent_agent_run_id
        )
        SELECT EXISTS (
            SELECT 1 FROM ancestors WHERE agent_run_id = ancestor_id
        );
        $$ LANGUAGE SQL STABLE SECURITY DEFINER;
    """)

    # RLS policy: agents can see their own requests and their subagents' requests
    op.execute("""
        CREATE POLICY llm_requests_select ON llm_requests FOR SELECT USING (
            current_agent_run_id() IS NULL  -- Admin can see all
            OR is_agent_ancestor(current_agent_run_id(), agent_run_id)  -- Agent sees own + descendants
        )
    """)

    # Only proxy (admin) can insert
    op.execute("""
        CREATE POLICY llm_requests_insert ON llm_requests FOR INSERT WITH CHECK (
            current_agent_run_id() IS NULL  -- Only admin/proxy can insert
        )
    """)

    # Create view for computing costs - extracts tokens from response_body->'usage'
    op.execute("""
        CREATE OR REPLACE VIEW llm_request_costs AS
        SELECT
            r.id,
            r.agent_run_id,
            r.model,
            (r.response_body->'usage'->>'input_tokens')::integer AS input_tokens,
            (r.response_body->'usage'->>'input_tokens_details'->>'cached_tokens')::integer AS cached_input_tokens,
            (r.response_body->'usage'->>'output_tokens')::integer AS output_tokens,
            r.latency_ms,
            r.created_at,
            -- Cost calculation using model_metadata pricing
            COALESCE(
                ((r.response_body->'usage'->>'input_tokens')::integer
                    - COALESCE((r.response_body->'usage'->'input_tokens_details'->>'cached_tokens')::integer, 0))
                    * m.input_usd_per_1m_tokens / 1000000.0
                + COALESCE((r.response_body->'usage'->'input_tokens_details'->>'cached_tokens')::integer, 0)
                    * m.cached_input_usd_per_1m_tokens / 1000000.0
                + (r.response_body->'usage'->>'output_tokens')::integer
                    * m.output_usd_per_1m_tokens / 1000000.0,
                0
            ) AS cost_usd
        FROM llm_requests r
        LEFT JOIN model_metadata m ON r.model = m.model_id
    """)

    # Create view for aggregated costs per agent run
    op.execute("""
        CREATE OR REPLACE VIEW llm_run_costs AS
        SELECT
            agent_run_id,
            model,
            SUM(input_tokens) AS input_tokens,
            SUM(cached_input_tokens) AS cached_input_tokens,
            SUM(output_tokens) AS output_tokens,
            SUM(cost_usd) AS cost_usd,
            COUNT(*) AS request_count
        FROM llm_request_costs
        GROUP BY agent_run_id, model
    """)

    # Add container log columns to agent_runs
    op.add_column("agent_runs", sa.Column("container_stdout", sa.Text(), nullable=True))
    op.add_column("agent_runs", sa.Column("container_stderr", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove llm_requests table, views, and container log columns."""
    # Remove container log columns
    op.drop_column("agent_runs", "container_stderr")
    op.drop_column("agent_runs", "container_stdout")

    # Drop views and table
    op.execute("DROP VIEW IF EXISTS llm_run_costs")
    op.execute("DROP VIEW IF EXISTS llm_request_costs")
    op.execute("DROP POLICY IF EXISTS llm_requests_insert ON llm_requests")
    op.execute("DROP POLICY IF EXISTS llm_requests_select ON llm_requests")
    op.drop_table("llm_requests")
    op.execute("DROP FUNCTION IF EXISTS is_agent_ancestor(UUID, UUID)")
