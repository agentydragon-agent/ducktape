-- PostgreSQL database dump
-- Generated with: pg_dump --schema-only --no-owner --no-privileges props > schema_dump_for_squash.sql
-- Then manually edited to apply the changes below.
--
-- CHANGES FROM ORIGINAL DUMP (require Python-side updates):
-- 1. Renamed functions:
--    - get_validation_run_aggregates() -> get_validation_full_snapshot_aggregates()
--    - is_agent_example_allowed() -> is_improvement_example_allowed()
--    - is_agent_snapshot_allowed() -> is_improvement_snapshot_allowed()
--    - get_agent_run_ids_for_improvement_allowed() -> get_improvement_allowed_agent_run_ids()
-- 2. Removed types:
--    - critic_run_status_enum (use agent_run_status_enum instead)
-- 3. Removed roles:
--    - prompt_optimizer_agent_template (grants moved to agent_base)
-- 4. Views now use status_counts JSONB instead of separate n_* columns:
--    - aggregated_recall_by_definition: status_counts replaces n_successful, n_max_turns_exceeded, etc.
--    - aggregated_recall_by_example: status_counts replaces n_successful, n_max_turns_exceeded, etc.
--    - New helper function: agg_status_counts(agent_run_status_enum[]) -> jsonb
-- 5. Views now use stats_with_ci composite type for statistics with 95% confidence intervals:
--    - New composite type: stats_with_ci (n, mean, min, max, lcb95, ucb95)
--      * lcb95/ucb95 = mean ± 1.96 * stddev/sqrt(n) (95% CI bounds)
--    - New helper function: compute_stats_with_ci(double precision[]) -> stats_with_ci
--    - aggregated_recall_by_definition:
--        * recall/ucb/lcb -> recall_stats (stats_with_ci)
--        * occurrences_caught -> occurrences_caught_stats (stats_with_ci)
--        * avg_grader_runs_per_critic -> grader_runs_stats (stats_with_ci)
--        * Removed: avg_occurrences_caught_overall, avg_catchable_occurrences
--    - aggregated_recall_by_example:
--        * recall -> recall_stats (stats_with_ci)
--        * occurrences_caught -> occurrences_caught_stats (stats_with_ci)
--        * avg_grader_runs_per_critic -> grader_runs_stats (stats_with_ci)
--        * Removed: avg_occurrences_caught_overall, avg_catchable_occurrences
--    - occurrence_statistics:
--        * mean_credit/stddev_credit/min_credit/max_credit -> credit_stats (stats_with_ci)
--    - pareto_frontier_by_example:
--        * avg_recall -> recall_stats (stats_with_ci)
--        * best_recall -> best_mean_recall
--        * winning_definition_n_runs -> winning_definition_recall_stats (stats_with_ci[])
-- 6. Removed tables:
--    - prompts (and all related indexes, constraints, grants)
-- 7. Added updated_at columns to mutable tables:
--    - agent_definitions, grading_decisions, reported_issue_occurrences,
--      unknown_assignments, reported_issues, unknown_clusters
-- 8. Added created_at to model_metadata
-- 9. Removed SECURITY DEFINER from snapshot predicate functions:
--    - is_train_or_valid_snapshot(), is_train_snapshot(), is_valid_snapshot()
-- 10. DRY refactoring of helper functions:
--    - New function: get_graded_agent_run_id(uuid) extracts graded_agent_run_id from grader type_config
--    - current_agent_type_config() now uses current_agent_run_id()
--    - current_graded_agent_run_id() now uses get_graded_agent_run_id(current_agent_run_id())
--    - get_graded_snapshot_slug() now uses get_graded_agent_run_id()
--    - check_input_issue_exists() trigger now uses get_graded_agent_run_id()
--    - occurrence_credits view JOIN now uses get_graded_agent_run_id()
--    - reported_issues_agent_select/reported_issue_occurrences_agent_select policies use get_graded_agent_run_id()
--    - examples_agent_select policy uses current_agent_type_config() instead of inline subqueries
-- 11. Simplified plpgsql functions to SQL where possible (no logic changes):
--    - is_improvement_example_allowed: plpgsql -> sql
--    - is_improvement_snapshot_allowed: plpgsql -> sql
--    - is_train_or_valid_snapshot: plpgsql -> sql
--    - is_train_snapshot: plpgsql -> sql
--    - is_valid_snapshot: plpgsql -> sql
--    - is_train_agent_run: plpgsql -> sql
--    - get_improvement_allowed_agent_run_ids: plpgsql -> sql
--    - get_agent_run_ids_for_train_snapshots: plpgsql -> sql
--    - get_agent_type_config: plpgsql -> sql
-- 12. Refactored critic_run_occurrence_stats view:
--    - Replaced nested correlated subqueries with CTE (grader_stats)
--    - Pre-computes per-grader total_credit and n_catchable in one pass
--    - Uses FILTER clause instead of SELECT WHERE subqueries
--    - Joins to CTE instead of repeated table scans
--    - Uses get_graded_agent_run_id() and get_agent_type_config() helpers
-- 13. DRY: is_train_agent_run() now uses get_agent_type_config() instead of
--     querying agent_runs twice for agent_type and snapshot_slug
-- 14. Removed created_at/updated_at from events table (immutable log entries
--     already have timestamp field)
-- 15. Removed unused num_decisions column from grading_credit_sums view
-- 16. Renamed agent_definition_id to critic_definition_id in views where it refers
--     to the critic's definition (not grader's):
--     - occurrence_credits: agent_definition_id -> critic_definition_id
--     - occurrence_run_credits: agent_definition_id -> critic_definition_id
--     - occurrence_statistics: agent_definition_id -> critic_definition_id
--     - critic_run_occurrence_stats: agent_definition_id -> critic_definition_id
--     - aggregated_recall_by_definition: agent_definition_id -> critic_definition_id
--     - pareto_frontier_by_example: agent_definition_id -> critic_definition_id,
--                                   winning_definition_ids -> winning_critic_definition_ids
--     - get_validation_full_snapshot_aggregates(): agent_definition_id -> critic_definition_id
-- 17. Renamed status to critic_status in views for clarity:
--     - critic_run_occurrence_stats: status -> critic_status
--     - aggregated_recall_by_definition: uses critic_status in agg_status_counts
--     - aggregated_recall_by_example: uses critic_status in agg_status_counts
-- 18. Column reordering for consistency:
--     - Grouped columns logically: example identification, then ground truth,
--       then critic-specific, then grader-aggregated
--     - scope_kind now appears before scope_hash in all views
-- 19. Fixed total_catchable_occurrences computation in aggregated_recall_by_definition:
--     - Was: SUM(n_catchable) across runs (wrong: n_catchable is constant per example)
--     - Now: SUM(n_catchable) across distinct examples via per_example CTE
-- 20. Fixed total_catchable_occurrences in aggregated_recall_by_example:
--     - Was: SUM(n_catchable) across runs
--     - Now: MAX(n_catchable) since it's constant within each example group
--     - Renamed column from total_catchable_occurrences to n_catchable_occurrences
-- 21. Views now return raw totals instead of recall fractions:
--     - aggregated_recall_by_definition: removed recall_stats, keep occurrences_caught_stats
--     - aggregated_recall_by_example: removed recall_stats, keep occurrences_caught_stats
--     - pareto_frontier_by_example: best_mean_recall -> best_mean_credit,
--       winning_definition_recall_stats -> winning_definition_credit_stats,
--       added n_catchable_occurrences
--     - Consumer can compute recall as occurrences_caught / n_catchable if needed
-- 22. Unified grader statistics into stats_with_ci (n_grader_runs becomes .n):
--     - occurrence_run_credits: avg(found_credit) -> sum(found_credit) as total_credit
--     - occurrence_statistics: removed n_grader_runs (use credit_stats.n instead)
--     - critic_run_occurrence_stats: replaced n_grader_runs + avg_occurrences_caught
--       with occurrences_caught_stats (stats_with_ci: .n = grader count, .mean = avg credit)
--     - aggregated_recall_by_definition: removed total_grader_runs, grader_runs_stats
--       (grader count now available via occurrences_caught_stats at lower levels)
--     - aggregated_recall_by_example: same removals
--     - pareto_frontier_by_example: now uses (occurrences_caught_stats).mean instead of avg_occurrences_caught
-- 23. Failed critic runs now count as 0 credit in aggregate statistics:
--     - aggregated_recall_by_definition: COALESCE(..., 0.0) instead of excluding NULLs
--     - aggregated_recall_by_example: same change
--     - occurrences_caught_stats.n now equals n_runs (all runs, not just completed)
-- BACKWARD-INCOMPATIBLE VIEW CHANGES (columns removed/renamed):
-- critic_run_occurrence_stats:
--   REMOVED: n_grader_runs, avg_occurrences_caught
--   ADDED: occurrences_caught_stats (stats_with_ci: .n = grader count, .mean = avg credit)
--   RENAMED: agent_definition_id -> critic_definition_id
--   RENAMED: status -> critic_status
--   REORDERED: scope_kind now before scope_hash
-- aggregated_recall_by_definition:
--   REMOVED: avg_occurrences_caught_overall, avg_catchable_occurrences, avg_grader_runs_per_critic,
--            recall_stats, total_grader_runs, grader_runs_stats
--   CHANGED: occurrences_caught -> occurrences_caught_stats (uses .mean from per-run stats)
--   CHANGED: failed runs now count as 0 credit (previously excluded from stats)
--   RENAMED: agent_definition_id -> critic_definition_id
--   FIXED: total_catchable_occurrences now sums across distinct examples (not runs)
--   REORDERED: columns grouped by (split, scope_kind, critic_definition_id, critic_model)
-- aggregated_recall_by_example:
--   REMOVED: avg_occurrences_caught_overall, avg_catchable_occurrences, avg_grader_runs_per_critic,
--            recall_stats, total_grader_runs, grader_runs_stats
--   ADDED: scope_kind
--   CHANGED: occurrences_caught -> occurrences_caught_stats (uses .mean from per-run stats)
--   CHANGED: failed runs now count as 0 credit (previously excluded from stats)
--   RENAMED: total_catchable_occurrences -> n_catchable_occurrences
--   FIXED: n_catchable_occurrences now uses MAX (constant per example)
--   REORDERED: scope_kind now before scope_hash
-- pareto_frontier_by_example:
--   REMOVED: winning_definition_n_runs, best_recall (now best_mean_credit)
--   ADDED: n_catchable_occurrences (ground truth count)
--   CHANGED: best_recall -> best_mean_credit (raw total, not fraction)
--   CHANGED: winning_definition_recall_stats -> winning_definition_credit_stats (stats_with_ci[])
--   RENAMED: agent_definition_id -> critic_definition_id
--   RENAMED: winning_definition_ids -> winning_critic_definition_ids
--   REORDERED: columns grouped by example identification -> ground truth -> critic-specific
-- occurrence_statistics:
--   REMOVED: mean_credit, stddev_credit, min_credit, max_credit, n_grader_runs
--   ADDED: credit_stats (stats_with_ci: .n = grader count, .mean = avg credit)
--   RENAMED: agent_definition_id -> critic_definition_id
--   REORDERED: columns grouped by example identification -> ground truth -> critic -> grader
-- occurrence_credits:
--   RENAMED: agent_definition_id -> critic_definition_id
--   REORDERED: columns grouped by example identification -> ground truth -> critic -> grader
-- occurrence_run_credits:
--   CHANGED: avg(found_credit) -> sum(found_credit) as total_credit (was avg_credit)
--   RENAMED: agent_definition_id -> critic_definition_id
--   REORDERED: columns grouped by example identification -> ground truth -> critic -> grader
-- get_validation_full_snapshot_aggregates():
--   RENAMED: agent_definition_id -> critic_definition_id

