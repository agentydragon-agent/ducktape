"""Update RLS for improvement agent and agent_definitions access.

Revision ID: 20250101000000
Revises: 20251231000005
Create Date: 2025-01-01

This migration makes two key changes:

1. **Improvement agent ground truth access**: Same as prompt optimizer (full TRAIN access)
   - Previously: Scoped to allowed_examples only
   - Now: Full TRAIN split access (is_train_snapshot check)
   - Rationale: Both agents need to understand ground truth patterns to improve prompts

2. **Agent definitions access**: Minimal-access model
   - Default (all agents): Own definition + definitions they created
   - Prompt optimizer: All definitions (needs to compare/analyze)
   - Improvement agent: Additionally sees baseline_definition_ids from type_config

Helper functions added:
- get_current_agent_definition_id(): Returns current agent's definition_id
- get_improvement_baseline_definition_ids(): Returns baseline IDs from type_config
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20250101000000"
down_revision: str | Sequence[str] | None = "20251231000005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Update RLS policies for improvement agent and agent_definitions."""
    # Step 1: Create helper function to get current agent's definition_id
    op.execute("""
        CREATE OR REPLACE FUNCTION get_current_agent_definition_id() RETURNS TEXT
        LANGUAGE SQL STABLE SECURITY DEFINER
        AS $$
            SELECT agent_definition_id
            FROM agent_runs
            WHERE agent_run_id = current_agent_run_id()
        $$;

        COMMENT ON FUNCTION get_current_agent_definition_id() IS
            'Returns agent_definition_id for current agent. SECURITY DEFINER to bypass RLS.';
    """)

    # Step 2: Create helper to get improvement agent's baseline_definition_ids
    op.execute("""
        CREATE OR REPLACE FUNCTION get_improvement_baseline_definition_ids() RETURNS TEXT[]
        LANGUAGE SQL STABLE SECURITY DEFINER
        AS $$
            SELECT ARRAY(
                SELECT jsonb_array_elements_text(type_config->'baseline_definition_ids')
                FROM agent_runs
                WHERE agent_run_id = current_agent_run_id()
                  AND type_config->>'agent_type' = 'improvement'
            )
        $$;

        COMMENT ON FUNCTION get_improvement_baseline_definition_ids() IS
            'Returns baseline_definition_ids array for improvement agents. Empty for others.';
    """)

    # Step 3: Grant execute on new functions to agent_base
    op.execute("GRANT EXECUTE ON FUNCTION get_current_agent_definition_id() TO agent_base")
    op.execute("GRANT EXECUTE ON FUNCTION get_improvement_baseline_definition_ids() TO agent_base")

    # Step 4: Update agent_definitions SELECT policy
    # Minimal access: own definition, created definitions, optimizer sees all, improvement sees baselines
    op.execute("""
        DROP POLICY IF EXISTS agent_definitions_select ON agent_definitions;

        CREATE POLICY agent_definitions_select ON agent_definitions
            FOR SELECT
            USING (
                -- Own definition (the one this agent is running as)
                id = get_current_agent_definition_id()
                OR
                -- Definitions this agent created
                created_by_agent_run_id = current_agent_run_id()
                OR
                -- Prompt optimizer: all definitions
                current_agent_type() = 'prompt_optimizer'
                OR
                -- Improvement agent: baseline definitions from type_config
                (
                    current_agent_type() = 'improvement'
                    AND id = ANY(get_improvement_baseline_definition_ids())
                )
            );
    """)

    # Step 5: Update true_positives policy to include improvement agent with TRAIN access
    op.execute("""
        DROP POLICY IF EXISTS true_positives_agent_select ON true_positives;

        CREATE POLICY true_positives_agent_select ON true_positives
            FOR SELECT
            USING (
                (
                    -- prompt_optimizer: TRAIN split ground truth only
                    current_agent_type() = 'prompt_optimizer'
                    AND is_train_snapshot(snapshot_slug)
                )
                OR
                (
                    -- improvement: TRAIN split ground truth (same as optimizer)
                    current_agent_type() = 'improvement'
                    AND is_train_snapshot(snapshot_slug)
                )
                OR
                (
                    -- grader: ground truth for snapshot being graded
                    current_agent_type() = 'grader'
                    AND snapshot_slug = get_graded_snapshot_slug(current_agent_run_id())
                )
            );
    """)

    # Step 6: Update false_positives policy to include improvement agent with TRAIN access
    op.execute("""
        DROP POLICY IF EXISTS false_positives_agent_select ON false_positives;

        CREATE POLICY false_positives_agent_select ON false_positives
            FOR SELECT
            USING (
                (
                    -- prompt_optimizer: TRAIN split ground truth only
                    current_agent_type() = 'prompt_optimizer'
                    AND is_train_snapshot(snapshot_slug)
                )
                OR
                (
                    -- improvement: TRAIN split ground truth (same as optimizer)
                    current_agent_type() = 'improvement'
                    AND is_train_snapshot(snapshot_slug)
                )
                OR
                (
                    -- grader: ground truth for snapshot being graded
                    current_agent_type() = 'grader'
                    AND snapshot_slug = get_graded_snapshot_slug(current_agent_run_id())
                )
            );
    """)

    # Step 7: Update examples policy to include improvement agent with TRAIN access
    op.execute("""
        DROP POLICY IF EXISTS examples_agent_select ON examples;

        CREATE POLICY examples_agent_select ON examples
            FOR SELECT
            USING (
                (
                    -- prompt_optimizer: see all TRAIN examples
                    current_agent_type() = 'prompt_optimizer'
                    AND is_train_snapshot(snapshot_slug)
                )
                OR
                (
                    -- improvement: see all TRAIN examples (same as optimizer)
                    current_agent_type() = 'improvement'
                    AND is_train_snapshot(snapshot_slug)
                )
                OR
                (
                    -- Other agents: see only their specific scope
                    current_agent_type() IN ('critic', 'clustering')
                    AND snapshot_slug = (
                        SELECT type_config->>'snapshot_slug'
                        FROM agent_runs
                        WHERE agent_run_id = current_agent_run_id()
                    )
                    AND scope_hash = (
                        SELECT type_config->>'scope_hash'
                        FROM agent_runs
                        WHERE agent_run_id = current_agent_run_id()
                    )
                )
            );
    """)

    # Step 8: Update agent_runs policy to include improvement agent with TRAIN access
    op.execute("""
        DROP POLICY IF EXISTS agent_runs_agent_select ON agent_runs;

        CREATE POLICY agent_runs_agent_select ON agent_runs
            FOR SELECT
            USING (
                (
                    -- prompt_optimizer: see all TRAIN split agent runs
                    current_agent_type() = 'prompt_optimizer'
                    AND (
                        (
                            type_config->>'agent_type' = 'critic'
                            AND is_train_snapshot(type_config->>'snapshot_slug')
                        )
                        OR
                        (
                            type_config->>'agent_type' = 'grader'
                            AND is_train_snapshot(get_graded_snapshot_slug(agent_run_id))
                        )
                    )
                )
                OR
                (
                    -- improvement: see all TRAIN split agent runs (same as optimizer)
                    current_agent_type() = 'improvement'
                    AND (
                        (
                            type_config->>'agent_type' = 'critic'
                            AND is_train_snapshot(type_config->>'snapshot_slug')
                        )
                        OR
                        (
                            type_config->>'agent_type' = 'grader'
                            AND is_train_snapshot(get_graded_snapshot_slug(agent_run_id))
                        )
                    )
                )
                OR
                (
                    -- Own run (all agents)
                    agent_run_id = current_agent_run_id()
                )
                OR
                (
                    -- Graders can see the critic run they're grading
                    current_agent_type() = 'grader'
                    AND agent_run_id = current_graded_agent_run_id()
                )
            );
    """)

    # Step 9: Update events policy to include improvement agent with TRAIN access
    op.execute("""
        DROP POLICY IF EXISTS events_agent_select ON events;

        CREATE POLICY events_agent_select ON events
            FOR SELECT
            USING (
                (
                    -- prompt_optimizer: TRAIN split events only
                    current_agent_type() = 'prompt_optimizer'
                    AND is_train_agent_run(events.agent_run_id)
                )
                OR
                (
                    -- improvement: TRAIN split events (same as optimizer)
                    current_agent_type() = 'improvement'
                    AND is_train_agent_run(events.agent_run_id)
                )
                OR
                (
                    -- Other agents: their own run's events
                    events.agent_run_id = current_agent_run_id()
                )
            );
    """)

    # Step 10: Update reported_issues policy to include improvement agent with TRAIN access
    op.execute("""
        DROP POLICY IF EXISTS reported_issues_agent_select ON reported_issues;

        CREATE POLICY reported_issues_agent_select ON reported_issues
            FOR SELECT
            USING (
                (
                    -- prompt_optimizer: TRAIN split only
                    current_agent_type() = 'prompt_optimizer'
                    AND is_train_agent_run(agent_run_id)
                )
                OR
                (
                    -- improvement: TRAIN split (same as optimizer)
                    current_agent_type() = 'improvement'
                    AND is_train_agent_run(agent_run_id)
                )
                OR
                (
                    -- Own issues (critics)
                    agent_run_id = current_agent_run_id()
                )
                OR
                (
                    -- Graders can see the graded critic's issues
                    current_agent_type() = 'grader'
                    AND agent_run_id = current_graded_agent_run_id()
                )
            );
    """)

    # Step 11: Update reported_issue_occurrences policy
    op.execute("""
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_select ON reported_issue_occurrences;

        CREATE POLICY reported_issue_occurrences_agent_select ON reported_issue_occurrences
            FOR SELECT
            USING (
                (
                    -- prompt_optimizer: TRAIN split only
                    current_agent_type() = 'prompt_optimizer'
                    AND is_train_agent_run(agent_run_id)
                )
                OR
                (
                    -- improvement: TRAIN split (same as optimizer)
                    current_agent_type() = 'improvement'
                    AND is_train_agent_run(agent_run_id)
                )
                OR
                (
                    -- Own occurrences (critics)
                    agent_run_id = current_agent_run_id()
                )
                OR
                (
                    -- Graders can see the graded critic's occurrences
                    current_agent_type() = 'grader'
                    AND agent_run_id = current_graded_agent_run_id()
                )
            );
    """)

    # Step 12: Update grading_decisions policy
    op.execute("""
        DROP POLICY IF EXISTS grading_decisions_agent_select ON grading_decisions;

        CREATE POLICY grading_decisions_agent_select ON grading_decisions
            FOR SELECT
            USING (
                (
                    -- prompt_optimizer: TRAIN split only
                    current_agent_type() = 'prompt_optimizer'
                    AND is_train_agent_run(agent_run_id)
                )
                OR
                (
                    -- improvement: TRAIN split (same as optimizer)
                    current_agent_type() = 'improvement'
                    AND is_train_agent_run(agent_run_id)
                )
                OR
                (
                    -- Own decisions (graders)
                    agent_run_id = current_agent_run_id()
                    AND current_agent_type() = 'grader'
                )
            );
    """)

    # Step 13: Drop old improvement-specific helper functions (no longer needed)
    op.execute("DROP FUNCTION IF EXISTS is_agent_example_allowed(TEXT, TEXT)")
    op.execute("DROP FUNCTION IF EXISTS is_agent_snapshot_allowed(TEXT)")
    op.execute("DROP FUNCTION IF EXISTS get_agent_run_ids_for_improvement_allowed()")


