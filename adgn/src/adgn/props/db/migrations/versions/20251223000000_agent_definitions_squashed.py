"""Unified agent system infrastructure (squashed).

This migration combines:
- agent_type_enum PostgreSQL type
- get_validation_run_aggregates() with scope filtering
- agent_definitions table
- agent_runs unified table
- Role lifecycle (salt, functions)
- agent_base role with RLS policies

Revision ID: 20251223000000
Revises: 20251222000003
Create Date: 2025-12-23 (squashed 2025-12-19)
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20251223000000"
down_revision: str | Sequence[str] | None = "20251222000003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create unified agent system infrastructure.

    Order matters:
    1. agent_type_enum (used by agent_definitions.agent_type)
    2. agent_definitions table (referenced by agent_runs)
    3. agent_runs table (used by functions and policies)
    4. Role lifecycle functions (use agent_runs)
    5. agent_base role and RLS policies
    6. get_validation_run_aggregates() (uses existing scope_kind_enum)
    """
    # 1. Create agent_type_enum
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'agent_type_enum') THEN
                CREATE TYPE agent_type_enum AS ENUM (
                    'critic',
                    'grader',
                    'prompt_optimizer',
                    'clustering',
                    'freeform'
                );
            END IF;
        END
        $$
    """)

    # 2. Create agent_definitions table
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

    # 3. Create agent_runs table
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

    # 4. Create role lifecycle infrastructure
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

    # 5. Create agent_base role and RLS policies
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

    # 6. Recreate get_validation_run_aggregates() with scope filtering
    # Uses TEXT for scope_kind (derived from JSONB), not an enum
    op.execute("DROP FUNCTION IF EXISTS get_validation_run_aggregates() CASCADE")

    op.execute("""
        CREATE FUNCTION get_validation_run_aggregates()
        RETURNS TABLE(
            snapshot_slug text,
            prompt_sha256 text,
            critic_model text,
            grader_model text,
            critic_run_id uuid,
            grader_run_id uuid,
            status critic_run_status_enum,
            scope_kind text,
            scope_hash text,
            total_credit double precision,
            n_occurrences integer
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path TO 'public'
        AS $$
          WITH occurrence_avg_credits AS (
            SELECT
                oc.snapshot_slug,
                oc.prompt_sha256,
                oc.critic_model,
                oc.grader_model,
                oc.critic_run_id,
                oc.grader_run_id,
                cr.status,
                oc.scope_kind,
                oc.scope_hash,
                oc.tp_id,
                oc.occurrence_id,
                AVG(oc.found_credit) as avg_credit
            FROM occurrence_credits oc
            JOIN snapshots s ON oc.snapshot_slug = s.slug
            JOIN critic_runs cr ON oc.critic_run_id = cr.id
            WHERE s.split = 'valid'::split_enum
              AND (
                -- whole-repo mode: only entire_snapshot
                (current_prompt_optimizer_target_metric() = 'whole-repo'
                 AND oc.scope_kind = 'entire_snapshot')
                OR
                -- targeted mode: both scope kinds
                (current_prompt_optimizer_target_metric() = 'targeted')
                OR
                -- no prompt optimizer context: default to entire_snapshot only
                (current_prompt_optimizer_target_metric() IS NULL
                 AND oc.scope_kind = 'entire_snapshot')
              )
            GROUP BY oc.snapshot_slug, oc.prompt_sha256, oc.critic_model, oc.grader_model,
                     oc.critic_run_id, oc.grader_run_id, cr.status, oc.scope_kind,
                     oc.scope_hash, oc.tp_id, oc.occurrence_id
          )
          SELECT
            snapshot_slug,
            prompt_sha256,
            critic_model,
            grader_model,
            critic_run_id,
            grader_run_id,
            status,
            scope_kind,
            scope_hash,
            SUM(avg_credit) as total_credit,
            CAST(COUNT(*) AS integer) as n_occurrences
          FROM occurrence_avg_credits
          GROUP BY snapshot_slug, prompt_sha256, critic_model, grader_model,
                   critic_run_id, grader_run_id, status, scope_kind, scope_hash
          ORDER BY snapshot_slug, prompt_sha256, critic_model, grader_model,
                   critic_run_id, grader_run_id, scope_kind, scope_hash
        $$;
    """)

    op.execute("""
        COMMENT ON FUNCTION get_validation_run_aggregates() IS
        'Validation metrics filtered by prompt optimizer target_metric.
        Returns per-run recall for VALID split, grouped by scope.
        - whole-repo mode: only entire_snapshot scope_kind
        - targeted mode: both entire_snapshot and explicit_file scope_kinds
        - no context: defaults to entire_snapshot only
        SECURITY DEFINER bypasses RLS to access validation data.'
    """)


def downgrade() -> None:
    """Drop all unified agent infrastructure."""
    # Restore previous get_validation_run_aggregates()
    op.execute("DROP FUNCTION IF EXISTS get_validation_run_aggregates() CASCADE")
    op.execute("""
        CREATE FUNCTION get_validation_run_aggregates()
        RETURNS TABLE(
            snapshot_slug text,
            prompt_sha256 text,
            critic_model text,
            grader_model text,
            critic_run_id uuid,
            grader_run_id uuid,
            status critic_run_status_enum,
            total_credit double precision,
            n_occurrences integer
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path TO 'public'
        AS $$
          WITH occurrence_avg_credits AS (
            SELECT
                oc.snapshot_slug,
                oc.prompt_sha256,
                oc.critic_model,
                oc.grader_model,
                oc.critic_run_id,
                oc.grader_run_id,
                cr.status,
                oc.tp_id,
                oc.occurrence_id,
                AVG(oc.found_credit) as avg_credit
            FROM occurrence_credits oc
            JOIN snapshots s ON oc.snapshot_slug = s.slug
            JOIN critic_runs cr ON oc.critic_run_id = cr.id
            WHERE s.split = 'valid'::split_enum
              AND oc.scope_kind = 'entire_snapshot'
            GROUP BY oc.snapshot_slug, oc.prompt_sha256, oc.critic_model, oc.grader_model,
                     oc.critic_run_id, oc.grader_run_id, cr.status, oc.tp_id, oc.occurrence_id
          )
          SELECT
            snapshot_slug,
            prompt_sha256,
            critic_model,
            grader_model,
            critic_run_id,
            grader_run_id,
            status,
            SUM(avg_credit) as total_credit,
            CAST(COUNT(*) AS integer) as n_occurrences
          FROM occurrence_avg_credits
          GROUP BY snapshot_slug, prompt_sha256, critic_model, grader_model,
                   critic_run_id, grader_run_id, status
          ORDER BY snapshot_slug, prompt_sha256, critic_model, grader_model,
                   critic_run_id, grader_run_id
        $$;
    """)

    # Drop RLS policies
    op.execute("""
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

    # Drop role lifecycle
    op.execute("""
        DROP FUNCTION IF EXISTS create_agent_role(UUID);
        DROP FUNCTION IF EXISTS derive_agent_password(UUID);
        DROP FUNCTION IF EXISTS current_agent_type();
        DROP FUNCTION IF EXISTS current_agent_run_id();
        DROP TABLE IF EXISTS agent_role_salt;
    """)

    # Drop FK constraint before dropping agent_runs
    op.execute("""
        ALTER TABLE agent_definitions
            DROP CONSTRAINT IF EXISTS fk_agent_definitions_created_by;
    """)

    # Drop tables
    op.execute("DROP TABLE IF EXISTS agent_runs")
    op.execute("DROP TABLE IF EXISTS agent_definitions")

    # Drop enum
    op.execute("DROP TYPE IF EXISTS agent_type_enum")
