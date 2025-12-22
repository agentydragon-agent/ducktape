"""Simplify RLS by dropping SECURITY DEFINER helper functions.

This migration simplifies the RLS design:
- Drops SECURITY DEFINER helper functions (current_agent_type, current_agent_snapshot_slug,
  current_agent_scope_hash, current_grader_snapshot_slug)
- Updates agent_runs policy to NOT use current_agent_type() (breaks recursion)
- Updates all other policies to use inline subqueries (safe because agents can read their own row)
- Simplifies current_agent_run_id() to only support agent_{uuid} pattern

The key insight: if agent_runs allows reading own row via current_agent_run_id() (which just
parses the username), then inline subqueries in other policies can safely query agent_runs
without causing recursion.

Revision ID: 20251229000003
Revises: 20251229000002
Create Date: 2025-12-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20251229000003"
down_revision: str | Sequence[str] | None = "20251229000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop SECURITY DEFINER helpers and simplify RLS to use inline subqueries."""
    # Step 1: Drop SECURITY DEFINER helper functions
    op.execute("DROP FUNCTION IF EXISTS current_agent_type() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS current_agent_snapshot_slug() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS current_agent_scope_hash() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS current_grader_snapshot_slug() CASCADE")

    # Step 2: Simplify current_agent_run_id() to only support agent_{uuid} pattern
    # Remove legacy fallbacks (critic_agent_, grader_agent_)
    op.execute("""
        CREATE OR REPLACE FUNCTION current_agent_run_id() RETURNS uuid
        LANGUAGE SQL STABLE
        AS $$
            SELECT CASE
                WHEN current_user LIKE 'agent_%'
                THEN substring(current_user from 'agent_([0-9a-f-]+)')::uuid
                ELSE NULL
            END
        $$;

        COMMENT ON FUNCTION current_agent_run_id() IS
            'Extracts agent run UUID from database username (pattern: agent_{uuid}). Returns NULL for non-agent users.';
    """)

    # Step 3: Create minimal SECURITY DEFINER function for graded_agent_run_id
    # This is the ONLY helper we need - to allow graders to see the graded critic's run.
    # Without this, the agent_runs policy would have a subquery that causes recursion.
    op.execute("""
        CREATE OR REPLACE FUNCTION current_graded_agent_run_id() RETURNS UUID
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $$
        DECLARE
            graded_run_id UUID;
            run_id_text TEXT;
            run_id UUID;
        BEGIN
            run_id_text := SUBSTRING(session_user FROM 'agent_([0-9a-f-]+)');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            run_id := run_id_text::UUID;

            SELECT (type_config->>'graded_agent_run_id')::UUID INTO graded_run_id
            FROM agent_runs
            WHERE agent_run_id = run_id;

            RETURN graded_run_id;
        END;
        $$;

        COMMENT ON FUNCTION current_graded_agent_run_id() IS
            'Returns graded_agent_run_id from current agent type_config. SECURITY DEFINER to bypass RLS. Returns NULL for non-graders.';
    """)

    # Step 4: Update agent_runs policy
    # Uses current_agent_run_id() (just parses username) and current_graded_agent_run_id() (SECURITY DEFINER)
    # No subqueries in this policy = no recursion!
    op.execute("""
        DROP POLICY IF EXISTS agent_runs_agent_select ON agent_runs;

        CREATE POLICY agent_runs_agent_select ON agent_runs
            FOR SELECT
            USING (
                agent_run_id = current_agent_run_id()
                OR agent_run_id = current_graded_agent_run_id()
            );
    """)

    # Step 5: Update reported_issues policies
    # Use current_graded_agent_run_id() for grader SELECT access
    # Use inline subqueries for type checks (agent can read their own row in agent_runs)
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
                OR agent_run_id = current_graded_agent_run_id()
            );

        -- INSERT/UPDATE/DELETE: only own issues (critics only)
        CREATE POLICY reported_issues_agent_insert ON reported_issues
            FOR INSERT
            WITH CHECK (
                agent_run_id = current_agent_run_id()
                AND (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'critic'
            );

        CREATE POLICY reported_issues_agent_update ON reported_issues
            FOR UPDATE
            USING (
                agent_run_id = current_agent_run_id()
                AND (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'critic'
            );

        CREATE POLICY reported_issues_agent_delete ON reported_issues
            FOR DELETE
            USING (
                agent_run_id = current_agent_run_id()
                AND (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'critic'
            );
    """)

    # Step 6: Update reported_issue_occurrences policies similarly
    op.execute("""
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_select ON reported_issue_occurrences;
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_insert ON reported_issue_occurrences;
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_update ON reported_issue_occurrences;
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_delete ON reported_issue_occurrences;

        CREATE POLICY reported_issue_occurrences_agent_select ON reported_issue_occurrences
            FOR SELECT
            USING (
                agent_run_id = current_agent_run_id()
                OR agent_run_id = (
                    SELECT (type_config->>'graded_agent_run_id')::UUID
                    FROM agent_runs
                    WHERE agent_run_id = current_agent_run_id()
                )
            );

        CREATE POLICY reported_issue_occurrences_agent_insert ON reported_issue_occurrences
            FOR INSERT
            WITH CHECK (
                agent_run_id = current_agent_run_id()
                AND (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'critic'
            );

        CREATE POLICY reported_issue_occurrences_agent_update ON reported_issue_occurrences
            FOR UPDATE
            USING (
                agent_run_id = current_agent_run_id()
                AND (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'critic'
            );

        CREATE POLICY reported_issue_occurrences_agent_delete ON reported_issue_occurrences
            FOR DELETE
            USING (
                agent_run_id = current_agent_run_id()
                AND (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'critic'
            );
    """)

    # Step 7: Update grading_decisions policies
    op.execute("""
        DROP POLICY IF EXISTS grading_decisions_agent_select ON grading_decisions;
        DROP POLICY IF EXISTS grading_decisions_agent_insert ON grading_decisions;
        DROP POLICY IF EXISTS grading_decisions_agent_update ON grading_decisions;
        DROP POLICY IF EXISTS grading_decisions_agent_delete ON grading_decisions;

        CREATE POLICY grading_decisions_agent_select ON grading_decisions
            FOR SELECT
            USING (
                agent_run_id = current_agent_run_id()
                AND (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'grader'
            );

        CREATE POLICY grading_decisions_agent_insert ON grading_decisions
            FOR INSERT
            WITH CHECK (
                agent_run_id = current_agent_run_id()
                AND (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'grader'
            );

        CREATE POLICY grading_decisions_agent_update ON grading_decisions
            FOR UPDATE
            USING (
                agent_run_id = current_agent_run_id()
                AND (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'grader'
            );

        CREATE POLICY grading_decisions_agent_delete ON grading_decisions
            FOR DELETE
            USING (
                agent_run_id = current_agent_run_id()
                AND (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'grader'
            );
    """)

    # Step 8: Update true_positives and false_positives policies
    op.execute("""
        DROP POLICY IF EXISTS true_positives_agent_select ON true_positives;
        DROP POLICY IF EXISTS false_positives_agent_select ON false_positives;

        -- Graders can read ground truth for the snapshot they're grading
        CREATE POLICY true_positives_agent_select ON true_positives
            FOR SELECT
            USING (
                (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'grader'
                AND snapshot_slug = (
                    SELECT graded.type_config->>'snapshot_slug'
                    FROM agent_runs grader
                    INNER JOIN agent_runs graded ON graded.agent_run_id = (grader.type_config->>'graded_agent_run_id')::UUID
                    WHERE grader.agent_run_id = current_agent_run_id()
                )
            );

        CREATE POLICY false_positives_agent_select ON false_positives
            FOR SELECT
            USING (
                (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'grader'
                AND snapshot_slug = (
                    SELECT graded.type_config->>'snapshot_slug'
                    FROM agent_runs grader
                    INNER JOIN agent_runs graded ON graded.agent_run_id = (grader.type_config->>'graded_agent_run_id')::UUID
                    WHERE grader.agent_run_id = current_agent_run_id()
                )
            );
    """)

    # Step 9: Update snapshots policy
    op.execute("""
        DROP POLICY IF EXISTS snapshots_agent_select ON snapshots;

        CREATE POLICY snapshots_agent_select ON snapshots
            FOR SELECT
            USING (
                -- For critics and clustering: snapshot_slug is directly in type_config
                (
                    (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) IN ('critic', 'clustering')
                    AND slug = (
                        SELECT type_config->>'snapshot_slug'
                        FROM agent_runs
                        WHERE agent_run_id = current_agent_run_id()
                    )
                )
                OR
                -- For graders: snapshot_slug is derived from the graded critic's type_config
                (
                    (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'grader'
                    AND slug = (
                        SELECT graded.type_config->>'snapshot_slug'
                        FROM agent_runs grader
                        INNER JOIN agent_runs graded ON graded.agent_run_id = (grader.type_config->>'graded_agent_run_id')::UUID
                        WHERE grader.agent_run_id = current_agent_run_id()
                    )
                )
            );
    """)

    # Step 10: Update examples policy
    op.execute("""
        DROP POLICY IF EXISTS examples_agent_select ON examples;

        CREATE POLICY examples_agent_select ON examples
            FOR SELECT
            USING (
                -- Critics can only see their specific example
                (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'critic'
                AND snapshot_slug = (SELECT type_config->>'snapshot_slug' FROM agent_runs WHERE agent_run_id = current_agent_run_id())
                AND scope_hash = (SELECT type_config->>'scope_hash' FROM agent_runs WHERE agent_run_id = current_agent_run_id())
            );
    """)


def downgrade() -> None:
    """Restore SECURITY DEFINER helper functions and policies that use them."""
    # Drop the new function we created
    op.execute("DROP FUNCTION IF EXISTS current_graded_agent_run_id() CASCADE")

    # Recreate current_agent_type() as SECURITY DEFINER
    op.execute("""
        CREATE OR REPLACE FUNCTION current_agent_type() RETURNS TEXT
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $$
        DECLARE
            agent_type TEXT;
            run_id UUID;
            run_id_text TEXT;
        BEGIN
            run_id_text := SUBSTRING(session_user FROM 'agent_([0-9a-f-]+)');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            run_id := run_id_text::UUID;

            SELECT type_config->>'agent_type' INTO agent_type
            FROM agent_runs
            WHERE agent_run_id = run_id;

            RETURN agent_type;
        END;
        $$;

        COMMENT ON FUNCTION current_agent_type() IS
            'Returns the agent_type from the current agent''s type_config. Uses SECURITY DEFINER to bypass RLS.';
    """)

    # Recreate current_agent_snapshot_slug() as SECURITY DEFINER
    op.execute("""
        CREATE OR REPLACE FUNCTION current_agent_snapshot_slug() RETURNS TEXT
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $$
        DECLARE
            snapshot_slug TEXT;
            run_id UUID;
            run_id_text TEXT;
        BEGIN
            run_id_text := SUBSTRING(session_user FROM 'agent_([0-9a-f-]+)');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            run_id := run_id_text::UUID;

            SELECT type_config->>'snapshot_slug' INTO snapshot_slug
            FROM agent_runs
            WHERE agent_run_id = run_id;

            RETURN snapshot_slug;
        END;
        $$;

        COMMENT ON FUNCTION current_agent_snapshot_slug() IS
            'Returns the snapshot_slug from the current agent''s type_config. Uses SECURITY DEFINER to bypass RLS.';
    """)

    # Recreate current_agent_scope_hash() as SECURITY DEFINER
    op.execute("""
        CREATE OR REPLACE FUNCTION current_agent_scope_hash() RETURNS TEXT
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $$
        DECLARE
            scope_hash TEXT;
            run_id UUID;
            run_id_text TEXT;
        BEGIN
            run_id_text := SUBSTRING(session_user FROM 'agent_([0-9a-f-]+)');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            run_id := run_id_text::UUID;

            SELECT type_config->>'scope_hash' INTO scope_hash
            FROM agent_runs
            WHERE agent_run_id = run_id;

            RETURN scope_hash;
        END;
        $$;

        COMMENT ON FUNCTION current_agent_scope_hash() IS
            'Returns the scope_hash from the current agent''s type_config (for critics). Uses SECURITY DEFINER to bypass RLS.';
    """)

    # Recreate current_grader_snapshot_slug() as SECURITY DEFINER
    op.execute("""
        CREATE OR REPLACE FUNCTION current_grader_snapshot_slug() RETURNS TEXT
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $$
        DECLARE
            snapshot_slug TEXT;
            run_id UUID;
            run_id_text TEXT;
            graded_run_id UUID;
        BEGIN
            run_id_text := SUBSTRING(session_user FROM 'agent_([0-9a-f-]+)');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            run_id := run_id_text::UUID;

            SELECT (type_config->>'graded_agent_run_id')::UUID INTO graded_run_id
            FROM agent_runs
            WHERE agent_run_id = run_id;

            IF graded_run_id IS NULL THEN
                RETURN NULL;
            END IF;

            SELECT type_config->>'snapshot_slug' INTO snapshot_slug
            FROM agent_runs
            WHERE agent_run_id = graded_run_id;

            RETURN snapshot_slug;
        END;
        $$;

        COMMENT ON FUNCTION current_grader_snapshot_slug() IS
            'Returns the snapshot_slug from the graded agent''s type_config (for graders). Uses SECURITY DEFINER to bypass RLS.';
    """)

    # Restore current_agent_run_id() with legacy pattern support
    op.execute("""
        CREATE OR REPLACE FUNCTION current_agent_run_id() RETURNS uuid
        LANGUAGE plpgsql STABLE
        AS $$
        DECLARE
            run_id_text TEXT;
        BEGIN
            run_id_text := SUBSTRING(current_user FROM 'agent_([0-9a-f-]+)');
            IF run_id_text IS NOT NULL THEN
                RETURN run_id_text::UUID;
            END IF;

            run_id_text := SUBSTRING(current_user FROM 'critic_agent_([0-9a-f-]+)');
            IF run_id_text IS NOT NULL THEN
                RETURN run_id_text::UUID;
            END IF;

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

    # Restore agent_runs policy using current_agent_type()
    op.execute("""
        DROP POLICY IF EXISTS agent_runs_agent_select ON agent_runs;

        CREATE POLICY agent_runs_agent_select ON agent_runs
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
    """)

    # Restore other policies using current_agent_type()
    op.execute("""
        DROP POLICY IF EXISTS reported_issues_agent_select ON reported_issues;
        DROP POLICY IF EXISTS reported_issues_agent_insert ON reported_issues;
        DROP POLICY IF EXISTS reported_issues_agent_update ON reported_issues;
        DROP POLICY IF EXISTS reported_issues_agent_delete ON reported_issues;

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

    op.execute("""
        DROP POLICY IF EXISTS true_positives_agent_select ON true_positives;
        DROP POLICY IF EXISTS false_positives_agent_select ON false_positives;

        CREATE POLICY true_positives_agent_select ON true_positives
            FOR SELECT
            USING (
                current_agent_type() = 'grader'
                AND snapshot_slug = current_grader_snapshot_slug()
            );

        CREATE POLICY false_positives_agent_select ON false_positives
            FOR SELECT
            USING (
                current_agent_type() = 'grader'
                AND snapshot_slug = current_grader_snapshot_slug()
            );
    """)

    op.execute("""
        DROP POLICY IF EXISTS snapshots_agent_select ON snapshots;

        CREATE POLICY snapshots_agent_select ON snapshots
            FOR SELECT
            USING (
                (
                    current_agent_type() IN ('critic', 'clustering')
                    AND slug = current_agent_snapshot_slug()
                )
                OR
                (
                    current_agent_type() = 'grader'
                    AND slug = current_grader_snapshot_slug()
                )
            );
    """)

    op.execute("""
        DROP POLICY IF EXISTS examples_agent_select ON examples;

        CREATE POLICY examples_agent_select ON examples
            FOR SELECT
            USING (
                current_agent_type() = 'critic'
                AND snapshot_slug = current_agent_snapshot_slug()
                AND scope_hash = current_agent_scope_hash()
            );
    """)
