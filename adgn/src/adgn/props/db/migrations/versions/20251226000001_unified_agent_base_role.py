"""Create unified agent_base template role.

This migration creates a single template role that all agent users inherit from,
replacing the separate per-type template roles (critic_agent_template,
grader_agent_template, etc.).

Type-specific access is handled entirely by RLS policies based on the agent's
type_config in agent_runs table, not by separate role grants.

Changes:
- Create agent_base template role with common grants
- Create current_agent_type() helper function
- Update current_agent_run_id() to use generic agent_{uuid} pattern
- Create type-aware RLS policies for all agent tables

The old template roles (critic_agent_template, etc.) are kept for backward
compatibility during transition. They will be dropped in a later migration
after all user managers are updated to use agent_base.

Revision ID: 20251226000001
Revises: 20251226000000
Create Date: 2025-12-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20251226000001"
down_revision: str | Sequence[str] | None = "20251226000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create unified agent_base role and type-aware RLS policies."""
    # Step 1: Create agent_base template role
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'agent_base') THEN
                CREATE ROLE agent_base NOLOGIN;
            END IF;
        END
        $$;

        COMMENT ON ROLE agent_base IS
            'Base template role for all agent users. Type-specific access controlled by RLS.';
    """)

    # Step 2: Grant schema and sequence usage
    op.execute("""
        GRANT USAGE ON SCHEMA public TO agent_base;
        GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO agent_base;
    """)

    # Step 3: Grant table-level permissions
    # All agents can read agent_runs (RLS filters to own run and related runs)
    op.execute("""
        GRANT SELECT ON TABLE agent_runs TO agent_base;
        GRANT SELECT ON TABLE agent_definitions TO agent_base;
    """)

    # reported_issues: Critics write, graders read (RLS handles this)
    op.execute("""
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE reported_issues TO agent_base;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE reported_issue_occurrences TO agent_base;
    """)

    # grading_decisions: Graders write (RLS handles this)
    op.execute("""
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE grading_decisions TO agent_base;
    """)

    # Ground truth: Graders read (RLS filters by snapshot)
    op.execute("""
        GRANT SELECT ON TABLE true_positives TO agent_base;
        GRANT SELECT ON TABLE false_positives TO agent_base;
    """)

    # Reference tables: All agents can read
    op.execute("""
        GRANT SELECT ON TABLE snapshots TO agent_base;
        GRANT SELECT ON TABLE examples TO agent_base;
        GRANT SELECT ON TABLE prompts TO agent_base;
    """)

    # Aggregate views (exist or will be recreated in later migration)
    op.execute("""
        -- These may not exist yet if views haven't been recreated
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM information_schema.views WHERE table_name = 'occurrence_credits') THEN
                EXECUTE 'GRANT SELECT ON occurrence_credits TO agent_base';
            END IF;
            IF EXISTS (SELECT FROM information_schema.views WHERE table_name = 'occurrence_run_credits') THEN
                EXECUTE 'GRANT SELECT ON occurrence_run_credits TO agent_base';
            END IF;
            IF EXISTS (SELECT FROM information_schema.views WHERE table_name = 'aggregated_recall_by_prompt') THEN
                EXECUTE 'GRANT SELECT ON aggregated_recall_by_prompt TO agent_base';
            END IF;
            IF EXISTS (SELECT FROM information_schema.views WHERE table_name = 'aggregated_recall_by_example') THEN
                EXECUTE 'GRANT SELECT ON aggregated_recall_by_example TO agent_base';
            END IF;
            IF EXISTS (SELECT FROM information_schema.views WHERE table_name = 'grading_credit_sums') THEN
                EXECUTE 'GRANT SELECT ON grading_credit_sums TO agent_base';
            END IF;
        END
        $$;
    """)

    # Validation function for prompt optimizers
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_proc WHERE proname = 'get_validation_run_aggregates') THEN
                EXECUTE 'GRANT EXECUTE ON FUNCTION get_validation_run_aggregates() TO agent_base';
            END IF;
        END
        $$;
    """)

    # Step 4: Update current_agent_run_id() to use agent_{uuid} pattern
    op.execute("""
        CREATE OR REPLACE FUNCTION current_agent_run_id() RETURNS uuid
        LANGUAGE plpgsql STABLE
        AS $$
        DECLARE
            run_id_text TEXT;
        BEGIN
            -- Try new pattern: agent_{uuid}
            run_id_text := SUBSTRING(current_user FROM 'agent_([0-9a-f-]+)');
            IF run_id_text IS NOT NULL THEN
                RETURN run_id_text::UUID;
            END IF;

            -- Fall back to legacy pattern: critic_agent_{uuid}
            run_id_text := SUBSTRING(current_user FROM 'critic_agent_([0-9a-f-]+)');
            IF run_id_text IS NOT NULL THEN
                RETURN run_id_text::UUID;
            END IF;

            -- Fall back to legacy pattern: grader_agent_{uuid}
            run_id_text := SUBSTRING(current_user FROM 'grader_agent_([0-9a-f-]+)');
            IF run_id_text IS NOT NULL THEN
                RETURN run_id_text::UUID;
            END IF;

            RETURN NULL;
        END;
        $$;

        COMMENT ON FUNCTION current_agent_run_id() IS
            'Extracts agent run UUID from database username. Supports agent_{uuid} (new) and critic_agent_{uuid}/grader_agent_{uuid} (legacy) patterns.';
    """)

    # Step 5: Create current_agent_type() helper function
    # Must drop first in case it exists with a different return type
    op.execute("DROP FUNCTION IF EXISTS current_agent_type() CASCADE")
    op.execute("""
        CREATE OR REPLACE FUNCTION current_agent_type() RETURNS TEXT
        LANGUAGE plpgsql STABLE
        AS $$
        DECLARE
            agent_type TEXT;
        BEGIN
            SELECT type_config->>'agent_type' INTO agent_type
            FROM agent_runs
            WHERE agent_run_id = current_agent_run_id();

            RETURN agent_type;
        END;
        $$;

        COMMENT ON FUNCTION current_agent_type() IS
            'Returns the agent_type from the current agent''s type_config. Used for type-specific RLS policies.';
    """)

    # Step 6: Enable RLS on agent_runs if not already enabled
    op.execute("""
        ALTER TABLE agent_runs ENABLE ROW LEVEL SECURITY;
    """)

    # Step 7: Create RLS policy for agent_runs
    # Agents can see their own run AND (for graders) the critic run they're grading
    op.execute("""
        DROP POLICY IF EXISTS agent_runs_agent_select ON agent_runs;

        CREATE POLICY agent_runs_agent_select ON agent_runs
            FOR SELECT
            USING (
                -- Own run
                agent_run_id = current_agent_run_id()
                OR
                -- Graders can see the critic run they're grading
                (
                    current_agent_type() = 'grader'
                    AND agent_run_id = (
                        SELECT (type_config->>'graded_agent_run_id')::UUID
                        FROM agent_runs
                        WHERE agent_run_id = current_agent_run_id()
                    )
                )
            );
    """)

    # Step 8: Update RLS policies on reported_issues to be type-aware
    # Critics: can read/write their own issues
    # Graders: can read the critic's issues they're grading
    op.execute("""
        DROP POLICY IF EXISTS reported_issues_agent_select ON reported_issues;
        DROP POLICY IF EXISTS reported_issues_agent_insert ON reported_issues;
        DROP POLICY IF EXISTS reported_issues_agent_update ON reported_issues;
        DROP POLICY IF EXISTS reported_issues_agent_delete ON reported_issues;

        -- SELECT: own issues OR (graders) the graded critic's issues
        CREATE POLICY reported_issues_agent_select ON reported_issues
            FOR SELECT
            USING (
                agent_run_id = current_agent_run_id()
                OR
                (
                    current_agent_type() = 'grader'
                    AND agent_run_id = (
                        SELECT (type_config->>'graded_agent_run_id')::UUID
                        FROM agent_runs
                        WHERE agent_run_id = current_agent_run_id()
                    )
                )
            );

        -- INSERT/UPDATE/DELETE: only own issues (critics only)
        CREATE POLICY reported_issues_agent_insert ON reported_issues
            FOR INSERT
            WITH CHECK (
                agent_run_id = current_agent_run_id()
                AND current_agent_type() = 'critic'
            );

        CREATE POLICY reported_issues_agent_update ON reported_issues
            FOR UPDATE
            USING (
                agent_run_id = current_agent_run_id()
                AND current_agent_type() = 'critic'
            );

        CREATE POLICY reported_issues_agent_delete ON reported_issues
            FOR DELETE
            USING (
                agent_run_id = current_agent_run_id()
                AND current_agent_type() = 'critic'
            );
    """)

    # Step 9: Update RLS policies on reported_issue_occurrences similarly
    op.execute("""
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_select ON reported_issue_occurrences;
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_insert ON reported_issue_occurrences;
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_update ON reported_issue_occurrences;
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_delete ON reported_issue_occurrences;

        CREATE POLICY reported_issue_occurrences_agent_select ON reported_issue_occurrences
            FOR SELECT
            USING (
                agent_run_id = current_agent_run_id()
                OR
                (
                    current_agent_type() = 'grader'
                    AND agent_run_id = (
                        SELECT (type_config->>'graded_agent_run_id')::UUID
                        FROM agent_runs
                        WHERE agent_run_id = current_agent_run_id()
                    )
                )
            );

        CREATE POLICY reported_issue_occurrences_agent_insert ON reported_issue_occurrences
            FOR INSERT
            WITH CHECK (
                agent_run_id = current_agent_run_id()
                AND current_agent_type() = 'critic'
            );

        CREATE POLICY reported_issue_occurrences_agent_update ON reported_issue_occurrences
            FOR UPDATE
            USING (
                agent_run_id = current_agent_run_id()
                AND current_agent_type() = 'critic'
            );

        CREATE POLICY reported_issue_occurrences_agent_delete ON reported_issue_occurrences
            FOR DELETE
            USING (
                agent_run_id = current_agent_run_id()
                AND current_agent_type() = 'critic'
            );
    """)

    # Step 10: RLS policies on grading_decisions (grader only)
    op.execute("""
        DROP POLICY IF EXISTS grading_decisions_agent_select ON grading_decisions;
        DROP POLICY IF EXISTS grading_decisions_agent_insert ON grading_decisions;
        DROP POLICY IF EXISTS grading_decisions_agent_update ON grading_decisions;
        DROP POLICY IF EXISTS grading_decisions_agent_delete ON grading_decisions;

        CREATE POLICY grading_decisions_agent_select ON grading_decisions
            FOR SELECT
            USING (
                agent_run_id = current_agent_run_id()
                AND current_agent_type() = 'grader'
            );

        CREATE POLICY grading_decisions_agent_insert ON grading_decisions
            FOR INSERT
            WITH CHECK (
                agent_run_id = current_agent_run_id()
                AND current_agent_type() = 'grader'
            );

        CREATE POLICY grading_decisions_agent_update ON grading_decisions
            FOR UPDATE
            USING (
                agent_run_id = current_agent_run_id()
                AND current_agent_type() = 'grader'
            );

        CREATE POLICY grading_decisions_agent_delete ON grading_decisions
            FOR DELETE
            USING (
                agent_run_id = current_agent_run_id()
                AND current_agent_type() = 'grader'
            );
    """)

    # Step 11: RLS policies on ground truth (grader can read for their snapshot)
    # NOTE: Grader's snapshot_slug is derived from the graded critic's type_config, not stored in grader
    op.execute("""
        ALTER TABLE true_positives ENABLE ROW LEVEL SECURITY;
        ALTER TABLE false_positives ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS true_positives_agent_select ON true_positives;
        DROP POLICY IF EXISTS false_positives_agent_select ON false_positives;

        -- Graders can read ground truth for the snapshot they're grading
        -- snapshot_slug is derived from the graded critic's type_config
        CREATE POLICY true_positives_agent_select ON true_positives
            FOR SELECT
            USING (
                current_agent_type() = 'grader'
                AND snapshot_slug = (
                    -- Get snapshot_slug from the graded critic's type_config
                    SELECT graded.type_config->>'snapshot_slug'
                    FROM agent_runs grader
                    INNER JOIN agent_runs graded ON graded.agent_run_id = (grader.type_config->>'graded_agent_run_id')::UUID
                    WHERE grader.agent_run_id = current_agent_run_id()
                )
            );

        CREATE POLICY false_positives_agent_select ON false_positives
            FOR SELECT
            USING (
                current_agent_type() = 'grader'
                AND snapshot_slug = (
                    -- Get snapshot_slug from the graded critic's type_config
                    SELECT graded.type_config->>'snapshot_slug'
                    FROM agent_runs grader
                    INNER JOIN agent_runs graded ON graded.agent_run_id = (grader.type_config->>'graded_agent_run_id')::UUID
                    WHERE grader.agent_run_id = current_agent_run_id()
                )
            );
    """)

    # Step 12: RLS policies on snapshots (all agents can read relevant snapshots)
    # NOTE: Critics have snapshot_slug in their type_config, graders derive it from graded critic
    op.execute("""
        ALTER TABLE snapshots ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS snapshots_agent_select ON snapshots;

        -- Critics can read the snapshot they're working on (from their type_config)
        -- Graders can read the snapshot from the graded critic's type_config
        CREATE POLICY snapshots_agent_select ON snapshots
            FOR SELECT
            USING (
                -- For critics (and clustering): snapshot_slug is directly in type_config
                (
                    current_agent_type() IN ('critic', 'clustering')
                    AND slug = (
                        SELECT type_config->>'snapshot_slug'
                        FROM agent_runs
                        WHERE agent_run_id = current_agent_run_id()
                    )
                )
                OR
                -- For graders: snapshot_slug is derived from the graded critic's type_config
                (
                    current_agent_type() = 'grader'
                    AND slug = (
                        SELECT graded.type_config->>'snapshot_slug'
                        FROM agent_runs grader
                        INNER JOIN agent_runs graded ON graded.agent_run_id = (grader.type_config->>'graded_agent_run_id')::UUID
                        WHERE grader.agent_run_id = current_agent_run_id()
                    )
                )
            );
    """)

    # Step 13: RLS policies on examples (critics can read their scope)
    op.execute("""
        ALTER TABLE examples ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS examples_agent_select ON examples;

        -- Critics can read the example they're reviewing
        CREATE POLICY examples_agent_select ON examples
            FOR SELECT
            USING (
                snapshot_slug = (
                    SELECT type_config->>'snapshot_slug'
                    FROM agent_runs
                    WHERE agent_run_id = current_agent_run_id()
                )
                AND scope_hash = (
                    SELECT type_config->>'scope_hash'
                    FROM agent_runs
                    WHERE agent_run_id = current_agent_run_id()
                )
            );
    """)


