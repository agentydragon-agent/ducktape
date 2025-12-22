"""Migrate improvement_runs to unified agent_runs table.

Revision ID: 20251230000000
Revises: 20251229000004
Create Date: 2025-12-30

This migration removes the legacy improvement_runs infrastructure:
1. Drop prompts.improvement_run_id FK (column kept for backward compat)
2. Drop old improvement-specific RLS policies
3. Drop old helper functions
4. Drop old template role
5. Drop improvement_runs table and enum
6. Create new RLS helper functions for improvement agents
7. Update existing RLS policies to include improvement agent access

Note: improvement_runs table is empty so no data migration needed.
Improvement agents will use agent_runs with ImprovementTypeConfig going forward.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20251230000000"
down_revision: str | Sequence[str] | None = "20251229000004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop improvement_runs and set up unified RLS for improvement agents."""
    # 1. Drop prompts FK constraint (column kept for backward compat)
    op.execute("ALTER TABLE prompts DROP CONSTRAINT IF EXISTS prompts_improvement_run_id_fkey")

    # 2. Drop old RLS policies for improvement_agent_template
    op.execute("DROP POLICY IF EXISTS improvement_examples_policy ON examples")
    op.execute("DROP POLICY IF EXISTS improvement_snapshots_policy ON snapshots")
    op.execute("DROP POLICY IF EXISTS improvement_true_positives_policy ON true_positives")
    op.execute("DROP POLICY IF EXISTS improvement_false_positives_policy ON false_positives")
    op.execute("DROP POLICY IF EXISTS improvement_critic_runs_policy ON critic_runs")
    op.execute("DROP POLICY IF EXISTS improvement_grader_runs_policy ON grader_runs")
    op.execute("DROP POLICY IF EXISTS improvement_events_policy ON events")

    # 3. Drop old helper functions
    op.execute("DROP FUNCTION IF EXISTS current_improvement_run_id()")
    op.execute("DROP FUNCTION IF EXISTS is_improvement_example_allowed(TEXT, TEXT)")
    op.execute("DROP FUNCTION IF EXISTS is_improvement_snapshot_allowed(TEXT)")

    # 4. Revoke privileges and drop old template role (if it exists)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'improvement_agent_template') THEN
                REVOKE ALL PRIVILEGES ON SCHEMA public FROM improvement_agent_template;
                REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM improvement_agent_template;
            END IF;
        END
        $$
    """)
    op.execute("DROP ROLE IF EXISTS improvement_agent_template")

    # 5. Drop old table and enum (table is empty, no data to preserve)
    op.execute("DROP INDEX IF EXISTS ix_improvement_runs_id")
    op.execute("DROP TABLE IF EXISTS improvement_runs")
    op.execute("DROP TYPE IF EXISTS improvement_run_status_enum")

    # 6. Create SECURITY DEFINER helpers to access agent_runs without RLS recursion
    # These functions bypass RLS when called from within RLS policies

    # 6a. Get current agent's type_config
    op.execute("""
        CREATE OR REPLACE FUNCTION current_agent_type_config() RETURNS JSONB
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $$
        DECLARE
            run_id_text TEXT;
            run_id UUID;
            config JSONB;
        BEGIN
            run_id_text := SUBSTRING(session_user FROM 'agent_([0-9a-f-]+)');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            run_id := run_id_text::UUID;

            SELECT type_config INTO config
            FROM agent_runs
            WHERE agent_run_id = run_id;

            RETURN config;
        END;
        $$;

        COMMENT ON FUNCTION current_agent_type_config() IS
            'Returns type_config JSONB for current agent. SECURITY DEFINER to bypass RLS on agent_runs. Returns NULL for non-agents.';
    """)

    # 6b. Get type_config for a specific agent_run_id (used by grader to access graded run's config)
    op.execute("""
        CREATE OR REPLACE FUNCTION get_agent_type_config(p_agent_run_id UUID) RETURNS JSONB
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $$
        DECLARE
            config JSONB;
        BEGIN
            SELECT type_config INTO config
            FROM agent_runs
            WHERE agent_run_id = p_agent_run_id;

            RETURN config;
        END;
        $$;

        COMMENT ON FUNCTION get_agent_type_config(UUID) IS
            'Returns type_config JSONB for given agent_run_id. SECURITY DEFINER to bypass RLS on agent_runs.';
    """)

    # 6c. Get agent_run_ids matching criteria (for events policy - avoids subquery to agent_runs)
    op.execute("""
        CREATE OR REPLACE FUNCTION get_agent_run_ids_for_train_snapshots() RETURNS SETOF UUID
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $$
        BEGIN
            RETURN QUERY
            SELECT agent_run_id
            FROM agent_runs
            WHERE type_config->>'agent_type' IN ('critic', 'grader')
              AND type_config->>'snapshot_slug' IN (SELECT slug FROM snapshots WHERE split = 'train');
        END;
        $$;

        COMMENT ON FUNCTION get_agent_run_ids_for_train_snapshots() IS
            'Returns agent_run_ids for critic/grader runs on TRAIN snapshots. SECURITY DEFINER to bypass RLS.';
    """)

    # 6d. Get agent_run_ids for allowed improvement examples
    op.execute("""
        CREATE OR REPLACE FUNCTION get_agent_run_ids_for_improvement_allowed() RETURNS SETOF UUID
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $$
        DECLARE
            config JSONB;
            allowed JSONB;
        BEGIN
            config := current_agent_type_config();
            IF config IS NULL OR config->>'agent_type' != 'improvement' THEN
                RETURN;
            END IF;

            allowed := config->'allowed_examples';
            IF allowed IS NULL THEN
                RETURN;
            END IF;

            RETURN QUERY
            SELECT ar.agent_run_id
            FROM agent_runs ar
            WHERE ar.type_config->>'agent_type' IN ('critic', 'grader')
              AND EXISTS (
                  SELECT 1 FROM jsonb_array_elements(allowed) elem
                  WHERE elem->>'snapshot_slug' = ar.type_config->>'snapshot_slug'
                    AND elem->>'scope_hash' = ar.type_config->>'scope_hash'
              );
        END;
        $$;

        COMMENT ON FUNCTION get_agent_run_ids_for_improvement_allowed() IS
            'Returns agent_run_ids for critic/grader runs that match current improvement agent allowed_examples. SECURITY DEFINER to bypass RLS.';
    """)

    # 7. Create helper function to check allowed_examples from type_config
    # Uses SECURITY DEFINER current_agent_type_config() to avoid RLS recursion
    op.execute("""
        CREATE OR REPLACE FUNCTION is_agent_example_allowed(p_snapshot_slug TEXT, p_scope_hash TEXT)
        RETURNS boolean
        LANGUAGE plpgsql STABLE
        AS $$
        DECLARE
            config JSONB;
            allowed JSONB;
            agent_type TEXT;
        BEGIN
            config := current_agent_type_config();
            IF config IS NULL THEN
                RETURN FALSE;
            END IF;

            agent_type := config->>'agent_type';
            -- Only for improvement agents
            IF agent_type != 'improvement' THEN
                RETURN FALSE;
            END IF;

            allowed := config->'allowed_examples';
            IF allowed IS NULL THEN
                RETURN FALSE;
            END IF;

            RETURN EXISTS (
                SELECT 1 FROM jsonb_array_elements(allowed) elem
                WHERE elem->>'snapshot_slug' = p_snapshot_slug
                  AND elem->>'scope_hash' = p_scope_hash
            );
        END;
        $$
    """)

    # 8. Create helper for snapshot-level access
    # Uses SECURITY DEFINER current_agent_type_config() to avoid RLS recursion
    op.execute("""
        CREATE OR REPLACE FUNCTION is_agent_snapshot_allowed(p_slug TEXT)
        RETURNS boolean
        LANGUAGE plpgsql STABLE
        AS $$
        DECLARE
            config JSONB;
            allowed JSONB;
            agent_type TEXT;
        BEGIN
            config := current_agent_type_config();
            IF config IS NULL THEN
                RETURN FALSE;
            END IF;

            agent_type := config->>'agent_type';
            IF agent_type != 'improvement' THEN
                RETURN FALSE;
            END IF;

            allowed := config->'allowed_examples';
            IF allowed IS NULL THEN
                RETURN FALSE;
            END IF;

            RETURN EXISTS (
                SELECT 1 FROM jsonb_array_elements(allowed) elem
                WHERE elem->>'snapshot_slug' = p_slug
            );
        END;
        $$
    """)

    # 9. Update RLS policies to include improvement agent access
    # Uses current_agent_type_config() (SECURITY DEFINER) to avoid RLS recursion on agent_runs

    # Examples: improvement agents can access their allowed examples
    op.execute("DROP POLICY IF EXISTS examples_agent_select ON examples")
    op.execute("""
        CREATE POLICY examples_agent_select ON examples
            FOR SELECT
            USING (
                -- Critics/Clustering: match their assigned scope
                (
                    (current_agent_type_config()->>'agent_type') IN ('critic', 'clustering')
                    AND snapshot_slug = (current_agent_type_config()->>'snapshot_slug')
                    AND scope_hash = (current_agent_type_config()->>'scope_hash')
                )
                OR
                -- Prompt optimizers: access based on target_metric mode
                (
                    (current_agent_type_config()->>'agent_type') = 'prompt_optimizer'
                )
                OR
                -- Improvement agents: check allowed_examples array
                is_agent_example_allowed(snapshot_slug, scope_hash)
            )
    """)

    # Snapshots: improvement agents can access snapshots with allowed examples
    op.execute("DROP POLICY IF EXISTS snapshots_agent_select ON snapshots")
    op.execute("""
        CREATE POLICY snapshots_agent_select ON snapshots
            FOR SELECT
            USING (
                -- Critics/Clustering: their snapshot
                (
                    (current_agent_type_config()->>'agent_type') IN ('critic', 'clustering')
                    AND slug = (current_agent_type_config()->>'snapshot_slug')
                )
                OR
                -- Graders: graded critic's snapshot (use SECURITY DEFINER get_agent_type_config)
                (
                    (current_agent_type_config()->>'agent_type') = 'grader'
                    AND slug = (
                        get_agent_type_config((current_agent_type_config()->>'graded_agent_run_id')::UUID)->>'snapshot_slug'
                    )
                )
                OR
                -- Prompt optimizers: all snapshots (filtered by split in views)
                (
                    (current_agent_type_config()->>'agent_type') = 'prompt_optimizer'
                )
                OR
                -- Improvement agents: any snapshot with allowed examples
                is_agent_snapshot_allowed(slug)
            )
    """)

    # True positives: improvement agents can access ground truth for allowed snapshots
    op.execute("DROP POLICY IF EXISTS true_positives_agent_select ON true_positives")
    op.execute("""
        CREATE POLICY true_positives_agent_select ON true_positives
            FOR SELECT
            USING (
                -- Graders: can read TPs for their snapshot (use SECURITY DEFINER get_agent_type_config)
                (
                    (current_agent_type_config()->>'agent_type') = 'grader'
                    AND snapshot_slug = (
                        get_agent_type_config((current_agent_type_config()->>'graded_agent_run_id')::UUID)->>'snapshot_slug'
                    )
                )
                OR
                -- Prompt optimizers: TRAIN split only
                (
                    (current_agent_type_config()->>'agent_type') = 'prompt_optimizer'
                    AND snapshot_slug IN (SELECT slug FROM snapshots WHERE split = 'train')
                )
                OR
                -- Improvement agents: allowed snapshots
                is_agent_snapshot_allowed(snapshot_slug)
            )
    """)

    # False positives: improvement agents can access ground truth for allowed snapshots
    op.execute("DROP POLICY IF EXISTS false_positives_agent_select ON false_positives")
    op.execute("""
        CREATE POLICY false_positives_agent_select ON false_positives
            FOR SELECT
            USING (
                -- Graders: can read FPs for their snapshot (use SECURITY DEFINER get_agent_type_config)
                (
                    (current_agent_type_config()->>'agent_type') = 'grader'
                    AND snapshot_slug = (
                        get_agent_type_config((current_agent_type_config()->>'graded_agent_run_id')::UUID)->>'snapshot_slug'
                    )
                )
                OR
                -- Prompt optimizers: TRAIN split only
                (
                    (current_agent_type_config()->>'agent_type') = 'prompt_optimizer'
                    AND snapshot_slug IN (SELECT slug FROM snapshots WHERE split = 'train')
                )
                OR
                -- Improvement agents: allowed snapshots
                is_agent_snapshot_allowed(snapshot_slug)
            )
    """)

    # Agent runs: improvement agents can see runs for their allowed examples
    # Uses current_agent_type_config() (SECURITY DEFINER) and current_graded_agent_run_id() (SECURITY DEFINER)
    # to avoid RLS recursion on agent_runs table
    op.execute("DROP POLICY IF EXISTS agent_runs_agent_select ON agent_runs")
    op.execute("""
        CREATE POLICY agent_runs_agent_select ON agent_runs
            FOR SELECT
            USING (
                -- Own run
                agent_run_id = current_agent_run_id()
                OR
                -- Graders can see the critic run they're grading (use SECURITY DEFINER helper)
                agent_run_id = current_graded_agent_run_id()
                OR
                -- Prompt optimizers can see runs for TRAIN examples
                (
                    (current_agent_type_config()->>'agent_type') = 'prompt_optimizer'
                    AND type_config->>'agent_type' IN ('critic', 'grader')
                    AND type_config->>'snapshot_slug' IN (SELECT slug FROM snapshots WHERE split = 'train')
                )
                OR
                -- Improvement agents can see critic/grader runs for their allowed examples
                (
                    (current_agent_type_config()->>'agent_type') = 'improvement'
                    AND type_config->>'agent_type' IN ('critic', 'grader')
                    AND is_agent_example_allowed(
                        type_config->>'snapshot_slug',
                        type_config->>'scope_hash'
                    )
                )
            )
    """)

    # Events: improvement agents can see events for allowed runs
    # Uses SECURITY DEFINER functions to avoid RLS recursion on agent_runs
    op.execute("DROP POLICY IF EXISTS events_agent_select ON events")
    op.execute("""
        CREATE POLICY events_agent_select ON events
            FOR SELECT
            USING (
                -- Own events
                agent_run_id = current_agent_run_id()
                OR
                -- Graders can see graded critic's events (use SECURITY DEFINER helper)
                agent_run_id = current_graded_agent_run_id()
                OR
                -- Prompt optimizers can see TRAIN events (use SECURITY DEFINER function)
                (
                    (current_agent_type_config()->>'agent_type') = 'prompt_optimizer'
                    AND agent_run_id IN (SELECT * FROM get_agent_run_ids_for_train_snapshots())
                )
                OR
                -- Improvement agents can see events for their allowed runs (use SECURITY DEFINER function)
                (
                    (current_agent_type_config()->>'agent_type') = 'improvement'
                    AND agent_run_id IN (SELECT * FROM get_agent_run_ids_for_improvement_allowed())
                )
            )
    """)


def downgrade() -> None:
    """Restore improvement_runs table (empty)."""
    # 1. Drop new helper functions
    op.execute("DROP FUNCTION IF EXISTS is_agent_example_allowed(TEXT, TEXT)")
    op.execute("DROP FUNCTION IF EXISTS is_agent_snapshot_allowed(TEXT)")
    op.execute("DROP FUNCTION IF EXISTS get_agent_run_ids_for_improvement_allowed()")
    op.execute("DROP FUNCTION IF EXISTS get_agent_run_ids_for_train_snapshots()")
    op.execute("DROP FUNCTION IF EXISTS get_agent_type_config(UUID)")
    op.execute("DROP FUNCTION IF EXISTS current_agent_type_config()")

    # 2. Recreate enum
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'improvement_run_status_enum') THEN
                CREATE TYPE improvement_run_status_enum AS ENUM ('in_progress', 'completed', 'abandoned');
            END IF;
        END
        $$
    """)

    # 3. Recreate improvement_runs table (empty)
    op.execute("""
        CREATE TABLE IF NOT EXISTS improvement_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            allowed_examples JSONB NOT NULL,
            status improvement_run_status_enum NOT NULL DEFAULT 'in_progress',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_improvement_runs_id ON improvement_runs (id)")

    # 4. Recreate helper functions
    op.execute("""
        CREATE OR REPLACE FUNCTION current_improvement_run_id() RETURNS uuid
        LANGUAGE plpgsql STABLE
        AS $$
        DECLARE
            run_id_text TEXT;
        BEGIN
            run_id_text := SUBSTRING(current_user FROM 'improvement_agent_([0-9a-f-]+)');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            RETURN run_id_text::UUID;
        END;
        $$
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION is_improvement_example_allowed(
            p_snapshot_slug TEXT,
            p_scope_hash TEXT
        ) RETURNS boolean
        LANGUAGE plpgsql STABLE
        AS $$
        DECLARE
            run_id UUID;
            allowed JSONB;
        BEGIN
            run_id := current_improvement_run_id();
            IF run_id IS NULL THEN
                RETURN FALSE;
            END IF;

            SELECT allowed_examples INTO allowed
            FROM improvement_runs
            WHERE id = run_id;

            IF allowed IS NULL THEN
                RETURN FALSE;
            END IF;

            RETURN EXISTS (
                SELECT 1 FROM jsonb_array_elements(allowed) elem
                WHERE elem->>'snapshot_slug' = p_snapshot_slug
                  AND elem->>'scope_hash' = p_scope_hash
            );
        END;
        $$
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION is_improvement_snapshot_allowed(p_slug TEXT) RETURNS boolean
        LANGUAGE plpgsql STABLE
        AS $$
        DECLARE
            run_id UUID;
            allowed JSONB;
        BEGIN
            run_id := current_improvement_run_id();
            IF run_id IS NULL THEN
                RETURN FALSE;
            END IF;

            SELECT allowed_examples INTO allowed
            FROM improvement_runs
            WHERE id = run_id;

            IF allowed IS NULL THEN
                RETURN FALSE;
            END IF;

            RETURN EXISTS (
                SELECT 1 FROM jsonb_array_elements(allowed) elem
                WHERE elem->>'snapshot_slug' = p_slug
            );
        END;
        $$
    """)

    # 5. Recreate template role
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'improvement_agent_template') THEN
                CREATE ROLE improvement_agent_template NOLOGIN;
            END IF;
        END
        $$
    """)
    op.execute("GRANT USAGE ON SCHEMA public TO improvement_agent_template")
    op.execute("GRANT SELECT ON TABLE snapshots TO improvement_agent_template")
    op.execute("GRANT SELECT ON TABLE true_positives TO improvement_agent_template")
    op.execute("GRANT SELECT ON TABLE false_positives TO improvement_agent_template")
    op.execute("GRANT SELECT ON TABLE examples TO improvement_agent_template")

    # 6. Recreate RLS policies for improvement_agent_template
    op.execute("""
        CREATE POLICY improvement_examples_policy ON examples
        FOR SELECT TO improvement_agent_template
        USING (is_improvement_example_allowed(snapshot_slug, scope_hash))
    """)

    op.execute("""
        CREATE POLICY improvement_snapshots_policy ON snapshots
        FOR SELECT TO improvement_agent_template
        USING (is_improvement_snapshot_allowed(slug))
    """)

    op.execute("""
        CREATE POLICY improvement_true_positives_policy ON true_positives
        FOR SELECT TO improvement_agent_template
        USING (is_improvement_snapshot_allowed(snapshot_slug))
    """)

    op.execute("""
        CREATE POLICY improvement_false_positives_policy ON false_positives
        FOR SELECT TO improvement_agent_template
        USING (is_improvement_snapshot_allowed(snapshot_slug))
    """)

    # 7. Restore prompts FK
    op.execute("""
        ALTER TABLE prompts
        ADD CONSTRAINT prompts_improvement_run_id_fkey
        FOREIGN KEY (improvement_run_id) REFERENCES improvement_runs(id)
    """)

    # 8. Restore original RLS policies (without improvement OR clauses)
    # Use inline subqueries matching the format from 20251229000003
    op.execute("DROP POLICY IF EXISTS examples_agent_select ON examples")
    op.execute("""
        CREATE POLICY examples_agent_select ON examples
            FOR SELECT
            USING (
                -- Critics can only see their specific example
                (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'critic'
                AND snapshot_slug = (SELECT type_config->>'snapshot_slug' FROM agent_runs WHERE agent_run_id = current_agent_run_id())
                AND scope_hash = (SELECT type_config->>'scope_hash' FROM agent_runs WHERE agent_run_id = current_agent_run_id())
            )
    """)
