"""Add agent_definitions table.

Creates the table storing agent definition archives (tar files containing
AGENT.md, init, tools, etc.). Each definition has a type and optional
provenance linking to the agent that created it.

Revision ID: 20251223000002
Revises: 20251223000001
Create Date: 2025-12-23

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251223000002"
down_revision: str | Sequence[str] | None = "20251223000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create agent_definitions table.

    Columns:
    - id: readable name ('critic', 'grader') or auto-generated ('critic_a1b2c3')
    - agent_type: enum from agent_type_enum
    - archive: uncompressed tar containing AGENT.md, init, tools/, etc.
    - created_at: timestamp
    - created_by_agent_run_id: provenance (NULL for repo-backed definitions)
    """
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_definitions (
            id TEXT PRIMARY KEY,
            agent_type agent_type_enum NOT NULL,
            archive BYTEA NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by_agent_run_id UUID
            -- FK to agent_runs added after agent_runs table exists
        );

        CREATE INDEX IF NOT EXISTS idx_agent_definitions_type
            ON agent_definitions(agent_type);

        CREATE INDEX IF NOT EXISTS idx_agent_definitions_created_by
            ON agent_definitions(created_by_agent_run_id)
            WHERE created_by_agent_run_id IS NOT NULL;

        COMMENT ON TABLE agent_definitions IS
            'Agent definition archives containing AGENT.md, init script, and tools';
        COMMENT ON COLUMN agent_definitions.id IS
            'Readable ID: repo-backed use names like "critic", agent-created use auto-generated';
        COMMENT ON COLUMN agent_definitions.archive IS
            'Uncompressed tar archive of the definition directory';
        COMMENT ON COLUMN agent_definitions.created_by_agent_run_id IS
            'Agent run that created this definition (NULL for repo-backed)';
    """)


def downgrade() -> None:
    """Drop agent_definitions table."""
    op.execute("DROP TABLE IF EXISTS agent_definitions")
