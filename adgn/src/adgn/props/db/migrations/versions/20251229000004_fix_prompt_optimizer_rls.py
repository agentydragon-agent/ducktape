"""Fix prompt optimizer RLS for unified agent_runs table.

Revision ID: 20251229000004
Revises: 20251229000003
Create Date: 2025-12-29

This migration fixes the prompt optimizer's RLS policies after the migration to
unified agent_runs. The previous policies referenced dropped tables (critic_runs,
grader_runs) and dropped helper functions (current_prompt_optimizer_run_id).

## Prompt Optimizer RLS Design (Anti-Overfitting)

The prompt optimizer agent optimizes critic prompts using training data. To prevent
overfitting to validation/test data, RLS enforces strict data isolation:

### TRAIN Split (Full Access)
- Examples: All examples visible (per-file and whole-snapshot)
- Ground truth: true_positives, false_positives tables readable
- Agent runs: All critic/grader runs on TRAIN snapshots visible
- Events: Full execution traces for debugging and analysis
- Purpose: Agent can debug, inspect per-occurrence credits, iterate on failures

### VALID Split (Restricted - Prevents Overfitting)
Access depends on optimization mode:

**Whole-Repo Mode (default, black-box validation):**
- Examples: RLS-blocked (no filenames visible)
- Ground truth: RLS-blocked
- Agent runs: RLS-blocked
- Events: RLS-blocked
- Access: Only via get_validation_run_aggregates() SECURITY DEFINER function
- Purpose: Agent sees aggregate recall metrics only, no failure inspection

**Targeted Mode:**
- Examples: Accessible (filenames visible, but ground truth still hidden)
- Ground truth: RLS-blocked
- Agent runs: RLS-blocked (no detailed run inspection)
- Events: RLS-blocked (no execution traces)
- Access: Via aggregated_recall_by_prompt view
- Purpose: Agent can target specific files for faster iteration

### TEST Split (Off-Limits)
- All tables RLS-blocked
- Never accessible to prompt optimizer
- Reserved for final evaluation

## Implementation

1. Creates current_prompt_optimizer_run_id() function
   - Parses username pattern: prompt_optimizer_agent_{uuid}
   - Returns NULL for non-optimizer users

2. Creates current_prompt_optimizer_target_metric() function
   - Reads target_metric from agent_runs.type_config JSONB
   - Returns 'whole_repo' or 'targeted'

3. Updates prompt_optimizer_agent_template grants
   - Removes references to dropped tables (critic_runs, grader_runs)
   - Adds grant on agent_runs table

4. Creates RLS policies on agent_runs for prompt optimizer
   - Filters to critic/grader runs on TRAIN split only
   - Uses inline subquery (no SECURITY DEFINER needed)

5. Updates events RLS policy
   - Uses agent_run_id instead of transcript_id chain
   - Filters via agent_runs.type_config
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20251229000004"
down_revision: str | Sequence[str] | None = "20251229000003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Fix prompt optimizer RLS for unified agent_runs table."""
    # Step 1: Create helper function to extract prompt optimizer run ID from username
    # Username pattern: prompt_optimizer_agent_{uuid}
    op.execute("""
        CREATE OR REPLACE FUNCTION current_prompt_optimizer_run_id() RETURNS UUID
        LANGUAGE plpgsql STABLE
        AS $fn$
        DECLARE
            run_id_text TEXT;
        BEGIN
            run_id_text := SUBSTRING(session_user FROM 'prompt_optimizer_agent_([0-9a-f-]+)');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            RETURN run_id_text::UUID;
        END;
        $fn$;
    """)

    # Step 2: Create helper function to get target metric from type_config
    # This function reads from agent_runs (requires SECURITY DEFINER to avoid RLS loop)
    op.execute("""
        CREATE OR REPLACE FUNCTION current_prompt_optimizer_target_metric() RETURNS TEXT
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $fn$
        DECLARE
            run_id UUID;
            metric TEXT;
        BEGIN
            run_id := current_prompt_optimizer_run_id();
            IF run_id IS NULL THEN
                RETURN NULL;
            END IF;

            SELECT type_config->>'target_metric' INTO metric
            FROM agent_runs
            WHERE agent_run_id = run_id;

            RETURN COALESCE(metric, 'whole_repo');
        END;
        $fn$;
    """)

    # Step 2b: Create SECURITY DEFINER functions to check snapshot split without RLS
    # These bypass RLS on the snapshots table to avoid infinite recursion
    op.execute("""
        CREATE OR REPLACE FUNCTION is_train_snapshot(slug TEXT) RETURNS BOOLEAN
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $fn$
        BEGIN
            RETURN EXISTS (SELECT 1 FROM snapshots WHERE snapshots.slug = is_train_snapshot.slug AND split = 'train');
        END;
        $fn$;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION is_train_or_valid_snapshot(slug TEXT) RETURNS BOOLEAN
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $fn$
        BEGIN
            RETURN EXISTS (SELECT 1 FROM snapshots WHERE snapshots.slug = is_train_or_valid_snapshot.slug AND split IN ('train', 'valid'));
        END;
        $fn$;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION is_valid_snapshot(slug TEXT) RETURNS BOOLEAN
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $fn$
        BEGIN
            RETURN EXISTS (SELECT 1 FROM snapshots WHERE snapshots.slug = is_valid_snapshot.slug AND split = 'valid');
        END;
        $fn$;
    """)

    # Helper to get snapshot_slug for a grader's graded critic (bypasses agent_runs RLS)
    op.execute("""
        CREATE OR REPLACE FUNCTION get_graded_snapshot_slug(grader_run_id UUID) RETURNS TEXT
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $fn$
        DECLARE
            graded_run_id UUID;
            snapshot TEXT;
        BEGIN
            -- Get the graded_agent_run_id from the grader's type_config
            SELECT (type_config->>'graded_agent_run_id')::UUID INTO graded_run_id
            FROM agent_runs
            WHERE agent_run_id = grader_run_id;

            IF graded_run_id IS NULL THEN
                RETURN NULL;
            END IF;

            -- Get the snapshot_slug from the graded critic's type_config
            SELECT type_config->>'snapshot_slug' INTO snapshot
            FROM agent_runs
            WHERE agent_run_id = graded_run_id;

            RETURN snapshot;
        END;
        $fn$;
    """)

    # Helper to check if an agent run is on a TRAIN split snapshot
    # Works for both critics (direct snapshot_slug) and graders (via graded critic)
    # Used by events, reported_issues, grading_decisions policies
    op.execute("""
        CREATE OR REPLACE FUNCTION is_train_agent_run(run_id UUID) RETURNS BOOLEAN
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $fn$
        DECLARE
            agent_type TEXT;
            snapshot_slug TEXT;
        BEGIN
            -- Get agent type and snapshot slug from type_config
            SELECT
                type_config->>'agent_type',
                type_config->>'snapshot_slug'
            INTO agent_type, snapshot_slug
            FROM agent_runs
            WHERE agent_run_id = run_id;

            IF agent_type IS NULL THEN
                RETURN FALSE;
            END IF;

            -- Critics: check their snapshot_slug directly
            IF agent_type = 'critic' THEN
                RETURN is_train_snapshot(snapshot_slug);
            END IF;

            -- Graders: check the graded critic's snapshot
            IF agent_type = 'grader' THEN
                RETURN is_train_snapshot(get_graded_snapshot_slug(run_id));
            END IF;

            -- Other agent types: not accessible to prompt optimizer
            RETURN FALSE;
        END;
        $fn$;
    """)

    # Step 3: Recreate prompt_optimizer_agent_template role with correct grants
    # (The role may already exist from previous migrations, but grants were revoked)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'prompt_optimizer_agent_template') THEN
                CREATE ROLE prompt_optimizer_agent_template NOLOGIN;
            END IF;
        END
        $$
    """)

    # Grant privileges on tables the prompt optimizer needs
    op.execute("GRANT USAGE ON SCHEMA public TO prompt_optimizer_agent_template")

    # Tables with RLS policies (read-only)
    op.execute("GRANT SELECT ON TABLE snapshots TO prompt_optimizer_agent_template")
    op.execute("GRANT SELECT ON TABLE examples TO prompt_optimizer_agent_template")
    op.execute("GRANT SELECT ON TABLE true_positives TO prompt_optimizer_agent_template")
    op.execute("GRANT SELECT ON TABLE false_positives TO prompt_optimizer_agent_template")
    op.execute("GRANT SELECT ON TABLE agent_runs TO prompt_optimizer_agent_template")
    op.execute("GRANT SELECT ON TABLE events TO prompt_optimizer_agent_template")
    op.execute("GRANT SELECT ON TABLE prompts TO prompt_optimizer_agent_template")
    op.execute("GRANT SELECT ON TABLE reported_issues TO prompt_optimizer_agent_template")
    op.execute("GRANT SELECT ON TABLE reported_issue_occurrences TO prompt_optimizer_agent_template")
    op.execute("GRANT SELECT ON TABLE grading_decisions TO prompt_optimizer_agent_template")

    # Aggregate views (read-only) - grant only if view exists
    # Views may or may not exist depending on migration state
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_views WHERE viewname = 'occurrence_credits') THEN
                GRANT SELECT ON occurrence_credits TO prompt_optimizer_agent_template;
            END IF;
            IF EXISTS (SELECT FROM pg_views WHERE viewname = 'occurrence_run_credits') THEN
                GRANT SELECT ON occurrence_run_credits TO prompt_optimizer_agent_template;
            END IF;
            IF EXISTS (SELECT FROM pg_views WHERE viewname = 'aggregated_recall_by_prompt') THEN
                GRANT SELECT ON aggregated_recall_by_prompt TO prompt_optimizer_agent_template;
            END IF;
            IF EXISTS (SELECT FROM pg_views WHERE viewname = 'aggregated_recall_by_example') THEN
                GRANT SELECT ON aggregated_recall_by_example TO prompt_optimizer_agent_template;
            END IF;
        END
        $$;
    """)

    # Validation function (SECURITY DEFINER, provides VALID split aggregates)
    # Grant only if function exists
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM pg_proc p
                JOIN pg_namespace n ON p.pronamespace = n.oid
                WHERE n.nspname = 'public' AND p.proname = 'get_validation_run_aggregates'
            ) THEN
                GRANT EXECUTE ON FUNCTION get_validation_run_aggregates() TO prompt_optimizer_agent_template;
            END IF;
        END
        $$;
    """)

    # Step 4: Drop old prompt optimizer RLS policies (they reference dropped tables/functions)
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_snapshots ON snapshots")
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_examples ON examples")
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_true_positives ON true_positives")
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_false_positives ON false_positives")
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_critiques ON critiques")
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_critic_runs ON critic_runs")
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_grader_runs ON grader_runs")
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_events ON events")

    # Step 5: Create new RLS policies for prompt optimizer
    #
    # Snapshots table contains only metadata (slug, split, source) - not sensitive.
    # All agents can see all snapshots. This simplifies RLS and avoids recursion issues.

    op.execute("""
        DROP POLICY IF EXISTS snapshots_agent_select ON snapshots;
        DROP POLICY IF EXISTS prompt_optimizer_snapshots ON snapshots;

        CREATE POLICY snapshots_agent_select ON snapshots
            FOR SELECT
            USING (
                -- Any agent (prompt optimizer or regular agent) can see all snapshots
                current_prompt_optimizer_run_id() IS NOT NULL
                OR current_agent_run_id() IS NOT NULL
            );
    """)
    op.execute("""
        COMMENT ON POLICY snapshots_agent_select ON snapshots IS
        'All agents can see all snapshots. The snapshots table contains only metadata
        (slug, split, source info) which is not sensitive. Actual data access control
        is enforced on examples, true_positives, false_positives, and agent_runs tables.'
    """)

    # Examples: TRAIN always visible; VALID only in targeted mode
    # Uses SECURITY DEFINER functions to avoid RLS recursion on snapshots
    op.execute("""
        CREATE POLICY prompt_optimizer_examples ON examples
        FOR SELECT
        USING (
            current_prompt_optimizer_run_id() IS NOT NULL
            AND (
                is_train_snapshot(snapshot_slug)
                OR (
                    current_prompt_optimizer_target_metric() = 'targeted'
                    AND is_valid_snapshot(snapshot_slug)
                )
            )
        )
    """)
    op.execute("""
        COMMENT ON POLICY prompt_optimizer_examples ON examples IS
        'Prompt optimizer access to examples:
        - TRAIN: always accessible (filenames + ground truth via TPs)
        - VALID: only in targeted mode (filenames visible, ground truth hidden via TPs policy)
        - TEST: never accessible'
    """)

    # True positives: TRAIN only (prevents overfitting to VALID ground truth)
    op.execute("""
        CREATE POLICY prompt_optimizer_true_positives ON true_positives
        FOR SELECT
        USING (
            current_prompt_optimizer_run_id() IS NOT NULL
            AND is_train_snapshot(snapshot_slug)
        )
    """)
    op.execute("""
        COMMENT ON POLICY prompt_optimizer_true_positives ON true_positives IS
        'Prompt optimizer sees TRAIN split ground truth only (VALID/TEST hidden to prevent overfitting)'
    """)

    # False positives: TRAIN only
    op.execute("""
        CREATE POLICY prompt_optimizer_false_positives ON false_positives
        FOR SELECT
        USING (
            current_prompt_optimizer_run_id() IS NOT NULL
            AND is_train_snapshot(snapshot_slug)
        )
    """)
    op.execute("""
        COMMENT ON POLICY prompt_optimizer_false_positives ON false_positives IS
        'Prompt optimizer sees TRAIN split false positives only (VALID/TEST hidden)'
    """)

    # Agent runs: See critic/grader runs on TRAIN split only
    # Uses SECURITY DEFINER functions to check split without RLS recursion
    op.execute("""
        CREATE POLICY prompt_optimizer_agent_runs ON agent_runs
        FOR SELECT
        USING (
            current_prompt_optimizer_run_id() IS NOT NULL
            AND (
                -- Critic runs: check snapshot_slug in type_config
                (
                    type_config->>'agent_type' = 'critic'
                    AND is_train_snapshot(type_config->>'snapshot_slug')
                )
                OR
                -- Grader runs: use SECURITY DEFINER function to get graded snapshot
                (
                    type_config->>'agent_type' = 'grader'
                    AND is_train_snapshot(get_graded_snapshot_slug(agent_run_id))
                )
            )
        )
    """)
    op.execute("""
        COMMENT ON POLICY prompt_optimizer_agent_runs ON agent_runs IS
        'Prompt optimizer sees critic/grader runs on TRAIN split only:
        - Critic runs: snapshot_slug must be in TRAIN split
        - Grader runs: graded critic''s snapshot must be in TRAIN split
        - VALID/TEST runs hidden to prevent overfitting to specific failures'
    """)

    # Events: Accessible only for TRAIN split agent runs
    # Uses SECURITY DEFINER functions to avoid RLS recursion
    op.execute("""
        CREATE POLICY prompt_optimizer_events ON events
        FOR SELECT
        USING (
            current_prompt_optimizer_run_id() IS NOT NULL
            AND is_train_agent_run(events.agent_run_id)
        )
    """)
    op.execute("""
        COMMENT ON POLICY prompt_optimizer_events ON events IS
        'Prompt optimizer sees execution traces only for TRAIN split runs
        (VALID/TEST traces hidden to prevent learning from validation failures)'
    """)

    # Reported issues: Accessible for TRAIN split critic runs only
    op.execute("""
        CREATE POLICY prompt_optimizer_reported_issues ON reported_issues
        FOR SELECT
        USING (
            current_prompt_optimizer_run_id() IS NOT NULL
            AND is_train_agent_run(reported_issues.agent_run_id)
        )
    """)

    # Reported issue occurrences: Accessible for TRAIN split critic runs only
    op.execute("""
        CREATE POLICY prompt_optimizer_reported_issue_occurrences ON reported_issue_occurrences
        FOR SELECT
        USING (
            current_prompt_optimizer_run_id() IS NOT NULL
            AND is_train_agent_run(reported_issue_occurrences.agent_run_id)
        )
    """)

    # Grading decisions: Accessible for grader runs on TRAIN split only
    op.execute("""
        CREATE POLICY prompt_optimizer_grading_decisions ON grading_decisions
        FOR SELECT
        USING (
            current_prompt_optimizer_run_id() IS NOT NULL
            AND is_train_agent_run(grading_decisions.agent_run_id)
        )
    """)


def downgrade() -> None:
    """Remove prompt optimizer RLS policies and helper functions."""
    # Drop new policies
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_grading_decisions ON grading_decisions")
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_reported_issue_occurrences ON reported_issue_occurrences")
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_reported_issues ON reported_issues")
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_events ON events")
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_agent_runs ON agent_runs")
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_false_positives ON false_positives")
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_true_positives ON true_positives")
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_examples ON examples")

    # Restore original snapshots policy (without prompt optimizer case)
    # Note: The simplified "all agents see all snapshots" policy doesn't need
    # to be reverted to complex logic - just remove prompt optimizer from condition
    op.execute("""
        DROP POLICY IF EXISTS snapshots_agent_select ON snapshots;

        CREATE POLICY snapshots_agent_select ON snapshots
            FOR SELECT
            USING (
                -- Regular agents can see all snapshots (metadata only, not sensitive)
                current_agent_run_id() IS NOT NULL
            );
    """)

    # Drop helper functions (in reverse dependency order)
    op.execute("DROP FUNCTION IF EXISTS is_train_agent_run(UUID) CASCADE")
    op.execute("DROP FUNCTION IF EXISTS get_graded_snapshot_slug(UUID) CASCADE")
    op.execute("DROP FUNCTION IF EXISTS is_valid_snapshot(TEXT) CASCADE")
    op.execute("DROP FUNCTION IF EXISTS is_train_or_valid_snapshot(TEXT) CASCADE")
    op.execute("DROP FUNCTION IF EXISTS is_train_snapshot(TEXT) CASCADE")
    op.execute("DROP FUNCTION IF EXISTS current_prompt_optimizer_target_metric() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS current_prompt_optimizer_run_id() CASCADE")

    # Revoke grants from template role
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'prompt_optimizer_agent_template') THEN
                DROP OWNED BY prompt_optimizer_agent_template CASCADE;
            END IF;
        END
        $$;
    """)
