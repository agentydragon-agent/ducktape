"""Squashed schema for props database.

This is a complete schema migration that replaces all previous migrations.
It was generated from schema_dump_for_squash.sql with manual translation
to proper Alembic operations where practical.

Key schema features:
- Unified agent_runs table (replaces legacy critic_runs, grader_runs, etc.)
- stats_with_ci composite type for statistics with 95% confidence intervals
- Occurrence-weighted aggregation (raw totals, not normalized ratios)
- RLS policies for agent data isolation
- SECURITY DEFINER functions for RLS bypasses

Revision ID: 20251223000000
Revises: None
Create Date: 2025-12-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20251223000000"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Issue ID format constraint (matches props.ids.BaseIssueID):
# - lowercase alphanumeric, underscore, hyphen only
# - 5-40 characters
# - no colons (implicit from pattern)
ISSUE_ID_CHECK_SQL = "~ '^[a-z0-9_-]+$' AND length({col}) >= 5 AND length({col}) <= 40"


def issue_id_constraint(column: str, name: str) -> sa.CheckConstraint:
    """Create a CHECK constraint enforcing BaseIssueID format on a column."""
    return sa.CheckConstraint(f"{column} {ISSUE_ID_CHECK_SQL.format(col=column)}", name=name)


def upgrade() -> None:
    """Create complete schema.

    Order:
    1. Extensions
    2. ENUMs
    3. Composite types
    4. Functions (all - body checking disabled to allow forward references)
    5. Tables
    6. Indexes
    7. Views (including grading_credit_sums needed by trigger)
    8. Triggers
    9. Roles and grants
    10. RLS policies
    """

    # Disable function body checking to allow functions to reference tables not yet created
    # (same as pg_dump does - references are validated at execution time instead)
    op.execute("SET check_function_bodies = false")

    # =========================================================================
    # 1. Extensions
    # =========================================================================
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public")

    # =========================================================================
    # 2. ENUMs
    # =========================================================================
    op.execute("""
        CREATE TYPE agent_run_status_enum AS ENUM (
            'in_progress',
            'completed',
            'max_turns_exceeded',
            'context_length_exceeded',
            'reported_failure'
        )
    """)

    op.execute("""
        CREATE TYPE agent_type_enum AS ENUM (
            'critic',
            'grader',
            'prompt_optimizer',
            'clustering',
            'freeform',
            'improvement'
        )
    """)

    op.execute("""
        CREATE TYPE split_enum AS ENUM (
            'train',
            'valid',
            'test'
        )
    """)

    op.execute("""
        CREATE TYPE example_kind_enum AS ENUM (
            'whole_snapshot',
            'file_set'
        )
    """)

    # =========================================================================
    # 3. Composite types
    # =========================================================================
    op.execute("""
        CREATE TYPE stats_with_ci AS (
            n integer,
            mean double precision,
            min double precision,
            max double precision,
            lcb95 double precision,
            ucb95 double precision
        )
    """)

    op.execute("""
        COMMENT ON TYPE stats_with_ci IS
        'Statistics with 95% confidence interval bounds. Used for aggregated metrics.
- n: sample count
- mean: sample mean
- min: minimum value
- max: maximum value
- lcb95: lower 95% confidence bound (mean - 1.96 * stddev/sqrt(n))
- ucb95: upper 95% confidence bound (mean + 1.96 * stddev/sqrt(n))
Returns NULL for lcb95/ucb95 when n < 2 (insufficient samples for CI).'
    """)

    # =========================================================================
    # 4. Functions (table-independent - can be created before tables)
    # =========================================================================

    # Helper: aggregate status counts into JSONB
    op.execute("""
        CREATE FUNCTION agg_status_counts(statuses agent_run_status_enum[])
        RETURNS jsonb
        LANGUAGE sql
        IMMUTABLE
        AS $$
            SELECT jsonb_object_agg(s, cnt)
            FROM (
                SELECT s, count(*) AS cnt
                FROM unnest(statuses) AS s
                GROUP BY s
            ) sub
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION agg_status_counts(agent_run_status_enum[]) IS
        'Aggregates an array of status values into JSONB counts. Used by aggregate views.
Example: agg_status_counts(array_agg(status)) -> {"completed": 5, "max_turns_exceeded": 2}'
    """)

    # Helper: merge array of status count JSONBs (for re-aggregation)
    op.execute("""
        CREATE FUNCTION agg_status_counts(counts jsonb[])
        RETURNS jsonb
        LANGUAGE sql
        IMMUTABLE
        AS $$
            SELECT COALESCE(
                jsonb_object_agg(key, total),
                '{}'::jsonb
            )
            FROM (
                SELECT key, SUM(value::bigint) AS total
                FROM unnest(counts) AS c,
                     jsonb_each_text(c) AS kv(key, value)
                GROUP BY key
            ) sub
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION agg_status_counts(jsonb[]) IS
        'Merges an array of status count JSONBs by summing counts per status. Used by higher-level views.
Example: agg_status_counts(ARRAY[''{"completed": 2}'', ''{"completed": 3}'']::jsonb[]) -> {"completed": 5}'
    """)

    # Helper: compute statistics with confidence intervals
    op.execute("""
        CREATE FUNCTION compute_stats_with_ci(vals double precision[])
        RETURNS stats_with_ci
        LANGUAGE sql
        IMMUTABLE
        AS $$
            SELECT ROW(
                count(*)::integer,
                avg(v),
                min(v),
                max(v),
                CASE WHEN count(*) > 1 THEN avg(v) - 1.96 * stddev_samp(v) / sqrt(count(*)) ELSE NULL END,
                CASE WHEN count(*) > 1 THEN avg(v) + 1.96 * stddev_samp(v) / sqrt(count(*)) ELSE NULL END
            )::stats_with_ci
            FROM unnest(vals) AS v
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION compute_stats_with_ci(double precision[]) IS
        'Computes n, mean, min, max, and 95% confidence bounds from an array of values.
Usage: compute_stats_with_ci(array_agg(some_metric))
Access fields: (compute_stats_with_ci(...)).mean, .min, .max, .lcb95, .ucb95, etc.'
    """)

    # Helper: scale stats_with_ci by a divisor (e.g., credit -> recall)
    op.execute("""
        CREATE FUNCTION scale_stats(s stats_with_ci, divisor double precision)
        RETURNS stats_with_ci
        LANGUAGE sql
        IMMUTABLE
        AS $$
            SELECT CASE WHEN divisor = 0 THEN
                ROW(s.n, 0.0, 0.0, 0.0, NULL, NULL)::stats_with_ci
            ELSE
                ROW(
                    s.n,
                    s.mean / divisor,
                    s.min / divisor,
                    s.max / divisor,
                    s.lcb95 / divisor,
                    s.ucb95 / divisor
                )::stats_with_ci
            END
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION scale_stats(stats_with_ci, double precision) IS
        'Divides all values in a stats_with_ci by a divisor.
Use to convert raw count stats to ratio stats (e.g., credit / n_catchable_occurrences for recall).
Example: scale_stats(credit_stats, n_catchable_occurrences)'
    """)

    # Helper: current_agent_run_id from session username
    op.execute("""
        CREATE FUNCTION current_agent_run_id() RETURNS uuid
        LANGUAGE sql STABLE
        AS $$
            SELECT CASE
                WHEN session_user LIKE 'agent_%'
                THEN substring(session_user from 'agent_([0-9a-f-]+)')::uuid
                ELSE NULL
            END
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION current_agent_run_id() IS
        'Extract agent_run_id from session username (NULL if not an agent).
Uses session_user (not current_user) to work correctly when called from within SECURITY DEFINER functions.'
    """)

    # Helper: get_agent_type_config (SECURITY DEFINER)
    op.execute("""
        CREATE FUNCTION get_agent_type_config(p_agent_run_id uuid) RETURNS jsonb
        LANGUAGE sql STABLE SECURITY DEFINER
        AS $$
            SELECT type_config
            FROM agent_runs
            WHERE agent_run_id = p_agent_run_id
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION get_agent_type_config(uuid) IS
        'Returns type_config JSONB for given agent_run_id. SECURITY DEFINER to bypass RLS on agent_runs.'
    """)

    # Helper: current_agent_type_config (SECURITY DEFINER)
    op.execute("""
        CREATE FUNCTION current_agent_type_config() RETURNS jsonb
        LANGUAGE sql STABLE SECURITY DEFINER
        AS $$
            SELECT type_config
            FROM agent_runs
            WHERE agent_run_id = current_agent_run_id()
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION current_agent_type_config() IS
        'Returns type_config JSONB for current agent. SECURITY DEFINER to bypass RLS on agent_runs.
Returns NULL for non-agents.'
    """)

    # Helper: current_agent_type (SECURITY DEFINER)
    op.execute("""
        CREATE FUNCTION current_agent_type() RETURNS text
        LANGUAGE sql STABLE SECURITY DEFINER
        AS $$
            SELECT current_agent_type_config()->>'agent_type'
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION current_agent_type() IS
        'Returns agent_type from current_agent_type_config(). SECURITY DEFINER for RLS policy use.'
    """)

    # Helper: get_graded_agent_run_id (SECURITY DEFINER)
    op.execute("""
        CREATE FUNCTION get_graded_agent_run_id(p_grader_run_id uuid) RETURNS uuid
        LANGUAGE sql STABLE SECURITY DEFINER
        AS $$
            SELECT (type_config->>'graded_agent_run_id')::UUID
            FROM agent_runs
            WHERE agent_run_id = p_grader_run_id
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION get_graded_agent_run_id(uuid) IS
        'Returns graded_agent_run_id from grader type_config. SECURITY DEFINER to bypass RLS.'
    """)

    # Helper: current_graded_agent_run_id (SECURITY DEFINER)
    op.execute("""
        CREATE FUNCTION current_graded_agent_run_id() RETURNS uuid
        LANGUAGE sql STABLE SECURITY DEFINER
        AS $$
            SELECT get_graded_agent_run_id(current_agent_run_id())
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION current_graded_agent_run_id() IS
        'Returns graded_agent_run_id from current grader type_config. SECURITY DEFINER to bypass RLS.'
    """)

    # Helper: get_graded_snapshot_slug (SECURITY DEFINER)
    op.execute("""
        CREATE FUNCTION get_graded_snapshot_slug(grader_run_id uuid) RETURNS text
        LANGUAGE sql STABLE SECURITY DEFINER
        AS $$
            SELECT type_config->'example'->>'snapshot_slug'
            FROM agent_runs
            WHERE agent_run_id = get_graded_agent_run_id(grader_run_id)
        $$
    """)

    # Helper: derive_agent_password (SECURITY DEFINER)
    op.execute("""
        CREATE FUNCTION derive_agent_password(run_id uuid) RETURNS text
        LANGUAGE sql STABLE SECURITY DEFINER
        AS $$
            SELECT encode(
                sha256((SELECT salt FROM agent_role_salt) || run_id::text::bytea),
                'hex'
            )
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION derive_agent_password(uuid) IS
        'Derive deterministic password for agent role (admin-only)'
    """)

    # Helper: create_agent_role (SECURITY DEFINER)
    op.execute("""
        CREATE FUNCTION create_agent_role(run_id uuid) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER
        AS $$
        DECLARE
            username TEXT := 'agent_' || run_id::text;
            password TEXT := derive_agent_password(run_id);
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = username) THEN
                EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', username, password);
                EXECUTE format('GRANT agent_base TO %I', username);
            END IF;
        END
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION create_agent_role(uuid) IS
        'Create LOGIN role for agent with deterministic password (admin-only)'
    """)

    # Snapshot predicate functions
    op.execute("""
        CREATE FUNCTION is_train_snapshot(slug text) RETURNS boolean
        LANGUAGE sql STABLE
        AS $$
            SELECT EXISTS (
                SELECT 1 FROM snapshots
                WHERE snapshots.slug = is_train_snapshot.slug AND split = 'train'
            )
        $$
    """)

    op.execute("""
        CREATE FUNCTION is_valid_snapshot(slug text) RETURNS boolean
        LANGUAGE sql STABLE
        AS $$
            SELECT EXISTS (
                SELECT 1 FROM snapshots
                WHERE snapshots.slug = is_valid_snapshot.slug AND split = 'valid'
            )
        $$
    """)

    op.execute("""
        CREATE FUNCTION is_train_or_valid_snapshot(slug text) RETURNS boolean
        LANGUAGE sql STABLE
        AS $$
            SELECT EXISTS (
                SELECT 1 FROM snapshots
                WHERE snapshots.slug = is_train_or_valid_snapshot.slug
                  AND split IN ('train', 'valid')
            )
        $$
    """)

    # Helper: is_train_agent_run (SECURITY DEFINER)
    op.execute("""
        CREATE FUNCTION is_train_agent_run(run_id uuid) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER
        AS $$
            SELECT COALESCE(
                CASE get_agent_type_config(run_id)->>'agent_type'
                    WHEN 'critic' THEN is_train_snapshot(get_agent_type_config(run_id)->'example'->>'snapshot_slug')
                    WHEN 'grader' THEN is_train_snapshot(get_graded_snapshot_slug(run_id))
                    ELSE FALSE
                END,
                FALSE
            )
        $$
    """)

    # Improvement agent helpers
    op.execute("""
        CREATE FUNCTION is_improvement_example_allowed(
            p_snapshot_slug text,
            p_example_kind example_kind_enum,
            p_files_hash text
        ) RETURNS boolean
        LANGUAGE sql STABLE
        AS $$
            SELECT COALESCE(
                (current_agent_type_config()->>'agent_type' = 'improvement')
                AND EXISTS (
                    SELECT 1 FROM jsonb_array_elements(current_agent_type_config()->'allowed_examples') elem
                    WHERE elem->>'snapshot_slug' = p_snapshot_slug
                      AND (elem->>'kind')::example_kind_enum = p_example_kind
                      AND (
                          -- NULL files_hash for whole_snapshot examples
                          (p_example_kind = 'whole_snapshot' AND (elem->>'files_hash') IS NULL)
                          OR (p_example_kind = 'file_set' AND (elem->>'files_hash') = p_files_hash)
                      )
                ),
                FALSE
            )
        $$
    """)

    op.execute("""
        CREATE FUNCTION is_improvement_snapshot_allowed(p_slug text) RETURNS boolean
        LANGUAGE sql STABLE
        AS $$
            SELECT COALESCE(
                (current_agent_type_config()->>'agent_type' = 'improvement')
                AND EXISTS (
                    SELECT 1 FROM jsonb_array_elements(current_agent_type_config()->'allowed_examples') elem
                    WHERE elem->>'snapshot_slug' = p_slug
                ),
                FALSE
            )
        $$
    """)

    op.execute("""
        CREATE FUNCTION get_improvement_allowed_agent_run_ids() RETURNS SETOF uuid
        LANGUAGE sql STABLE SECURITY DEFINER
        AS $$
            SELECT ar.agent_run_id
            FROM agent_runs ar
            WHERE current_agent_type_config()->>'agent_type' = 'improvement'
              AND ar.type_config->>'agent_type' IN ('critic', 'grader')
              AND EXISTS (
                  SELECT 1 FROM jsonb_array_elements(current_agent_type_config()->'allowed_examples') elem
                  WHERE elem->>'snapshot_slug' = ar.type_config->'example'->>'snapshot_slug'
                    AND elem->>'kind' = ar.type_config->'example'->>'kind'
                    AND (
                        (ar.type_config->'example'->>'kind' = 'whole_snapshot' AND (elem->>'files_hash') IS NULL)
                        OR (ar.type_config->'example'->>'kind' = 'file_set' AND (elem->>'files_hash') = (ar.type_config->'example'->>'files_hash'))
                    )
              )
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION get_improvement_allowed_agent_run_ids() IS
        'Returns agent_run_ids for critic/grader runs that match current improvement agent allowed_examples.
