"""Add run_costs view for token usage and cost tracking.

Revision ID: 20260101000001
Revises: 20260101000000
Create Date: 2026-01-01 00:00:01.000000

Creates two views:
1. event_costs: Per-event cost calculation (low-level, joins events with model_metadata)
2. run_costs: Aggregated costs per agent run including all transitive child runs
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260101000001"
down_revision: str = "20260101000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create event_costs and run_costs views."""
    # Step 1: Create event_costs view (per-event cost calculation)
    op.execute("""
        CREATE VIEW event_costs AS
        SELECT
            (events.payload->'response_id')::text AS response_id,
            events.agent_run_id,
            ((events.payload->'usage'->'model')::text) AS model,
            ((events.payload->'usage'->'input_tokens')::text)::integer AS input_tokens,
            COALESCE(((events.payload->'usage'->'input_tokens_details'->'cached_tokens')::text)::integer, 0) AS cached_tokens,
            ((events.payload->'usage'->'output_tokens')::text)::integer AS output_tokens,
            COALESCE(((events.payload->'usage'->'output_tokens_details'->'reasoning_tokens')::text)::integer, 0) AS reasoning_tokens,
            (
                (((events.payload->'usage'->'input_tokens')::text)::integer -
                 COALESCE(((events.payload->'usage'->'input_tokens_details'->'cached_tokens')::text)::integer, 0))::float
                * model_metadata.input_usd_per_1m_tokens / 1000000.0
                +
                COALESCE(((events.payload->'usage'->'input_tokens_details'->'cached_tokens')::text)::integer, 0)::float
                * model_metadata.cached_input_usd_per_1m_tokens / 1000000.0
                +
                ((events.payload->'usage'->'output_tokens')::text)::integer::float
                * model_metadata.output_usd_per_1m_tokens / 1000000.0
            ) AS cost_usd,
            events.timestamp
        FROM events
        JOIN model_metadata ON ((events.payload->'usage'->'model')::text) = model_metadata.model_id
        WHERE events.event_type = 'response' AND events.payload->'usage' IS NOT NULL
    """)

    # Step 2: Create run_costs view (aggregated costs including transitive children)
    # Groups by model so queries can see per-model breakdown
    op.execute("""
        CREATE VIEW run_costs AS
        WITH RECURSIVE run_tree AS (
            -- Base case: the run itself
            SELECT agent_run_id, agent_run_id AS root_run_id
            FROM agent_runs

            UNION ALL

            -- Recursive case: children of runs already in the tree
            SELECT ar.agent_run_id, rt.root_run_id
            FROM agent_runs ar
            JOIN run_tree rt ON ar.parent_agent_run_id = rt.agent_run_id
        )
        SELECT
            rt.root_run_id AS agent_run_id,
            ec.model,
            SUM(ec.input_tokens) AS input_tokens,
            SUM(ec.cached_tokens) AS cached_tokens,
            SUM(ec.output_tokens) AS output_tokens,
            SUM(ec.reasoning_tokens) AS reasoning_tokens,
            SUM(ec.cost_usd) AS cost_usd
        FROM run_tree rt
        JOIN event_costs ec ON ec.agent_run_id = rt.agent_run_id
        GROUP BY rt.root_run_id, ec.model
    """)


def downgrade() -> None:
    """Drop run_costs and event_costs views."""
    op.execute("DROP VIEW IF EXISTS run_costs CASCADE")
    op.execute("DROP VIEW IF EXISTS event_costs CASCADE")