def downgrade() -> None:
    """Restore previous RLS policies."""
    # Drop new helper functions
    op.execute("DROP FUNCTION IF EXISTS get_improvement_baseline_definition_ids()")
    op.execute("DROP FUNCTION IF EXISTS get_current_agent_definition_id()")

    # Restore agent_definitions policy (all agents see all)
    op.execute("""
        DROP POLICY IF EXISTS agent_definitions_select ON agent_definitions;

        CREATE POLICY agent_definitions_select ON agent_definitions
            FOR SELECT
            USING (true);
    """)

    # Restore old improvement-specific helper functions
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

    # Note: Full restoration of previous policies would be lengthy.
    # This downgrade removes the new policies; a full restore should
    # copy from migration 20251231000002.
    op.execute("""
        DROP POLICY IF EXISTS true_positives_agent_select ON true_positives;
        DROP POLICY IF EXISTS false_positives_agent_select ON false_positives;
        DROP POLICY IF EXISTS examples_agent_select ON examples;
        DROP POLICY IF EXISTS agent_runs_agent_select ON agent_runs;
        DROP POLICY IF EXISTS events_agent_select ON events;
        DROP POLICY IF EXISTS reported_issues_agent_select ON reported_issues;
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_select ON reported_issue_occurrences;
        DROP POLICY IF EXISTS grading_decisions_agent_select ON grading_decisions;
    """)