SECURITY DEFINER to bypass RLS.'
    """)

    op.execute("""
        CREATE FUNCTION get_agent_run_ids_for_train_snapshots() RETURNS SETOF uuid
        LANGUAGE sql STABLE SECURITY DEFINER
        AS $$
            SELECT agent_run_id
            FROM agent_runs
            WHERE type_config->>'agent_type' IN ('critic', 'grader')
              AND type_config->'example'->>'snapshot_slug' IN (SELECT slug FROM snapshots WHERE split = 'train')
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION get_agent_run_ids_for_train_snapshots() IS
        'Returns agent_run_ids for critic/grader runs on TRAIN snapshots. SECURITY DEFINER to bypass RLS.'
    """)

    # DRY helper: can_access_snapshot - unified snapshot access check for RLS policies
    op.execute("""
        CREATE FUNCTION can_access_snapshot(p_slug text) RETURNS boolean
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $$
        BEGIN
            RETURN (
                (current_agent_type() = 'prompt_optimizer' AND is_train_snapshot(p_slug))
                OR (current_agent_type() = 'grader' AND p_slug = get_graded_snapshot_slug(current_agent_run_id()))
                OR (current_agent_type() = 'improvement' AND is_improvement_snapshot_allowed(p_slug))
                OR (current_agent_type() = 'clustering' AND p_slug = current_agent_type_config()->>'snapshot_slug')
            );
        END;
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION can_access_snapshot(text) IS
        'Unified snapshot access check for RLS policies. Returns TRUE if current agent can access the given snapshot.
Used by true_positives, false_positives, and their occurrence tables.'
    """)

    # DRY helper: is_own_run_as - check if run belongs to current agent with specific type
    op.execute("""
        CREATE FUNCTION is_own_run_as(p_run_id uuid, p_type text) RETURNS boolean
        LANGUAGE plpgsql STABLE
        AS $$
        BEGIN
            RETURN p_run_id = current_agent_run_id() AND current_agent_type() = p_type;
        END;
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION is_own_run_as(uuid, text) IS
        'Returns TRUE if the given run_id belongs to current agent AND agent is of the specified type.
Used for critic/grader write policies.'
    """)

    # Catchability functions - check if TP/FP is catchable/relevant given a scope
    op.execute("""
        CREATE FUNCTION is_tp_catchable_from_scope(
            p_snapshot_slug text,
            p_tp_id text,
            p_example_kind example_kind_enum,
            p_files_hash text
        ) RETURNS boolean
        LANGUAGE sql STABLE
        AS $$
            -- Whole-snapshot scope catches everything
            SELECT CASE
                WHEN p_example_kind = 'whole_snapshot' THEN TRUE
                ELSE EXISTS (
                    -- Check if any file set for this TP is a subset of the reviewed scope
                    SELECT 1
                    FROM occurrence_triggers ot
                    WHERE ot.snapshot_slug = p_snapshot_slug
                      AND ot.tp_id = p_tp_id
                      -- All files in this file set must be in the reviewed scope
                      AND NOT EXISTS (
                          SELECT 1 FROM file_set_members fsm
                          WHERE fsm.snapshot_slug = p_snapshot_slug
                            AND fsm.files_hash = ot.files_hash
                            AND fsm.file_path NOT IN (
                                SELECT fsm2.file_path
                                FROM file_set_members fsm2
                                WHERE fsm2.snapshot_slug = p_snapshot_slug
                                  AND fsm2.files_hash = p_files_hash
                            )
                      )
                )
            END
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION is_tp_catchable_from_scope(text, text, example_kind_enum, text) IS
        'Returns TRUE if any file set for the given TP is a subset of the reviewed scope files.
For whole-snapshot scope, always returns TRUE.'
    """)

    op.execute("""
        CREATE FUNCTION is_fp_relevant_for_scope(
            p_snapshot_slug text,
            p_fp_id text,
            p_example_kind example_kind_enum,
            p_files_hash text
        ) RETURNS boolean
        LANGUAGE sql STABLE
        AS $$
            -- Whole-snapshot scope makes all FPs relevant
            SELECT CASE
                WHEN p_example_kind = 'whole_snapshot' THEN TRUE
                ELSE EXISTS (
                    -- Check if any relevant_file for this FP is in the reviewed scope
                    SELECT 1
                    FROM false_positives fp
                    CROSS JOIN LATERAL jsonb_array_elements(fp.occurrences) AS occ
                    CROSS JOIN LATERAL jsonb_array_elements_text(occ->'relevant_files') AS rf
                    WHERE fp.snapshot_slug = p_snapshot_slug
                      AND fp.fp_id = p_fp_id
                      AND rf IN (
                          SELECT fsm.file_path
                          FROM file_set_members fsm
                          WHERE fsm.snapshot_slug = p_snapshot_slug
                            AND fsm.files_hash = p_files_hash
                      )
                )
            END
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION is_fp_relevant_for_scope(text, text, example_kind_enum, text) IS
        'Returns TRUE if any relevant_file in any FP occurrence overlaps with the reviewed scope files.