\restrict TCoce1f8sFaVdKyQ0oIg4svuybwmXpgf9kPWKxb9vMvJbRpaXaZOdWf5Uh2DKAW

-- Dumped from database version 16.11 (Debian 16.11-1.pgdg13+1)
-- Dumped by pg_dump version 16.11 (Debian 16.11-1.pgdg13+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

-- *not* creating schema, since initdb creates it

COMMENT ON SCHEMA public IS '';

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';

CREATE TYPE public.agent_run_status_enum AS ENUM (
    'in_progress',
    'completed',
    'max_turns_exceeded',
    'context_length_exceeded',
    'reported_failure'
);

CREATE FUNCTION public.agg_status_counts(statuses public.agent_run_status_enum[])
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT jsonb_object_agg(s, cnt)
    FROM (
        SELECT unnest(statuses) AS s, count(*) AS cnt
        FROM unnest(statuses)
        GROUP BY 1
    ) sub
$$;

COMMENT ON FUNCTION public.agg_status_counts(public.agent_run_status_enum[]) IS
'Aggregates an array of status values into JSONB counts. Used by aggregate views to avoid repeating CASE/WHEN for each enum value.
Example: agg_status_counts(array_agg(status)) -> {"completed": 5, "max_turns_exceeded": 2}';

CREATE TYPE public.stats_with_ci AS (
    n integer,
    mean double precision,
    min double precision,
    max double precision,
    lcb95 double precision,
    ucb95 double precision
);

COMMENT ON TYPE public.stats_with_ci IS
'Statistics with 95% confidence interval bounds. Used for aggregated metrics.
- n: sample count
- mean: sample mean
- min: minimum value
- max: maximum value
- lcb95: lower 95% confidence bound (mean - 1.96 * stddev/sqrt(n))
- ucb95: upper 95% confidence bound (mean + 1.96 * stddev/sqrt(n))
Returns NULL for lcb95/ucb95 when n < 2 (insufficient samples for CI).';

CREATE FUNCTION public.compute_stats_with_ci(vals double precision[])
RETURNS public.stats_with_ci
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
    )::public.stats_with_ci
    FROM unnest(vals) AS v
$$;

COMMENT ON FUNCTION public.compute_stats_with_ci(double precision[]) IS
'Computes n, mean, min, max, and 95% confidence bounds from an array of values.
Usage: compute_stats_with_ci(array_agg(some_metric))
Access fields: (compute_stats_with_ci(...)).mean, .min, .max, .lcb95, .ucb95, etc.';

CREATE TYPE public.agent_type_enum AS ENUM (
    'critic',
    'grader',
    'prompt_optimizer',
    'clustering',
    'freeform',
    'improvement'
);

CREATE TYPE public.split_enum AS ENUM (
    'train',
    'valid',
    'test'
);

CREATE FUNCTION public.check_credit_sum() RETURNS trigger
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
        $$;

COMMENT ON FUNCTION public.check_credit_sum() IS 'Trigger function that validates credit sums per occurrence do not exceed 1.0.';

CREATE FUNCTION public.check_input_issue_exists() RETURNS trigger
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
        $$;

COMMENT ON FUNCTION public.check_input_issue_exists() IS 'Validates that grading_decisions.input_issue_id exists in the graded critic run''s reported_issues';

CREATE FUNCTION public.create_agent_role(run_id uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
        DECLARE
            username TEXT := 'agent_' || run_id::text;
            password TEXT := derive_agent_password(run_id);
        BEGIN
            -- Check if role already exists
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = username) THEN
                EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', username, password);
                EXECUTE format('GRANT agent_base TO %I', username);
            END IF;
        END
        $$;

COMMENT ON FUNCTION public.create_agent_role(run_id uuid) IS 'Create LOGIN role for agent with deterministic password (admin-only)';

CREATE FUNCTION public.current_agent_run_id() RETURNS uuid
    LANGUAGE sql STABLE
    AS $$
            SELECT CASE
                WHEN session_user LIKE 'agent_%'
                THEN substring(session_user from 'agent_([0-9a-f-]+)')::uuid
                ELSE NULL
            END
        $$;

COMMENT ON FUNCTION public.current_agent_run_id() IS 'Extract agent_run_id from session username (NULL if not an agent). Uses session_user (not current_user) to work correctly when called from within SECURITY DEFINER functions.';

CREATE FUNCTION public.current_agent_type() RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
            SELECT current_agent_type_config()->>'agent_type'
        $$;

COMMENT ON FUNCTION public.current_agent_type() IS 'Returns agent_type from current_agent_type_config(). SECURITY DEFINER for RLS policy use.';

CREATE FUNCTION public.current_agent_type_config() RETURNS jsonb
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
            SELECT type_config
            FROM agent_runs
            WHERE agent_run_id = current_agent_run_id()
        $$;

COMMENT ON FUNCTION public.current_agent_type_config() IS 'Returns type_config JSONB for current agent. SECURITY DEFINER to bypass RLS on agent_runs. Returns NULL for non-agents.';

