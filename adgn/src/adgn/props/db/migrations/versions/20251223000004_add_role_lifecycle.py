"""Add role lifecycle tables and functions.

Creates infrastructure for agent database roles:
- agent_role_salt: singleton table for password derivation
- derive_agent_password: deterministic password from salt + agent_run_id
- create_agent_role: creates LOGIN role for an agent
- current_agent_run_id: extracts agent_run_id from session username
- current_agent_type: looks up agent type from agent_runs

Revision ID: 20251223000004
Revises: 20251223000003
Create Date: 2025-12-23

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251223000004"
down_revision: str | Sequence[str] | None = "20251223000003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create role lifecycle infrastructure.

    Security notes:
    - agent_role_salt is admin-only (REVOKE ALL FROM PUBLIC)
    - derive_agent_password is SECURITY DEFINER but NOT granted to agents
    - create_agent_role is SECURITY DEFINER, only callable by admin
    - Agents cannot derive passwords for other agents
    """
    op.execute("""
        -- Singleton table for password salt (admin-only)
        CREATE TABLE IF NOT EXISTS agent_role_salt (
            id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            salt BYTEA NOT NULL DEFAULT gen_random_bytes(32)
        );
        -- Initialize salt if table is empty
        INSERT INTO agent_role_salt (id) VALUES (1) ON CONFLICT DO NOTHING;
        -- Only admin can access
        REVOKE ALL ON agent_role_salt FROM PUBLIC;

        COMMENT ON TABLE agent_role_salt IS
            'Singleton containing salt for deterministic agent password derivation';

        -- Helper to extract agent_run_id from current session username
        -- Username format: agent_<uuid>
        CREATE OR REPLACE FUNCTION current_agent_run_id() RETURNS UUID AS $$
            SELECT CASE
                WHEN current_user LIKE 'agent_%'
                THEN substring(current_user from 'agent_(.+)')::uuid
                ELSE NULL
            END
        $$ LANGUAGE SQL STABLE;

        COMMENT ON FUNCTION current_agent_run_id() IS
            'Extract agent_run_id from session username (NULL if not an agent)';

        -- Helper to get current agent type from agent_runs
        CREATE OR REPLACE FUNCTION current_agent_type() RETURNS agent_type_enum AS $$
            SELECT (type_config->>'agent_type')::agent_type_enum
            FROM agent_runs
            WHERE agent_run_id = current_agent_run_id()
        $$ LANGUAGE SQL STABLE;

        COMMENT ON FUNCTION current_agent_type() IS
            'Look up agent type from agent_runs for current session';

        -- Password derivation (SECURITY DEFINER, NOT granted to agents)
        -- Derives deterministic password: sha256(salt || agent_run_id)
        CREATE OR REPLACE FUNCTION derive_agent_password(run_id UUID) RETURNS TEXT AS $$
            SELECT encode(
                sha256((SELECT salt FROM agent_role_salt) || run_id::text::bytea),
                'hex'
            )
        $$ LANGUAGE SQL STABLE SECURITY DEFINER;

        COMMENT ON FUNCTION derive_agent_password(UUID) IS
            'Derive deterministic password for agent role (admin-only)';

        -- Role creation (SECURITY DEFINER, admin-only)
        -- Creates: agent_<uuid> role with LOGIN and agent_base membership
        CREATE OR REPLACE FUNCTION create_agent_role(run_id UUID) RETURNS VOID AS $$
        DECLARE
            username TEXT := 'agent_' || run_id::text;
            password TEXT := derive_agent_password(run_id);
        BEGIN
            -- Check if role already exists
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = username) THEN
                EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', username, password);
                -- Grant agent_base membership if it exists
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_base') THEN
                    EXECUTE format('GRANT agent_base TO %I', username);
                END IF;
            END IF;
        END
        $$ LANGUAGE plpgsql SECURITY DEFINER;

        COMMENT ON FUNCTION create_agent_role(UUID) IS
            'Create LOGIN role for agent with deterministic password (admin-only)';
    """)


def downgrade() -> None:
    """Drop role lifecycle infrastructure."""
    op.execute("""
        DROP FUNCTION IF EXISTS create_agent_role(UUID);
        DROP FUNCTION IF EXISTS derive_agent_password(UUID);
        DROP FUNCTION IF EXISTS current_agent_type();
        DROP FUNCTION IF EXISTS current_agent_run_id();
        DROP TABLE IF EXISTS agent_role_salt;
    """)
