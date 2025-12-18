"""Add improvement_runs table and function-based RLS for improvement agents.

Revision ID: 20251222000000
Revises: 20251221000000
Create Date: 2025-12-22

Migrates ImprovementUserManager from per-user RLS policies (O(n) overhead) to
function-based RLS with template role inheritance (O(1) overhead).

Key components:
1. improvement_runs table - tracks runs with allowed_examples JSONB
2. current_improvement_run_id() - extracts run ID from username
3. is_improvement_example_allowed() - checks if (snapshot_slug, scope_hash) is allowed
4. is_improvement_snapshot_allowed() - checks if snapshot has any allowed examples
5. improvement_agent_template - NOLOGIN role with static SELECT grants
6. RLS policies using the helper functions
"""

from alembic import op

revision = "20251222000000"
down_revision = "20251221000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0. Create enum type for status (native PostgreSQL enum with lowercase values)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'improvement_run_status_enum') THEN
                CREATE TYPE improvement_run_status_enum AS ENUM ('in_progress', 'completed', 'abandoned');
            END IF;
        END
        $$
    """)

    # 1. Table to track improvement runs with allowed examples
    op.execute("""
        CREATE TABLE improvement_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            allowed_examples JSONB NOT NULL,
            status improvement_run_status_enum NOT NULL DEFAULT 'in_progress',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        COMMENT ON TABLE improvement_runs IS
        'Tracks improvement agent runs with allowed training examples (JSONB array of {snapshot_slug, scope_hash} objects)'
    """)
    op.execute("""
        COMMENT ON COLUMN improvement_runs.allowed_examples IS
        'Array of {"snapshot_slug": "...", "scope_hash": "..."} objects defining which examples the agent can access'
    """)

    # Index for looking up run by ID (used by RLS functions)
    op.execute("CREATE INDEX ix_improvement_runs_id ON improvement_runs (id)")

    # 2. Function to extract run_id from username (improvement_agent_{uuid})
    op.execute("""
        CREATE FUNCTION current_improvement_run_id() RETURNS uuid
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

    # 3. Helper function to check example membership
    op.execute("""
        CREATE FUNCTION is_improvement_example_allowed(
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

            -- Check if (snapshot_slug, scope_hash) is in the allowed list
            RETURN EXISTS (
                SELECT 1 FROM jsonb_array_elements(allowed) elem
                WHERE elem->>'snapshot_slug' = p_snapshot_slug
                  AND elem->>'scope_hash' = p_scope_hash
            );
        END;
        $$
    """)

    # 4. Helper function to check if snapshot has any allowed examples
    op.execute("""
        CREATE FUNCTION is_improvement_snapshot_allowed(p_slug TEXT) RETURNS boolean
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

    # 5. Template role
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
    # SELECT on tables - RLS policies will filter rows
    op.execute("GRANT SELECT ON TABLE snapshots TO improvement_agent_template")
    op.execute("GRANT SELECT ON TABLE true_positives TO improvement_agent_template")
    op.execute("GRANT SELECT ON TABLE false_positives TO improvement_agent_template")
    op.execute("GRANT SELECT ON TABLE examples TO improvement_agent_template")
    op.execute("GRANT SELECT ON TABLE critic_runs TO improvement_agent_template")
    op.execute("GRANT SELECT ON TABLE grader_runs TO improvement_agent_template")
    op.execute("GRANT SELECT ON TABLE events TO improvement_agent_template")

    # 6. RLS policies using the helper functions
    # Note: RLS is already enabled on these tables from initial schema
    # We just need to add policies for the improvement_agent_template role

    # examples: filter by exact (snapshot_slug, scope_hash) match
    op.execute("""
        CREATE POLICY improvement_examples_policy ON examples
        FOR SELECT TO improvement_agent_template
        USING (is_improvement_example_allowed(snapshot_slug, scope_hash))
    """)

    # snapshots: filter by having any allowed examples from this snapshot
    op.execute("""
        CREATE POLICY improvement_snapshots_policy ON snapshots
        FOR SELECT TO improvement_agent_template
        USING (is_improvement_snapshot_allowed(slug))
    """)

    # true_positives: filter by snapshot_slug
    op.execute("""
        CREATE POLICY improvement_true_positives_policy ON true_positives
        FOR SELECT TO improvement_agent_template
        USING (is_improvement_snapshot_allowed(snapshot_slug))
    """)

    # false_positives: filter by snapshot_slug
    op.execute("""
        CREATE POLICY improvement_false_positives_policy ON false_positives
        FOR SELECT TO improvement_agent_template
        USING (is_improvement_snapshot_allowed(snapshot_slug))
    """)

    # critic_runs: filter by (snapshot_slug, scope_hash)
    op.execute("""
        CREATE POLICY improvement_critic_runs_policy ON critic_runs
        FOR SELECT TO improvement_agent_template
        USING (is_improvement_example_allowed(snapshot_slug, scope_hash))
    """)

    # grader_runs: filter via critic_run_id FK
    op.execute("""
        CREATE POLICY improvement_grader_runs_policy ON grader_runs
        FOR SELECT TO improvement_agent_template
        USING (critic_run_id IN (
            SELECT id FROM critic_runs
            WHERE is_improvement_example_allowed(snapshot_slug, scope_hash)
        ))
    """)

    # events: filter via transcript_id FK to critic_runs
    op.execute("""
        CREATE POLICY improvement_events_policy ON events
        FOR SELECT TO improvement_agent_template
        USING (transcript_id IN (
            SELECT transcript_id FROM critic_runs
            WHERE is_improvement_example_allowed(snapshot_slug, scope_hash)
        ))
    """)

    # 7. Add improvement_run_id FK to prompts for provenance tracking
    op.execute("""
        ALTER TABLE prompts
        ADD COLUMN improvement_run_id UUID REFERENCES improvement_runs(id)
    """)
    op.execute("CREATE INDEX ix_prompts_improvement_run_id ON prompts (improvement_run_id)")


def downgrade() -> None:
    # Drop prompts.improvement_run_id column first (before dropping table)
    op.execute("DROP INDEX IF EXISTS ix_prompts_improvement_run_id")
    op.execute("ALTER TABLE prompts DROP COLUMN IF EXISTS improvement_run_id")

    # Drop RLS policies
    op.execute("DROP POLICY IF EXISTS improvement_events_policy ON events")
    op.execute("DROP POLICY IF EXISTS improvement_grader_runs_policy ON grader_runs")
    op.execute("DROP POLICY IF EXISTS improvement_critic_runs_policy ON critic_runs")
    op.execute("DROP POLICY IF EXISTS improvement_false_positives_policy ON false_positives")
    op.execute("DROP POLICY IF EXISTS improvement_true_positives_policy ON true_positives")
    op.execute("DROP POLICY IF EXISTS improvement_snapshots_policy ON snapshots")
    op.execute("DROP POLICY IF EXISTS improvement_examples_policy ON examples")

    # Drop template role (CASCADE handles grants)
    op.execute("DROP ROLE IF EXISTS improvement_agent_template")

    # Drop functions
    op.execute("DROP FUNCTION IF EXISTS is_improvement_snapshot_allowed(TEXT)")
    op.execute("DROP FUNCTION IF EXISTS is_improvement_example_allowed(TEXT, TEXT)")
    op.execute("DROP FUNCTION IF EXISTS current_improvement_run_id()")

    # Drop index and table
    op.execute("DROP INDEX IF EXISTS ix_improvement_runs_id")
    op.execute("DROP TABLE IF EXISTS improvement_runs")

    # Drop enum type
    op.execute("DROP TYPE IF EXISTS improvement_run_status_enum")