CREATE FUNCTION public.current_graded_agent_run_id() RETURNS uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
            SELECT get_graded_agent_run_id(current_agent_run_id())
        $$;

COMMENT ON FUNCTION public.current_graded_agent_run_id() IS 'Returns graded_agent_run_id from current grader type_config. SECURITY DEFINER to bypass RLS.';

CREATE FUNCTION public.derive_agent_password(run_id uuid) RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
            SELECT encode(
                sha256((SELECT salt FROM agent_role_salt) || run_id::text::bytea),
                'hex'
            )
        $$;

COMMENT ON FUNCTION public.derive_agent_password(run_id uuid) IS 'Derive deterministic password for agent role (admin-only)';

CREATE FUNCTION public.get_improvement_allowed_agent_run_ids() RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
            SELECT ar.agent_run_id
            FROM agent_runs ar
            WHERE current_agent_type_config()->>'agent_type' = 'improvement'
              AND ar.type_config->>'agent_type' IN ('critic', 'grader')
              AND EXISTS (
                  SELECT 1 FROM jsonb_array_elements(current_agent_type_config()->'allowed_examples') elem
                  WHERE elem->>'snapshot_slug' = ar.type_config->>'snapshot_slug'
                    AND elem->>'scope_hash' = ar.type_config->>'scope_hash'
              )
        $$;

COMMENT ON FUNCTION public.get_improvement_allowed_agent_run_ids() IS 'Returns agent_run_ids for critic/grader runs that match current improvement agent allowed_examples. SECURITY DEFINER to bypass RLS.';

CREATE FUNCTION public.get_agent_run_ids_for_train_snapshots() RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
            SELECT agent_run_id
            FROM agent_runs
            WHERE type_config->>'agent_type' IN ('critic', 'grader')
              AND type_config->>'snapshot_slug' IN (SELECT slug FROM snapshots WHERE split = 'train')
        $$;

COMMENT ON FUNCTION public.get_agent_run_ids_for_train_snapshots() IS 'Returns agent_run_ids for critic/grader runs on TRAIN snapshots. SECURITY DEFINER to bypass RLS.';

CREATE FUNCTION public.get_agent_type_config(p_agent_run_id uuid) RETURNS jsonb
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
            SELECT type_config
            FROM agent_runs
            WHERE agent_run_id = p_agent_run_id
        $$;

COMMENT ON FUNCTION public.get_agent_type_config(p_agent_run_id uuid) IS 'Returns type_config JSONB for given agent_run_id. SECURITY DEFINER to bypass RLS on agent_runs.';

CREATE FUNCTION public.get_graded_agent_run_id(p_grader_run_id uuid) RETURNS uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
            SELECT (type_config->>'graded_agent_run_id')::UUID
            FROM agent_runs
            WHERE agent_run_id = p_grader_run_id
        $$;

COMMENT ON FUNCTION public.get_graded_agent_run_id(p_grader_run_id uuid) IS 'Returns graded_agent_run_id from grader type_config. SECURITY DEFINER to bypass RLS.';

CREATE FUNCTION public.get_graded_snapshot_slug(grader_run_id uuid) RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
            SELECT type_config->>'snapshot_slug'
            FROM agent_runs
            WHERE agent_run_id = get_graded_agent_run_id(grader_run_id)
        $$;

CREATE FUNCTION public.get_validation_full_snapshot_aggregates() RETURNS TABLE(snapshot_slug text, critic_definition_id text, critic_model text, grader_model text, critic_run_id uuid, grader_run_id uuid, status public.agent_run_status_enum, total_credit double precision, n_occurrences integer)
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
              AND oc.scope_kind = 'entire_snapshot'
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
        $$;

COMMENT ON FUNCTION public.get_validation_full_snapshot_aggregates() IS 'Black-box validation metrics for whole-repo mode.
        Returns per-run recall for VALID split, entire_snapshot scope_kind only.
        Includes critic_run status for proper outcome counting.
        Used by prompt optimizer in whole-repo validation mode.';

