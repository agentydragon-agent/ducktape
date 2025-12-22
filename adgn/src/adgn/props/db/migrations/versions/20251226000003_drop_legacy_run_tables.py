"""Drop legacy run tables (critic_runs, grader_runs, prompt_optimization_runs).

This migration removes the legacy per-type run tables that have been replaced by
the unified agent_runs table. All data and functionality has been migrated:

- critic_runs → agent_runs with type_config->>'agent_type' = 'critic'
- grader_runs → agent_runs with type_config->>'agent_type' = 'grader'
- prompt_optimization_runs → agent_runs with type_config->>'agent_type' = 'prompt_optimizer'

The views were already updated in 20251226000002 to use agent_runs.
The grading_decisions FK was already updated in 20251226000000 to use agent_run_id.
The RLS policies were already updated in 20251226000001 to use agent_base role.

Also drops:
- Legacy template roles (critic_agent_template, grader_agent_template, etc.)
- Legacy RLS helper functions (current_critic_run_id, current_grader_run_id, etc.)

Revision ID: 20251226000003
Revises: 20251226000002
Create Date: 2025-12-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20251226000003"
down_revision: str | Sequence[str] | None = "20251226000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop legacy run tables and supporting objects."""
    # Step 1: Drop views that still reference legacy tables (should be none after 20251226000002)
    # Just in case, drop any remaining dependent objects
    op.execute("DROP VIEW IF EXISTS grading_credit_sums CASCADE")
    op.execute("DROP VIEW IF EXISTS run_costs CASCADE")
    op.execute("DROP VIEW IF EXISTS snapshot_files_with_issues CASCADE")

    # Step 2: Drop legacy RLS policies on grading_decisions (if any remain)
    op.execute("""
        DROP POLICY IF EXISTS grading_decisions_grader_select ON grading_decisions;
        DROP POLICY IF EXISTS grading_decisions_grader_insert ON grading_decisions;
        DROP POLICY IF EXISTS grading_decisions_grader_delete ON grading_decisions;
    """)

    # Step 3: Drop the legacy run tables
    # Order matters due to FK relationships:
    # grader_runs references critic_runs, so drop grader_runs first
    op.execute("DROP TABLE IF EXISTS grader_runs CASCADE")
    op.execute("DROP TABLE IF EXISTS critic_runs CASCADE")
    op.execute("DROP TABLE IF EXISTS prompt_optimization_runs CASCADE")

    # Step 4: Drop legacy RLS helper functions (keeping current_agent_run_id and current_agent_type)
    op.execute("""
        DROP FUNCTION IF EXISTS current_critic_run_id() CASCADE;
        DROP FUNCTION IF EXISTS current_grader_run_id() CASCADE;
        DROP FUNCTION IF EXISTS current_prompt_optimizer_run_id() CASCADE;
        DROP FUNCTION IF EXISTS current_clustering_run_id() CASCADE;
    """)

    # Step 5: Revoke privileges from legacy template roles in this database
    # These were replaced by agent_base in 20251226000001
    # NOTE: We only revoke privileges in the current database, not DROP the roles.
    # PostgreSQL roles are cluster-wide, so if the role has privileges in other databases,
    # we cannot drop the role from a migration. The roles can be manually cleaned up later
    # once privileges are revoked from all databases.
    op.execute("""
        DO $$
        DECLARE
            role_name TEXT;
            roles TEXT[] := ARRAY['critic_agent_template', 'grader_agent_template',
                                  'prompt_optimizer_agent_template', 'clustering_agent_template'];
        BEGIN
            FOREACH role_name IN ARRAY roles
            LOOP
                -- Check if role exists before revoking owned objects
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = role_name) THEN
                    -- DROP OWNED BY revokes all privileges granted to the role in the current database
                    -- This does NOT drop the role itself (which is cluster-wide)
                    EXECUTE format('DROP OWNED BY %I CASCADE', role_name);
                END IF;
            END LOOP;
        END
        $$;
    """)

    # Step 6: Drop the grader_run_status_enum type (no longer used)
    op.execute("DROP TYPE IF EXISTS grader_run_status_enum CASCADE")