For whole-snapshot scope, always returns TRUE.'
    """)

    # Trigger functions
    op.execute("""
        CREATE FUNCTION check_credit_sum() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            current_total FLOAT;
        BEGIN
            -- Skip if no target (no-match case)
            IF NEW.target_tp_id IS NULL AND NEW.target_fp_id IS NULL THEN
                RETURN NEW;
            END IF;

            -- Get current total from view (excluding NEW row)
            IF NEW.target_tp_id IS NOT NULL THEN
                SELECT COALESCE(total_credit, 0.0) INTO current_total
                FROM grading_credit_sums
                WHERE agent_run_id = NEW.agent_run_id
                  AND target_tp_id = NEW.target_tp_id
                  AND target_tp_occurrence_id = NEW.target_tp_occurrence_id;

                -- On UPDATE, subtract old credit from current total
                IF TG_OP = 'UPDATE' THEN
                    current_total := current_total - OLD.credit;
                END IF;
            ELSE
                SELECT COALESCE(total_credit, 0.0) INTO current_total
                FROM grading_credit_sums
                WHERE agent_run_id = NEW.agent_run_id
                  AND target_fp_id = NEW.target_fp_id
                  AND target_fp_occurrence_id = NEW.target_fp_occurrence_id;

                -- On UPDATE, subtract old credit from current total
                IF TG_OP = 'UPDATE' THEN
                    current_total := current_total - OLD.credit;
                END IF;
            END IF;

            -- Add new credit and validate
            current_total := COALESCE(current_total, 0.0) + NEW.credit;

            IF current_total > 1.0 THEN
                RAISE EXCEPTION 'Credit sum would exceed 1.0 for occurrence (current: %, new: %, total: %)',
                    current_total - NEW.credit, NEW.credit, current_total
                USING HINT = 'Each occurrence can have at most 1.0 total credit across all input issues';
            END IF;

            RETURN NEW;
        END;
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION check_credit_sum() IS
        'Trigger function that validates credit sums per occurrence do not exceed 1.0.'
    """)

    op.execute("""
        CREATE FUNCTION check_input_issue_exists() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            graded_critic_run_id UUID;
        BEGIN
            -- Get the critic run ID being graded from the grader's type_config
            graded_critic_run_id := get_graded_agent_run_id(NEW.agent_run_id);

            IF graded_critic_run_id IS NULL THEN
                RAISE EXCEPTION 'Grader run % has no graded_agent_run_id in type_config', NEW.agent_run_id;
            END IF;

            -- Check that the input_issue_id exists in reported_issues for that critic run
            IF NOT EXISTS (
                SELECT 1 FROM reported_issues
                WHERE agent_run_id = graded_critic_run_id
                  AND issue_id = NEW.input_issue_id
            ) THEN
                RAISE EXCEPTION 'Input issue % does not exist in critic run %',
                    NEW.input_issue_id, graded_critic_run_id;
            END IF;

            RETURN NEW;
        END;
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION check_input_issue_exists() IS
        'Validates that grading_decisions.input_issue_id exists in the graded critic run''s reported_issues'
    """)

    # Validation function (for legacy compatibility)
    op.execute("""
        CREATE FUNCTION validate_input_issue_exists(grader_run_id uuid, input_issue_id text) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER
        AS $_$
            SELECT EXISTS (
                SELECT 1
                FROM reported_issues ri
                JOIN agent_runs gr ON gr.agent_run_id = get_graded_agent_run_id($1)
                WHERE ri.agent_run_id = gr.agent_run_id AND ri.issue_id = $2
            )
        $_$
    """)

    # Trigger function to validate grading target TP/FP exists
    op.execute("""
        CREATE FUNCTION check_grading_target_exists() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            graded_critic_run_id UUID;
            grader_snapshot_slug TEXT;
        BEGIN
            -- Get the critic run ID being graded
            graded_critic_run_id := get_graded_agent_run_id(NEW.agent_run_id);

            IF graded_critic_run_id IS NULL THEN
                RAISE EXCEPTION 'Grader run % has no graded_agent_run_id in type_config', NEW.agent_run_id;
            END IF;

            -- Get the snapshot slug from the critic run's example
            SELECT (type_config -> 'example' ->> 'snapshot_slug')
            INTO grader_snapshot_slug
            FROM agent_runs
            WHERE agent_run_id = graded_critic_run_id;

            -- Validate target TP occurrence exists
            IF NEW.target_tp_id IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1 FROM true_positive_occurrences
                    WHERE snapshot_slug = grader_snapshot_slug
                      AND tp_id = NEW.target_tp_id
                      AND occurrence_id = NEW.target_tp_occurrence_id
                ) THEN
                    RAISE EXCEPTION 'TP occurrence (tp_id=%, occurrence_id=%) does not exist in snapshot %',
                        NEW.target_tp_id, NEW.target_tp_occurrence_id, grader_snapshot_slug;
                END IF;
            END IF;

            -- Validate target FP occurrence exists
            IF NEW.target_fp_id IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1 FROM false_positive_occurrences
                    WHERE snapshot_slug = grader_snapshot_slug
                      AND fp_id = NEW.target_fp_id
                      AND occurrence_id = NEW.target_fp_occurrence_id
                ) THEN
                    RAISE EXCEPTION 'FP occurrence (fp_id=%, occurrence_id=%) does not exist in snapshot %',
                        NEW.target_fp_id, NEW.target_fp_occurrence_id, grader_snapshot_slug;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION check_grading_target_exists() IS
        'Validates that grading_decisions target_tp_id/target_fp_id references exist in ground truth'
    """)

    # Trigger function to validate unknown_assignments mapped TP/FP exists
    op.execute("""
        CREATE FUNCTION check_unknown_mapping_exists() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            grader_run_snapshot_slug TEXT;
        BEGIN
            -- Only validate if a mapping is set
            IF NEW.mapped_tp_id IS NULL AND NEW.mapped_fp_id IS NULL THEN
                RETURN NEW;
            END IF;

            -- Get the snapshot slug from the grader run's graded critic run
            SELECT (cr.type_config -> 'example' ->> 'snapshot_slug')
            INTO grader_run_snapshot_slug
            FROM agent_runs gr
            JOIN agent_runs cr ON cr.agent_run_id = get_graded_agent_run_id(gr.agent_run_id)
            WHERE gr.agent_run_id = NEW.grader_run_id;

            IF grader_run_snapshot_slug IS NULL THEN
                RAISE EXCEPTION 'Could not determine snapshot for grader run %', NEW.grader_run_id;
            END IF;

            -- Validate mapped TP exists
            IF NEW.mapped_tp_id IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1 FROM true_positives
                    WHERE snapshot_slug = grader_run_snapshot_slug
                      AND tp_id = NEW.mapped_tp_id
                ) THEN
                    RAISE EXCEPTION 'Mapped TP (tp_id=%) does not exist in snapshot %',
                        NEW.mapped_tp_id, grader_run_snapshot_slug;
                END IF;
            END IF;

            -- Validate mapped FP exists
            IF NEW.mapped_fp_id IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1 FROM false_positives
                    WHERE snapshot_slug = grader_run_snapshot_slug
                      AND fp_id = NEW.mapped_fp_id
                ) THEN
                    RAISE EXCEPTION 'Mapped FP (fp_id=%) does not exist in snapshot %',
                        NEW.mapped_fp_id, grader_run_snapshot_slug;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION check_unknown_mapping_exists() IS
        'Validates that unknown_assignments mapped_tp_id/mapped_fp_id references exist in ground truth'
    """)

    # SECURITY DEFINER function for validation aggregates
    op.execute("""
        CREATE FUNCTION get_validation_full_snapshot_aggregates()
        RETURNS TABLE(
            snapshot_slug text,
            critic_definition_id text,
            critic_model text,
            grader_model text,
            critic_run_id uuid,
            grader_run_id uuid,
            status agent_run_status_enum,
            total_credit double precision,
            n_occurrences integer
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path TO 'public'
        AS $$
          WITH occurrence_avg_credits AS (
            SELECT
                oc.snapshot_slug,
                oc.critic_definition_id,
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
            JOIN agent_runs cr ON oc.critic_run_id = cr.agent_run_id
            WHERE s.split = 'valid'::split_enum
              AND oc.example_kind = 'whole_snapshot'
              AND (cr.type_config->>'agent_type') = 'critic'
            GROUP BY oc.snapshot_slug, oc.critic_definition_id, oc.critic_model, oc.grader_model,
                     oc.critic_run_id, oc.grader_run_id, cr.status, oc.tp_id, oc.occurrence_id
          )
          SELECT
            snapshot_slug,
            critic_definition_id,
            critic_model,
            grader_model,
            critic_run_id,
            grader_run_id,
            status,
            SUM(avg_credit) as total_credit,
            CAST(COUNT(*) AS integer) as n_occurrences
          FROM occurrence_avg_credits
          GROUP BY snapshot_slug, critic_definition_id, critic_model, grader_model,
                   critic_run_id, grader_run_id, status
          ORDER BY snapshot_slug, critic_definition_id, critic_model, grader_model,
                   critic_run_id, grader_run_id
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION get_validation_full_snapshot_aggregates() IS
        'Black-box validation metrics for whole-repo mode.
Returns per-run recall for VALID split, whole_snapshot example_kind only.
Includes critic_run status for proper outcome counting.
Used by prompt optimizer in whole-repo validation mode.'
    """)

    # Line number validation trigger function for reported_issue_occurrences
    op.execute("""
        CREATE FUNCTION validate_reported_issue_line_numbers()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        DECLARE
          loc jsonb;
          file_path text;
          start_ln int;
          end_ln int;
          max_lines int;
          example_snapshot text;
        BEGIN
          -- Get snapshot slug from agent run
          SELECT ar.type_config -> 'example' ->> 'snapshot_slug'
          INTO example_snapshot
          FROM agent_runs ar
          JOIN reported_issues ri ON ri.agent_run_id = ar.agent_run_id
          WHERE ar.agent_run_id = NEW.agent_run_id;

          -- Iterate through locations array
          FOR loc IN SELECT * FROM jsonb_array_elements(NEW.locations)
          LOOP
            file_path := loc->>'file';
            start_ln := (loc->>'start_line')::int;
            end_ln := (loc->>'end_line')::int;

            -- Skip if no line numbers specified
            CONTINUE WHEN start_ln IS NULL AND end_ln IS NULL;

            -- Get file's line count from snapshot_files
            SELECT line_count INTO max_lines
            FROM snapshot_files sf
            WHERE sf.snapshot_slug = example_snapshot
              AND sf.relative_path = file_path;

            IF NOT FOUND THEN
              RAISE EXCEPTION 'File % not found in snapshot_files for snapshot %',
                file_path, example_snapshot;
            END IF;

            -- Validate line numbers against file bounds
            -- Use <= because line N exists in an N-line file (1-based indexing, inclusive range)
            IF start_ln IS NOT NULL AND start_ln > max_lines THEN
              RAISE EXCEPTION 'start_line % exceeds file line_count % for % (valid range: 1..%)',
                start_ln, max_lines, file_path, max_lines;
            END IF;

            IF end_ln IS NOT NULL AND end_ln > max_lines THEN
              RAISE EXCEPTION 'end_line % exceeds file line_count % for % (valid range: 1..%)',
                end_ln, max_lines, file_path, max_lines;
            END IF;
          END LOOP;

          RETURN NEW;
        END;
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION validate_reported_issue_line_numbers() IS
        'Validates reported issue line numbers against snapshot_files.line_count.
Line numbers are 1-based: for a file with line_count=N, valid range is 1..N (inclusive).
Raises exception if line numbers exceed file bounds or file not found in snapshot_files.'
    """)

    # NOTE: validate_true_positive_line_numbers() is no longer needed since occurrences
    # moved to the separate true_positive_occurrences table. Line number validation
    # happens via validate_occurrence_line_numbers() trigger on that table.

    # NOTE: validate_false_positive_line_numbers() is no longer needed since occurrences
    # moved to the separate false_positive_occurrences table. Line number validation
    # happens via validate_occurrence_line_numbers() trigger on that table.

    # =========================================================================
    # 5. Tables
    # =========================================================================

    # Snapshots table
    op.create_table(
        "snapshots",
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column(
            "split", postgresql.ENUM("train", "valid", "test", name="split_enum", create_type=False), nullable=False
        ),
        sa.Column("content", sa.LargeBinary(), nullable=True, comment="tar archive of source code"),
        sa.Column("source", postgresql.JSONB(), nullable=True, comment="provenance"),
        sa.Column("bundle", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("slug"),
    )

    # Agent definitions table
    op.create_table(
        "agent_definitions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column(
            "agent_type",
            postgresql.ENUM(
                "critic",
                "grader",
                "prompt_optimizer",
                "clustering",
                "freeform",
                "improvement",
                name="agent_type_enum",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("archive", sa.LargeBinary(), nullable=False),
        sa.Column("created_by_agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("octet_length(archive) <= 10485760", name="agent_definitions_archive_max_size"),
    )

    op.execute(
        "COMMENT ON TABLE agent_definitions IS 'Agent definition archives containing AGENT.md, init script, and tools'"
    )
    op.execute(
        "COMMENT ON COLUMN agent_definitions.id IS 'Readable ID: repo-backed use names like \"critic\", agent-created use auto-generated'"
    )
    op.execute(
        "COMMENT ON COLUMN agent_definitions.archive IS 'Uncompressed tar archive of the definition directory (max 10MB)'"
    )
    op.execute(
        "COMMENT ON COLUMN agent_definitions.created_by_agent_run_id IS 'Agent run that created this definition (NULL for repo-backed)'"
    )

    # Agent role salt table (singleton)
    op.create_table(
        "agent_role_salt",
        sa.Column("id", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("salt", sa.LargeBinary(), server_default=sa.text("gen_random_bytes(32)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id = 1", name="agent_role_salt_id_check"),
    )

    op.execute(
        "COMMENT ON TABLE agent_role_salt IS 'Singleton containing salt for deterministic agent password derivation'"
    )
    op.execute("REVOKE ALL ON agent_role_salt FROM PUBLIC")

    # Agent runs table
    op.create_table(
        "agent_runs",
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_definition_id", sa.Text(), nullable=False),
        sa.Column("parent_agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("type_config", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "in_progress",
                "completed",
                "max_turns_exceeded",
                "context_length_exceeded",
                "reported_failure",
                name="agent_run_status_enum",
                create_type=False,
            ),
            server_default=sa.text("'in_progress'"),
            nullable=False,
        ),
        sa.Column("completion_summary", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("agent_run_id"),
        sa.ForeignKeyConstraint(["agent_definition_id"], ["agent_definitions.id"]),
        sa.ForeignKeyConstraint(["parent_agent_run_id"], ["agent_runs.agent_run_id"]),
    )

    op.execute(
        "COMMENT ON TABLE agent_runs IS 'Unified table for all agent runs (critics, graders, optimizers, freeform)'"
    )
    op.execute(
        "COMMENT ON COLUMN agent_runs.parent_agent_run_id IS 'Parent agent that spawned this sub-agent (NULL for top-level)'"
    )
    op.execute(
        "COMMENT ON COLUMN agent_runs.type_config IS 'JSONB with agent_type discriminator and type-specific fields'"
    )
    op.execute(
        "COMMENT ON COLUMN agent_runs.status IS 'Run status: in_progress, completed, max_turns_exceeded, context_length_exceeded, or reported_failure'"
    )
    op.execute(
        "COMMENT ON COLUMN agent_runs.completion_summary IS 'Markdown summary from agent when status=completed, or error message when status=reported_failure'"
    )

    # Add FK from agent_definitions to agent_runs (circular reference)
    op.create_foreign_key(
        "fk_agent_definitions_created_by",
        "agent_definitions",
        "agent_runs",
        ["created_by_agent_run_id"],
        ["agent_run_id"],
    )

    # Snapshot files table - all files in each snapshot for FK validation
    op.create_table(
        "snapshot_files",
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column("relative_path", sa.String(), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_slug", "relative_path"),
        sa.ForeignKeyConstraint(["snapshot_slug"], ["snapshots.slug"], ondelete="CASCADE"),
    )

    op.execute(
        "COMMENT ON TABLE snapshot_files IS 'All files in each snapshot. Used for FK validation of file paths in occurrences and trigger sets.'"
    )
    op.execute(
        "COMMENT ON COLUMN snapshot_files.relative_path IS "
        "'Path relative to snapshot root (e.g., \"src/utils.py\"). NOT absolute paths.'"
    )

    # True positives table (issue header - occurrences are in separate table)
    op.create_table(
        "true_positives",
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column("tp_id", sa.String(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_slug", "tp_id"),
        sa.ForeignKeyConstraint(["snapshot_slug"], ["snapshots.slug"], ondelete="CASCADE"),
        issue_id_constraint("tp_id", "tp_id_format"),
    )

    # False positives table (issue header - occurrences are in separate table)
    op.create_table(
        "false_positives",
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column("fp_id", sa.String(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_slug", "fp_id"),
        sa.ForeignKeyConstraint(["snapshot_slug"], ["snapshots.slug"], ondelete="CASCADE"),
        issue_id_constraint("fp_id", "fp_id_format"),
    )

    op.execute(
        "COMMENT ON TABLE false_positives IS "
        "'Patterns the labeler considers acceptable - teaches agents what NOT to flag.'"
    )

    # True positive occurrences table (normalized from JSONB)
    # Note: expect_caught_from is stored in occurrence_triggers M:N table, not as JSONB column
    op.create_table(
        "true_positive_occurrences",
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column("tp_id", sa.String(), nullable=False),
        sa.Column("occurrence_id", sa.String(), nullable=False),
        sa.Column("files", postgresql.JSONB(), nullable=False),  # {path: [line_ranges] | null}
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_slug", "tp_id", "occurrence_id"),
        sa.ForeignKeyConstraint(
            ["snapshot_slug", "tp_id"], ["true_positives.snapshot_slug", "true_positives.tp_id"], ondelete="CASCADE"
        ),
    )

    # False positive occurrences table (normalized from JSONB)
    op.create_table(
        "false_positive_occurrences",
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column("fp_id", sa.String(), nullable=False),
        sa.Column("occurrence_id", sa.String(), nullable=False),
        sa.Column("files", postgresql.JSONB(), nullable=False),  # {path: [line_ranges] | null}
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("relevant_files", postgresql.JSONB(), nullable=False),  # [path, ...]
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_slug", "fp_id", "occurrence_id"),
        sa.ForeignKeyConstraint(
            ["snapshot_slug", "fp_id"], ["false_positives.snapshot_slug", "false_positives.fp_id"], ondelete="CASCADE"
        ),
    )

    # Trigger-based validation for occurrence line numbers
    # SEMANTICS: Line numbers are 1-based. Ranges are inclusive [start_line, end_line].
    # Structure: files[path][j].{start_line, end_line}
    op.execute("""
        CREATE OR REPLACE FUNCTION validate_occurrence_line_numbers()
        RETURNS TRIGGER AS $$
        DECLARE
            invalid_count INTEGER;
        BEGIN
            -- Only validate files with non-null line ranges (null = no line ranges specified)
            SELECT COUNT(*) INTO invalid_count
            FROM jsonb_each(NEW.files) AS file_entry
            CROSS JOIN LATERAL jsonb_array_elements(file_entry.value) AS line_range
            WHERE file_entry.value IS NOT NULL
              AND jsonb_typeof(file_entry.value) = 'array'
              AND ((line_range->>'start_line')::int < 1
                   OR (line_range->>'end_line' IS NOT NULL AND (line_range->>'end_line')::int < 1)
                   OR (line_range->>'end_line' IS NOT NULL
                       AND (line_range->>'end_line')::int < (line_range->>'start_line')::int));

            IF invalid_count > 0 THEN
                RAISE EXCEPTION 'Invalid line numbers in occurrence: line numbers must be >= 1 and end_line >= start_line';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        COMMENT ON FUNCTION validate_occurrence_line_numbers() IS
        'Validates line numbers in occurrence files are positive (>= 1) and end_line >= start_line. Line numbers are 1-based.
        Does NOT validate against file line_count - that must be validated at insertion time.';
    """)

    op.execute("""
        CREATE TRIGGER validate_tp_occ_line_numbers
        BEFORE INSERT OR UPDATE ON true_positive_occurrences
        FOR EACH ROW EXECUTE FUNCTION validate_occurrence_line_numbers();
    """)

    op.execute("""
        CREATE TRIGGER validate_fp_occ_line_numbers
        BEFORE INSERT OR UPDATE ON false_positive_occurrences
        FOR EACH ROW EXECUTE FUNCTION validate_occurrence_line_numbers();
    """)

    # Basic line number validation for reported_issue_occurrences
    # (different structure: locations array with {file, start_line, end_line} objects)
    op.execute("""
        CREATE OR REPLACE FUNCTION validate_reported_issue_occ_basic_line_numbers()
        RETURNS TRIGGER AS $$
        DECLARE
            invalid_count INTEGER;
        BEGIN
            SELECT COUNT(*) INTO invalid_count
            FROM jsonb_array_elements(NEW.locations) AS loc
            WHERE (loc->>'start_line' IS NOT NULL AND (loc->>'start_line')::int < 1)
               OR (loc->>'end_line' IS NOT NULL AND (loc->>'end_line')::int < 1)
               OR (loc->>'start_line' IS NOT NULL AND loc->>'end_line' IS NOT NULL
                   AND (loc->>'end_line')::int < (loc->>'start_line')::int);

            IF invalid_count > 0 THEN
                RAISE EXCEPTION 'Invalid line numbers in reported issue occurrence: line numbers must be >= 1 and end_line >= start_line';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        COMMENT ON FUNCTION validate_reported_issue_occ_basic_line_numbers() IS
        'Validates basic line number constraints for reported_issue_occurrences: positive (>= 1) and end_line >= start_line.
        Cross-table validation against snapshot_files.line_count is done by validate_reported_issue_line_numbers().';
    """)

    # File sets table - deduplicated, content-addressable by (snapshot_slug, files_hash)
    op.create_table(
        "file_sets",
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column("files_hash", sa.String(), nullable=False),  # MD5 of sorted file paths
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_slug", "files_hash"),
        sa.ForeignKeyConstraint(["snapshot_slug"], ["snapshots.slug"], ondelete="CASCADE"),
    )

    op.execute("""
        COMMENT ON TABLE file_sets IS
        'Content-addressable file sets for training examples.
Primary key is (snapshot_slug, files_hash) where files_hash = MD5 of sorted file paths.
Deduplicated by PK constraint - same files always produce same hash.'
    """)

    # File set members table - files in each file set (FK-validated)
    op.create_table(
        "file_set_members",
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column("files_hash", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_slug", "files_hash", "file_path"),
        sa.ForeignKeyConstraint(
            ["snapshot_slug", "files_hash"], ["file_sets.snapshot_slug", "file_sets.files_hash"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_slug", "file_path"],
            ["snapshot_files.snapshot_slug", "snapshot_files.relative_path"],
            ondelete="CASCADE",
        ),
    )

    op.execute("""
        COMMENT ON TABLE file_set_members IS
        'Files belonging to each file set. FK to snapshot_files validates file paths exist in snapshot.'
    """)

    # Occurrence triggers - M:N linking occurrences to file sets
    op.create_table(
        "occurrence_triggers",
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column("tp_id", sa.String(), nullable=False),
        sa.Column("occurrence_id", sa.String(), nullable=False),
        sa.Column("files_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_slug", "tp_id", "occurrence_id", "files_hash"),
        sa.ForeignKeyConstraint(
            ["snapshot_slug", "tp_id", "occurrence_id"],
            [
                "true_positive_occurrences.snapshot_slug",
                "true_positive_occurrences.tp_id",
                "true_positive_occurrences.occurrence_id",
            ],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_slug", "files_hash"], ["file_sets.snapshot_slug", "file_sets.files_hash"], ondelete="CASCADE"
        ),
    )

    op.execute("""
        COMMENT ON TABLE occurrence_triggers IS
        'M:N relationship linking true_positive_occurrences to file_sets.
Each occurrence can be triggered by multiple file sets (expect_caught_from alternatives).'
    """)

    # Reported issues table
    op.create_table(
        "reported_issues",
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue_id", sa.String(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("agent_run_id", "issue_id"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.agent_run_id"], ondelete="CASCADE"),
        issue_id_constraint("issue_id", "issue_id_format"),
    )

    op.execute(
        "COMMENT ON COLUMN reported_issues.agent_run_id IS 'FK to agent_runs - identifies which agent run reported this issue'"
    )

    # Reported issue occurrences table
    op.create_table(
        "reported_issue_occurrences",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reported_issue_id", sa.String(), nullable=False),
        sa.Column(
            "locations",
            postgresql.JSONB(),
            nullable=False,
            comment="1+ location anchors: {file, start_line?, end_line?}",
        ),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["agent_run_id", "reported_issue_id"],
            ["reported_issues.agent_run_id", "reported_issues.issue_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("jsonb_array_length(locations) > 0", name="locations_not_empty"),
        # Line number validation done via trigger (validate_reported_issue_occ_basic_line_numbers)
        # because PostgreSQL doesn't allow subqueries in CHECK constraints
    )

    op.execute(
        "COMMENT ON COLUMN reported_issue_occurrences.agent_run_id IS 'FK to agent_runs (denormalized from reported_issues for RLS efficiency)'"
    )

    op.execute("""
        CREATE TRIGGER validate_reported_issue_occ_basic_line_numbers_trigger
        BEFORE INSERT OR UPDATE ON reported_issue_occurrences
        FOR EACH ROW EXECUTE FUNCTION validate_reported_issue_occ_basic_line_numbers();
    """)

    # Grading decisions table
    op.create_table(
        "grading_decisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("input_issue_id", sa.String(), nullable=False),
        sa.Column("target_tp_id", sa.String(), nullable=True, comment="TP target (nullable)"),
        sa.Column("target_tp_occurrence_id", sa.String(), nullable=True, comment="TP target (nullable)"),
        sa.Column("target_fp_id", sa.String(), nullable=True, comment="FP target (nullable)"),
        sa.Column("target_fp_occurrence_id", sa.String(), nullable=True, comment="FP target (nullable)"),
        sa.Column("credit", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "agent_run_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("current_agent_run_id()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.agent_run_id"], ondelete="CASCADE"),
        sa.CheckConstraint("credit >= 0.0 AND credit <= 1.0", name="credit_in_range"),
        sa.CheckConstraint(
            "(target_tp_id IS NOT NULL AND target_tp_occurrence_id IS NOT NULL AND target_fp_id IS NULL AND target_fp_occurrence_id IS NULL) "
            "OR (target_tp_id IS NULL AND target_tp_occurrence_id IS NULL AND target_fp_id IS NOT NULL AND target_fp_occurrence_id IS NOT NULL) "
            "OR (target_tp_id IS NULL AND target_tp_occurrence_id IS NULL AND target_fp_id IS NULL AND target_fp_occurrence_id IS NULL)",
            name="exactly_one_target",
        ),
        sa.CheckConstraint(
            "target_tp_id IS NOT NULL OR target_fp_id IS NOT NULL OR credit = 0.0", name="no_match_zero_credit"
        ),
        # Issue ID format constraints
        issue_id_constraint("input_issue_id", "input_issue_id_format"),
        sa.CheckConstraint(
            f"target_tp_id IS NULL OR (target_tp_id {ISSUE_ID_CHECK_SQL.format(col='target_tp_id')})",
            name="target_tp_id_format",
        ),
        sa.CheckConstraint(
            f"target_fp_id IS NULL OR (target_fp_id {ISSUE_ID_CHECK_SQL.format(col='target_fp_id')})",
            name="target_fp_id_format",
        ),
    )

    op.execute(
        "COMMENT ON COLUMN grading_decisions.agent_run_id IS 'FK to agent_runs - identifies which grader agent run created this decision'"
    )
    op.execute(
        "COMMENT ON TABLE grading_decisions IS "
        "'Matches input issues to TPs/FPs. Trigger enforces SUM(credit) <= 1.0 per occurrence.'"
    )

    # Events table
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_num", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["agent_run_id"], ["agent_runs.agent_run_id"], ondelete="CASCADE", name="fk_events_agent_run_id"
        ),
        sa.UniqueConstraint("agent_run_id", "sequence_num", name="uq_events_agent_run_id_seq"),
    )

    # Unknown clusters table
    op.create_table(
        "unknown_clusters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cluster_name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["agent_run_id"], ["agent_runs.agent_run_id"], ondelete="CASCADE", name="fk_unknown_clusters_agent_run_id"
        ),
        sa.UniqueConstraint("agent_run_id", "cluster_name", name="uq_unknown_clusters_agent_run_cluster_name"),
    )

    # Unknown assignments table
    op.create_table(
        "unknown_assignments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("grader_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("unknown_id", sa.String(), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=True),
        sa.Column("mapped_tp_id", sa.String(), nullable=True),
        sa.Column("mapped_fp_id", sa.String(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["grader_run_id"],
            ["agent_runs.agent_run_id"],
            ondelete="CASCADE",
            name="fk_unknown_assignments_grader_run_id",
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.agent_run_id"],
            ondelete="CASCADE",
            name="fk_unknown_assignments_agent_run_id",
        ),
        sa.ForeignKeyConstraint(["cluster_id"], ["unknown_clusters.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "agent_run_id", "grader_run_id", "unknown_id", "cancelled_at", name="uq_unknown_assignments_unique_active"
        ),
        sa.CheckConstraint(
            "(cluster_id IS NOT NULL AND mapped_tp_id IS NULL AND mapped_fp_id IS NULL) "
            "OR (cluster_id IS NULL AND mapped_tp_id IS NOT NULL AND mapped_fp_id IS NULL) "
            "OR (cluster_id IS NULL AND mapped_tp_id IS NULL AND mapped_fp_id IS NOT NULL)",
            name="unknown_assignments_exactly_one_target_check",
        ),
        # Issue ID format constraints
        issue_id_constraint("unknown_id", "unknown_id_format"),
        sa.CheckConstraint(
            f"mapped_tp_id IS NULL OR (mapped_tp_id {ISSUE_ID_CHECK_SQL.format(col='mapped_tp_id')})",
            name="mapped_tp_id_format",
        ),
        sa.CheckConstraint(
            f"mapped_fp_id IS NULL OR (mapped_fp_id {ISSUE_ID_CHECK_SQL.format(col='mapped_fp_id')})",
            name="mapped_fp_id_format",
        ),
    )

    # Model metadata table
    op.create_table(
        "model_metadata",
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("input_usd_per_1m_tokens", sa.Float(), nullable=False),
        sa.Column("cached_input_usd_per_1m_tokens", sa.Float(), nullable=True),
        sa.Column("output_usd_per_1m_tokens", sa.Float(), nullable=False),
        sa.Column("context_window_tokens", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("model_id"),
    )

    # =========================================================================
    # 6. Indexes
    # =========================================================================
    op.create_index("idx_agent_definitions_type", "agent_definitions", ["agent_type"])
    op.create_index(
        "idx_agent_definitions_created_by",
        "agent_definitions",
        ["created_by_agent_run_id"],
        postgresql_where=sa.text("created_by_agent_run_id IS NOT NULL"),
    )

    op.create_index("idx_agent_runs_type", "agent_runs", [sa.text("(type_config->>'agent_type')")])
    op.create_index(
        "idx_agent_runs_parent",
        "agent_runs",
        ["parent_agent_run_id"],
        postgresql_where=sa.text("parent_agent_run_id IS NOT NULL"),
    )
    op.create_index(
        "idx_agent_runs_snapshot",
        "agent_runs",
        [sa.text("(type_config->'example'->>'snapshot_slug')")],
        postgresql_where=sa.text("(type_config->>'agent_type') = 'critic'"),
    )

    # NOTE: examples is now a VIEW (not a table), so we cannot create indexes on it.
    # The underlying tables (snapshots, file_sets, occurrence_triggers) are already indexed.

    op.create_index("ix_true_positives_snapshot_slug", "true_positives", ["snapshot_slug"])
    op.create_index("ix_false_positives_snapshot_slug", "false_positives", ["snapshot_slug"])

    op.create_index("ix_reported_issues_critic_run", "reported_issues", ["agent_run_id"])
    op.create_index(
        "ix_reported_issue_occurrences_reported_issue",
        "reported_issue_occurrences",
        ["agent_run_id", "reported_issue_id"],
    )

    op.create_index("grading_decisions_agent_run_id_idx", "grading_decisions", ["agent_run_id"])

    op.create_index("ix_events_agent_run_id_seq", "events", ["agent_run_id", "sequence_num"])

    op.create_index("ix_unknown_clusters_agent_run_id", "unknown_clusters", ["agent_run_id"])

    op.create_index("ix_unknown_assignments_agent_run_id", "unknown_assignments", ["agent_run_id"])
    op.create_index("ix_unknown_assignments_grader_run_id", "unknown_assignments", ["grader_run_id"])
    op.create_index("ix_unknown_assignments_grader_unknown", "unknown_assignments", ["grader_run_id", "unknown_id"])
    op.create_index(
        "ix_unknown_assignments_active",
        "unknown_assignments",
        ["agent_run_id", "grader_run_id", "unknown_id"],
        postgresql_where=sa.text("cancelled_at IS NULL"),
    )
    op.create_index(
        "ix_unknown_assignments_cluster_active",
        "unknown_assignments",
        ["cluster_id"],
        postgresql_where=sa.text("cancelled_at IS NULL"),
    )

    # =========================================================================
    # 7. Views (grading_credit_sums must be created before trigger that uses it)
    # =========================================================================

    # grading_credit_sums view (used by check_credit_sum trigger function)
    op.execute("""
        CREATE VIEW grading_credit_sums AS
        SELECT agent_run_id,
            target_tp_id,
            target_tp_occurrence_id,
            target_fp_id,
            target_fp_occurrence_id,
            sum(credit) AS total_credit
        FROM grading_decisions
        WHERE target_tp_id IS NOT NULL OR target_fp_id IS NOT NULL
        GROUP BY agent_run_id, target_tp_id, target_tp_occurrence_id, target_fp_id, target_fp_occurrence_id
    """)

    op.execute("""
        COMMENT ON VIEW grading_credit_sums IS
        'Aggregate credit sums per (agent_run, occurrence) for enforcing credit <= 1.0 constraint.
Used by check_credit_sum trigger function.'
    """)

    # examples view - derived from file_sets + whole-snapshot entries
    # Uses set-based join for catchable count (optimized from per-row function calls)
    op.execute("""
        CREATE VIEW examples AS
        -- Whole-snapshot examples (one per snapshot)
        SELECT
            slug AS snapshot_slug,
            'whole_snapshot'::example_kind_enum AS example_kind,
            NULL::text AS files_hash,
            (
                SELECT COUNT(DISTINCT (tpo.tp_id, tpo.occurrence_id))::integer
                FROM true_positive_occurrences tpo
                WHERE tpo.snapshot_slug = slug
            ) AS n_catchable_occurrences
        FROM snapshots

        UNION ALL

        -- Per-file-set examples with optimized catchable count
        -- Uses set-based join instead of per-row function calls
        SELECT
            fs.snapshot_slug,
            'file_set'::example_kind_enum AS example_kind,
            fs.files_hash,
            COALESCE(catchable.n_catchable, 0) AS n_catchable_occurrences
        FROM file_sets fs
        LEFT JOIN (
            -- Compute catchable occurrences per file_set using set operations
            SELECT
                fs_inner.snapshot_slug,
                fs_inner.files_hash,
                COUNT(DISTINCT (tpo.tp_id, tpo.occurrence_id))::integer AS n_catchable
            FROM file_sets fs_inner
            JOIN true_positive_occurrences tpo ON tpo.snapshot_slug = fs_inner.snapshot_slug
            WHERE EXISTS (
                -- Check if any trigger for this TP occurrence is a subset of the scope
                SELECT 1 FROM occurrence_triggers ot
                WHERE ot.snapshot_slug = fs_inner.snapshot_slug
                  AND ot.tp_id = tpo.tp_id
                  AND ot.occurrence_id = tpo.occurrence_id
                  -- Trigger files must be subset of scope files
                  AND NOT EXISTS (
                      SELECT 1 FROM file_set_members trigger_f
                      LEFT JOIN file_set_members scope_f
                        ON scope_f.snapshot_slug = fs_inner.snapshot_slug
                        AND scope_f.files_hash = fs_inner.files_hash
                        AND scope_f.file_path = trigger_f.file_path
                      WHERE trigger_f.snapshot_slug = fs_inner.snapshot_slug
                        AND trigger_f.files_hash = ot.files_hash
                        AND scope_f.file_path IS NULL  -- file in trigger but not in scope
                  )
            )
            GROUP BY fs_inner.snapshot_slug, fs_inner.files_hash
        ) catchable ON catchable.snapshot_slug = fs.snapshot_slug
                   AND catchable.files_hash = fs.files_hash
    """)

    op.execute("""
        COMMENT ON VIEW examples IS
        'Training examples derived from file_sets (per-file) + whole-snapshot entries.
Primary key: (snapshot_slug, example_kind, files_hash).
For per-file examples, files are resolved via FK joins to file_set_members.
Already deduplicated by content-addressable file_sets PK.

n_catchable_occurrences: Computed from ground truth using set-based join
(optimized from per-row function calls for ~900x speedup).'
    """)

    # =========================================================================
    # 8. Triggers (after views they depend on)
    # =========================================================================
    op.execute("""
        CREATE TRIGGER enforce_credit_sum
        BEFORE INSERT OR UPDATE ON grading_decisions
        FOR EACH ROW EXECUTE FUNCTION check_credit_sum()
    """)

    op.execute("""
        CREATE TRIGGER check_input_issue_exists_trigger
        BEFORE INSERT OR UPDATE ON grading_decisions
        FOR EACH ROW EXECUTE FUNCTION check_input_issue_exists()
    """)

    op.execute("""
        CREATE TRIGGER check_grading_target_exists_trigger
        BEFORE INSERT OR UPDATE ON grading_decisions
        FOR EACH ROW EXECUTE FUNCTION check_grading_target_exists()
    """)

    op.execute("""
        CREATE TRIGGER check_unknown_mapping_exists_trigger
        BEFORE INSERT OR UPDATE ON unknown_assignments
        FOR EACH ROW EXECUTE FUNCTION check_unknown_mapping_exists()
    """)

    op.execute("""
        CREATE TRIGGER validate_line_numbers_trigger
        BEFORE INSERT OR UPDATE ON reported_issue_occurrences
        FOR EACH ROW EXECUTE FUNCTION validate_reported_issue_line_numbers()
    """)

    # NOTE: validate_tp_line_numbers_trigger and validate_fp_line_numbers_trigger
    # are no longer needed since occurrences moved to separate tables.
    # Line number validation happens via validate_tp_occ_line_numbers and
    # validate_fp_occ_line_numbers triggers on the occurrences tables.

    # =========================================================================
    # 9. Additional Views
    # =========================================================================

    # occurrence_credits view
    op.execute("""
        CREATE VIEW occurrence_credits AS
        SELECT
            -- Example identification
            (cr.type_config -> 'example' ->> 'snapshot_slug') AS snapshot_slug,
            s.split,
            ex.example_kind,
            ex.files_hash,
            -- Ground truth
            gd.target_tp_id AS tp_id,
            gd.target_tp_occurrence_id AS occurrence_id,
            -- Critic-specific
            cr.agent_run_id AS critic_run_id,
            cr.agent_run_id AS critic_transcript_id,
            cr.agent_definition_id AS critic_definition_id,
            cr.model AS critic_model,
            -- Grader-specific
            gr.agent_run_id AS grader_run_id,
            gr.agent_run_id AS grader_transcript_id,
            gr.created_at AS graded_at,
            gr.model AS grader_model,
            sum(gd.credit) AS found_credit,
            jsonb_agg(gd.input_issue_id ORDER BY gd.input_issue_id) AS matched_by_json,
            max(gd.rationale) AS grader_rationale
        FROM agent_runs gr
        JOIN agent_runs cr ON cr.agent_run_id = get_graded_agent_run_id(gr.agent_run_id)
        JOIN snapshots s ON (cr.type_config -> 'example' ->> 'snapshot_slug') = s.slug
        JOIN examples ex ON (
            (cr.type_config -> 'example' ->> 'snapshot_slug') = ex.snapshot_slug
            AND (cr.type_config -> 'example' ->> 'kind')::example_kind_enum = ex.example_kind
            AND COALESCE((cr.type_config -> 'example' ->> 'files_hash'), '') = COALESCE(ex.files_hash, '')
        )
        JOIN grading_decisions gd ON gr.agent_run_id = gd.agent_run_id
        WHERE (gr.type_config ->> 'agent_type') = 'grader'
          AND (cr.type_config ->> 'agent_type') = 'critic'
          AND gd.target_tp_id IS NOT NULL
        GROUP BY (cr.type_config -> 'example' ->> 'snapshot_slug'), s.split, ex.example_kind, ex.files_hash,
            gd.target_tp_id, gd.target_tp_occurrence_id, cr.agent_run_id, cr.agent_definition_id, cr.model,
            gr.agent_run_id, gr.created_at, gr.model
        UNION ALL
        SELECT
            -- Example identification
            (cr.type_config -> 'example' ->> 'snapshot_slug') AS snapshot_slug,
            s.split,
            ex.example_kind,
            ex.files_hash,
            -- Ground truth
            tpo.tp_id,
            tpo.occurrence_id,
            -- Critic-specific
            cr.agent_run_id AS critic_run_id,
            cr.agent_run_id AS critic_transcript_id,
            cr.agent_definition_id AS critic_definition_id,
            cr.model AS critic_model,
            -- Grader-specific (NULL for failed critics)
            NULL::uuid AS grader_run_id,
            NULL::uuid AS grader_transcript_id,
            cr.created_at AS graded_at,
            NULL::varchar AS grader_model,
            0.0 AS found_credit,
            NULL::jsonb AS matched_by_json,
            ('Critic failed: ' || cr.status) AS grader_rationale
        FROM agent_runs cr
        JOIN snapshots s ON (cr.type_config -> 'example' ->> 'snapshot_slug') = s.slug
        JOIN examples ex ON (
            (cr.type_config -> 'example' ->> 'snapshot_slug') = ex.snapshot_slug
            AND (cr.type_config -> 'example' ->> 'kind')::example_kind_enum = ex.example_kind
            AND COALESCE((cr.type_config -> 'example' ->> 'files_hash'), '') = COALESCE(ex.files_hash, '')
        )
        CROSS JOIN true_positive_occurrences tpo
        WHERE (cr.type_config ->> 'agent_type') = 'critic'
          AND cr.status = ANY (ARRAY['max_turns_exceeded'::agent_run_status_enum, 'context_length_exceeded'::agent_run_status_enum])
          AND (cr.type_config -> 'example' ->> 'snapshot_slug') = tpo.snapshot_slug
          AND is_tp_catchable_from_scope(tpo.snapshot_slug, tpo.tp_id, ex.example_kind, ex.files_hash)
    """)

    op.execute("""
        COMMENT ON VIEW occurrence_credits IS
        'Per-occurrence credit assignments from grader decisions or failed critic runs.

For successful grading: joins grader agent_run to critic agent_run via type_config->graded_agent_run_id.
For failed critics: synthesizes zero-credit rows for catchable occurrences.'
    """)

    # occurrence_run_credits view
    op.execute("""
        CREATE VIEW occurrence_run_credits AS
        SELECT
            -- Example identification
            snapshot_slug,
            split,
            example_kind,
            files_hash,
            -- Ground truth
            tp_id,
            occurrence_id,
            -- Critic-specific
            critic_run_id,
            critic_transcript_id,
            critic_definition_id,
            critic_model,
            -- Grader-specific
            grader_run_id,
            grader_transcript_id,
            graded_at,
            grader_model,
            sum(found_credit) AS total_credit,
            array_agg(DISTINCT matched_by_json) FILTER (WHERE matched_by_json IS NOT NULL) AS all_matched_by,
            string_agg(DISTINCT grader_rationale, ' | ') AS combined_rationale
        FROM occurrence_credits
        GROUP BY snapshot_slug, split, example_kind, files_hash, tp_id, occurrence_id,
            critic_run_id, critic_transcript_id, critic_definition_id, critic_model,
            grader_run_id, grader_transcript_id, graded_at, grader_model
    """)

    # occurrence_statistics view
    op.execute("""
        CREATE VIEW occurrence_statistics AS
        SELECT
            -- Example identification
            snapshot_slug,
            split,
            example_kind,
            files_hash,
            -- Ground truth
            tp_id,
            occurrence_id,
            -- Critic-specific
            critic_definition_id,
            critic_model,
            -- Grader statistics
            grader_model,
            compute_stats_with_ci(array_agg(total_credit)) AS credit_stats
        FROM occurrence_run_credits
        GROUP BY snapshot_slug, split, example_kind, files_hash, tp_id, occurrence_id,
            critic_definition_id, critic_model, grader_model
    """)

    # recall_by_run view (formerly critic_run_occurrence_stats)
    # NOTE: credit_stats contains stats of RAW total_credit per grader run.
    # recall_stats = scale_stats(credit_stats, n_catchable_occurrences)
    op.execute("""
        CREATE VIEW recall_by_run AS
        WITH grader_stats AS (
            SELECT
                gr.agent_run_id AS grader_run_id,
                get_graded_agent_run_id(gr.agent_run_id) AS critic_run_id,
                COALESCE(SUM(gd.credit) FILTER (WHERE gd.target_tp_id IS NOT NULL), 0.0) AS total_credit,
                COUNT(DISTINCT (gd.target_tp_id, gd.target_tp_occurrence_id))
                    FILTER (WHERE gd.target_tp_id IS NOT NULL) AS n_catchable
            FROM agent_runs gr
            JOIN grading_decisions gd ON gd.agent_run_id = gr.agent_run_id
            WHERE get_agent_type_config(gr.agent_run_id)->>'agent_type' = 'grader'
            GROUP BY gr.agent_run_id
        ),
        per_run AS (
            SELECT
                -- Example identification
                cr.type_config->'example'->>'snapshot_slug' AS snapshot_slug,
                e.example_kind,
                e.files_hash,
                s.split,
                e.n_catchable_occurrences,
                -- Critic-specific columns
                cr.agent_run_id AS critic_run_id,
                cr.agent_definition_id AS critic_definition_id,
                cr.model AS critic_model,
                cr.status AS critic_status,
                -- Totals-space stats over grader credits; failed critics default to 0 credit
                compute_stats_with_ci(
                    COALESCE(
                        array_agg(gs.total_credit) FILTER (WHERE cr.status = 'completed'),
                        ARRAY[0.0]::double precision[]
                    )
                ) AS credit_stats
            FROM agent_runs cr
            JOIN examples e ON (
                cr.type_config->'example'->>'snapshot_slug' = e.snapshot_slug
                AND (cr.type_config->'example'->>'kind')::example_kind_enum = e.example_kind
                AND COALESCE((cr.type_config->'example'->>'files_hash'), '') = COALESCE(e.files_hash, '')
            )
            JOIN snapshots s ON cr.type_config->'example'->>'snapshot_slug' = s.slug
            LEFT JOIN grader_stats gs ON gs.critic_run_id = cr.agent_run_id
            WHERE cr.type_config->>'agent_type' = 'critic'
            GROUP BY cr.agent_run_id, cr.agent_definition_id, cr.type_config, s.split, cr.model, cr.status, e.example_kind, e.files_hash, e.n_catchable_occurrences
        )
        SELECT
            snapshot_slug,
            example_kind,
            files_hash,
            split,
            n_catchable_occurrences,
            critic_run_id,
            critic_definition_id,
            critic_model,
            critic_status,
            credit_stats,
            -- Recall derived by dividing credit by n_catchable_occurrences
            scale_stats(credit_stats, n_catchable_occurrences) AS recall_stats
        FROM per_run
    """)

    op.execute("""
        COMMENT ON VIEW recall_by_run IS
        'Per-critic-run recall statistics aggregated over all graders.

Columns grouped by: example identification, then critic-specific, then statistics.

- n_catchable_occurrences: Ground truth count (denominator for recall)
- critic_status: Critic run status (completed, max_turns_exceeded, etc.)
- credit_stats: Stats over grader total credits (numerator; not normalized)
- recall_stats: credit_stats / n_catchable_occurrences via scale_stats()

Failed critics contribute 0 credit via COALESCE.'
    """)

    # recall_by_definition_example view (NEW - intermediate aggregation)
    # Groups recall_by_run by (definition, model, example) - used by GEPA and feeds into other views
    op.execute("""
        CREATE VIEW recall_by_definition_example AS
        WITH raw_stats AS (
            SELECT
                rbr.critic_definition_id,
                rbr.critic_model,
                rbr.snapshot_slug,
                rbr.example_kind,
                rbr.files_hash,
                rbr.split,
                MAX(rbr.n_catchable_occurrences)::integer AS n_catchable_occurrences,
                COUNT(*)::integer AS n_runs,
                agg_status_counts(array_agg(rbr.critic_status)) AS status_counts,
                compute_stats_with_ci(array_agg(
                    COALESCE((rbr.credit_stats).mean, 0.0)
                )) AS credit_stats
            FROM recall_by_run rbr
            GROUP BY rbr.critic_definition_id, rbr.critic_model,
                     rbr.snapshot_slug, rbr.example_kind, rbr.files_hash, rbr.split
        )
        SELECT
            critic_definition_id, critic_model,
            snapshot_slug, example_kind, files_hash, split,
            n_catchable_occurrences, n_runs, status_counts, credit_stats,
            scale_stats(credit_stats, n_catchable_occurrences) AS recall_stats
        FROM raw_stats
    """)

    op.execute("""
        COMMENT ON VIEW recall_by_definition_example IS
        'Per-(definition, model, example) recall statistics aggregated over all runs.

Intermediate view between recall_by_run and higher-level aggregations.
Used by GEPA to get recall for a specific (definition, model, example) tuple.

- n_catchable_occurrences: Ground truth count (denominator)
- n_runs: Number of critic runs for this (definition, model, example)
- credit_stats: Stats of raw credit counts across runs (numerator)
- recall_stats: credit_stats / n_catchable_occurrences via scale_stats()'
    """)

    # recall_by_definition_split_kind view (formerly aggregated_recall_by_definition)
    op.execute("""
        CREATE VIEW recall_by_definition_split_kind AS
        WITH
        -- Pre-aggregate per-example counts by grouping keys
        example_counts AS (
            SELECT
                split, example_kind, critic_definition_id, critic_model,
                COUNT(*)::integer AS n_examples,
                SUM(n_catchable_occurrences)::integer AS n_catchable_occurrences
            FROM (
                SELECT DISTINCT
                    split, example_kind, files_hash, n_catchable_occurrences,
                    critic_definition_id, critic_model
                FROM recall_by_definition_example
            ) per_example
            GROUP BY split, example_kind, critic_definition_id, critic_model
        ),
        -- Aggregate run-level stats
        run_stats AS (
            SELECT
                split, example_kind, critic_definition_id, critic_model,
                COUNT(*)::integer AS n_runs,
                agg_status_counts(array_agg(status_counts)) AS status_counts,
                compute_stats_with_ci(array_agg(
                    COALESCE((credit_stats).mean, 0.0)
                )) AS credit_stats,
                COUNT(*) FILTER (WHERE COALESCE((credit_stats).mean, 0.0) = 0.0)::integer AS zero_count
            FROM recall_by_definition_example
            GROUP BY split, example_kind, critic_definition_id, critic_model
        )
        SELECT
            rs.split, rs.example_kind, rs.critic_definition_id, rs.critic_model,
            ec.n_examples, rs.n_runs, ec.n_catchable_occurrences,
            rs.status_counts, rs.credit_stats,
            scale_stats(rs.credit_stats, ec.n_catchable_occurrences) AS recall_stats,
            rs.zero_count
        FROM run_stats rs
        JOIN example_counts ec USING (split, example_kind, critic_definition_id, critic_model)
    """)

    op.execute("""
        COMMENT ON VIEW recall_by_definition_split_kind IS
        'Per-critic-definition aggregate metrics grouped by (definition, model, split, example_kind).

Aggregates recall_by_definition_example across examples within each (split, example_kind) group.

- n_catchable_occurrences: Sum across distinct examples (denominator)
- credit_stats: Stats of raw credit counts across runs (numerator); failed runs count as 0 credit
- recall_stats: credit_stats / n_catchable_occurrences via scale_stats()'
    """)

    # recall_by_example view (formerly aggregated_recall_by_example)
    # Aggregates recall_by_definition_example across definitions
    op.execute("""
        CREATE VIEW recall_by_example AS
        WITH raw_stats AS (
            SELECT
                rbde.snapshot_slug,
                rbde.example_kind,
                rbde.files_hash,
                rbde.split,
                MAX(rbde.n_catchable_occurrences)::integer AS n_catchable_occurrences,
                rbde.critic_model,
                SUM(rbde.n_runs)::integer AS n_runs,
                agg_status_counts(array_agg(rbde.status_counts)) AS status_counts,
                compute_stats_with_ci(array_agg(
                    COALESCE((rbde.credit_stats).mean, 0.0)
                )) AS credit_stats
            FROM recall_by_definition_example rbde
            GROUP BY rbde.snapshot_slug, rbde.example_kind, rbde.files_hash, rbde.split, rbde.critic_model
        )
        SELECT
            snapshot_slug, example_kind, files_hash, split,
            n_catchable_occurrences, critic_model, n_runs, status_counts, credit_stats,
            scale_stats(credit_stats, n_catchable_occurrences) AS recall_stats
        FROM raw_stats
    """)

    # pareto_frontier_by_example view
    # Now uses recall_by_definition_example directly (already aggregated to definition+example level)
    op.execute("""
        CREATE VIEW pareto_frontier_by_example AS
        WITH best_scores AS (
            SELECT
                snapshot_slug,
                split,
                example_kind,
                files_hash,
                n_catchable_occurrences,
                critic_model,
                max((credit_stats).mean) AS best_mean_credit
            FROM recall_by_definition_example
            GROUP BY snapshot_slug, split, example_kind, files_hash, n_catchable_occurrences, critic_model
        )
        SELECT
            bs.snapshot_slug,
            bs.split,
            bs.example_kind,
            bs.files_hash,
            bs.n_catchable_occurrences,
            bs.critic_model,
            -- Single column: list of winning definitions with their stats
            jsonb_agg(
                jsonb_build_object(
                    'definition_id', rbde.critic_definition_id,
                    'credit_stats', jsonb_build_object(
                        'n', (rbde.credit_stats).n,
                        'mean', (rbde.credit_stats).mean,
                        'min', (rbde.credit_stats).min,
                        'max', (rbde.credit_stats).max,
                        'lcb95', (rbde.credit_stats).lcb95,
                        'ucb95', (rbde.credit_stats).ucb95
                    ),
                    'n_runs', rbde.n_runs
                )
                ORDER BY rbde.critic_definition_id
            ) AS winning_definitions
        FROM best_scores bs
        JOIN recall_by_definition_example rbde ON (
            bs.snapshot_slug = rbde.snapshot_slug AND
            bs.split = rbde.split AND
            bs.example_kind = rbde.example_kind AND
            COALESCE(bs.files_hash, '') = COALESCE(rbde.files_hash, '') AND
            bs.critic_model = rbde.critic_model AND
            bs.best_mean_credit = (rbde.credit_stats).mean
        )
        GROUP BY bs.snapshot_slug, bs.split, bs.example_kind, bs.files_hash,
            bs.n_catchable_occurrences, bs.critic_model
    """)

    op.execute("""
        COMMENT ON VIEW pareto_frontier_by_example IS
        'Pareto frontier: definitions that achieved best mean credit on each example.

For each (snapshot_slug, split, example_kind, files_hash, critic_model), shows:
- n_catchable_occurrences: ground truth count (denominator for recall)
- winning_definitions: JSONB array of {definition_id, credit_stats} for all definitions at best score

All entries in winning_definitions have the same credit_stats.mean (the best score).
Consumer can compute recall as credit_stats.mean / n_catchable_occurrences.

Built on recall_by_definition_example, which aggregates over runs.
Failed critic runs (max_turns/context_length) count as 0.0 credit.'
    """)

    # event_costs view - per-event cost calculation
    op.execute("""
        CREATE VIEW event_costs AS
        SELECT
            (events.payload->'response_id')::text AS response_id,
            events.agent_run_id,
            ((events.payload->'usage'->'model')::text) AS model,
            ((events.payload->'usage'->'input_tokens')::text)::integer AS input_tokens,
            COALESCE(((events.payload->'usage'->'input_tokens_details'->'cached_tokens')::text)::integer, 0) AS cached_tokens,
            ((events.payload->'usage'->'output_tokens')::text)::integer AS output_tokens,
            COALESCE(((events.payload->'usage'->'output_tokens_details'->'reasoning_tokens')::text)::integer, 0) AS reasoning_tokens,
            (
                (((events.payload->'usage'->'input_tokens')::text)::integer -
                 COALESCE(((events.payload->'usage'->'input_tokens_details'->'cached_tokens')::text)::integer, 0))::float
                * model_metadata.input_usd_per_1m_tokens / 1000000.0
                +
                COALESCE(((events.payload->'usage'->'input_tokens_details'->'cached_tokens')::text)::integer, 0)::float
                * model_metadata.cached_input_usd_per_1m_tokens / 1000000.0
                +
                ((events.payload->'usage'->'output_tokens')::text)::integer::float
                * model_metadata.output_usd_per_1m_tokens / 1000000.0
            ) AS cost_usd,
            events.timestamp
        FROM events
        JOIN model_metadata ON ((events.payload->'usage'->'model')::text) = model_metadata.model_id
        WHERE events.event_type = 'response' AND events.payload->'usage' IS NOT NULL
    """)

    op.execute("""
        COMMENT ON VIEW event_costs IS
        'Per-event cost calculation. Joins events with model_metadata to compute cost_usd.
        Extracts token usage from response events and applies pricing from model_metadata.'
    """)

    # run_costs view - aggregated costs per agent run including transitive children
    op.execute("""
        CREATE VIEW run_costs AS
        WITH RECURSIVE run_tree AS (
            -- Base case: the run itself
            SELECT agent_run_id, agent_run_id AS root_run_id
            FROM agent_runs

            UNION ALL

            -- Recursive case: children of runs already in the tree
            SELECT ar.agent_run_id, rt.root_run_id
            FROM agent_runs ar
            JOIN run_tree rt ON ar.parent_agent_run_id = rt.agent_run_id
        )
        SELECT
            rt.root_run_id AS agent_run_id,
            ec.model,
            SUM(ec.input_tokens) AS input_tokens,
            SUM(ec.cached_tokens) AS cached_tokens,
            SUM(ec.output_tokens) AS output_tokens,
            SUM(ec.reasoning_tokens) AS reasoning_tokens,
            SUM(ec.cost_usd) AS cost_usd
        FROM run_tree rt
        JOIN event_costs ec ON ec.agent_run_id = rt.agent_run_id
        GROUP BY rt.root_run_id, ec.model
    """)

    op.execute("""
        COMMENT ON VIEW run_costs IS
        'Aggregated costs per agent run. Includes all transitive child runs via recursive CTE.
        Groups by model so queries can see per-model breakdown.'
    """)

    # =========================================================================
    # 10. Roles and Grants
    # =========================================================================

    # Create agent_base role if not exists
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'agent_base') THEN
                CREATE ROLE agent_base NOLOGIN;
            END IF;
        END
        $$
    """)

    op.execute("GRANT USAGE ON SCHEMA public TO agent_base")
    op.execute("GRANT SELECT,INSERT ON TABLE agent_definitions TO agent_base")
    op.execute("GRANT SELECT ON TABLE agent_runs TO agent_base")
    op.execute("GRANT SELECT ON TABLE examples TO agent_base")
    op.execute("GRANT SELECT ON TABLE file_sets TO agent_base")
    op.execute("GRANT SELECT ON TABLE file_set_members TO agent_base")
    op.execute("GRANT SELECT ON TABLE occurrence_triggers TO agent_base")
    op.execute("GRANT SELECT ON TABLE snapshot_files TO agent_base")
    op.execute("GRANT SELECT ON TABLE true_positive_occurrences TO agent_base")
    op.execute("GRANT SELECT ON TABLE false_positive_occurrences TO agent_base")
    op.execute("GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE grading_decisions TO agent_base")
    op.execute("GRANT SELECT ON TABLE snapshots TO agent_base")
    op.execute("GRANT SELECT ON TABLE recall_by_run TO agent_base")
    op.execute("GRANT SELECT ON TABLE recall_by_definition_example TO agent_base")
    op.execute("GRANT SELECT ON TABLE recall_by_definition_split_kind TO agent_base")
    op.execute("GRANT SELECT ON TABLE recall_by_example TO agent_base")
    op.execute("GRANT SELECT ON TABLE events TO agent_base")
    op.execute("GRANT USAGE ON SEQUENCE events_id_seq TO agent_base")
    # examples is now a VIEW (no sequence)
    op.execute("GRANT SELECT ON TABLE false_positives TO agent_base")
    op.execute("GRANT SELECT ON TABLE grading_credit_sums TO agent_base")
    op.execute("GRANT USAGE ON SEQUENCE grading_decisions_id_seq TO agent_base")
    op.execute("GRANT SELECT ON TABLE true_positives TO agent_base")
    op.execute("GRANT SELECT ON TABLE occurrence_credits TO agent_base")
    op.execute("GRANT SELECT ON TABLE occurrence_run_credits TO agent_base")
    op.execute("GRANT SELECT ON TABLE occurrence_statistics TO agent_base")
    op.execute("GRANT SELECT ON TABLE pareto_frontier_by_example TO agent_base")
    op.execute("GRANT SELECT ON TABLE event_costs TO agent_base")
    op.execute("GRANT SELECT ON TABLE run_costs TO agent_base")
    op.execute("GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE reported_issue_occurrences TO agent_base")
    op.execute("GRANT USAGE ON SEQUENCE reported_issue_occurrences_id_seq TO agent_base")
    op.execute("GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE reported_issues TO agent_base")
    op.execute("GRANT SELECT,INSERT,UPDATE ON TABLE unknown_assignments TO agent_base")
    op.execute("GRANT SELECT,USAGE ON SEQUENCE unknown_assignments_id_seq TO agent_base")
    op.execute("GRANT SELECT,INSERT,UPDATE ON TABLE unknown_clusters TO agent_base")
    op.execute("GRANT SELECT,USAGE ON SEQUENCE unknown_clusters_id_seq TO agent_base")

    # =========================================================================
    # 11. RLS Policies
    # =========================================================================

    # Force RLS on tables
    # NOTE: examples is now a VIEW - VIEWs don't support RLS directly
    # (they inherit RLS from underlying tables they query)
    op.execute("ALTER TABLE snapshots FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE true_positives FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE false_positives FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE events FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reported_issues FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reported_issue_occurrences FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE unknown_clusters FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE unknown_assignments FORCE ROW LEVEL SECURITY")

    # Enable RLS
    op.execute("ALTER TABLE agent_definitions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agent_runs ENABLE ROW LEVEL SECURITY")
    # examples is a VIEW - no RLS
    op.execute("ALTER TABLE snapshots ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE true_positives ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE false_positives ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE true_positive_occurrences ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE false_positive_occurrences ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE occurrence_triggers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE grading_decisions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reported_issues ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reported_issue_occurrences ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE unknown_clusters ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE unknown_assignments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE file_sets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE file_set_members ENABLE ROW LEVEL SECURITY")

    # Admin policies for postgres user
    op.execute("CREATE POLICY admin_full_access_events ON events TO postgres USING (true) WITH CHECK (true)")
    # examples is a VIEW - no RLS policies
    op.execute(
        "CREATE POLICY admin_full_access_false_positives ON false_positives TO postgres USING (true) WITH CHECK (true)"
    )
    op.execute("CREATE POLICY admin_full_access_snapshots ON snapshots TO postgres USING (true) WITH CHECK (true)")
    op.execute(
        "CREATE POLICY admin_full_access_true_positives ON true_positives TO postgres USING (true) WITH CHECK (true)"
    )
    op.execute(
        "CREATE POLICY admin_full_access_tp_occurrences ON true_positive_occurrences TO postgres USING (true) WITH CHECK (true)"
    )
    op.execute(
        "CREATE POLICY admin_full_access_fp_occurrences ON false_positive_occurrences TO postgres USING (true) WITH CHECK (true)"
    )
    op.execute(
        "CREATE POLICY admin_full_access_occ_triggers ON occurrence_triggers TO postgres USING (true) WITH CHECK (true)"
    )
    op.execute("CREATE POLICY admin_full_access_file_sets ON file_sets TO postgres USING (true) WITH CHECK (true)")
    op.execute(
        "CREATE POLICY admin_full_access_file_set_members ON file_set_members TO postgres USING (true) WITH CHECK (true)"
    )

    # Agent definitions policies
    op.execute("CREATE POLICY agent_definitions_select ON agent_definitions FOR SELECT USING (true)")
    op.execute(
        "CREATE POLICY agent_definitions_insert ON agent_definitions FOR INSERT WITH CHECK (created_by_agent_run_id = current_agent_run_id())"
    )

    # Agent runs policies
    op.execute("""
        CREATE POLICY agent_runs_agent_select ON agent_runs FOR SELECT USING (
            (current_agent_type() = 'prompt_optimizer'
             AND (((type_config->>'agent_type') = 'critic' AND is_train_snapshot(type_config->'example'->>'snapshot_slug'))
                  OR ((type_config->>'agent_type') = 'grader' AND is_train_snapshot(get_graded_snapshot_slug(agent_run_id)))))
            OR (agent_run_id = current_agent_run_id())
            OR (current_agent_type() = 'grader' AND agent_run_id = current_graded_agent_run_id())
            OR (current_agent_type() = 'improvement'
                AND (type_config->>'agent_type') IN ('critic', 'grader')
                AND is_improvement_example_allowed(type_config->'example'->>'snapshot_slug', (type_config->'example'->>'kind')::example_kind_enum, (type_config->'example'->>'files_hash')))
            OR (current_agent_type() = 'clustering'
                AND (type_config->>'agent_type') IN ('critic', 'grader')
                AND (((type_config->>'agent_type') = 'critic' AND type_config->'example'->>'snapshot_slug' = current_agent_type_config()->>'snapshot_slug')
                     OR ((type_config->>'agent_type') = 'grader' AND get_graded_snapshot_slug(agent_run_id) = current_agent_type_config()->>'snapshot_slug')))
        )
    """)
    op.execute(
        "CREATE POLICY agent_runs_select_own ON agent_runs FOR SELECT USING (agent_run_id = current_agent_run_id())"
    )
    op.execute(
        "CREATE POLICY agent_runs_select_children ON agent_runs FOR SELECT USING (parent_agent_run_id = current_agent_run_id())"
    )

    # file_sets policies - controls access to per-file examples
    # Key constraint: Prompt optimizer in whole-repo mode must NOT see VALID file_sets (file paths)
    op.execute("""
        CREATE POLICY file_sets_agent_select ON file_sets FOR SELECT USING (
            -- Prompt optimizer in whole-repo mode: only TRAIN file_sets
            (current_agent_type() = 'prompt_optimizer'
             AND current_agent_type_config()->>'target_metric' = 'whole_repo'
             AND is_train_snapshot(snapshot_slug))
            -- Prompt optimizer in targeted mode: TRAIN + VALID file_sets
            OR (current_agent_type() = 'prompt_optimizer'
                AND (current_agent_type_config()->>'target_metric' IS NULL
                     OR current_agent_type_config()->>'target_metric' != 'whole_repo')
                AND is_train_or_valid_snapshot(snapshot_slug))
            -- Critic: only their example's file_set
            OR (current_agent_type() = 'critic'
                AND snapshot_slug = current_agent_type_config()->'example'->>'snapshot_slug'
                AND files_hash = current_agent_type_config()->'example'->>'files_hash')
            -- Grader: graded example's file_set
            OR (current_agent_type() = 'grader'
                AND snapshot_slug = get_graded_snapshot_slug(current_agent_run_id()))
            -- Improvement: allowed snapshots only
            OR (current_agent_type() = 'improvement'
                AND is_improvement_snapshot_allowed(snapshot_slug))
            -- Clustering: all file_sets
            OR (current_agent_type() = 'clustering')
        )
    """)

    # file_set_members policies - follows file_sets access (same snapshot_slug/files_hash FK)
    op.execute("""
        CREATE POLICY file_set_members_agent_select ON file_set_members FOR SELECT USING (
            -- Prompt optimizer in whole-repo mode: only TRAIN file_set_members
            (current_agent_type() = 'prompt_optimizer'
             AND current_agent_type_config()->>'target_metric' = 'whole_repo'
             AND is_train_snapshot(snapshot_slug))
            -- Prompt optimizer in targeted mode: TRAIN + VALID file_set_members
            OR (current_agent_type() = 'prompt_optimizer'
                AND (current_agent_type_config()->>'target_metric' IS NULL
                     OR current_agent_type_config()->>'target_metric' != 'whole_repo')
                AND is_train_or_valid_snapshot(snapshot_slug))
            -- Critic: only their example's file_set_members
            OR (current_agent_type() = 'critic'
                AND snapshot_slug = current_agent_type_config()->'example'->>'snapshot_slug'
                AND files_hash = current_agent_type_config()->'example'->>'files_hash')
            -- Grader: graded example's file_set_members
            OR (current_agent_type() = 'grader'
                AND snapshot_slug = get_graded_snapshot_slug(current_agent_run_id()))
            -- Improvement: allowed snapshots only
            OR (current_agent_type() = 'improvement'
                AND is_improvement_snapshot_allowed(snapshot_slug))
            -- Clustering: all file_set_members
            OR (current_agent_type() = 'clustering')
        )
    """)

    # Examples VIEW - inherits RLS from underlying tables (snapshots, file_sets)
    # Whole-snapshot examples always visible (from snapshots), file_set examples filtered via file_sets RLS

    # Snapshots - any agent with a valid run can see all snapshots metadata
    op.execute(
        "CREATE POLICY snapshots_agent_select ON snapshots FOR SELECT USING (current_agent_run_id() IS NOT NULL)"
    )

    # True positives - uses can_access_snapshot() helper
    op.execute(
        "CREATE POLICY true_positives_agent_select ON true_positives FOR SELECT USING (can_access_snapshot(snapshot_slug))"
    )

    # False positives - uses can_access_snapshot() helper
    op.execute(
        "CREATE POLICY false_positives_agent_select ON false_positives FOR SELECT USING (can_access_snapshot(snapshot_slug))"
    )

    # True positive occurrences - uses can_access_snapshot() helper
    op.execute(
        "CREATE POLICY tp_occurrences_agent_select ON true_positive_occurrences FOR SELECT USING (can_access_snapshot(snapshot_slug))"
    )

    # False positive occurrences - uses can_access_snapshot() helper
    op.execute(
        "CREATE POLICY fp_occurrences_agent_select ON false_positive_occurrences FOR SELECT USING (can_access_snapshot(snapshot_slug))"
    )

    # Occurrence triggers - uses can_access_snapshot() helper
    op.execute(
        "CREATE POLICY occ_triggers_agent_select ON occurrence_triggers FOR SELECT USING (can_access_snapshot(snapshot_slug))"
    )

    # Events policies
    op.execute("""
        CREATE POLICY events_agent_select ON events FOR SELECT USING (
            (current_agent_type() = 'prompt_optimizer' AND is_train_agent_run(agent_run_id))
            OR (agent_run_id = current_agent_run_id())
            OR (current_agent_type() = 'improvement'
                AND agent_run_id IN (SELECT get_improvement_allowed_agent_run_ids()))
            OR (current_agent_type() = 'clustering')
        )
    """)

    # Grading decisions policies
    op.execute("""
        CREATE POLICY grading_decisions_agent_select ON grading_decisions FOR SELECT USING (
            (current_agent_type() = 'prompt_optimizer' AND is_train_agent_run(agent_run_id))
            OR is_own_run_as(agent_run_id, 'grader')
            OR (current_agent_type() = 'improvement'
                AND agent_run_id IN (SELECT get_improvement_allowed_agent_run_ids()))
        )
    """)
    op.execute(
        "CREATE POLICY grading_decisions_agent_insert ON grading_decisions FOR INSERT WITH CHECK (is_own_run_as(agent_run_id, 'grader'))"
    )
    op.execute(
        "CREATE POLICY grading_decisions_agent_update ON grading_decisions FOR UPDATE USING (is_own_run_as(agent_run_id, 'grader'))"
    )
    op.execute(
        "CREATE POLICY grading_decisions_agent_delete ON grading_decisions FOR DELETE USING (is_own_run_as(agent_run_id, 'grader'))"
    )

    # Reported issues policies
    op.execute("""
        CREATE POLICY reported_issues_agent_select ON reported_issues FOR SELECT USING (
            (current_agent_type() = 'prompt_optimizer' AND is_train_agent_run(agent_run_id))
            OR (agent_run_id = current_agent_run_id())
            OR (current_agent_type() = 'grader' AND agent_run_id = get_graded_agent_run_id(current_agent_run_id()))
            OR (current_agent_type() = 'improvement'
                AND agent_run_id IN (SELECT get_improvement_allowed_agent_run_ids()))
        )
    """)
    op.execute(
        "CREATE POLICY reported_issues_agent_insert ON reported_issues FOR INSERT WITH CHECK (is_own_run_as(agent_run_id, 'critic'))"
    )
    op.execute(
        "CREATE POLICY reported_issues_agent_update ON reported_issues FOR UPDATE USING (is_own_run_as(agent_run_id, 'critic'))"
    )
    op.execute(
        "CREATE POLICY reported_issues_agent_delete ON reported_issues FOR DELETE USING (is_own_run_as(agent_run_id, 'critic'))"
    )

    # Reported issue occurrences policies
    op.execute("""
        CREATE POLICY reported_issue_occurrences_agent_select ON reported_issue_occurrences FOR SELECT USING (
            (current_agent_type() = 'prompt_optimizer' AND is_train_agent_run(agent_run_id))
            OR (agent_run_id = current_agent_run_id())
            OR (current_agent_type() = 'grader' AND agent_run_id = get_graded_agent_run_id(current_agent_run_id()))
            OR (current_agent_type() = 'improvement'
                AND agent_run_id IN (SELECT get_improvement_allowed_agent_run_ids()))
        )
    """)
    op.execute(
        "CREATE POLICY reported_issue_occurrences_agent_insert ON reported_issue_occurrences FOR INSERT WITH CHECK (is_own_run_as(agent_run_id, 'critic'))"
    )
    op.execute(
        "CREATE POLICY reported_issue_occurrences_agent_update ON reported_issue_occurrences FOR UPDATE USING (is_own_run_as(agent_run_id, 'critic'))"
    )
    op.execute(
        "CREATE POLICY reported_issue_occurrences_agent_delete ON reported_issue_occurrences FOR DELETE USING (is_own_run_as(agent_run_id, 'critic'))"
    )

    # Unknown clusters policies (clustering agent)
    op.execute(
        "CREATE POLICY unknown_clusters_agent_select ON unknown_clusters FOR SELECT USING (agent_run_id = current_agent_run_id())"
    )
    op.execute(
        "CREATE POLICY unknown_clusters_agent_insert ON unknown_clusters FOR INSERT WITH CHECK (agent_run_id = current_agent_run_id())"
    )
    op.execute(
        "CREATE POLICY unknown_clusters_agent_update ON unknown_clusters FOR UPDATE USING (agent_run_id = current_agent_run_id())"
    )

    # Unknown assignments policies (clustering agent)
    op.execute(
        "CREATE POLICY unknown_assignments_agent_select ON unknown_assignments FOR SELECT USING (agent_run_id = current_agent_run_id())"
    )
    op.execute(
        "CREATE POLICY unknown_assignments_agent_insert ON unknown_assignments FOR INSERT WITH CHECK (agent_run_id = current_agent_run_id())"
    )
    op.execute(
        "CREATE POLICY unknown_assignments_agent_update ON unknown_assignments FOR UPDATE USING (agent_run_id = current_agent_run_id())"
    )

    # Initialize salt singleton
    op.execute("INSERT INTO agent_role_salt (id) VALUES (1) ON CONFLICT DO NOTHING")