CREATE FUNCTION public.is_improvement_example_allowed(p_snapshot_slug text, p_scope_hash text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
            SELECT COALESCE(
                (current_agent_type_config()->>'agent_type' = 'improvement')
                AND EXISTS (
                    SELECT 1 FROM jsonb_array_elements(current_agent_type_config()->'allowed_examples') elem
                    WHERE elem->>'snapshot_slug' = p_snapshot_slug
                      AND elem->>'scope_hash' = p_scope_hash
                ),
                FALSE
            )
        $$;

CREATE FUNCTION public.is_improvement_snapshot_allowed(p_slug text) RETURNS boolean
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
        $$;

CREATE FUNCTION public.is_train_agent_run(run_id uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
            SELECT COALESCE(
                CASE get_agent_type_config(run_id)->>'agent_type'
                    WHEN 'critic' THEN is_train_snapshot(get_agent_type_config(run_id)->>'snapshot_slug')
                    WHEN 'grader' THEN is_train_snapshot(get_graded_snapshot_slug(run_id))
                    ELSE FALSE
                END,
                FALSE
            )
        $$;

CREATE FUNCTION public.is_train_or_valid_snapshot(slug text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
            SELECT EXISTS (SELECT 1 FROM snapshots WHERE snapshots.slug = is_train_or_valid_snapshot.slug AND split IN ('train', 'valid'))
        $$;

CREATE FUNCTION public.is_train_snapshot(slug text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
            SELECT EXISTS (SELECT 1 FROM snapshots WHERE snapshots.slug = is_train_snapshot.slug AND split = 'train')
        $$;

CREATE FUNCTION public.is_valid_snapshot(slug text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
            SELECT EXISTS (SELECT 1 FROM snapshots WHERE snapshots.slug = is_valid_snapshot.slug AND split = 'valid')
        $$;

CREATE FUNCTION public.validate_input_issue_exists(grader_run_id uuid, input_issue_id text) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $_$
            SELECT EXISTS (
                SELECT 1
                FROM reported_issues ri
                JOIN grader_runs gr ON gr.critic_run_id = ri.critic_run_id
                WHERE gr.id = $1 AND ri.issue_id = $2
            )
        $_$;

SET default_tablespace = '';

SET default_table_access_method = heap;

CREATE TABLE public.agent_definitions (
    id text NOT NULL,
    agent_type public.agent_type_enum NOT NULL,
    archive bytea NOT NULL,
    created_by_agent_run_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

COMMENT ON TABLE public.agent_definitions IS 'Agent definition archives containing AGENT.md, init script, and tools';

COMMENT ON COLUMN public.agent_definitions.id IS 'Readable ID: repo-backed use names like "critic", agent-created use auto-generated';

COMMENT ON COLUMN public.agent_definitions.archive IS 'Uncompressed tar archive of the definition directory';

COMMENT ON COLUMN public.agent_definitions.created_by_agent_run_id IS 'Agent run that created this definition (NULL for repo-backed)';

CREATE TABLE public.agent_role_salt (
    id integer DEFAULT 1 NOT NULL,
    salt bytea DEFAULT public.gen_random_bytes(32) NOT NULL,
    CONSTRAINT agent_role_salt_id_check CHECK ((id = 1))
);

COMMENT ON TABLE public.agent_role_salt IS 'Singleton containing salt for deterministic agent password derivation';

CREATE TABLE public.agent_runs (
    agent_run_id uuid NOT NULL,
    agent_definition_id text NOT NULL,
    parent_agent_run_id uuid,
    model text NOT NULL,
    type_config jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    status public.agent_run_status_enum DEFAULT 'in_progress'::public.agent_run_status_enum NOT NULL,
    completion_summary text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

COMMENT ON TABLE public.agent_runs IS 'Unified table for all agent runs (critics, graders, optimizers, freeform)';

COMMENT ON COLUMN public.agent_runs.parent_agent_run_id IS 'Parent agent that spawned this sub-agent (NULL for top-level)';

COMMENT ON COLUMN public.agent_runs.type_config IS 'JSONB with agent_type discriminator and type-specific fields';

COMMENT ON COLUMN public.agent_runs.status IS 'Run status: in_progress, completed, max_turns_exceeded, context_length_exceeded, or reported_failure';

COMMENT ON COLUMN public.agent_runs.completion_summary IS 'Markdown summary from agent when status=completed, or error message when status=reported_failure';

CREATE TABLE public.examples (
    id integer NOT NULL,
    snapshot_slug character varying NOT NULL,
    scope_hash character varying NOT NULL,
    scope jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.examples FORCE ROW LEVEL SECURITY;

CREATE TABLE public.grading_decisions (
    id integer NOT NULL,
    input_issue_id character varying NOT NULL,
    target_tp_id character varying,
    target_tp_occurrence_id character varying,
    target_fp_id character varying,
    target_fp_occurrence_id character varying,
    credit double precision NOT NULL,
    rationale text NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    agent_run_id uuid DEFAULT public.current_agent_run_id() NOT NULL,
    CONSTRAINT credit_in_range CHECK (((credit >= (0.0)::double precision) AND (credit <= (1.0)::double precision))),
    CONSTRAINT exactly_one_target CHECK ((((target_tp_id IS NOT NULL) AND (target_tp_occurrence_id IS NOT NULL) AND (target_fp_id IS NULL) AND (target_fp_occurrence_id IS NULL)) OR ((target_tp_id IS NULL) AND (target_tp_occurrence_id IS NULL) AND (target_fp_id IS NOT NULL) AND (target_fp_occurrence_id IS NOT NULL)) OR ((target_tp_id IS NULL) AND (target_tp_occurrence_id IS NULL) AND (target_fp_id IS NULL) AND (target_fp_occurrence_id IS NULL)))),
    CONSTRAINT no_match_zero_credit CHECK (((target_tp_id IS NOT NULL) OR (target_fp_id IS NOT NULL) OR (credit = (0.0)::double precision)))
);

COMMENT ON COLUMN public.grading_decisions.agent_run_id IS 'FK to agent_runs - identifies which grader agent run created this decision';

CREATE TABLE public.snapshots (
    slug character varying NOT NULL,
    split public.split_enum NOT NULL,
    source jsonb NOT NULL,
    bundle jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.snapshots FORCE ROW LEVEL SECURITY;

CREATE VIEW public.critic_run_occurrence_stats AS
 WITH grader_stats AS (
    -- Pre-compute per-grader stats to avoid repeated correlated subqueries
    SELECT
        gr.agent_run_id AS grader_run_id,
        get_graded_agent_run_id(gr.agent_run_id) AS critic_run_id,
        COALESCE(SUM(gd.credit) FILTER (WHERE gd.target_tp_id IS NOT NULL), 0.0) AS total_credit,
        COUNT(DISTINCT (gd.target_tp_id, gd.target_tp_occurrence_id))
            FILTER (WHERE gd.target_tp_id IS NOT NULL) AS n_catchable
    FROM public.agent_runs gr
    JOIN public.grading_decisions gd ON gd.agent_run_id = gr.agent_run_id
    WHERE get_agent_type_config(gr.agent_run_id)->>'agent_type' = 'grader'
    GROUP BY gr.agent_run_id
 )
 SELECT
    -- Example identification
    cr.type_config->>'snapshot_slug' AS snapshot_slug,
    e.scope->>'kind' AS scope_kind,
    cr.type_config->>'scope_hash' AS scope_hash,
    s.split,
    -- n_catchable is same for all runs on this example (ground truth count)
    COALESCE(MAX(gs.n_catchable), 0)::integer AS n_catchable_occurrences,
    -- Critic-specific columns
    cr.agent_run_id AS critic_run_id,
    cr.agent_definition_id AS critic_definition_id,
    cr.model AS critic_model,
    cr.status AS critic_status,
    -- Grader statistics (stats_with_ci includes count as .n)
    public.compute_stats_with_ci(
        array_agg(gs.total_credit) FILTER (WHERE cr.status = 'completed')
    ) AS occurrences_caught_stats
 FROM public.agent_runs cr
 JOIN public.examples e ON (
    cr.type_config->>'snapshot_slug' = e.snapshot_slug
    AND cr.type_config->>'scope_hash' = e.scope_hash
 )
 JOIN public.snapshots s ON cr.type_config->>'snapshot_slug' = s.slug
 LEFT JOIN grader_stats gs ON gs.critic_run_id = cr.agent_run_id
 WHERE cr.type_config->>'agent_type' = 'critic'
 GROUP BY cr.agent_run_id, cr.agent_definition_id, cr.type_config, s.split, cr.model, cr.status, e.scope;

COMMENT ON VIEW public.critic_run_occurrence_stats IS 'Per-critic-run occurrence statistics aggregated over all graders.

        Columns grouped by: example identification, then critic-specific, then grader statistics.

        - n_catchable_occurrences: Ground truth count (same for all runs on this example)
        - critic_status: Critic run status (completed, max_turns_exceeded, etc.)
        - occurrences_caught_stats: Full statistics across graders (stats_with_ci: .n is grader count, .mean is average credit, etc.)';

CREATE VIEW public.aggregated_recall_by_definition AS
 WITH per_example AS (
    -- Deduplicate n_catchable per example (it's constant for all runs on same example)
    SELECT DISTINCT
        snapshot_slug,
        scope_kind,
        scope_hash,
        n_catchable_occurrences,
        split,
        critic_definition_id,
        critic_model
    FROM public.critic_run_occurrence_stats
 )
 SELECT
    -- Grouping columns
    cros.split,
    cros.scope_kind,
    cros.critic_definition_id,
    cros.critic_model,
    -- Example/run counts
    (SELECT COUNT(*)::integer FROM per_example pe
     WHERE pe.critic_definition_id = cros.critic_definition_id
       AND pe.split = cros.split AND pe.critic_model = cros.critic_model
       AND pe.scope_kind = cros.scope_kind) AS n_examples,
    COUNT(*)::integer AS n_runs,
    -- Ground truth (sum across distinct examples, not runs)
    (SELECT SUM(pe.n_catchable_occurrences)::integer FROM per_example pe
     WHERE pe.critic_definition_id = cros.critic_definition_id
       AND pe.split = cros.split AND pe.critic_model = cros.critic_model
       AND pe.scope_kind = cros.scope_kind) AS total_catchable_occurrences,
    -- Critic status breakdown
    public.agg_status_counts(array_agg(cros.critic_status)) AS status_counts,
    -- Occurrences caught statistics (failed runs count as 0 credit)
    public.compute_stats_with_ci(array_agg(
        COALESCE((cros.occurrences_caught_stats).mean, 0.0)
    )) AS occurrences_caught_stats
   FROM public.critic_run_occurrence_stats cros
  GROUP BY cros.split, cros.scope_kind, cros.critic_definition_id, cros.critic_model;

COMMENT ON VIEW public.aggregated_recall_by_definition IS 'Per-critic-definition aggregate metrics across all examples.

        Columns grouped: grouping keys, then example/run counts, then occurrence stats.

        - total_catchable_occurrences: Sum across distinct examples (not runs)
        - occurrences_caught_stats: Stats across all critic runs; failed runs count as 0 credit (.n = total run count)';

CREATE VIEW public.aggregated_recall_by_example AS
 SELECT
    -- Example identification
    cros.snapshot_slug,
    cros.scope_kind,
    cros.scope_hash,
    cros.split,
    -- Ground truth (constant for all runs on this example, use MAX)
    MAX(cros.n_catchable_occurrences)::integer AS n_catchable_occurrences,
    -- Critic columns
    cros.critic_model,
    COUNT(*)::integer AS n_runs,
    public.agg_status_counts(array_agg(cros.critic_status)) AS status_counts,
    -- Occurrences caught statistics (failed runs count as 0 credit)
    public.compute_stats_with_ci(array_agg(
        COALESCE((cros.occurrences_caught_stats).mean, 0.0)
    )) AS occurrences_caught_stats
   FROM public.critic_run_occurrence_stats cros
  GROUP BY cros.snapshot_slug, cros.scope_kind, cros.scope_hash, cros.split, cros.critic_model;

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);

CREATE TABLE public.events (
    id integer NOT NULL,
    agent_run_id uuid NOT NULL,
    sequence_num integer NOT NULL,
    event_type character varying NOT NULL,
    "timestamp" timestamp without time zone NOT NULL,
    payload jsonb NOT NULL
);

ALTER TABLE ONLY public.events FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.events_id_seq OWNED BY public.events.id;

CREATE SEQUENCE public.examples_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.examples_id_seq OWNED BY public.examples.id;

CREATE TABLE public.false_positives (
    snapshot_slug character varying NOT NULL,
    fp_id character varying NOT NULL,
    rationale text NOT NULL,
    occurrences jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.false_positives FORCE ROW LEVEL SECURITY;

CREATE VIEW public.grading_credit_sums AS
 SELECT agent_run_id,
    target_tp_id,
    target_tp_occurrence_id,
    target_fp_id,
    target_fp_occurrence_id,
    sum(credit) AS total_credit
   FROM public.grading_decisions
  WHERE ((target_tp_id IS NOT NULL) OR (target_fp_id IS NOT NULL))
  GROUP BY agent_run_id, target_tp_id, target_tp_occurrence_id, target_fp_id, target_fp_occurrence_id;

COMMENT ON VIEW public.grading_credit_sums IS 'Aggregate credit sums per (agent_run, occurrence) for enforcing credit ≤ 1.0 constraint.
        Used by check_credit_sum trigger function.';

CREATE SEQUENCE public.grading_decisions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.grading_decisions_id_seq OWNED BY public.grading_decisions.id;

CREATE TABLE public.model_metadata (
    model_id character varying NOT NULL,
    input_usd_per_1m_tokens double precision NOT NULL,
    cached_input_usd_per_1m_tokens double precision,
    output_usd_per_1m_tokens double precision NOT NULL,
    context_window_tokens integer NOT NULL,
    max_output_tokens integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.true_positives (
    snapshot_slug character varying NOT NULL,
    tp_id character varying NOT NULL,
    rationale text NOT NULL,
    occurrences jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.true_positives FORCE ROW LEVEL SECURITY;

CREATE VIEW public.occurrence_credits AS
 SELECT
    -- Example identification
    (cr.type_config ->> 'snapshot_slug'::text) AS snapshot_slug,
    s.split,
    (ex.scope ->> 'kind'::text) AS scope_kind,
    (cr.type_config ->> 'scope_hash'::text) AS scope_hash,
    ex.scope AS reviewed_scope,
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
   FROM ((((public.agent_runs gr
     JOIN public.agent_runs cr ON ((cr.agent_run_id = public.get_graded_agent_run_id(gr.agent_run_id))))
     JOIN public.snapshots s ON (((cr.type_config ->> 'snapshot_slug'::text) = (s.slug)::text)))
     JOIN public.examples ex ON ((((cr.type_config ->> 'snapshot_slug'::text) = (ex.snapshot_slug)::text) AND ((cr.type_config ->> 'scope_hash'::text) = (ex.scope_hash)::text))))
     JOIN public.grading_decisions gd ON ((gr.agent_run_id = gd.agent_run_id)))
  WHERE (((gr.type_config ->> 'agent_type'::text) = 'grader'::text) AND ((cr.type_config ->> 'agent_type'::text) = 'critic'::text) AND (gd.target_tp_id IS NOT NULL))
  GROUP BY (cr.type_config ->> 'snapshot_slug'::text), s.split, ex.scope, (cr.type_config ->> 'scope_hash'::text), gd.target_tp_id, gd.target_tp_occurrence_id, cr.agent_run_id, cr.agent_definition_id, cr.model, gr.agent_run_id, gr.created_at, gr.model
UNION ALL
 SELECT
    -- Example identification
    (cr.type_config ->> 'snapshot_slug'::text) AS snapshot_slug,
    s.split,
    (ex.scope ->> 'kind'::text) AS scope_kind,
    (cr.type_config ->> 'scope_hash'::text) AS scope_hash,
    ex.scope AS reviewed_scope,
    -- Ground truth
    tp.tp_id,
    (occ_data.value ->> 'occurrence_id'::text) AS occurrence_id,
    -- Critic-specific
    cr.agent_run_id AS critic_run_id,
    cr.agent_run_id AS critic_transcript_id,
    cr.agent_definition_id AS critic_definition_id,
    cr.model AS critic_model,
    -- Grader-specific (NULL for failed critics)
    NULL::uuid AS grader_run_id,
    NULL::uuid AS grader_transcript_id,
    cr.created_at AS graded_at,
    NULL::character varying AS grader_model,
    0.0 AS found_credit,
    NULL::jsonb AS matched_by_json,
    ('Critic failed: '::text || cr.status) AS grader_rationale
   FROM ((((public.agent_runs cr
     JOIN public.snapshots s ON (((cr.type_config ->> 'snapshot_slug'::text) = (s.slug)::text)))
     JOIN public.examples ex ON ((((cr.type_config ->> 'snapshot_slug'::text) = (ex.snapshot_slug)::text) AND ((cr.type_config ->> 'scope_hash'::text) = (ex.scope_hash)::text))))
     CROSS JOIN public.true_positives tp)
     CROSS JOIN LATERAL jsonb_array_elements(tp.occurrences) occ_data(value))
  WHERE (((cr.type_config ->> 'agent_type'::text) = 'critic'::text) AND (cr.status = ANY (ARRAY['max_turns_exceeded'::public.agent_run_status_enum, 'context_length_exceeded'::public.agent_run_status_enum])) AND ((cr.type_config ->> 'snapshot_slug'::text) = (tp.snapshot_slug)::text) AND (((ex.scope ->> 'kind'::text) = 'entire_snapshot'::text) OR (EXISTS ( SELECT 1
           FROM jsonb_array_elements((occ_data.value -> 'expect_caught_from'::text)) trigger_set(value)
          WHERE ( SELECT bool_and((file_elem.value IN ( SELECT jsonb_array_elements_text((ex.scope -> 'files'::text)) AS jsonb_array_elements_text))) AS bool_and
                   FROM jsonb_array_elements_text(trigger_set.value) file_elem(value))))));

COMMENT ON VIEW public.occurrence_credits IS 'Per-occurrence credit assignments from grader decisions or failed critic runs.

        For successful grading: joins grader agent_run to critic agent_run via type_config->graded_agent_run_id.
        For failed critics: synthesizes zero-credit rows for catchable occurrences.';

CREATE VIEW public.occurrence_run_credits AS
 SELECT
    -- Example identification
    snapshot_slug,
    split,
    scope_kind,
    scope_hash,
    reviewed_scope,
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
    array_agg(DISTINCT matched_by_json) FILTER (WHERE (matched_by_json IS NOT NULL)) AS all_matched_by,
    string_agg(DISTINCT grader_rationale, ' | '::text) AS combined_rationale
   FROM public.occurrence_credits
  GROUP BY snapshot_slug, split, scope_kind, scope_hash, reviewed_scope, tp_id, occurrence_id, critic_run_id, critic_transcript_id, critic_definition_id, critic_model, grader_run_id, grader_transcript_id, graded_at, grader_model;

CREATE VIEW public.occurrence_statistics AS
 SELECT
    -- Example identification
    snapshot_slug,
    split,
    scope_kind,
    scope_hash,
    reviewed_scope,
    -- Ground truth
    tp_id,
    occurrence_id,
    -- Critic-specific
    critic_definition_id,
    critic_model,
    -- Grader statistics (stats_with_ci includes count as .n)
    grader_model,
    public.compute_stats_with_ci(array_agg(total_credit)) AS credit_stats
   FROM public.occurrence_run_credits
  GROUP BY snapshot_slug, split, scope_kind, scope_hash, reviewed_scope, tp_id, occurrence_id, critic_definition_id, critic_model, grader_model;

CREATE VIEW public.pareto_frontier_by_example AS
 WITH credit_stats_per_definition_example AS (
         SELECT
            cros.snapshot_slug,
            cros.split,
            cros.scope_kind,
            cros.scope_hash,
            MAX(cros.n_catchable_occurrences)::integer AS n_catchable_occurrences,
            cros.critic_definition_id,
            cros.critic_model,
            -- Aggregate per-run means into definition-level stats (treating NULL as 0)
            public.compute_stats_with_ci(array_agg(COALESCE((cros.occurrences_caught_stats).mean, 0.0))) AS credit_stats
           FROM public.critic_run_occurrence_stats cros
          GROUP BY cros.snapshot_slug, cros.split, cros.scope_kind, cros.scope_hash, cros.critic_definition_id, cros.critic_model
        ), best_scores AS (
         SELECT
            snapshot_slug,
            split,
            scope_kind,
            scope_hash,
            n_catchable_occurrences,
            critic_model,
            max((credit_stats).mean) AS best_mean_credit
           FROM credit_stats_per_definition_example
          GROUP BY snapshot_slug, split, scope_kind, scope_hash, n_catchable_occurrences, critic_model
        )
 SELECT
    -- Example identification
    bs.snapshot_slug,
    bs.split,
    bs.scope_kind,
    bs.scope_hash,
    -- Ground truth
    bs.n_catchable_occurrences,
    -- Critic-specific
    bs.critic_model,
    bs.best_mean_credit,
    array_agg(cspde.critic_definition_id ORDER BY cspde.critic_definition_id) AS winning_critic_definition_ids,
    array_agg(cspde.credit_stats ORDER BY cspde.critic_definition_id) AS winning_definition_credit_stats
   FROM (best_scores bs
     JOIN credit_stats_per_definition_example cspde ON (
        (bs.snapshot_slug = cspde.snapshot_slug) AND
        (bs.split = cspde.split) AND
        (bs.scope_kind = cspde.scope_kind) AND
        (bs.scope_hash = cspde.scope_hash) AND
        (bs.critic_model = cspde.critic_model) AND
        (bs.best_mean_credit = (cspde.credit_stats).mean)))
  GROUP BY bs.snapshot_slug, bs.split, bs.scope_kind, bs.scope_hash, bs.n_catchable_occurrences, bs.critic_model, bs.best_mean_credit;

COMMENT ON VIEW public.pareto_frontier_by_example IS 'Pareto frontier: best total credit achieved on each example and which agent definitions achieved it.

        Returns raw totals (total_credit, n_catchable_occurrences) rather than computing recall fraction.
        Consumer can compute recall as total_credit / n_catchable_occurrences if needed.

        For each (snapshot_slug, split, scope_kind, scope_hash, critic_model), shows the best average
        total_credit across all definitions and lists all definition IDs that achieved this best score.

        Built on critic_run_occurrence_stats, which already aggregates over grader models.
        Failed critic runs (max_turns/context_length) count as 0.0 credit.';

CREATE TABLE public.reported_issue_occurrences (
    id integer NOT NULL,
    agent_run_id uuid NOT NULL,
    reported_issue_id character varying NOT NULL,
    locations jsonb NOT NULL,
    cancelled_at timestamp without time zone,
    cancellation_reason text,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT locations_not_empty CHECK ((jsonb_array_length(locations) > 0))
);

ALTER TABLE ONLY public.reported_issue_occurrences FORCE ROW LEVEL SECURITY;

COMMENT ON COLUMN public.reported_issue_occurrences.agent_run_id IS 'FK to agent_runs (denormalized from reported_issues for RLS efficiency)';

CREATE SEQUENCE public.reported_issue_occurrences_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.reported_issue_occurrences_id_seq OWNED BY public.reported_issue_occurrences.id;

CREATE TABLE public.reported_issues (
    agent_run_id uuid NOT NULL,
    issue_id character varying NOT NULL,
    rationale text NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.reported_issues FORCE ROW LEVEL SECURITY;

COMMENT ON COLUMN public.reported_issues.agent_run_id IS 'FK to agent_runs - identifies which agent run reported this issue';

CREATE TABLE public.unknown_assignments (
    id integer NOT NULL,
    grader_run_id uuid NOT NULL,
    unknown_id character varying NOT NULL,
    cluster_id integer,
    mapped_tp_id character varying,
    mapped_fp_id character varying,
    rationale text NOT NULL,
    cancelled_at timestamp without time zone,
    cancellation_reason text,
    agent_run_id uuid NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT unknown_assignments_exactly_one_target_check CHECK ((((cluster_id IS NOT NULL) AND (mapped_tp_id IS NULL) AND (mapped_fp_id IS NULL)) OR ((cluster_id IS NULL) AND (mapped_tp_id IS NOT NULL) AND (mapped_fp_id IS NULL)) OR ((cluster_id IS NULL) AND (mapped_tp_id IS NULL) AND (mapped_fp_id IS NOT NULL))))
);

ALTER TABLE ONLY public.unknown_assignments FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.unknown_assignments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.unknown_assignments_id_seq OWNED BY public.unknown_assignments.id;

CREATE TABLE public.unknown_clusters (
    id integer NOT NULL,
    cluster_name character varying NOT NULL,
    description text NOT NULL,
    agent_run_id uuid NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.unknown_clusters FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.unknown_clusters_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.unknown_clusters_id_seq OWNED BY public.unknown_clusters.id;

ALTER TABLE ONLY public.events ALTER COLUMN id SET DEFAULT nextval('public.events_id_seq'::regclass);

ALTER TABLE ONLY public.examples ALTER COLUMN id SET DEFAULT nextval('public.examples_id_seq'::regclass);

ALTER TABLE ONLY public.grading_decisions ALTER COLUMN id SET DEFAULT nextval('public.grading_decisions_id_seq'::regclass);

ALTER TABLE ONLY public.reported_issue_occurrences ALTER COLUMN id SET DEFAULT nextval('public.reported_issue_occurrences_id_seq'::regclass);

ALTER TABLE ONLY public.unknown_assignments ALTER COLUMN id SET DEFAULT nextval('public.unknown_assignments_id_seq'::regclass);

ALTER TABLE ONLY public.unknown_clusters ALTER COLUMN id SET DEFAULT nextval('public.unknown_clusters_id_seq'::regclass);

ALTER TABLE ONLY public.agent_definitions
    ADD CONSTRAINT agent_definitions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.agent_role_salt
    ADD CONSTRAINT agent_role_salt_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_pkey PRIMARY KEY (agent_run_id);

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);

ALTER TABLE ONLY public.events
    ADD CONSTRAINT events_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.examples
    ADD CONSTRAINT examples_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.false_positives
    ADD CONSTRAINT false_positives_pkey PRIMARY KEY (snapshot_slug, fp_id);

ALTER TABLE ONLY public.grading_decisions
    ADD CONSTRAINT grading_decisions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.model_metadata
    ADD CONSTRAINT model_metadata_pkey PRIMARY KEY (model_id);

ALTER TABLE ONLY public.reported_issue_occurrences
    ADD CONSTRAINT reported_issue_occurrences_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.reported_issues
    ADD CONSTRAINT reported_issues_pkey PRIMARY KEY (agent_run_id, issue_id);

ALTER TABLE ONLY public.snapshots
    ADD CONSTRAINT snapshots_pkey PRIMARY KEY (slug);

ALTER TABLE ONLY public.true_positives
    ADD CONSTRAINT true_positives_pkey PRIMARY KEY (snapshot_slug, tp_id);

ALTER TABLE ONLY public.unknown_assignments
    ADD CONSTRAINT unknown_assignments_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.unknown_clusters
    ADD CONSTRAINT unknown_clusters_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.events
    ADD CONSTRAINT uq_events_agent_run_id_seq UNIQUE (agent_run_id, sequence_num);

ALTER TABLE ONLY public.unknown_assignments
    ADD CONSTRAINT uq_unknown_assignments_unique_active UNIQUE (agent_run_id, grader_run_id, unknown_id, cancelled_at);

ALTER TABLE ONLY public.unknown_clusters
    ADD CONSTRAINT uq_unknown_clusters_agent_run_cluster_name UNIQUE (agent_run_id, cluster_name);

CREATE INDEX grading_decisions_agent_run_id_idx ON public.grading_decisions USING btree (agent_run_id);

CREATE INDEX idx_agent_definitions_created_by ON public.agent_definitions USING btree (created_by_agent_run_id) WHERE (created_by_agent_run_id IS NOT NULL);

CREATE INDEX idx_agent_definitions_type ON public.agent_definitions USING btree (agent_type);

CREATE INDEX idx_agent_runs_parent ON public.agent_runs USING btree (parent_agent_run_id) WHERE (parent_agent_run_id IS NOT NULL);

CREATE INDEX idx_agent_runs_snapshot ON public.agent_runs USING btree (((type_config ->> 'snapshot_slug'::text))) WHERE ((type_config ->> 'agent_type'::text) = 'critic'::text);

CREATE INDEX idx_agent_runs_type ON public.agent_runs USING btree (((type_config ->> 'agent_type'::text)));

CREATE INDEX ix_events_agent_run_id_seq ON public.events USING btree (agent_run_id, sequence_num);

CREATE INDEX ix_examples_snapshot_slug ON public.examples USING btree (snapshot_slug);

CREATE INDEX ix_false_positives_snapshot_slug ON public.false_positives USING btree (snapshot_slug);

CREATE INDEX ix_reported_issue_occurrences_reported_issue ON public.reported_issue_occurrences USING btree (agent_run_id, reported_issue_id);

CREATE INDEX ix_reported_issues_critic_run ON public.reported_issues USING btree (agent_run_id);

CREATE INDEX ix_true_positives_snapshot_slug ON public.true_positives USING btree (snapshot_slug);

CREATE INDEX ix_unknown_assignments_active ON public.unknown_assignments USING btree (agent_run_id, grader_run_id, unknown_id) WHERE (cancelled_at IS NULL);

CREATE INDEX ix_unknown_assignments_agent_run_id ON public.unknown_assignments USING btree (agent_run_id);

CREATE INDEX ix_unknown_assignments_cluster_active ON public.unknown_assignments USING btree (cluster_id) WHERE (cancelled_at IS NULL);

CREATE INDEX ix_unknown_assignments_grader_run_id ON public.unknown_assignments USING btree (grader_run_id);

CREATE INDEX ix_unknown_assignments_grader_unknown ON public.unknown_assignments USING btree (grader_run_id, unknown_id);

CREATE INDEX ix_unknown_clusters_agent_run_id ON public.unknown_clusters USING btree (agent_run_id);

CREATE UNIQUE INDEX uq_examples_scope ON public.examples USING btree (snapshot_slug, scope_hash);

CREATE TRIGGER enforce_credit_sum BEFORE INSERT OR UPDATE ON public.grading_decisions FOR EACH ROW EXECUTE FUNCTION public.check_credit_sum();

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_agent_definition_id_fkey FOREIGN KEY (agent_definition_id) REFERENCES public.agent_definitions(id);

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_parent_agent_run_id_fkey FOREIGN KEY (parent_agent_run_id) REFERENCES public.agent_runs(agent_run_id);

ALTER TABLE ONLY public.examples
    ADD CONSTRAINT examples_snapshot_slug_fkey FOREIGN KEY (snapshot_slug) REFERENCES public.snapshots(slug) ON DELETE CASCADE;

ALTER TABLE ONLY public.false_positives
    ADD CONSTRAINT false_positives_snapshot_slug_fkey FOREIGN KEY (snapshot_slug) REFERENCES public.snapshots(slug) ON DELETE CASCADE;

ALTER TABLE ONLY public.agent_definitions
    ADD CONSTRAINT fk_agent_definitions_created_by FOREIGN KEY (created_by_agent_run_id) REFERENCES public.agent_runs(agent_run_id);

ALTER TABLE ONLY public.events
    ADD CONSTRAINT fk_events_agent_run_id FOREIGN KEY (agent_run_id) REFERENCES public.agent_runs(agent_run_id) ON DELETE CASCADE;

ALTER TABLE ONLY public.unknown_assignments
    ADD CONSTRAINT fk_unknown_assignments_agent_run_id FOREIGN KEY (agent_run_id) REFERENCES public.agent_runs(agent_run_id) ON DELETE CASCADE;

ALTER TABLE ONLY public.unknown_assignments
    ADD CONSTRAINT fk_unknown_assignments_grader_run_id FOREIGN KEY (grader_run_id) REFERENCES public.agent_runs(agent_run_id) ON DELETE CASCADE;

ALTER TABLE ONLY public.unknown_clusters
    ADD CONSTRAINT fk_unknown_clusters_agent_run_id FOREIGN KEY (agent_run_id) REFERENCES public.agent_runs(agent_run_id) ON DELETE CASCADE;

ALTER TABLE ONLY public.grading_decisions
    ADD CONSTRAINT grading_decisions_agent_run_id_fkey FOREIGN KEY (agent_run_id) REFERENCES public.agent_runs(agent_run_id) ON DELETE CASCADE;

ALTER TABLE ONLY public.reported_issue_occurrences
    ADD CONSTRAINT reported_issue_occurrences_agent_run_id_issue_id_fkey FOREIGN KEY (agent_run_id, reported_issue_id) REFERENCES public.reported_issues(agent_run_id, issue_id) ON DELETE CASCADE;

ALTER TABLE ONLY public.reported_issues
    ADD CONSTRAINT reported_issues_agent_run_id_fkey FOREIGN KEY (agent_run_id) REFERENCES public.agent_runs(agent_run_id) ON DELETE CASCADE;

ALTER TABLE ONLY public.true_positives
    ADD CONSTRAINT true_positives_snapshot_slug_fkey FOREIGN KEY (snapshot_slug) REFERENCES public.snapshots(slug) ON DELETE CASCADE;

ALTER TABLE ONLY public.unknown_assignments
    ADD CONSTRAINT unknown_assignments_cluster_id_fkey FOREIGN KEY (cluster_id) REFERENCES public.unknown_clusters(id) ON DELETE CASCADE;

CREATE POLICY admin_full_access_events ON public.events TO postgres USING (true) WITH CHECK (true);

CREATE POLICY admin_full_access_examples ON public.examples TO postgres USING (true) WITH CHECK (true);

CREATE POLICY admin_full_access_false_positives ON public.false_positives TO postgres USING (true) WITH CHECK (true);

CREATE POLICY admin_full_access_snapshots ON public.snapshots TO postgres USING (true) WITH CHECK (true);

CREATE POLICY admin_full_access_true_positives ON public.true_positives TO postgres USING (true) WITH CHECK (true);

ALTER TABLE public.agent_definitions ENABLE ROW LEVEL SECURITY;

CREATE POLICY agent_definitions_insert ON public.agent_definitions FOR INSERT WITH CHECK ((created_by_agent_run_id = public.current_agent_run_id()));

CREATE POLICY agent_definitions_select ON public.agent_definitions FOR SELECT USING (true);

ALTER TABLE public.agent_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY agent_runs_agent_select ON public.agent_runs FOR SELECT USING ((((public.current_agent_type() = 'prompt_optimizer'::text) AND ((((type_config ->> 'agent_type'::text) = 'critic'::text) AND public.is_train_snapshot((type_config ->> 'snapshot_slug'::text))) OR (((type_config ->> 'agent_type'::text) = 'grader'::text) AND public.is_train_snapshot(public.get_graded_snapshot_slug(agent_run_id))))) OR (agent_run_id = public.current_agent_run_id()) OR ((public.current_agent_type() = 'grader'::text) AND (agent_run_id = public.current_graded_agent_run_id()))));

CREATE POLICY agent_runs_select_children ON public.agent_runs FOR SELECT USING ((parent_agent_run_id = public.current_agent_run_id()));

CREATE POLICY agent_runs_select_own ON public.agent_runs FOR SELECT USING ((agent_run_id = public.current_agent_run_id()));

CREATE POLICY clustering_user_events_policy ON public.events FOR SELECT USING ((CURRENT_USER ~ '^clustering_run_[0-9]+_agent$'::text));

CREATE POLICY clustering_user_false_positives_policy ON public.false_positives FOR SELECT USING ((CURRENT_USER ~ '^clustering_run_[0-9]+_agent$'::text));

CREATE POLICY clustering_user_snapshots_policy ON public.snapshots FOR SELECT USING ((CURRENT_USER ~ '^clustering_run_[0-9]+_agent$'::text));

CREATE POLICY clustering_user_true_positives_policy ON public.true_positives FOR SELECT USING ((CURRENT_USER ~ '^clustering_run_[0-9]+_agent$'::text));

ALTER TABLE public.events ENABLE ROW LEVEL SECURITY;

CREATE POLICY events_agent_select ON public.events FOR SELECT USING ((((public.current_agent_type() = 'prompt_optimizer'::text) AND public.is_train_agent_run(agent_run_id)) OR (agent_run_id = public.current_agent_run_id())));

ALTER TABLE public.examples ENABLE ROW LEVEL SECURITY;

CREATE POLICY examples_agent_select ON public.examples FOR SELECT USING ((((public.current_agent_type() = 'prompt_optimizer'::text) AND public.is_train_snapshot((snapshot_slug)::text)) OR ((public.current_agent_type() = ANY (ARRAY['critic'::text, 'clustering'::text])) AND ((snapshot_slug)::text = (public.current_agent_type_config() ->> 'snapshot_slug'::text)) AND ((scope_hash)::text = (public.current_agent_type_config() ->> 'scope_hash'::text)))));

ALTER TABLE public.false_positives ENABLE ROW LEVEL SECURITY;

CREATE POLICY false_positives_agent_select ON public.false_positives FOR SELECT USING ((((public.current_agent_type() = 'prompt_optimizer'::text) AND public.is_train_snapshot((snapshot_slug)::text)) OR ((public.current_agent_type() = 'grader'::text) AND ((snapshot_slug)::text = public.get_graded_snapshot_slug(public.current_agent_run_id())))));

ALTER TABLE public.grading_decisions ENABLE ROW LEVEL SECURITY;

CREATE POLICY grading_decisions_agent_delete ON public.grading_decisions FOR DELETE USING (((agent_run_id = public.current_agent_run_id()) AND (public.current_agent_type() = 'grader'::text)));

CREATE POLICY grading_decisions_agent_insert ON public.grading_decisions FOR INSERT WITH CHECK (((agent_run_id = public.current_agent_run_id()) AND (public.current_agent_type() = 'grader'::text)));

CREATE POLICY grading_decisions_agent_select ON public.grading_decisions FOR SELECT USING ((((public.current_agent_type() = 'prompt_optimizer'::text) AND public.is_train_agent_run(agent_run_id)) OR ((agent_run_id = public.current_agent_run_id()) AND (public.current_agent_type() = 'grader'::text))));

CREATE POLICY grading_decisions_agent_update ON public.grading_decisions FOR UPDATE USING (((agent_run_id = public.current_agent_run_id()) AND (public.current_agent_type() = 'grader'::text)));

ALTER TABLE public.reported_issue_occurrences ENABLE ROW LEVEL SECURITY;

CREATE POLICY reported_issue_occurrences_agent_delete ON public.reported_issue_occurrences FOR DELETE USING (((agent_run_id = public.current_agent_run_id()) AND (public.current_agent_type() = 'critic'::text)));
CREATE POLICY reported_issue_occurrences_agent_insert ON public.reported_issue_occurrences FOR INSERT WITH CHECK (((agent_run_id = public.current_agent_run_id()) AND (public.current_agent_type() = 'critic'::text)));
CREATE POLICY reported_issue_occurrences_agent_select ON public.reported_issue_occurrences FOR SELECT USING ((((public.current_agent_type() = 'prompt_optimizer'::text) AND public.is_train_agent_run(agent_run_id)) OR (agent_run_id = public.current_agent_run_id()) OR ((public.current_agent_type() = 'grader'::text) AND (agent_run_id = public.get_graded_agent_run_id(public.current_agent_run_id())))));

CREATE POLICY reported_issue_occurrences_agent_update ON public.reported_issue_occurrences FOR UPDATE USING (((agent_run_id = public.current_agent_run_id()) AND (public.current_agent_type() = 'critic'::text)));

ALTER TABLE public.reported_issues ENABLE ROW LEVEL SECURITY;

CREATE POLICY reported_issues_agent_delete ON public.reported_issues FOR DELETE USING (((agent_run_id = public.current_agent_run_id()) AND (public.current_agent_type() = 'critic'::text)));
CREATE POLICY reported_issues_agent_insert ON public.reported_issues FOR INSERT WITH CHECK (((agent_run_id = public.current_agent_run_id()) AND (public.current_agent_type() = 'critic'::text)));
CREATE POLICY reported_issues_agent_select ON public.reported_issues FOR SELECT USING ((((public.current_agent_type() = 'prompt_optimizer'::text) AND public.is_train_agent_run(agent_run_id)) OR (agent_run_id = public.current_agent_run_id()) OR ((public.current_agent_type() = 'grader'::text) AND (agent_run_id = public.get_graded_agent_run_id(public.current_agent_run_id())))));

CREATE POLICY reported_issues_agent_update ON public.reported_issues FOR UPDATE USING (((agent_run_id = public.current_agent_run_id()) AND (public.current_agent_type() = 'critic'::text)));

ALTER TABLE public.snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY snapshots_agent_select ON public.snapshots FOR SELECT USING ((public.current_agent_run_id() IS NOT NULL));

ALTER TABLE public.true_positives ENABLE ROW LEVEL SECURITY;

CREATE POLICY true_positives_agent_select ON public.true_positives FOR SELECT USING ((((public.current_agent_type() = 'prompt_optimizer'::text) AND public.is_train_snapshot((snapshot_slug)::text)) OR ((public.current_agent_type() = 'grader'::text) AND ((snapshot_slug)::text = public.get_graded_snapshot_slug(public.current_agent_run_id())))));

ALTER TABLE public.unknown_assignments ENABLE ROW LEVEL SECURITY;

CREATE POLICY unknown_assignments_agent_insert ON public.unknown_assignments FOR INSERT WITH CHECK ((agent_run_id = public.current_agent_run_id()));
CREATE POLICY unknown_assignments_agent_select ON public.unknown_assignments FOR SELECT USING ((agent_run_id = public.current_agent_run_id()));
CREATE POLICY unknown_assignments_agent_update ON public.unknown_assignments FOR UPDATE USING ((agent_run_id = public.current_agent_run_id()));

ALTER TABLE public.unknown_clusters ENABLE ROW LEVEL SECURITY;

CREATE POLICY unknown_clusters_agent_insert ON public.unknown_clusters FOR INSERT WITH CHECK ((agent_run_id = public.current_agent_run_id()));
CREATE POLICY unknown_clusters_agent_select ON public.unknown_clusters FOR SELECT USING ((agent_run_id = public.current_agent_run_id()));
CREATE POLICY unknown_clusters_agent_update ON public.unknown_clusters FOR UPDATE USING ((agent_run_id = public.current_agent_run_id()));

REVOKE USAGE ON SCHEMA public FROM PUBLIC;
GRANT ALL ON SCHEMA public TO PUBLIC;
GRANT USAGE ON SCHEMA public TO agent_base;

GRANT ALL ON FUNCTION public.current_agent_type() TO agent_base;
GRANT ALL ON FUNCTION public.get_graded_snapshot_slug(grader_run_id uuid) TO agent_base;
GRANT ALL ON FUNCTION public.get_validation_full_snapshot_aggregates() TO agent_base;
GRANT ALL ON FUNCTION public.is_train_agent_run(run_id uuid) TO agent_base;
GRANT ALL ON FUNCTION public.is_train_snapshot(slug text) TO agent_base;

GRANT SELECT,INSERT ON TABLE public.agent_definitions TO agent_base;
GRANT SELECT ON TABLE public.agent_runs TO agent_base;
GRANT SELECT ON TABLE public.examples TO agent_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.grading_decisions TO agent_base;
GRANT SELECT ON TABLE public.snapshots TO agent_base;
GRANT SELECT ON TABLE public.critic_run_occurrence_stats TO agent_base;
GRANT SELECT ON TABLE public.aggregated_recall_by_definition TO agent_base;
GRANT SELECT ON TABLE public.aggregated_recall_by_example TO agent_base;
GRANT SELECT ON TABLE public.events TO agent_base;
GRANT USAGE ON SEQUENCE public.events_id_seq TO agent_base;
GRANT USAGE ON SEQUENCE public.examples_id_seq TO agent_base;
GRANT SELECT ON TABLE public.false_positives TO agent_base;
GRANT SELECT ON TABLE public.grading_credit_sums TO agent_base;
GRANT USAGE ON SEQUENCE public.grading_decisions_id_seq TO agent_base;
GRANT SELECT ON TABLE public.true_positives TO agent_base;
GRANT SELECT ON TABLE public.occurrence_credits TO agent_base;
GRANT SELECT ON TABLE public.occurrence_run_credits TO agent_base;
GRANT SELECT ON TABLE public.occurrence_statistics TO agent_base;
GRANT SELECT ON TABLE public.pareto_frontier_by_example TO agent_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.reported_issue_occurrences TO agent_base;
GRANT USAGE ON SEQUENCE public.reported_issue_occurrences_id_seq TO agent_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.reported_issues TO agent_base;
GRANT SELECT,INSERT,UPDATE ON TABLE public.unknown_assignments TO agent_base;
GRANT SELECT,USAGE ON SEQUENCE public.unknown_assignments_id_seq TO agent_base;
GRANT SELECT,INSERT,UPDATE ON TABLE public.unknown_clusters TO agent_base;
GRANT SELECT,USAGE ON SEQUENCE public.unknown_clusters_id_seq TO agent_base;

-- PostgreSQL database dump complete

\unrestrict TCoce1f8sFaVdKyQ0oIg4svuybwmXpgf9kPWKxb9vMvJbRpaXaZOdWf5Uh2DKAW