def downgrade() -> None:
    """Recreate legacy run tables and supporting objects.

    WARNING: This downgrade does NOT restore data. It only recreates the schema.
    Data restoration would require a separate data migration.
    """
    # Step 1: Recreate grader_run_status_enum type
    op.execute("""
        CREATE TYPE grader_run_status_enum AS ENUM (
            'in_progress',
            'completed',
            'max_turns_exceeded'
        )
    """)

    # Step 2: Recreate legacy template roles
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'critic_agent_template') THEN
                CREATE ROLE critic_agent_template NOLOGIN;
            END IF;
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'grader_agent_template') THEN
                CREATE ROLE grader_agent_template NOLOGIN;
            END IF;
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'prompt_optimizer_agent_template') THEN
                CREATE ROLE prompt_optimizer_agent_template NOLOGIN;
            END IF;
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'clustering_agent_template') THEN
                CREATE ROLE clustering_agent_template NOLOGIN;
            END IF;
        END
        $$;
    """)

    # Step 3: Recreate legacy RLS helper functions
    op.execute("""
        CREATE OR REPLACE FUNCTION current_critic_run_id() RETURNS uuid
        LANGUAGE plpgsql STABLE
        AS $$
        DECLARE
            run_id_text TEXT;
        BEGIN
            run_id_text := SUBSTRING(current_user FROM 'critic_agent_([0-9a-f-]+)');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            RETURN run_id_text::UUID;
        END;
        $$;

        CREATE OR REPLACE FUNCTION current_grader_run_id() RETURNS uuid
        LANGUAGE plpgsql STABLE
        AS $$
        DECLARE
            run_id_text TEXT;
        BEGIN
            run_id_text := SUBSTRING(current_user FROM 'grader_agent_([0-9a-f-]+)');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            RETURN run_id_text::UUID;
        END;
        $$;

        CREATE OR REPLACE FUNCTION current_prompt_optimizer_run_id() RETURNS uuid
        LANGUAGE plpgsql STABLE
        AS $$
        DECLARE
            run_id_text TEXT;
        BEGIN
            run_id_text := SUBSTRING(current_user FROM 'prompt_optimizer_agent_([0-9a-f-]+)');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            RETURN run_id_text::UUID;
        END;
        $$;

        CREATE OR REPLACE FUNCTION current_clustering_run_id() RETURNS uuid
        LANGUAGE plpgsql STABLE
        AS $$
        DECLARE
            run_id_text TEXT;
        BEGIN
            run_id_text := SUBSTRING(current_user FROM 'clustering_agent_([0-9a-f-]+)');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            RETURN run_id_text::UUID;
        END;
        $$;
    """)

    # Step 4: Recreate critic_runs table
    op.execute("""
        CREATE TABLE critic_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            transcript_id UUID NOT NULL UNIQUE,
            snapshot_slug TEXT NOT NULL REFERENCES snapshots(slug) ON DELETE CASCADE,
            scope_hash TEXT NOT NULL,
            model VARCHAR NOT NULL,
            prompt_sha256 TEXT NOT NULL REFERENCES prompts(prompt_sha256),
            status critic_run_status_enum NOT NULL DEFAULT 'in_progress',
            completion_summary TEXT,
            notes_md TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMP WITH TIME ZONE,

            CONSTRAINT critic_runs_example_fk
                FOREIGN KEY (snapshot_slug, scope_hash) REFERENCES examples(snapshot_slug, scope_hash)
        );

        CREATE INDEX critic_runs_snapshot_slug_idx ON critic_runs(snapshot_slug);
        CREATE INDEX critic_runs_prompt_sha256_idx ON critic_runs(prompt_sha256);
        CREATE INDEX critic_runs_transcript_id_idx ON critic_runs(transcript_id);

        ALTER TABLE critic_runs ENABLE ROW LEVEL SECURITY;

        COMMENT ON TABLE critic_runs IS 'Legacy table for critic agent runs. Use agent_runs instead.';
    """)

    # Step 5: Recreate grader_runs table
    op.execute("""
        CREATE TABLE grader_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            transcript_id UUID NOT NULL UNIQUE,
            critic_run_id UUID NOT NULL REFERENCES critic_runs(id) ON DELETE CASCADE,
            snapshot_slug TEXT NOT NULL REFERENCES snapshots(slug) ON DELETE CASCADE,
            model VARCHAR NOT NULL,
            status grader_run_status_enum NOT NULL DEFAULT 'in_progress',
            output JSONB,
            notes_md TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMP WITH TIME ZONE
        );

        CREATE INDEX grader_runs_critic_run_id_idx ON grader_runs(critic_run_id);
        CREATE INDEX grader_runs_snapshot_slug_idx ON grader_runs(snapshot_slug);
        CREATE INDEX grader_runs_transcript_id_idx ON grader_runs(transcript_id);

        ALTER TABLE grader_runs ENABLE ROW LEVEL SECURITY;

        COMMENT ON TABLE grader_runs IS 'Legacy table for grader agent runs. Use agent_runs instead.';
    """)

    # Step 6: Recreate prompt_optimization_runs table
    op.execute("""
        CREATE TABLE prompt_optimization_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            transcript_id UUID NOT NULL UNIQUE,
            model VARCHAR NOT NULL,
            target_metric VARCHAR NOT NULL,
            status VARCHAR NOT NULL DEFAULT 'in_progress',
            budget_limit FLOAT,
            budget_spent FLOAT DEFAULT 0.0,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMP WITH TIME ZONE
        );

        CREATE INDEX prompt_optimization_runs_transcript_id_idx ON prompt_optimization_runs(transcript_id);

        ALTER TABLE prompt_optimization_runs ENABLE ROW LEVEL SECURITY;

        COMMENT ON TABLE prompt_optimization_runs IS 'Legacy table for prompt optimizer runs. Use agent_runs instead.';
    """)

    # Step 7: Recreate RLS policies for grading_decisions to use legacy pattern
    # Note: grading_decisions still has agent_run_id column at this point
    # The policies use agent_run_id which matches grader_runs.transcript_id
    op.execute("""
        DROP POLICY IF EXISTS grading_decisions_agent_select ON grading_decisions;
        DROP POLICY IF EXISTS grading_decisions_agent_insert ON grading_decisions;
        DROP POLICY IF EXISTS grading_decisions_agent_delete ON grading_decisions;

        -- During downgrade transition, decisions are accessible via grader_runs.transcript_id = agent_run_id
        CREATE POLICY grading_decisions_grader_select ON grading_decisions
            FOR SELECT
            USING (agent_run_id = current_grader_run_id());

        CREATE POLICY grading_decisions_grader_insert ON grading_decisions
            FOR INSERT
            WITH CHECK (agent_run_id = current_grader_run_id());

        CREATE POLICY grading_decisions_grader_delete ON grading_decisions
            FOR DELETE
            USING (agent_run_id = current_grader_run_id());
    """)