def downgrade() -> None:
    """Drop all schema objects."""
    # Drop policies
    policies = [
        ("unknown_assignments_agent_update", "unknown_assignments"),
        ("unknown_assignments_agent_insert", "unknown_assignments"),
        ("unknown_assignments_agent_select", "unknown_assignments"),
        ("unknown_clusters_agent_update", "unknown_clusters"),
        ("unknown_clusters_agent_insert", "unknown_clusters"),
        ("unknown_clusters_agent_select", "unknown_clusters"),
        ("reported_issue_occurrences_agent_delete", "reported_issue_occurrences"),
        ("reported_issue_occurrences_agent_update", "reported_issue_occurrences"),
        ("reported_issue_occurrences_agent_insert", "reported_issue_occurrences"),
        ("reported_issue_occurrences_agent_select", "reported_issue_occurrences"),
        ("reported_issues_agent_delete", "reported_issues"),
        ("reported_issues_agent_update", "reported_issues"),
        ("reported_issues_agent_insert", "reported_issues"),
        ("reported_issues_agent_select", "reported_issues"),
        ("grading_decisions_agent_delete", "grading_decisions"),
        ("grading_decisions_agent_update", "grading_decisions"),
        ("grading_decisions_agent_insert", "grading_decisions"),
        ("grading_decisions_agent_select", "grading_decisions"),
        ("events_agent_select", "events"),
        ("false_positives_agent_select", "false_positives"),
        ("true_positives_agent_select", "true_positives"),
        ("snapshots_agent_select", "snapshots"),
        ("clustering_user_events_policy", "events"),
        ("clustering_user_false_positives_policy", "false_positives"),
        ("clustering_user_true_positives_policy", "true_positives"),
        ("clustering_user_snapshots_policy", "snapshots"),
        ("examples_agent_select", "examples"),
        ("agent_runs_select_children", "agent_runs"),
        ("agent_runs_select_own", "agent_runs"),
        ("agent_runs_agent_select", "agent_runs"),
        ("agent_definitions_insert", "agent_definitions"),
        ("agent_definitions_select", "agent_definitions"),
        ("admin_full_access_true_positives", "true_positives"),
        ("admin_full_access_snapshots", "snapshots"),
        ("admin_full_access_false_positives", "false_positives"),
        ("admin_full_access_examples", "examples"),
        ("admin_full_access_events", "events"),
        ("admin_full_access_file_sets", "file_sets"),
        ("admin_full_access_file_set_members", "file_set_members"),
        ("file_sets_agent_select", "file_sets"),
        ("file_set_members_agent_select", "file_set_members"),
    ]
    for policy, table in policies:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")

    # Drop role
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM agent_base")
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM agent_base")
    op.execute("REVOKE USAGE ON SCHEMA public FROM agent_base")
    op.execute("DROP ROLE IF EXISTS agent_base")

    # Drop views
    op.execute("DROP VIEW IF EXISTS run_costs CASCADE")
    op.execute("DROP VIEW IF EXISTS event_costs CASCADE")
    op.execute("DROP VIEW IF EXISTS pareto_frontier_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS recall_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS recall_by_definition_split_kind CASCADE")
    op.execute("DROP VIEW IF EXISTS recall_by_definition_example CASCADE")
    op.execute("DROP VIEW IF EXISTS recall_by_run CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_statistics CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_run_credits CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_credits CASCADE")
    op.execute("DROP VIEW IF EXISTS examples CASCADE")  # Now a VIEW, not a table
    op.execute("DROP VIEW IF EXISTS grading_credit_sums CASCADE")

    # Drop triggers
    op.execute("DROP TRIGGER IF EXISTS enforce_credit_sum ON grading_decisions")
    op.execute("DROP TRIGGER IF EXISTS check_input_issue_exists_trigger ON grading_decisions")
    op.execute("DROP TRIGGER IF EXISTS check_grading_target_exists_trigger ON grading_decisions")
    op.execute("DROP TRIGGER IF EXISTS check_unknown_mapping_exists_trigger ON unknown_assignments")

    # Drop tables
    op.drop_table("unknown_assignments")
    op.drop_table("unknown_clusters")
    op.drop_table("events")
    op.drop_table("grading_decisions")
    op.drop_table("reported_issue_occurrences")
    op.drop_table("reported_issues")
    op.drop_table("occurrence_triggers")
    op.drop_table("file_set_members")
    op.drop_table("file_sets")
    op.drop_table("false_positives")
    op.drop_table("true_positives")
    op.drop_table("snapshot_files")
    op.execute("ALTER TABLE agent_definitions DROP CONSTRAINT IF EXISTS fk_agent_definitions_created_by")
    op.drop_table("agent_runs")
    op.drop_table("agent_definitions")
    op.drop_table("agent_role_salt")
    op.drop_table("model_metadata")
    op.drop_table("snapshots")

    # Drop functions
    functions = [
        "get_validation_full_snapshot_aggregates()",
        "validate_input_issue_exists(uuid, text)",
        "check_input_issue_exists()",
        "check_grading_target_exists()",
        "check_unknown_mapping_exists()",
        "check_credit_sum()",
        "is_fp_relevant_for_scope(text, text, example_kind_enum, text)",
        "is_tp_catchable_from_scope(text, text, example_kind_enum, text)",
        "get_agent_run_ids_for_train_snapshots()",
        "get_improvement_allowed_agent_run_ids()",
        "is_improvement_snapshot_allowed(text)",
        "is_improvement_example_allowed(text, example_kind_enum, text)",
        "is_train_agent_run(uuid)",
        "is_train_or_valid_snapshot(text)",
        "is_valid_snapshot(text)",
        "is_train_snapshot(text)",
        "create_agent_role(uuid)",
        "derive_agent_password(uuid)",
        "get_graded_snapshot_slug(uuid)",
        "current_graded_agent_run_id()",
        "get_graded_agent_run_id(uuid)",
        "current_agent_type()",
        "current_agent_type_config()",
        "get_agent_type_config(uuid)",
        "current_agent_run_id()",
        "compute_stats_with_ci(double precision[])",
        "scale_stats(stats_with_ci, double precision)",
        "agg_status_counts(agent_run_status_enum[])",
        "agg_status_counts(jsonb[])",
    ]
    for func in functions:
        op.execute(f"DROP FUNCTION IF EXISTS {func} CASCADE")

    # Drop types
    op.execute("DROP TYPE IF EXISTS stats_with_ci CASCADE")
    op.execute("DROP TYPE IF EXISTS split_enum CASCADE")
    op.execute("DROP TYPE IF EXISTS agent_type_enum CASCADE")
    op.execute("DROP TYPE IF EXISTS agent_run_status_enum CASCADE")

    # Drop extensions
    op.execute("DROP EXTENSION IF EXISTS pgcrypto CASCADE")
