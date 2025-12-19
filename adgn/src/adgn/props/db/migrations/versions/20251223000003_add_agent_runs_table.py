"""Add agent_runs unified table.

Creates the unified agent_runs table that replaces separate tables for
critic_runs, grader_runs, etc. Each run references an agent definition
and stores type-specific config as JSONB.

Revision ID: 20251223000003
Revises: 20251223000002
Create Date: 2025-12-23

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251223000003"
down_revision: str | Sequence[str] | None = "20251223000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create agent_runs table.

    Columns:
    - agent_run_id: UUID primary key
    - agent_definition_id: FK to agent_definitions
    - parent_agent_run_id: FK to parent agent (for sub-agents)
    - model: LLM model used
    - type_config: JSONB with agent_type discriminator + type-specific fields
    - created_at: timestamp

    Indexes:
    - type extraction from JSONB for filtering
    - parent lookup for lineage queries
    - snapshot slug for critic lookups
    """
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_runs (
            agent_run_id UUID PRIMARY KEY,
            agent_definition_id TEXT NOT NULL REFERENCES agent_definitions(id),
            parent_agent_run_id UUID REFERENCES agent_runs(agent_run_id),
            model TEXT NOT NULL,
            type_config JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        -- Index for filtering by agent type
        CREATE INDEX IF NOT EXISTS idx_agent_runs_type
            ON agent_runs((type_config->>'agent_type'));

        -- Index for parent lookup (sub-agent lineage)
        CREATE INDEX IF NOT EXISTS idx_agent_runs_parent
            ON agent_runs(parent_agent_run_id)
            WHERE parent_agent_run_id IS NOT NULL;

        -- Partial index for critic snapshot lookups
        CREATE INDEX IF NOT EXISTS idx_agent_runs_snapshot
            ON agent_runs((type_config->>'snapshot_slug'))
            WHERE type_config->>'agent_type' = 'critic';

        -- Add FK from agent_definitions.created_by_agent_run_id
        ALTER TABLE agent_definitions
            ADD CONSTRAINT fk_agent_definitions_created_by
            FOREIGN KEY (created_by_agent_run_id) REFERENCES agent_runs(agent_run_id);

        COMMENT ON TABLE agent_runs IS
            'Unified table for all agent runs (critics, graders, optimizers, freeform)';
        COMMENT ON COLUMN agent_runs.type_config IS
            'JSONB with agent_type discriminator and type-specific fields';
        COMMENT ON COLUMN agent_runs.parent_agent_run_id IS
            'Parent agent that spawned this sub-agent (NULL for top-level)';
    """)


def downgrade() -> None:
    """Drop agent_runs table and FK constraint."""
    op.execute("""
        ALTER TABLE agent_definitions
            DROP CONSTRAINT IF EXISTS fk_agent_definitions_created_by;
        DROP TABLE IF EXISTS agent_runs;
    """)