def downgrade() -> None:
    """Remove unified agent_base role and restore per-type patterns."""
    # Step 1: Drop RLS policies
    op.execute("""
        DROP POLICY IF EXISTS agent_runs_agent_select ON agent_runs;
        DROP POLICY IF EXISTS reported_issues_agent_select ON reported_issues;
        DROP POLICY IF EXISTS reported_issues_agent_insert ON reported_issues;
        DROP POLICY IF EXISTS reported_issues_agent_update ON reported_issues;
        DROP POLICY IF EXISTS reported_issues_agent_delete ON reported_issues;
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_select ON reported_issue_occurrences;
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_insert ON reported_issue_occurrences;
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_update ON reported_issue_occurrences;
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_delete ON reported_issue_occurrences;
        DROP POLICY IF EXISTS grading_decisions_agent_select ON grading_decisions;
        DROP POLICY IF EXISTS grading_decisions_agent_insert ON grading_decisions;
        DROP POLICY IF EXISTS grading_decisions_agent_update ON grading_decisions;
        DROP POLICY IF EXISTS grading_decisions_agent_delete ON grading_decisions;
        DROP POLICY IF EXISTS true_positives_agent_select ON true_positives;
        DROP POLICY IF EXISTS false_positives_agent_select ON false_positives;
        DROP POLICY IF EXISTS snapshots_agent_select ON snapshots;
        DROP POLICY IF EXISTS examples_agent_select ON examples;
    """)

    # Step 2: Restore simple RLS policies for reported_issues (critic pattern)
    op.execute("""
        CREATE POLICY reported_issues_agent_select ON reported_issues
            FOR SELECT
            USING (agent_run_id = current_agent_run_id());

        CREATE POLICY reported_issues_agent_insert ON reported_issues
            FOR INSERT
            WITH CHECK (agent_run_id = current_agent_run_id());

        CREATE POLICY reported_issues_agent_delete ON reported_issues
            FOR DELETE
            USING (agent_run_id = current_agent_run_id());

        CREATE POLICY reported_issue_occurrences_agent_select ON reported_issue_occurrences
            FOR SELECT
            USING (agent_run_id = current_agent_run_id());

        CREATE POLICY reported_issue_occurrences_agent_insert ON reported_issue_occurrences
            FOR INSERT
            WITH CHECK (agent_run_id = current_agent_run_id());

        CREATE POLICY reported_issue_occurrences_agent_delete ON reported_issue_occurrences
            FOR DELETE
            USING (agent_run_id = current_agent_run_id());
    """)

    # Step 3: Restore simple grading_decisions policies
    op.execute("""
        CREATE POLICY grading_decisions_agent_select ON grading_decisions
            FOR SELECT
            USING (agent_run_id = current_agent_run_id());

        CREATE POLICY grading_decisions_agent_insert ON grading_decisions
            FOR INSERT
            WITH CHECK (agent_run_id = current_agent_run_id());

        CREATE POLICY grading_decisions_agent_delete ON grading_decisions
            FOR DELETE
            USING (agent_run_id = current_agent_run_id());
    """)

    # Step 4: Drop helper function
    op.execute("DROP FUNCTION IF EXISTS current_agent_type();")

    # Step 5: Restore original current_agent_run_id()
    op.execute("""
        CREATE OR REPLACE FUNCTION current_agent_run_id() RETURNS uuid
        LANGUAGE plpgsql STABLE
        AS $$
        DECLARE
            run_id_text TEXT;
        BEGIN
            -- Extract UUID from critic_agent_{uuid} pattern
            run_id_text := SUBSTRING(current_user FROM 'critic_agent_([0-9a-f-]+)');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            RETURN run_id_text::UUID;
        END;
        $$;
    """)

    # Step 6: Disable RLS on tables that didn't have it before
    op.execute("""
        ALTER TABLE true_positives DISABLE ROW LEVEL SECURITY;
        ALTER TABLE false_positives DISABLE ROW LEVEL SECURITY;
        ALTER TABLE snapshots DISABLE ROW LEVEL SECURITY;
        ALTER TABLE examples DISABLE ROW LEVEL SECURITY;
    """)

    # Step 7: Drop agent_base role
    op.execute("DROP ROLE IF EXISTS agent_base;")
