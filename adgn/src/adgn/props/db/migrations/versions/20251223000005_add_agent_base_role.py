"""Add agent_base role with basic permissions.

Creates the base role that all agent roles inherit from. Individual
agent roles (agent_<uuid>) inherit from this role and get type-specific
access via RLS policies.

Revision ID: 20251223000005
Revises: 20251223000004
Create Date: 2025-12-23

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251223000005"
down_revision: str | Sequence[str] | None = "20251223000004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create agent_base role with schema access and basic permissions.

    Permissions:
    - USAGE on public schema
    - SELECT on agent_definitions (all agents can read definitions)
    - SELECT on agent_runs (all agents can read their own run)
    - INSERT on agent_definitions (agents can create new definitions)
    - RLS policies filter access based on agent type and run ID
    """
    op.execute("""
        -- Create base role if not exists
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'agent_base') THEN
                CREATE ROLE agent_base NOLOGIN;
            END IF;
        END
        $$;

        -- Basic schema access
        GRANT USAGE ON SCHEMA public TO agent_base;

        -- All agents can read definitions
        GRANT SELECT ON TABLE agent_definitions TO agent_base;

        -- All agents can read agent_runs (RLS will filter)
        GRANT SELECT ON TABLE agent_runs TO agent_base;

        -- All agents can insert definitions (with provenance tracking)
        GRANT INSERT ON TABLE agent_definitions TO agent_base;

        -- Enable RLS on agent tables
        ALTER TABLE agent_definitions ENABLE ROW LEVEL SECURITY;
        ALTER TABLE agent_runs ENABLE ROW LEVEL SECURITY;

        -- Policy: agents can read all definitions
        DROP POLICY IF EXISTS agent_definitions_select ON agent_definitions;
        CREATE POLICY agent_definitions_select ON agent_definitions
            FOR SELECT
            USING (true);

        -- Policy: agents can insert definitions only with their own run_id as creator
        DROP POLICY IF EXISTS agent_definitions_insert ON agent_definitions;
        CREATE POLICY agent_definitions_insert ON agent_definitions
            FOR INSERT
            WITH CHECK (created_by_agent_run_id = current_agent_run_id());

        -- Policy: agents can read their own run record
        DROP POLICY IF EXISTS agent_runs_select_own ON agent_runs;
        CREATE POLICY agent_runs_select_own ON agent_runs
            FOR SELECT
            USING (agent_run_id = current_agent_run_id());

        -- Policy: agents can read runs they spawned (sub-agents)
        DROP POLICY IF EXISTS agent_runs_select_children ON agent_runs;
        CREATE POLICY agent_runs_select_children ON agent_runs
            FOR SELECT
            USING (parent_agent_run_id = current_agent_run_id());

        COMMENT ON ROLE agent_base IS
            'Base role for all agent users - grants schema access and basic permissions';
    """)


def downgrade() -> None:
    """Drop agent_base role and policies."""
    op.execute("""
        -- Drop policies
        DROP POLICY IF EXISTS agent_runs_select_children ON agent_runs;
        DROP POLICY IF EXISTS agent_runs_select_own ON agent_runs;
        DROP POLICY IF EXISTS agent_definitions_insert ON agent_definitions;
        DROP POLICY IF EXISTS agent_definitions_select ON agent_definitions;

        -- Disable RLS
        ALTER TABLE agent_runs DISABLE ROW LEVEL SECURITY;
        ALTER TABLE agent_definitions DISABLE ROW LEVEL SECURITY;

        -- Revoke grants and drop role
        REVOKE ALL ON TABLE agent_runs FROM agent_base;
        REVOKE ALL ON TABLE agent_definitions FROM agent_base;
        REVOKE USAGE ON SCHEMA public FROM agent_base;
        DROP ROLE IF EXISTS agent_base;
    """)
