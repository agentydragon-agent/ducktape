"""Frozen final Props schema, retaining deployed revision 20260926000000.

A database already at 20260926000000 applies nothing. Older deployed revisions must first
reach 20260926000000 using the pre-squash image. Fresh databases create the final schema
without replaying intermediate data rewrites or retired tables.

DDL captured from the original chain in PostgreSQL 18 CI; see the adjacent
baseline test for its provenance and exact schema comparison. No runtime ORM
metadata is used. Specimen migration histories are independent and unchanged.
"""

import os

from alembic import op
from sqlalchemy import text

revision: str = "20260926000000"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    conn = op.get_bind()
    # Roles are cluster objects and absent from a schema-only database dump.
    # Preserve final attributes and the existing evaluator password contract.
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'agent_base') THEN
                CREATE ROLE agent_base NOLOGIN;
            END IF;
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'evaluator_base') THEN
                CREATE ROLE evaluator_base NOLOGIN;
            END IF;
        END $$;
        ALTER ROLE evaluator_base NOBYPASSRLS;
    """)
    if not conn.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = 'evaluator'")):
        password = os.environ.get("PROPS_EVALUATOR_PASSWORD")
        if password:
            conn.execute(text("CREATE ROLE evaluator LOGIN PASSWORD :pw IN ROLE evaluator_base"), {"pw": password})
        else:
            op.execute("CREATE ROLE evaluator LOGIN IN ROLE evaluator_base")
    # Some frozen function bodies reference tables created later in the dump.
    check_bodies = conn.scalar(text("SHOW check_function_bodies"))
    op.execute("SET LOCAL check_function_bodies = false")
    # Execute the multi-statement DDL without DBAPI parameter interpolation:
    # function bodies contain literal percent signs and dollar quoting.
    conn.exec_driver_sql(_SCHEMA_SQL, execution_options={"no_parameters": True})
    conn.execute(text("SELECT set_config('check_function_bodies', :value, true)"), {"value": check_bodies})
    # Bootstrap data is not included in schema-only dumps. Generate a NEW salt,
    # never copy one out of the capture database. Populate the empty matview so
    # fresh readers can query it before the first specimen sync.
    op.execute("INSERT INTO public.agent_role_salt (id) VALUES (1)")
    op.execute("REFRESH MATERIALIZED VIEW public.examples")


def downgrade() -> None:
    # Preserve the original baseline's explicit, destructive downgrade-to-base.
    op.execute("DROP SCHEMA public CASCADE")
    op.execute("CREATE SCHEMA public")
    op.execute("GRANT ALL ON SCHEMA public TO PUBLIC")


# Frozen SQL, not generated from the live ORM at migration time.
_SCHEMA_SQL = r"""
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

-- The extension owns its default comment; do not require ownership to reset it.


--
-- Name: agent_run_status_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_run_status_enum AS ENUM (
    'in_progress',
    'exited',
    'timed_out',
    'cancelled'
);


--
-- Name: agent_type_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_type_enum AS ENUM (
    'critic',
    'grader',
    'critic_dev_optimize',
    'freeform',
    'critic_dev_improve'
);


--
-- Name: example_kind_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.example_kind_enum AS ENUM (
    'whole_snapshot',
    'file_set'
);


--
-- Name: split_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.split_enum AS ENUM (
    'train',
    'valid',
    'test'
);


--
-- Name: stats_with_ci; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.stats_with_ci AS (
	n integer,
	mean double precision,
	min double precision,
	max double precision,
	lcb95 double precision,
	ucb95 double precision
);


--
-- Name: TYPE stats_with_ci; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TYPE public.stats_with_ci IS 'Statistics with 95% confidence interval bounds. Used for aggregated metrics.
- n: sample count
- mean: sample mean
- min: minimum value
- max: maximum value
- lcb95: lower 95% confidence bound (mean - 1.96 * stddev/sqrt(n))
- ucb95: upper 95% confidence bound (mean + 1.96 * stddev/sqrt(n))
Returns NULL for lcb95/ucb95 when n < 2 (insufficient samples for CI).';


--
-- Name: agg_status_counts(jsonb[]); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.agg_status_counts(counts jsonb[]) RETURNS jsonb
    LANGUAGE sql IMMUTABLE
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
        $$;


--
-- Name: agg_status_counts(public.agent_run_status_enum[]); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.agg_status_counts(statuses public.agent_run_status_enum[]) RETURNS jsonb
    LANGUAGE sql IMMUTABLE
    AS $$
            SELECT jsonb_object_agg(s, cnt)
            FROM (
                SELECT s, count(*) AS cnt
                FROM unnest(statuses) AS s
                GROUP BY s
            ) sub
        $$;


--
-- Name: all_valid_digests(jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.all_valid_digests(arr jsonb) RETURNS boolean
    LANGUAGE sql IMMUTABLE
    AS $$
            SELECT NOT EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(arr) AS d
                WHERE NOT public.is_valid_digest(d)
            )
        $$;


--
-- Name: can_access_snapshot_ground_truth(character varying); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.can_access_snapshot_ground_truth(p_slug character varying) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
            SELECT (current_agent_type() = 'critic_dev_optimize' AND is_train_snapshot(p_slug))
                OR (current_agent_type() = 'grader' AND p_slug = current_grader_snapshot_slug())
                OR (current_agent_type() = 'critic_dev_improve' AND is_improvement_snapshot_allowed(p_slug))
        $$;


--
-- Name: FUNCTION can_access_snapshot_ground_truth(p_slug character varying); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.can_access_snapshot_ground_truth(p_slug character varying) IS 'Can agent access ground truth (TPs/FPs) for this snapshot?
- critic_dev_optimize: TRAIN only (prevents overfitting to validation)
- grader: assigned snapshot only
- critic_dev_improve: allowed snapshots from config';


--
-- Name: can_list_snapshot_examples(character varying); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.can_list_snapshot_examples(p_slug character varying) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
            SELECT CASE
                WHEN current_agent_type_config()->>'target_metric' = 'whole_repo'
                    THEN is_train_snapshot(p_slug)
                ELSE is_train_or_valid_snapshot(p_slug)
            END
        $$;


--
-- Name: FUNCTION can_list_snapshot_examples(p_slug character varying); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.can_list_snapshot_examples(p_slug character varying) IS 'Can optimizer list file_sets/examples from this snapshot?
whole_repo optimizers: TRAIN only (sample from train, validate on valid)
other optimizers: TRAIN+VALID (need to see valid examples for selection)';


--
-- Name: can_read_agent_run_data(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.can_read_agent_run_data(p_run_id uuid) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
            SELECT (current_agent_type() = 'critic_dev_optimize' AND is_train_agent_run(p_run_id))
                OR (p_run_id = current_agent_run_id())
                OR (current_agent_type() = 'critic_dev_improve'
                    AND p_run_id IN (SELECT get_improvement_allowed_agent_run_ids()))
        $$;


--
-- Name: FUNCTION can_read_agent_run_data(p_run_id uuid); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.can_read_agent_run_data(p_run_id uuid) IS 'Returns TRUE if current agent can read data for the given agent_run_id.
Grants access to: own run, optimizer on TRAIN runs, improvement on allowed runs.
Used by reported_issues, reported_issue_occurrences SELECT policies.';


--
-- Name: check_cluster_member_no_positive_edges(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.check_cluster_member_no_positive_edges() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM grading_edges ge
                WHERE ge.critique_run_id = NEW.critique_run_id
                  AND ge.critique_issue_id = NEW.critique_issue_id
                  AND ge.credit > 0
            ) THEN
                RAISE EXCEPTION
                    'Cannot cluster issue (%, %) — it has grading edges with credit > 0',
                    NEW.critique_run_id, NEW.critique_issue_id;
            END IF;
            RETURN NEW;
        END;
        $$;


--
-- Name: check_cluster_not_empty(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.check_cluster_not_empty() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM issue_cluster_members icm
                WHERE icm.snapshot_slug = OLD.snapshot_slug
                  AND icm.cluster_id = OLD.cluster_id
            ) THEN
                RAISE EXCEPTION
                    'Cluster (%, %) would become empty — delete the cluster instead',
                    OLD.snapshot_slug, OLD.cluster_id;
            END IF;
            RETURN OLD;
        END;
        $$;


--
-- Name: check_edge_credit_sum(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.check_edge_credit_sum() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE
            current_total FLOAT;
        BEGIN
            -- Get current total (excluding this row if updating)
            IF NEW.tp_id IS NOT NULL THEN
                SELECT COALESCE(SUM(credit), 0.0) INTO current_total
                FROM grading_edges
                WHERE critique_run_id = NEW.critique_run_id
                  AND tp_id = NEW.tp_id
                  AND tp_occurrence_id = NEW.tp_occurrence_id
                  AND id != COALESCE(NEW.id, -1);
            ELSE
                SELECT COALESCE(SUM(credit), 0.0) INTO current_total
                FROM grading_edges
                WHERE critique_run_id = NEW.critique_run_id
                  AND fp_id = NEW.fp_id
                  AND fp_occurrence_id = NEW.fp_occurrence_id
                  AND id != COALESCE(NEW.id, -1);
            END IF;

            -- Check if adding new credit would exceed 1.0
            IF current_total + NEW.credit > 1.0 THEN
                RAISE EXCEPTION 'Credit sum for occurrence would exceed 1.0 (current: %, new: %)',
                    current_total, NEW.credit;
            END IF;

            RETURN NEW;
        END;
        $$;


--
-- Name: check_edge_matches_filter_scope(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.check_edge_matches_filter_scope() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'public'
    AS $$
    DECLARE
        filter_hash TEXT;
        reported_files VARCHAR[];
    BEGIN
        IF NEW.tp_id IS NOT NULL THEN
            SELECT match_file_restriction INTO filter_hash
            FROM true_positive_occurrences
            WHERE snapshot_slug = NEW.snapshot_slug
              AND tp_id = NEW.tp_id
              AND occurrence_id = NEW.tp_occurrence_id;
        ELSE
            SELECT match_file_restriction INTO filter_hash
            FROM false_positive_occurrences
            WHERE snapshot_slug = NEW.snapshot_slug
              AND fp_id = NEW.fp_id
              AND occurrence_id = NEW.fp_occurrence_id;
        END IF;

        IF filter_hash IS NULL THEN
            RETURN NEW;
        END IF;

        -- Files this critique issue reported (reported_issue_occurrences.locations
        -- is a JSONB array of {file, start_line?, end_line?}).
        SELECT array_agg(DISTINCT loc->>'file')
        INTO reported_files
        FROM reported_issue_occurrences rio
        CROSS JOIN LATERAL jsonb_array_elements(rio.locations) AS loc
        WHERE rio.agent_run_id = NEW.critique_run_id
          AND rio.reported_issue_id = NEW.critique_issue_id
          AND loc->>'file' IS NOT NULL;

        IF NOT occurrence_files_overlap(NEW.snapshot_slug, filter_hash, COALESCE(reported_files, ARRAY[]::VARCHAR[])) THEN
            RAISE EXCEPTION 'Critique issue % reports no files overlapping target occurrence match_file_restriction scope (filter: %)',
                NEW.critique_issue_id, filter_hash;
        END IF;

        RETURN NEW;
    END;
    $$;


--
-- Name: FUNCTION check_edge_matches_filter_scope(); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.check_edge_matches_filter_scope() IS 'Validates that grading edges only target occurrences whose match_file_restriction
includes the files where the critique issue was reported. Prevents matching
a critique to an occurrence that could not have been found from those files.';


--
-- Name: check_positive_edge_not_clustered(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.check_positive_edge_not_clustered() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.credit > 0 AND EXISTS (
                SELECT 1 FROM issue_cluster_members icm
                WHERE icm.critique_run_id = NEW.critique_run_id
                  AND icm.critique_issue_id = NEW.critique_issue_id
            ) THEN
                RAISE EXCEPTION
                    'Cannot assign credit > 0 to issue (%, %) — remove from cluster first',
                    NEW.critique_run_id, NEW.critique_issue_id;
            END IF;
            RETURN NEW;
        END;
        $$;


--
-- Name: compute_stats_with_ci(double precision[]); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.compute_stats_with_ci(vals double precision[]) RETURNS public.stats_with_ci
    LANGUAGE sql IMMUTABLE
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
        $$;


--
-- Name: create_agent_role(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.create_agent_role(run_id uuid) RETURNS void
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
        $$;


--
-- Name: current_agent_run_id(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.current_agent_run_id() RETURNS uuid
    LANGUAGE sql STABLE
    AS $$
            SELECT CASE
                WHEN session_user LIKE 'agent_%'
                THEN substring(session_user from 'agent_([0-9a-f-]+)')::uuid
                ELSE NULL
            END
        $$;


--
-- Name: FUNCTION current_agent_run_id(); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.current_agent_run_id() IS 'Uses session_user (not current_user) so it works inside SECURITY DEFINER functions.';


--
-- Name: current_agent_type(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.current_agent_type() RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
            SELECT current_agent_type_config()->>'agent_type'
        $$;


--
-- Name: current_agent_type_config(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.current_agent_type_config() RETURNS jsonb
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
            SELECT type_config
            FROM agent_runs
            WHERE agent_run_id = current_agent_run_id()
        $$;


--
-- Name: current_grader_snapshot_slug(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.current_grader_snapshot_slug() RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
            SELECT (type_config->>'snapshot_slug')::text
            FROM agent_runs
            WHERE agent_run_id = current_agent_run_id()
              AND (type_config->>'agent_type') = 'grader'
        $$;


--
-- Name: derive_agent_password(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.derive_agent_password(run_id uuid) RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
            SELECT encode(
                sha256((SELECT salt FROM agent_role_salt) || run_id::text::bytea),
                'hex'
            )
        $$;


--
-- Name: get_agent_run_ids_for_train_snapshots(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_agent_run_ids_for_train_snapshots() RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
            SELECT agent_run_id
            FROM agent_runs
            WHERE type_config->>'agent_type' IN ('critic', 'grader')
              AND type_config->'example'->>'snapshot_slug' IN (SELECT slug FROM snapshots WHERE split = 'train')
        $$;


--
-- Name: get_agent_type_config(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_agent_type_config(p_agent_run_id uuid) RETURNS jsonb
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
            SELECT type_config
            FROM agent_runs
            WHERE agent_run_id = p_agent_run_id
        $$;


--
-- Name: get_improvement_allowed_agent_run_ids(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_improvement_allowed_agent_run_ids() RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
            SELECT ar.agent_run_id
            FROM agent_runs ar
            WHERE current_agent_type() = 'critic_dev_improve'
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
        $$;


--
-- Name: get_validation_full_snapshot_aggregates(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_validation_full_snapshot_aggregates() RETURNS TABLE(snapshot_slug text, critic_image_digest text, critic_model text, critic_run_id uuid, status public.agent_run_status_enum, total_credit double precision, n_occurrences integer)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
        DECLARE
            config jsonb;
        BEGIN
            config := current_agent_type_config();

            IF config IS NULL OR config->>'target_metric' != 'whole-repo' THEN
                RAISE EXCEPTION 'Access denied: get_validation_full_snapshot_aggregates() requires whole-repo target_metric';
            END IF;

            RETURN QUERY
            SELECT
                toc.snapshot_slug,
                toc.critic_image_digest,
                toc.critic_model,
                toc.critic_run_id,
                cr.status,
                SUM(toc.found_credit)::double precision AS total_credit,
                CAST(COUNT(*) AS integer) AS n_occurrences
            FROM tp_occurrence_credits toc
            JOIN snapshots s ON toc.snapshot_slug = s.slug
            JOIN agent_runs cr ON toc.critic_run_id = cr.agent_run_id
            WHERE s.split = 'valid'::split_enum
              AND toc.example_kind = 'whole_snapshot'
              AND (cr.type_config->>'agent_type') = 'critic'
            GROUP BY toc.snapshot_slug, toc.critic_image_digest, toc.critic_model,
                     toc.critic_run_id, cr.status
            ORDER BY toc.snapshot_slug, toc.critic_image_digest, toc.critic_model,
                     toc.critic_run_id;
        END;
        $$;


--
-- Name: FUNCTION get_validation_full_snapshot_aggregates(); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.get_validation_full_snapshot_aggregates() IS 'Black-box validation metrics for whole-repo mode.
Returns per-critic-run recall for VALID split, whole_snapshot example_kind only.
Requires caller to be a whole-repo mode agent (critic_dev_optimize or critic_dev_improve).';


--
-- Name: is_agent_ancestor(uuid, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.is_agent_ancestor(ancestor_id uuid, descendant_id uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
        WITH RECURSIVE ancestors AS (
            SELECT agent_run_id, parent_agent_run_id
            FROM agent_runs
            WHERE agent_run_id = descendant_id

            UNION ALL

            SELECT ar.agent_run_id, ar.parent_agent_run_id
            FROM agent_runs ar
            JOIN ancestors a ON ar.agent_run_id = a.parent_agent_run_id
        )
        SELECT EXISTS (
            SELECT 1 FROM ancestors WHERE agent_run_id = ancestor_id
        );
        $$;


--
-- Name: is_critique_on_grader_snapshot(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.is_critique_on_grader_snapshot(p_critique_run_id uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
            SELECT EXISTS (
                SELECT 1 FROM agent_runs critique
                WHERE critique.agent_run_id = p_critique_run_id
                  AND (critique.type_config->>'agent_type') = 'critic'
                  AND (critique.type_config->'example'->>'snapshot_slug') = current_grader_snapshot_slug()
            )
        $$;


--
-- Name: is_fp_relevant_for_scope(text, text, public.example_kind_enum, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.is_fp_relevant_for_scope(p_snapshot_slug text, p_fp_id text, p_example_kind public.example_kind_enum, p_files_hash text) RETURNS boolean
    LANGUAGE sql STABLE
    SET search_path TO 'public'
    AS $$
        SELECT CASE
            WHEN p_example_kind = 'whole_snapshot' THEN TRUE
            ELSE EXISTS (
                SELECT 1
                FROM fp_occurrence_relevant_files frf
                WHERE frf.snapshot_slug = p_snapshot_slug
                  AND frf.fp_id = p_fp_id
                  AND frf.file_path IN (
                      SELECT fsm.file_path
                      FROM file_set_members fsm
                      WHERE fsm.snapshot_slug = p_snapshot_slug
                        AND fsm.files_hash = p_files_hash
                  )
            )
        END
    $$;


--
-- Name: is_improvement_example_allowed(text, public.example_kind_enum, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.is_improvement_example_allowed(p_snapshot_slug text, p_example_kind public.example_kind_enum, p_files_hash text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
            SELECT COALESCE(
                (current_agent_type() = 'critic_dev_improve')
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
        $$;


--
-- Name: is_improvement_snapshot_allowed(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.is_improvement_snapshot_allowed(p_slug text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
            SELECT COALESCE(
                (current_agent_type() = 'critic_dev_improve')
                AND EXISTS (
                    SELECT 1 FROM jsonb_array_elements(current_agent_type_config()->'allowed_examples') elem
                    WHERE elem->>'snapshot_slug' = p_slug
                ),
                FALSE
            )
        $$;


--
-- Name: is_own_run_as(uuid, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.is_own_run_as(p_run_id uuid, p_type text) RETURNS boolean
    LANGUAGE plpgsql STABLE
    AS $$
        BEGIN
            RETURN p_run_id = current_agent_run_id() AND current_agent_type() = p_type;
        END;
        $$;


--
-- Name: is_tp_in_expected_recall_scope(text, text, text, public.example_kind_enum, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.is_tp_in_expected_recall_scope(p_snapshot_slug text, p_tp_id text, p_occurrence_id text, p_example_kind public.example_kind_enum, p_files_hash text) RETURNS boolean
    LANGUAGE sql STABLE
    SET search_path TO 'public'
    AS $$
            -- Whole-snapshot scope includes all TPs in recall denominator
            SELECT CASE
                WHEN p_example_kind = 'whole_snapshot' THEN TRUE
                ELSE EXISTS (
                    -- Check if any critic_scopes_expected_to_recall entry for this occurrence
                    -- is a subset of the reviewed scope
                    SELECT 1
                    FROM critic_scopes_expected_to_recall csetr
                    WHERE csetr.snapshot_slug = p_snapshot_slug
                      AND csetr.tp_id = p_tp_id
                      AND csetr.occurrence_id = p_occurrence_id
                      -- All files in this expected recall scope must be in the reviewed scope
                      AND NOT EXISTS (
                          SELECT 1 FROM file_set_members fsm
                          WHERE fsm.snapshot_slug = p_snapshot_slug
                            AND fsm.files_hash = csetr.files_hash
                            AND fsm.file_path NOT IN (
                                SELECT fsm2.file_path
                                FROM file_set_members fsm2
                                WHERE fsm2.snapshot_slug = p_snapshot_slug
                                  AND fsm2.files_hash = p_files_hash
                            )
                      )
                )
            END
        $$;


--
-- Name: FUNCTION is_tp_in_expected_recall_scope(p_snapshot_slug text, p_tp_id text, p_occurrence_id text, p_example_kind public.example_kind_enum, p_files_hash text); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.is_tp_in_expected_recall_scope(p_snapshot_slug text, p_tp_id text, p_occurrence_id text, p_example_kind public.example_kind_enum, p_files_hash text) IS 'Returns TRUE if this TP occurrence should count toward recall denominator for the given scope.
Filters by (tp_id, occurrence_id) so only occurrences with matching scopes count.
For whole-snapshot scope, always returns TRUE.
NOTE: This determines the recall DENOMINATOR only. Critics CAN find issues outside expected scopes
(achieving >100%% recall). The match_file_restriction field separately constrains
where graders can give credit.';


--
-- Name: is_train_agent_run(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.is_train_agent_run(run_id uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    AS $$
            SELECT COALESCE(
                CASE get_agent_type_config(run_id)->>'agent_type'
                    WHEN 'critic' THEN is_train_snapshot(get_agent_type_config(run_id)->'example'->>'snapshot_slug')
                    WHEN 'grader' THEN is_train_snapshot(get_agent_type_config(run_id)->>'snapshot_slug')
                    ELSE FALSE
                END,
                FALSE
            )
        $$;


--
-- Name: is_train_or_valid_snapshot(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.is_train_or_valid_snapshot(slug text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
            SELECT EXISTS (
                SELECT 1 FROM snapshots
                WHERE snapshots.slug = is_train_or_valid_snapshot.slug
                  AND split IN ('train', 'valid')
            )
        $$;


--
-- Name: is_train_snapshot(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.is_train_snapshot(slug text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
            SELECT EXISTS (
                SELECT 1 FROM snapshots
                WHERE snapshots.slug = is_train_snapshot.slug AND split = 'train'
            )
        $$;


--
-- Name: is_valid_digest(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.is_valid_digest(val text) RETURNS boolean
    LANGUAGE sql IMMUTABLE
    AS $_$
            SELECT val ~ '^sha256:[0-9a-f]{64}$'
        $_$;


--
-- Name: is_valid_snapshot(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.is_valid_snapshot(slug text) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
            SELECT EXISTS (
                SELECT 1 FROM snapshots
                WHERE snapshots.slug = is_valid_snapshot.slug AND split = 'valid'
            )
        $$;


--
-- Name: matchable_occurrences(character varying, character varying[]); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.matchable_occurrences(p_snapshot_slug character varying, p_files character varying[]) RETURNS TABLE(tp_id character varying, tp_occurrence_id character varying, fp_id character varying, fp_occurrence_id character varying)
    LANGUAGE sql STABLE
    AS $$
        SELECT tpo.tp_id, tpo.occurrence_id, NULL::VARCHAR, NULL::VARCHAR
        FROM true_positive_occurrences tpo
        WHERE tpo.snapshot_slug = p_snapshot_slug
          AND occurrence_files_overlap(tpo.snapshot_slug, tpo.match_file_restriction, p_files)
        UNION ALL
        SELECT NULL, NULL, fpo.fp_id, fpo.occurrence_id
        FROM false_positive_occurrences fpo
        WHERE fpo.snapshot_slug = p_snapshot_slug
          AND occurrence_files_overlap(fpo.snapshot_slug, fpo.match_file_restriction, p_files)
    $$;


--
-- Name: FUNCTION matchable_occurrences(p_snapshot_slug character varying, p_files character varying[]); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.matchable_occurrences(p_snapshot_slug character varying, p_files character varying[]) IS 'Returns GT occurrences matchable from given files for a snapshot.
Used by:
- grading_pending view (drift detection)
- Edge validation trigger
- Workload estimation

NULL match_file_restriction = unrestricted (any critique can match)
Non-NULL = file-restricted (only critiques touching those files can match)';


--
-- Name: notify_critique_changed(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.notify_critique_changed() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE
            v_snapshot_slug VARCHAR;
            v_item JSONB;
        BEGIN
            SELECT ar.type_config->'example'->>'snapshot_slug'
            INTO v_snapshot_slug
            FROM agent_runs ar
            WHERE ar.agent_run_id = NEW.agent_run_id;

            IF v_snapshot_slug IS NOT NULL THEN
                v_item := jsonb_build_object('table', TG_TABLE_NAME);

                CASE TG_TABLE_NAME
                    WHEN 'reported_issues' THEN
                        v_item := v_item || jsonb_build_object(
                            'agent_run_id', NEW.agent_run_id,
                            'issue_id', NEW.issue_id
                        );
                    WHEN 'reported_issue_occurrences' THEN
                        v_item := v_item || jsonb_build_object(
                            'occurrence_id', NEW.id,
                            'agent_run_id', NEW.agent_run_id,
                            'reported_issue_id', NEW.reported_issue_id
                        );
                END CASE;

                PERFORM pg_notify('grading_pending', jsonb_build_object(
                    'operation', TG_OP,
                    'item', v_item,
                    'snapshot_slug', v_snapshot_slug
                )::text);
            END IF;

            RETURN NEW;
        END;
        $$;


--
-- Name: FUNCTION notify_critique_changed(); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.notify_critique_changed() IS 'Looks up snapshot_slug from agent_run type_config (critique tables don''t store it directly).';


--
-- Name: notify_gt_changed(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.notify_gt_changed() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE
            v_row RECORD;
            v_item JSONB;
        BEGIN
            v_row := COALESCE(NEW, OLD);

            v_item := jsonb_build_object('table', TG_TABLE_NAME);

            CASE TG_TABLE_NAME
                WHEN 'true_positives' THEN
                    v_item := v_item || jsonb_build_object('tp_id', v_row.tp_id);
                WHEN 'true_positive_occurrences' THEN
                    v_item := v_item || jsonb_build_object('tp_id', v_row.tp_id, 'occurrence_id', v_row.occurrence_id);
                WHEN 'false_positives' THEN
                    v_item := v_item || jsonb_build_object('fp_id', v_row.fp_id);
                WHEN 'false_positive_occurrences' THEN
                    v_item := v_item || jsonb_build_object('fp_id', v_row.fp_id, 'occurrence_id', v_row.occurrence_id);
            END CASE;

            PERFORM pg_notify('grading_pending', jsonb_build_object(
                'operation', TG_OP,
                'item', v_item,
                'snapshot_slug', v_row.snapshot_slug
            )::text);
            RETURN v_row;
        END;
        $$;


--
-- Name: FUNCTION notify_gt_changed(); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.notify_gt_changed() IS 'INSERT/DELETE only (not UPDATE — wording fixes don''t need re-grade).';


--
-- Name: notify_snapshot_created(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.notify_snapshot_created() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            PERFORM pg_notify('snapshot_created', jsonb_build_object(
                'operation', TG_OP,
                'snapshot_slug', NEW.slug
            )::text);
            RETURN NEW;
        END;
        $$;


--
-- Name: occurrence_files_overlap(character varying, character varying, character varying[]); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.occurrence_files_overlap(p_snapshot_slug character varying, p_files_hash character varying, p_files character varying[]) RETURNS boolean
    LANGUAGE sql STABLE
    SET search_path TO 'public'
    AS $$
        SELECT p_files_hash IS NULL
            OR EXISTS (
                SELECT 1 FROM file_set_members fsm
                WHERE fsm.snapshot_slug = p_snapshot_slug
                  AND fsm.files_hash = p_files_hash
                  AND fsm.file_path = ANY(p_files)
            )
    $$;


--
-- Name: FUNCTION occurrence_files_overlap(p_snapshot_slug character varying, p_files_hash character varying, p_files character varying[]); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.occurrence_files_overlap(p_snapshot_slug character varying, p_files_hash character varying, p_files character varying[]) IS 'Canonical match_file_restriction matchability rule (OVERLAP).
TRUE if p_files_hash IS NULL (unrestricted) or at least one of p_files is in the
restriction file set. Single source of truth shared by matchable_occurrences()
(grading_pending view, workload estimation) and the enforce_edge_filter_scope trigger.';


--
-- Name: scale_stats(public.stats_with_ci, double precision); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.scale_stats(s public.stats_with_ci, divisor double precision) RETURNS public.stats_with_ci
    LANGUAGE sql IMMUTABLE
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
        $$;


--
-- Name: validate_range_line_numbers(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.validate_range_line_numbers() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE
            file_line_count INT;
            effective_end_line INT;
        BEGIN
            -- Unspecified line anchor: no range bounds to validate
            IF NEW.start_line IS NULL THEN
                RETURN NEW;
            END IF;

            -- Get line count for the referenced file
            SELECT line_count INTO file_line_count
            FROM snapshot_files
            WHERE snapshot_slug = NEW.snapshot_slug
              AND file_path = NEW.file_path;

            effective_end_line := COALESCE(NEW.end_line, NEW.start_line);

            -- Validate line range does not exceed file length
            IF effective_end_line > file_line_count THEN
                RAISE EXCEPTION 'Line range [%, %] exceeds file line count % for file % in snapshot %',
                    NEW.start_line, NEW.end_line, file_line_count, NEW.file_path, NEW.snapshot_slug;
            END IF;

            RETURN NEW;
        END;
        $$;


--
-- Name: FUNCTION validate_range_line_numbers(); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.validate_range_line_numbers() IS 'Ensures end_line <= snapshot_files.line_count for ground truth ranges.';


--
-- Name: validate_reported_issue_line_numbers(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.validate_reported_issue_line_numbers() RETURNS trigger
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
              AND sf.file_path = file_path;

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
        $$;


--
-- Name: FUNCTION validate_reported_issue_line_numbers(); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.validate_reported_issue_line_numbers() IS 'Line numbers are 1-based inclusive: for line_count=N, valid range is 1..N.';


--
-- Name: validate_reported_issue_occ_basic_line_numbers(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.validate_reported_issue_occ_basic_line_numbers() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
        $$;


--
-- Name: FUNCTION validate_reported_issue_occ_basic_line_numbers(); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.validate_reported_issue_occ_basic_line_numbers() IS 'Basic checks (>= 1, end >= start). Cross-file validation in validate_reported_issue_line_numbers().';


SET LOCAL default_tablespace = '';

SET LOCAL default_table_access_method = heap;

--
-- Name: agent_definitions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_definitions (
    digest text NOT NULL,
    agent_type public.agent_type_enum NOT NULL,
    created_by_agent_run_id uuid,
    base_digest text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    display_name text,
    CONSTRAINT check_digest_format CHECK (public.is_valid_digest(digest))
);


--
-- Name: TABLE agent_definitions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.agent_definitions IS 'Agent images as OCI digests. Registry proxy writes rows on manifest push.';


--
-- Name: COLUMN agent_definitions.digest; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_definitions.digest IS 'OCI image digest (sha256:...)';


--
-- Name: COLUMN agent_definitions.agent_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_definitions.agent_type IS 'Agent type enum (maps to repository name in registry)';


--
-- Name: COLUMN agent_definitions.created_by_agent_run_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_definitions.created_by_agent_run_id IS 'Agent run that created this image (NULL for builtin images)';


--
-- Name: COLUMN agent_definitions.base_digest; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_definitions.base_digest IS 'Parent image digest if this is a layered image';


--
-- Name: COLUMN agent_definitions.display_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_definitions.display_name IS 'Human-readable name from OCI label org.opencontainers.image.title';


--
-- Name: agent_role_salt; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_role_salt (
    id integer DEFAULT 1 NOT NULL,
    salt bytea DEFAULT public.gen_random_bytes(32) NOT NULL,
    CONSTRAINT agent_role_salt_id_check CHECK ((id = 1))
);


--
-- Name: TABLE agent_role_salt; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.agent_role_salt IS 'Singleton containing salt for deterministic agent password derivation';


--
-- Name: agent_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_runs (
    agent_run_id uuid NOT NULL,
    image_digest text NOT NULL,
    parent_agent_run_id uuid,
    model text NOT NULL,
    type_config jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    status public.agent_run_status_enum DEFAULT 'in_progress'::public.agent_run_status_enum NOT NULL,
    container_exit_code integer,
    budget_usd double precision NOT NULL,
    timeout_seconds integer,
    started_at timestamp with time zone,
    ended_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT check_allowed_examples_not_empty CHECK ((((type_config ->> 'agent_type'::text) <> 'critic_dev_improve'::text) OR (jsonb_array_length((type_config -> 'allowed_examples'::text)) > 0))),
    CONSTRAINT check_baseline_digests CHECK ((((type_config ->> 'agent_type'::text) <> 'critic_dev_improve'::text) OR ((jsonb_array_length((type_config -> 'baseline_image_digests'::text)) > 0) AND public.all_valid_digests((type_config -> 'baseline_image_digests'::text)))))
);


--
-- Name: TABLE agent_runs; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.agent_runs IS 'Unified table for all agent runs (critics, graders, optimizers, freeform)';


--
-- Name: COLUMN agent_runs.image_digest; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_runs.image_digest IS 'OCI image digest (FK to agent_definitions.digest)';


--
-- Name: COLUMN agent_runs.parent_agent_run_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_runs.parent_agent_run_id IS 'Parent agent that spawned this sub-agent (NULL for top-level)';


--
-- Name: COLUMN agent_runs.type_config; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_runs.type_config IS 'JSONB with agent_type discriminator and type-specific fields';


--
-- Name: COLUMN agent_runs.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_runs.status IS 'Terminal status of the agent run';


--
-- Name: COLUMN agent_runs.container_exit_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_runs.container_exit_code IS 'Container exit code (NULL if still running or not container-based)';


--
-- Name: COLUMN agent_runs.budget_usd; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_runs.budget_usd IS 'Max USD cost allowed for this agent (including child agents). Enforced by proxy.';


--
-- Name: COLUMN agent_runs.timeout_seconds; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_runs.timeout_seconds IS 'Max seconds before agent is killed. Enforced by agent_registry.';


--
-- Name: COLUMN agent_runs.started_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_runs.started_at IS 'When container started executing';


--
-- Name: COLUMN agent_runs.ended_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_runs.ended_at IS 'When container finished (success or failure)';


--
-- Name: llm_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.llm_requests (
    id bigint NOT NULL,
    agent_run_id uuid NOT NULL,
    model character varying NOT NULL,
    request_body jsonb NOT NULL,
    response_body jsonb,
    error text,
    input_tokens integer,
    cached_input_tokens integer,
    output_tokens integer,
    latency_ms integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    api_shape character varying DEFAULT 'responses'::character varying NOT NULL,
    CONSTRAINT llm_requests_api_shape_check CHECK (((api_shape)::text = ANY ((ARRAY['responses'::character varying, 'chat_completions'::character varying, 'anthropic'::character varying])::text[])))
);


--
-- Name: TABLE llm_requests; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.llm_requests IS 'LLM API requests logged by the proxy. Replaces events table for LLM tracking.';


--
-- Name: model_metadata; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_metadata (
    model_id character varying NOT NULL,
    input_usd_per_1m_tokens double precision NOT NULL,
    cached_input_usd_per_1m_tokens double precision,
    output_usd_per_1m_tokens double precision NOT NULL,
    context_window_tokens integer NOT NULL,
    max_output_tokens integer,
    upstream_name character varying NOT NULL,
    upstream_model character varying,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    api_shape character varying DEFAULT 'responses'::character varying NOT NULL,
    CONSTRAINT model_metadata_api_shape_check CHECK (((api_shape)::text = ANY ((ARRAY['responses'::character varying, 'chat_completions'::character varying, 'anthropic'::character varying])::text[])))
);


--
-- Name: llm_request_costs; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.llm_request_costs AS
 SELECT r.id,
    r.agent_run_id,
    r.model,
    r.input_tokens,
    r.cached_input_tokens,
    r.output_tokens,
    r.latency_ms,
    r.created_at,
    ((((((COALESCE(r.input_tokens, 0) - COALESCE(r.cached_input_tokens, 0)))::double precision * COALESCE(m.input_usd_per_1m_tokens, (0)::double precision)) / (1000000.0)::double precision) + (((COALESCE(r.cached_input_tokens, 0))::double precision * COALESCE(m.cached_input_usd_per_1m_tokens, (0)::double precision)) / (1000000.0)::double precision)) + (((COALESCE(r.output_tokens, 0))::double precision * COALESCE(m.output_usd_per_1m_tokens, (0)::double precision)) / (1000000.0)::double precision)) AS cost_usd
   FROM (public.llm_requests r
     LEFT JOIN public.model_metadata m ON (((r.model)::text = (m.model_id)::text)));


--
-- Name: agent_run_budget_status; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.agent_run_budget_status AS
 SELECT ar.agent_run_id,
    ar.budget_usd,
    COALESCE(own.spent_usd, (0)::double precision) AS own_spent_usd,
    COALESCE(tree.spent_usd, (0)::double precision) AS tree_spent_usd,
    (ar.budget_usd - COALESCE(tree.spent_usd, (0)::double precision)) AS remaining_usd
   FROM ((public.agent_runs ar
     LEFT JOIN LATERAL ( SELECT sum(c.cost_usd) AS spent_usd
           FROM public.llm_request_costs c
          WHERE (c.agent_run_id = ar.agent_run_id)) own ON (true))
     LEFT JOIN LATERAL ( SELECT sum(c.cost_usd) AS spent_usd
           FROM (( WITH RECURSIVE run_tree AS (
                         SELECT ar.agent_run_id
                        UNION ALL
                         SELECT child.agent_run_id
                           FROM (public.agent_runs child
                             JOIN run_tree rt_1 ON ((child.parent_agent_run_id = rt_1.agent_run_id)))
                        )
                 SELECT rt.agent_run_id
                   FROM run_tree rt) tree_nodes
             JOIN public.llm_request_costs c ON ((c.agent_run_id = tree_nodes.agent_run_id)))) tree ON (true));


--
-- Name: VIEW agent_run_budget_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.agent_run_budget_status IS 'Per-agent-run budget status. own_spent_usd = direct LLM costs, tree_spent_usd = recursive subtree costs (including self). remaining_usd = budget - tree_spent.';


--
-- Name: grading_edges; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.grading_edges (
    id integer NOT NULL,
    critique_run_id uuid NOT NULL,
    critique_issue_id character varying NOT NULL,
    snapshot_slug character varying NOT NULL,
    tp_id character varying,
    tp_occurrence_id character varying,
    fp_id character varying,
    fp_occurrence_id character varying,
    credit double precision NOT NULL,
    rationale text NOT NULL,
    grader_run_id uuid NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT credit_range_edge CHECK (((credit >= (0.0)::double precision) AND (credit <= (1.0)::double precision))),
    CONSTRAINT exactly_one_target_edge CHECK ((((tp_id IS NOT NULL) AND (tp_occurrence_id IS NOT NULL) AND (fp_id IS NULL) AND (fp_occurrence_id IS NULL)) OR ((fp_id IS NOT NULL) AND (fp_occurrence_id IS NOT NULL) AND (tp_id IS NULL) AND (tp_occurrence_id IS NULL))))
);


--
-- Name: TABLE grading_edges; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.grading_edges IS 'Bipartite graph edges from critique issues to GT occurrences. Each edge = grader judgment on whether a critique matches a GT occurrence. Exactly one of TP or FP target set. Credit 0.0-1.0 for TPs, 0.0 for FPs. Drift = missing edges (see grading_pending view).';


--
-- Name: reported_issue_occurrences; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE reported_issue_occurrences; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.reported_issue_occurrences IS 'Locations where a reported issue occurs. Each occurrence has file path and line range. RLS: Same as reported_issues (scoped by agent_run_id).';


--
-- Name: COLUMN reported_issue_occurrences.agent_run_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.reported_issue_occurrences.agent_run_id IS 'FK to agent_runs (denormalized from reported_issues for RLS efficiency)';


--
-- Name: COLUMN reported_issue_occurrences.locations; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.reported_issue_occurrences.locations IS '1+ location anchors: {file, start_line?, end_line?}';


--
-- Name: reported_issues; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reported_issues (
    agent_run_id uuid NOT NULL,
    issue_id character varying NOT NULL,
    rationale text NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT issue_id_format CHECK ((((issue_id)::text ~ '^[a-z0-9_-]+$'::text) AND (length((issue_id)::text) >= 5) AND (length((issue_id)::text) <= 40)))
);


--
-- Name: TABLE reported_issues; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.reported_issues IS 'Issues reported by critic agents. Each issue has a rationale and one or more occurrences. RLS: Critic sees own run only. Grader sees graded run only. Optimizer sees TRAIN runs.';


--
-- Name: COLUMN reported_issues.agent_run_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.reported_issues.agent_run_id IS 'FK to agent_runs - identifies which agent run reported this issue';


--
-- Name: grading_pending; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.grading_pending AS
 WITH critique_issues AS (
         SELECT ri.agent_run_id AS critique_run_id,
            ri.issue_id AS critique_issue_id,
            ((ar.type_config -> 'example'::text) ->> 'snapshot_slug'::text) AS snapshot_slug,
            array_agg(DISTINCT (loc.value ->> 'file'::text)) FILTER (WHERE ((loc.value ->> 'file'::text) IS NOT NULL)) AS reported_files
           FROM (((public.reported_issues ri
             JOIN public.agent_runs ar ON ((ar.agent_run_id = ri.agent_run_id)))
             LEFT JOIN public.reported_issue_occurrences rio ON (((rio.agent_run_id = ri.agent_run_id) AND ((rio.reported_issue_id)::text = (ri.issue_id)::text))))
             LEFT JOIN LATERAL jsonb_array_elements(rio.locations) loc(value) ON (true))
          WHERE ((ar.type_config ->> 'agent_type'::text) = 'critic'::text)
          GROUP BY ri.agent_run_id, ri.issue_id, ar.type_config
        )
 SELECT ci.critique_run_id,
    ci.critique_issue_id,
    ci.snapshot_slug,
    mo.tp_id,
    mo.tp_occurrence_id,
    NULL::character varying AS fp_id,
    NULL::character varying AS fp_occurrence_id
   FROM (critique_issues ci
     CROSS JOIN LATERAL public.matchable_occurrences((ci.snapshot_slug)::character varying, (ci.reported_files)::character varying[]) mo(tp_id, tp_occurrence_id, fp_id, fp_occurrence_id))
  WHERE ((mo.tp_id IS NOT NULL) AND (NOT (EXISTS ( SELECT 1
           FROM public.grading_edges ge
          WHERE ((ge.critique_run_id = ci.critique_run_id) AND ((ge.critique_issue_id)::text = (ci.critique_issue_id)::text) AND ((ge.tp_id)::text = (mo.tp_id)::text) AND ((ge.tp_occurrence_id)::text = (mo.tp_occurrence_id)::text))))))
UNION ALL
 SELECT ci.critique_run_id,
    ci.critique_issue_id,
    ci.snapshot_slug,
    NULL::character varying AS tp_id,
    NULL::character varying AS tp_occurrence_id,
    mo.fp_id,
    mo.fp_occurrence_id
   FROM (critique_issues ci
     CROSS JOIN LATERAL public.matchable_occurrences((ci.snapshot_slug)::character varying, (ci.reported_files)::character varying[]) mo(tp_id, tp_occurrence_id, fp_id, fp_occurrence_id))
  WHERE ((mo.fp_id IS NOT NULL) AND (NOT (EXISTS ( SELECT 1
           FROM public.grading_edges ge
          WHERE ((ge.critique_run_id = ci.critique_run_id) AND ((ge.critique_issue_id)::text = (ci.critique_issue_id)::text) AND ((ge.fp_id)::text = (mo.fp_id)::text) AND ((ge.fp_occurrence_id)::text = (mo.fp_occurrence_id)::text))))));


--
-- Name: VIEW grading_pending; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.grading_pending IS 'Missing grading edges (drift detection). Includes all critic runs with
reported issues (including in_progress — grading can start before critic exits).
When this view returns no rows for a run, grading is complete for that run.
recall_by_run.missing_grading_edges is derived from this view.';


--
-- Name: issue_cluster_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.issue_cluster_members (
    snapshot_slug character varying NOT NULL,
    cluster_id character varying NOT NULL,
    critique_run_id uuid NOT NULL,
    critique_issue_id character varying NOT NULL,
    rationale text NOT NULL,
    grader_run_id uuid NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE issue_cluster_members; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.issue_cluster_members IS 'Membership of critique issues in clusters. Each issue belongs to at most one cluster.';


--
-- Name: clustering_pending; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.clustering_pending AS
 SELECT ri.agent_run_id AS critique_run_id,
    ri.issue_id AS critique_issue_id,
    ((ar.type_config -> 'example'::text) ->> 'snapshot_slug'::text) AS snapshot_slug
   FROM (public.reported_issues ri
     JOIN public.agent_runs ar ON ((ar.agent_run_id = ri.agent_run_id)))
  WHERE (((ar.type_config ->> 'agent_type'::text) = 'critic'::text) AND (NOT (EXISTS ( SELECT 1
           FROM public.grading_pending gp
          WHERE ((gp.critique_run_id = ri.agent_run_id) AND ((gp.critique_issue_id)::text = (ri.issue_id)::text))))) AND (NOT (EXISTS ( SELECT 1
           FROM public.grading_edges ge
          WHERE ((ge.critique_run_id = ri.agent_run_id) AND ((ge.critique_issue_id)::text = (ri.issue_id)::text) AND (ge.credit > (0)::double precision))))) AND (NOT (EXISTS ( SELECT 1
           FROM public.issue_cluster_members icm
          WHERE ((icm.critique_run_id = ri.agent_run_id) AND ((icm.critique_issue_id)::text = (ri.issue_id)::text))))));


--
-- Name: VIEW clustering_pending; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.clustering_pending IS 'Critique issues fully graded with no positive match and not yet clustered. When empty for a snapshot, all unmatched issues have been assigned to clusters.';


--
-- Name: critic_scopes_expected_to_recall; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.critic_scopes_expected_to_recall (
    snapshot_slug character varying NOT NULL,
    tp_id character varying NOT NULL,
    occurrence_id character varying NOT NULL,
    files_hash character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE critic_scopes_expected_to_recall; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.critic_scopes_expected_to_recall IS 'M:N linking TP occurrences to file_sets defining EXPECTED recall scopes. Determines recall DENOMINATOR only - critics CAN find issues outside expected scopes. Each occurrence may have multiple alternative scopes (OR logic: any one suffices). Distinct from match_file_restriction which is a HARD constraint on grader credit.';


--
-- Name: file_sets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.file_sets (
    snapshot_slug character varying NOT NULL,
    files_hash character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE file_sets; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.file_sets IS 'Content-addressable file sets for training examples. PK is (snapshot_slug, files_hash) where files_hash = MD5 of sorted file paths. Deduplicated by PK constraint - same files always produce same hash.';


--
-- Name: snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.snapshots (
    slug character varying NOT NULL,
    split public.split_enum NOT NULL,
    content bytea,
    source jsonb,
    bundle jsonb,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: COLUMN snapshots.content; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.snapshots.content IS 'tar archive of source code';


--
-- Name: COLUMN snapshots.source; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.snapshots.source IS 'provenance';


--
-- Name: true_positive_occurrences; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.true_positive_occurrences (
    snapshot_slug character varying NOT NULL,
    tp_id character varying NOT NULL,
    occurrence_id character varying NOT NULL,
    note text,
    match_file_restriction text,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE true_positive_occurrences; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.true_positive_occurrences IS 'Individual occurrences of true positive issues. Ranges stored in tp_occurrence_ranges.';


--
-- Name: true_positives; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.true_positives (
    snapshot_slug character varying NOT NULL,
    tp_id character varying NOT NULL,
    rationale text NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT tp_id_format CHECK ((((tp_id)::text ~ '^[a-z0-9_-]+$'::text) AND (length((tp_id)::text) >= 5) AND (length((tp_id)::text) <= 40)))
);


--
-- Name: TABLE true_positives; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.true_positives IS 'Ground truth issues that SHOULD be found by critics. Each TP has occurrences in true_positive_occurrences.';


--
-- Name: examples; Type: MATERIALIZED VIEW; Schema: public; Owner: -
--

CREATE MATERIALIZED VIEW public.examples AS
 SELECT s.slug AS snapshot_slug,
    'whole_snapshot'::public.example_kind_enum AS example_kind,
    NULL::text AS files_hash,
    (COALESCE(( SELECT count(DISTINCT ROW(tpo.tp_id, tpo.occurrence_id)) AS count
           FROM (public.true_positive_occurrences tpo
             JOIN public.true_positives t ON ((((tpo.snapshot_slug)::text = (t.snapshot_slug)::text) AND ((tpo.tp_id)::text = (t.tp_id)::text))))
          WHERE ((t.snapshot_slug)::text = (s.slug)::text)), (0)::bigint))::integer AS recall_denominator
   FROM public.snapshots s
UNION ALL
 SELECT fs.snapshot_slug,
    'file_set'::public.example_kind_enum AS example_kind,
    fs.files_hash,
    (COALESCE(( SELECT count(DISTINCT ROW(tpo.tp_id, tpo.occurrence_id)) AS count
           FROM (public.true_positive_occurrences tpo
             JOIN public.true_positives t ON ((((tpo.snapshot_slug)::text = (t.snapshot_slug)::text) AND ((tpo.tp_id)::text = (t.tp_id)::text))))
          WHERE (((t.snapshot_slug)::text = (fs.snapshot_slug)::text) AND public.is_tp_in_expected_recall_scope((fs.snapshot_slug)::text, (t.tp_id)::text, (tpo.occurrence_id)::text, 'file_set'::public.example_kind_enum, (fs.files_hash)::text))), (0)::bigint))::integer AS recall_denominator
   FROM public.file_sets fs
  WITH NO DATA;


--
-- Name: false_positive_occurrences; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.false_positive_occurrences (
    snapshot_slug character varying NOT NULL,
    fp_id character varying NOT NULL,
    occurrence_id character varying NOT NULL,
    note text,
    match_file_restriction text,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE false_positive_occurrences; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.false_positive_occurrences IS 'Individual occurrences of false positive patterns. Ranges stored in fp_occurrence_ranges.';


--
-- Name: false_positives; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.false_positives (
    snapshot_slug character varying NOT NULL,
    fp_id character varying NOT NULL,
    rationale text NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT fp_id_format CHECK ((((fp_id)::text ~ '^[a-z0-9_-]+$'::text) AND (length((fp_id)::text) >= 5) AND (length((fp_id)::text) <= 40)))
);


--
-- Name: TABLE false_positives; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.false_positives IS 'Patterns the labeler considers acceptable - teaches agents what NOT to flag.';


--
-- Name: file_set_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.file_set_members (
    snapshot_slug character varying NOT NULL,
    files_hash character varying NOT NULL,
    file_path character varying NOT NULL
);


--
-- Name: TABLE file_set_members; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.file_set_members IS 'Files belonging to each file set. FK to snapshot_files validates file paths exist in snapshot.';


--
-- Name: fp_occurrence_relevant_files; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fp_occurrence_relevant_files (
    snapshot_slug character varying NOT NULL,
    fp_id character varying NOT NULL,
    occurrence_id character varying NOT NULL,
    file_path character varying NOT NULL
);


--
-- Name: TABLE fp_occurrence_relevant_files; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.fp_occurrence_relevant_files IS 'Files that make false positive occurrences relevant (normalized from relevant_files JSONB)';


--
-- Name: grading_edge_credit_sums; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.grading_edge_credit_sums AS
 SELECT critique_run_id,
    tp_id,
    tp_occurrence_id,
    fp_id,
    fp_occurrence_id,
    sum(credit) AS total_credit
   FROM public.grading_edges
  GROUP BY critique_run_id, tp_id, tp_occurrence_id, fp_id, fp_occurrence_id;


--
-- Name: grading_edges_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.grading_edges_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: grading_edges_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.grading_edges_id_seq OWNED BY public.grading_edges.id;


--
-- Name: issue_clusters; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.issue_clusters (
    snapshot_slug character varying NOT NULL,
    cluster_id character varying NOT NULL,
    rationale text NOT NULL,
    grader_run_id uuid NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE issue_clusters; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.issue_clusters IS 'Clusters of unmatched critique issues reporting the same novel finding.';


--
-- Name: llm_requests_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.llm_requests_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: llm_requests_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.llm_requests_id_seq OWNED BY public.llm_requests.id;


--
-- Name: llm_run_costs; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.llm_run_costs AS
 SELECT agent_run_id,
    model,
    sum(input_tokens) AS input_tokens,
    sum(cached_input_tokens) AS cached_input_tokens,
    sum(output_tokens) AS output_tokens,
    sum(cost_usd) AS cost_usd,
    count(*) AS request_count
   FROM public.llm_request_costs
  GROUP BY agent_run_id, model;


--
-- Name: occurrence_ranges; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.occurrence_ranges (
    id integer NOT NULL,
    snapshot_slug character varying NOT NULL,
    tp_id character varying,
    fp_id character varying,
    occurrence_id character varying NOT NULL,
    file_path character varying NOT NULL,
    range_id integer NOT NULL,
    start_line integer,
    end_line integer,
    note text,
    CONSTRAINT occurrence_range_end_gte_start CHECK ((((start_line IS NULL) AND (end_line IS NULL)) OR ((start_line IS NOT NULL) AND ((end_line IS NULL) OR (end_line >= start_line))))),
    CONSTRAINT occurrence_range_exclusive_arc CHECK (((tp_id IS NULL) <> (fp_id IS NULL))),
    CONSTRAINT occurrence_range_start_line_positive CHECK (((start_line IS NULL) OR (start_line >= 1)))
);


--
-- Name: TABLE occurrence_ranges; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.occurrence_ranges IS 'Line ranges within TP/FP occurrences (normalized from files JSONB). Exactly one of tp_id or fp_id must be set (exclusive arc pattern).';


--
-- Name: COLUMN occurrence_ranges.range_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.occurrence_ranges.range_id IS '0-based index within file';


--
-- Name: occurrence_ranges_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.occurrence_ranges_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: occurrence_ranges_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.occurrence_ranges_id_seq OWNED BY public.occurrence_ranges.id;


--
-- Name: tp_occurrence_credits; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.tp_occurrence_credits AS
SELECT
    NULL::text AS snapshot_slug,
    NULL::public.split_enum AS split,
    NULL::public.example_kind_enum AS example_kind,
    NULL::text AS files_hash,
    NULL::character varying AS tp_id,
    NULL::character varying AS occurrence_id,
    NULL::uuid AS critic_run_id,
    NULL::text AS critic_image_digest,
    NULL::text AS critic_model,
    NULL::double precision AS found_credit;


--
-- Name: occurrence_statistics; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.occurrence_statistics AS
 SELECT snapshot_slug,
    split,
    example_kind,
    files_hash,
    tp_id,
    occurrence_id,
    critic_image_digest,
    critic_model,
    public.compute_stats_with_ci(array_agg(found_credit)) AS credit_stats
   FROM public.tp_occurrence_credits
  GROUP BY snapshot_slug, split, example_kind, files_hash, tp_id, occurrence_id, critic_image_digest, critic_model;


--
-- Name: recall_by_run; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.recall_by_run AS
 WITH per_run AS (
         SELECT ((cr.type_config -> 'example'::text) ->> 'snapshot_slug'::text) AS snapshot_slug,
            e.example_kind,
            e.files_hash,
            s.split,
            e.recall_denominator,
            cr.agent_run_id AS critic_run_id,
            cr.image_digest AS critic_image_digest,
            cr.model AS critic_model,
            cr.status AS critic_status,
            COALESCE(( SELECT sum(toc.found_credit) AS sum
                   FROM public.tp_occurrence_credits toc
                  WHERE (toc.critic_run_id = cr.agent_run_id)), (0.0)::double precision) AS total_credit,
            ( SELECT count(*) AS count
                   FROM public.grading_pending gp
                  WHERE (gp.critique_run_id = cr.agent_run_id)) AS missing_grading_edges
           FROM ((public.agent_runs cr
             JOIN public.examples e ON (((((cr.type_config -> 'example'::text) ->> 'snapshot_slug'::text) = (e.snapshot_slug)::text) AND ((((cr.type_config -> 'example'::text) ->> 'kind'::text))::public.example_kind_enum = e.example_kind) AND (COALESCE(((cr.type_config -> 'example'::text) ->> 'files_hash'::text), ''::text) = COALESCE(e.files_hash, ''::text)))))
             JOIN public.snapshots s ON ((((cr.type_config -> 'example'::text) ->> 'snapshot_slug'::text) = (s.slug)::text)))
          WHERE ((cr.type_config ->> 'agent_type'::text) = 'critic'::text)
        )
 SELECT snapshot_slug,
    example_kind,
    files_hash,
    split,
    recall_denominator,
    critic_run_id,
    critic_image_digest,
    critic_model,
    critic_status,
    total_credit,
        CASE
            WHEN (recall_denominator > 0) THEN (total_credit / (recall_denominator)::double precision)
            ELSE (0.0)::double precision
        END AS recall,
    missing_grading_edges
   FROM per_run;


--
-- Name: recall_by_definition_example; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.recall_by_definition_example AS
 WITH raw_stats AS (
         SELECT rbr.critic_image_digest,
            rbr.critic_model,
            rbr.snapshot_slug,
            rbr.example_kind,
            rbr.files_hash,
            rbr.split,
            max(rbr.recall_denominator) AS recall_denominator,
            (count(*))::integer AS n_runs,
            public.agg_status_counts(array_agg(rbr.critic_status)) AS status_counts,
            public.compute_stats_with_ci(array_agg(rbr.total_credit)) AS credit_stats
           FROM public.recall_by_run rbr
          GROUP BY rbr.critic_image_digest, rbr.critic_model, rbr.snapshot_slug, rbr.example_kind, rbr.files_hash, rbr.split
        )
 SELECT critic_image_digest,
    critic_model,
    snapshot_slug,
    example_kind,
    files_hash,
    split,
    recall_denominator,
    n_runs,
    status_counts,
    credit_stats,
    public.scale_stats(credit_stats, (recall_denominator)::double precision) AS recall_stats
   FROM raw_stats;


--
-- Name: pareto_frontier_by_example; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.pareto_frontier_by_example AS
 WITH best_scores AS (
         SELECT recall_by_definition_example.snapshot_slug,
            recall_by_definition_example.example_kind,
            recall_by_definition_example.files_hash,
            recall_by_definition_example.split,
            max(recall_by_definition_example.recall_denominator) AS recall_denominator,
            recall_by_definition_example.critic_model,
            max(COALESCE((recall_by_definition_example.credit_stats).mean, (0.0)::double precision)) AS best_mean_credit
           FROM public.recall_by_definition_example
          GROUP BY recall_by_definition_example.snapshot_slug, recall_by_definition_example.example_kind, recall_by_definition_example.files_hash, recall_by_definition_example.split, recall_by_definition_example.critic_model
        ), ranked AS (
         SELECT rbde.critic_image_digest,
            rbde.critic_model,
            rbde.snapshot_slug,
            rbde.example_kind,
            rbde.files_hash,
            rbde.split,
            rbde.recall_denominator,
            rbde.n_runs,
            rbde.status_counts,
            rbde.credit_stats,
            rbde.recall_stats,
            (rbde.credit_stats).mean AS mean_credit,
            bs.best_mean_credit
           FROM (public.recall_by_definition_example rbde
             JOIN best_scores bs USING (snapshot_slug, example_kind, files_hash, split, critic_model))
          WHERE (COALESCE((rbde.credit_stats).mean, (0.0)::double precision) = bs.best_mean_credit)
        )
 SELECT snapshot_slug,
    example_kind,
    files_hash,
    split,
    max(recall_denominator) AS recall_denominator,
    critic_model,
    jsonb_agg(DISTINCT jsonb_build_object('image_digest', critic_image_digest, 'credit_stats', credit_stats, 'n_runs', n_runs)) AS winning_definitions,
    best_mean_credit
   FROM ranked
  GROUP BY snapshot_slug, example_kind, files_hash, split, critic_model, best_mean_credit;


--
-- Name: recall_by_definition_split_kind; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.recall_by_definition_split_kind AS
 WITH example_counts AS (
         SELECT per_example.split,
            per_example.example_kind,
            per_example.critic_image_digest,
            per_example.critic_model,
            (count(*))::integer AS n_examples,
            (sum(per_example.recall_denominator))::integer AS recall_denominator
           FROM ( SELECT DISTINCT recall_by_definition_example.split,
                    recall_by_definition_example.example_kind,
                    recall_by_definition_example.files_hash,
                    recall_by_definition_example.recall_denominator,
                    recall_by_definition_example.critic_image_digest,
                    recall_by_definition_example.critic_model
                   FROM public.recall_by_definition_example) per_example
          GROUP BY per_example.split, per_example.example_kind, per_example.critic_image_digest, per_example.critic_model
        ), run_stats AS (
         SELECT recall_by_definition_example.split,
            recall_by_definition_example.example_kind,
            recall_by_definition_example.critic_image_digest,
            recall_by_definition_example.critic_model,
            (count(*))::integer AS n_runs,
            public.agg_status_counts(array_agg(recall_by_definition_example.status_counts)) AS status_counts,
            public.compute_stats_with_ci(array_agg(COALESCE((recall_by_definition_example.credit_stats).mean, (0.0)::double precision))) AS credit_stats,
            (count(*) FILTER (WHERE (COALESCE((recall_by_definition_example.credit_stats).mean, (0.0)::double precision) = (0.0)::double precision)))::integer AS zero_count
           FROM public.recall_by_definition_example
          GROUP BY recall_by_definition_example.split, recall_by_definition_example.example_kind, recall_by_definition_example.critic_image_digest, recall_by_definition_example.critic_model
        )
 SELECT rs.split,
    rs.example_kind,
    rs.critic_image_digest,
    rs.critic_model,
    ec.n_examples,
    rs.n_runs,
    ec.recall_denominator,
    rs.status_counts,
    rs.credit_stats,
    public.scale_stats(rs.credit_stats, (ec.recall_denominator)::double precision) AS recall_stats,
    rs.zero_count
   FROM (run_stats rs
     JOIN example_counts ec USING (split, example_kind, critic_image_digest, critic_model));


--
-- Name: recall_by_example; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.recall_by_example AS
 WITH raw_stats AS (
         SELECT rbde.snapshot_slug,
            rbde.example_kind,
            rbde.files_hash,
            rbde.split,
            max(rbde.recall_denominator) AS recall_denominator,
            rbde.critic_model,
            (sum(rbde.n_runs))::integer AS n_runs,
            public.agg_status_counts(array_agg(rbde.status_counts)) AS status_counts,
            public.compute_stats_with_ci(array_agg(COALESCE((rbde.credit_stats).mean, (0.0)::double precision))) AS credit_stats
           FROM public.recall_by_definition_example rbde
          GROUP BY rbde.snapshot_slug, rbde.example_kind, rbde.files_hash, rbde.split, rbde.critic_model
        )
 SELECT snapshot_slug,
    example_kind,
    files_hash,
    split,
    recall_denominator,
    critic_model,
    n_runs,
    status_counts,
    credit_stats,
    public.scale_stats(credit_stats, (recall_denominator)::double precision) AS recall_stats
   FROM raw_stats;


--
-- Name: reported_issue_occurrences_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.reported_issue_occurrences_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reported_issue_occurrences_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.reported_issue_occurrences_id_seq OWNED BY public.reported_issue_occurrences.id;


--
-- Name: snapshot_files; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.snapshot_files (
    snapshot_slug character varying NOT NULL,
    file_path character varying NOT NULL,
    line_count integer NOT NULL
);


--
-- Name: TABLE snapshot_files; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.snapshot_files IS 'All files in each snapshot. Used for FK validation of file paths in occurrences and trigger sets.';


--
-- Name: COLUMN snapshot_files.file_path; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.snapshot_files.file_path IS 'Path relative to snapshot root (e.g., "src/utils.py"). NOT absolute paths.';


--
-- Name: validation_recall_by_definition; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.validation_recall_by_definition AS
 SELECT critic_image_digest,
    critic_model,
    public.compute_stats_with_ci(array_agg((total_credit / (NULLIF(n_occurrences, 0))::double precision))) AS recall_stats
   FROM public.get_validation_full_snapshot_aggregates() get_validation_full_snapshot_aggregates(snapshot_slug, critic_image_digest, critic_model, critic_run_id, status, total_credit, n_occurrences)
  GROUP BY critic_image_digest, critic_model;


--
-- Name: grading_edges id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grading_edges ALTER COLUMN id SET DEFAULT nextval('public.grading_edges_id_seq'::regclass);


--
-- Name: llm_requests id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_requests ALTER COLUMN id SET DEFAULT nextval('public.llm_requests_id_seq'::regclass);


--
-- Name: occurrence_ranges id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.occurrence_ranges ALTER COLUMN id SET DEFAULT nextval('public.occurrence_ranges_id_seq'::regclass);


--
-- Name: reported_issue_occurrences id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reported_issue_occurrences ALTER COLUMN id SET DEFAULT nextval('public.reported_issue_occurrences_id_seq'::regclass);


--
-- Name: agent_definitions agent_definitions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_definitions
    ADD CONSTRAINT agent_definitions_pkey PRIMARY KEY (digest);


--
-- Name: agent_role_salt agent_role_salt_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_role_salt
    ADD CONSTRAINT agent_role_salt_pkey PRIMARY KEY (id);


--
-- Name: agent_runs agent_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_pkey PRIMARY KEY (agent_run_id);


--
-- Name: critic_scopes_expected_to_recall critic_scopes_expected_to_recall_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.critic_scopes_expected_to_recall
    ADD CONSTRAINT critic_scopes_expected_to_recall_pkey PRIMARY KEY (snapshot_slug, tp_id, occurrence_id, files_hash);


--
-- Name: false_positive_occurrences false_positive_occurrences_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.false_positive_occurrences
    ADD CONSTRAINT false_positive_occurrences_pkey PRIMARY KEY (snapshot_slug, fp_id, occurrence_id);


--
-- Name: false_positives false_positives_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.false_positives
    ADD CONSTRAINT false_positives_pkey PRIMARY KEY (snapshot_slug, fp_id);


--
-- Name: file_set_members file_set_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.file_set_members
    ADD CONSTRAINT file_set_members_pkey PRIMARY KEY (snapshot_slug, files_hash, file_path);


--
-- Name: file_sets file_sets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.file_sets
    ADD CONSTRAINT file_sets_pkey PRIMARY KEY (snapshot_slug, files_hash);


--
-- Name: fp_occurrence_relevant_files fp_occurrence_relevant_files_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fp_occurrence_relevant_files
    ADD CONSTRAINT fp_occurrence_relevant_files_pkey PRIMARY KEY (snapshot_slug, fp_id, occurrence_id, file_path);


--
-- Name: grading_edges grading_edges_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grading_edges
    ADD CONSTRAINT grading_edges_pkey PRIMARY KEY (id);


--
-- Name: issue_cluster_members issue_cluster_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issue_cluster_members
    ADD CONSTRAINT issue_cluster_members_pkey PRIMARY KEY (snapshot_slug, cluster_id, critique_run_id, critique_issue_id);


--
-- Name: issue_clusters issue_clusters_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issue_clusters
    ADD CONSTRAINT issue_clusters_pkey PRIMARY KEY (snapshot_slug, cluster_id);


--
-- Name: llm_requests llm_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_requests
    ADD CONSTRAINT llm_requests_pkey PRIMARY KEY (id);


--
-- Name: model_metadata model_metadata_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_metadata
    ADD CONSTRAINT model_metadata_pkey PRIMARY KEY (model_id);


--
-- Name: occurrence_ranges occurrence_ranges_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.occurrence_ranges
    ADD CONSTRAINT occurrence_ranges_pkey PRIMARY KEY (id);


--
-- Name: reported_issue_occurrences reported_issue_occurrences_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reported_issue_occurrences
    ADD CONSTRAINT reported_issue_occurrences_pkey PRIMARY KEY (id);


--
-- Name: reported_issues reported_issues_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reported_issues
    ADD CONSTRAINT reported_issues_pkey PRIMARY KEY (agent_run_id, issue_id);


--
-- Name: snapshot_files snapshot_files_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.snapshot_files
    ADD CONSTRAINT snapshot_files_pkey PRIMARY KEY (snapshot_slug, file_path);


--
-- Name: snapshots snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.snapshots
    ADD CONSTRAINT snapshots_pkey PRIMARY KEY (slug);


--
-- Name: true_positive_occurrences true_positive_occurrences_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.true_positive_occurrences
    ADD CONSTRAINT true_positive_occurrences_pkey PRIMARY KEY (snapshot_slug, tp_id, occurrence_id);


--
-- Name: true_positives true_positives_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.true_positives
    ADD CONSTRAINT true_positives_pkey PRIMARY KEY (snapshot_slug, tp_id);


--
-- Name: grading_edges uq_grading_edges_fp; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grading_edges
    ADD CONSTRAINT uq_grading_edges_fp UNIQUE (critique_run_id, critique_issue_id, fp_id, fp_occurrence_id);


--
-- Name: grading_edges uq_grading_edges_tp; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grading_edges
    ADD CONSTRAINT uq_grading_edges_tp UNIQUE (critique_run_id, critique_issue_id, tp_id, tp_occurrence_id);


--
-- Name: issue_cluster_members uq_issue_cluster_member_issue; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issue_cluster_members
    ADD CONSTRAINT uq_issue_cluster_member_issue UNIQUE (critique_run_id, critique_issue_id);


--
-- Name: occurrence_ranges uq_occurrence_ranges; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.occurrence_ranges
    ADD CONSTRAINT uq_occurrence_ranges UNIQUE (snapshot_slug, tp_id, fp_id, occurrence_id, file_path, range_id);


--
-- Name: idx_file_set_members_file_path; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_file_set_members_file_path ON public.file_set_members USING btree (snapshot_slug, file_path);


--
-- Name: ix_llm_requests_agent_run_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_requests_agent_run_created ON public.llm_requests USING btree (agent_run_id, created_at);


--
-- Name: ix_llm_requests_agent_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_requests_agent_run_id ON public.llm_requests USING btree (agent_run_id);


--
-- Name: ix_llm_requests_model; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_requests_model ON public.llm_requests USING btree (model);


--
-- Name: tp_occurrence_credits _RETURN; Type: RULE; Schema: public; Owner: -
--

CREATE OR REPLACE VIEW public.tp_occurrence_credits AS
 SELECT ((cr.type_config -> 'example'::text) ->> 'snapshot_slug'::text) AS snapshot_slug,
    s.split,
    ex.example_kind,
    ex.files_hash,
    tpo.tp_id,
    tpo.occurrence_id,
    cr.agent_run_id AS critic_run_id,
    cr.image_digest AS critic_image_digest,
    cr.model AS critic_model,
    COALESCE(sum(ge.credit), (0.0)::double precision) AS found_credit
   FROM ((((public.agent_runs cr
     JOIN public.snapshots s ON ((((cr.type_config -> 'example'::text) ->> 'snapshot_slug'::text) = (s.slug)::text)))
     JOIN public.examples ex ON (((((cr.type_config -> 'example'::text) ->> 'snapshot_slug'::text) = (ex.snapshot_slug)::text) AND ((((cr.type_config -> 'example'::text) ->> 'kind'::text))::public.example_kind_enum = ex.example_kind) AND (COALESCE(((cr.type_config -> 'example'::text) ->> 'files_hash'::text), ''::text) = COALESCE(ex.files_hash, ''::text)))))
     CROSS JOIN public.true_positive_occurrences tpo)
     LEFT JOIN public.grading_edges ge ON (((ge.critique_run_id = cr.agent_run_id) AND ((ge.snapshot_slug)::text = (tpo.snapshot_slug)::text) AND ((ge.tp_id)::text = (tpo.tp_id)::text) AND ((ge.tp_occurrence_id)::text = (tpo.occurrence_id)::text))))
  WHERE (((cr.type_config ->> 'agent_type'::text) = 'critic'::text) AND (((cr.type_config -> 'example'::text) ->> 'snapshot_slug'::text) = (tpo.snapshot_slug)::text) AND public.is_tp_in_expected_recall_scope((tpo.snapshot_slug)::text, (tpo.tp_id)::text, (tpo.occurrence_id)::text, ex.example_kind, ex.files_hash))
  GROUP BY cr.agent_run_id, s.split, ex.example_kind, ex.files_hash, tpo.snapshot_slug, tpo.tp_id, tpo.occurrence_id, cr.image_digest, cr.model;


--
-- Name: grading_edges enforce_edge_credit_sum; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER enforce_edge_credit_sum BEFORE INSERT OR UPDATE ON public.grading_edges FOR EACH ROW EXECUTE FUNCTION public.check_edge_credit_sum();


--
-- Name: grading_edges enforce_edge_filter_scope; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER enforce_edge_filter_scope BEFORE INSERT OR UPDATE ON public.grading_edges FOR EACH ROW EXECUTE FUNCTION public.check_edge_matches_filter_scope();


--
-- Name: issue_cluster_members trg_check_cluster_member_no_positive_edges; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_check_cluster_member_no_positive_edges BEFORE INSERT OR UPDATE ON public.issue_cluster_members FOR EACH ROW EXECUTE FUNCTION public.check_cluster_member_no_positive_edges();


--
-- Name: issue_cluster_members trg_check_cluster_not_empty; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER trg_check_cluster_not_empty AFTER DELETE ON public.issue_cluster_members DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.check_cluster_not_empty();


--
-- Name: grading_edges trg_check_positive_edge_not_clustered; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_check_positive_edge_not_clustered BEFORE INSERT OR UPDATE ON public.grading_edges FOR EACH ROW EXECUTE FUNCTION public.check_positive_edge_not_clustered();


--
-- Name: false_positive_occurrences trg_notify_false_positive_occurrences_changed; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_notify_false_positive_occurrences_changed AFTER INSERT OR DELETE ON public.false_positive_occurrences FOR EACH ROW EXECUTE FUNCTION public.notify_gt_changed();


--
-- Name: false_positives trg_notify_false_positives_changed; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_notify_false_positives_changed AFTER INSERT OR DELETE ON public.false_positives FOR EACH ROW EXECUTE FUNCTION public.notify_gt_changed();


--
-- Name: reported_issue_occurrences trg_notify_reported_issue_occurrences_changed; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_notify_reported_issue_occurrences_changed AFTER INSERT ON public.reported_issue_occurrences FOR EACH ROW EXECUTE FUNCTION public.notify_critique_changed();


--
-- Name: reported_issues trg_notify_reported_issues_changed; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_notify_reported_issues_changed AFTER INSERT ON public.reported_issues FOR EACH ROW EXECUTE FUNCTION public.notify_critique_changed();


--
-- Name: snapshots trg_notify_snapshot_created; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_notify_snapshot_created AFTER INSERT ON public.snapshots FOR EACH ROW EXECUTE FUNCTION public.notify_snapshot_created();


--
-- Name: true_positive_occurrences trg_notify_true_positive_occurrences_changed; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_notify_true_positive_occurrences_changed AFTER INSERT OR DELETE ON public.true_positive_occurrences FOR EACH ROW EXECUTE FUNCTION public.notify_gt_changed();


--
-- Name: true_positives trg_notify_true_positives_changed; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_notify_true_positives_changed AFTER INSERT OR DELETE ON public.true_positives FOR EACH ROW EXECUTE FUNCTION public.notify_gt_changed();


--
-- Name: occurrence_ranges validate_occurrence_range_bounds; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER validate_occurrence_range_bounds BEFORE INSERT OR UPDATE ON public.occurrence_ranges FOR EACH ROW EXECUTE FUNCTION public.validate_range_line_numbers();


--
-- Name: reported_issue_occurrences validate_reported_issue_occ_basic_line_numbers_trigger; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER validate_reported_issue_occ_basic_line_numbers_trigger BEFORE INSERT OR UPDATE ON public.reported_issue_occurrences FOR EACH ROW EXECUTE FUNCTION public.validate_reported_issue_occ_basic_line_numbers();


--
-- Name: agent_runs agent_runs_image_digest_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_image_digest_fkey FOREIGN KEY (image_digest) REFERENCES public.agent_definitions(digest) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: agent_runs agent_runs_parent_agent_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_parent_agent_run_id_fkey FOREIGN KEY (parent_agent_run_id) REFERENCES public.agent_runs(agent_run_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: critic_scopes_expected_to_recall critic_scopes_expected_to_rec_snapshot_slug_tp_id_occurren_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.critic_scopes_expected_to_recall
    ADD CONSTRAINT critic_scopes_expected_to_rec_snapshot_slug_tp_id_occurren_fkey FOREIGN KEY (snapshot_slug, tp_id, occurrence_id) REFERENCES public.true_positive_occurrences(snapshot_slug, tp_id, occurrence_id) ON DELETE CASCADE;


--
-- Name: critic_scopes_expected_to_recall critic_scopes_expected_to_recall_snapshot_slug_files_hash_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.critic_scopes_expected_to_recall
    ADD CONSTRAINT critic_scopes_expected_to_recall_snapshot_slug_files_hash_fkey FOREIGN KEY (snapshot_slug, files_hash) REFERENCES public.file_sets(snapshot_slug, files_hash) ON DELETE CASCADE;


--
-- Name: false_positive_occurrences false_positive_occurrences_snapshot_slug_fp_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.false_positive_occurrences
    ADD CONSTRAINT false_positive_occurrences_snapshot_slug_fp_id_fkey FOREIGN KEY (snapshot_slug, fp_id) REFERENCES public.false_positives(snapshot_slug, fp_id) ON DELETE CASCADE;


--
-- Name: false_positives false_positives_snapshot_slug_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.false_positives
    ADD CONSTRAINT false_positives_snapshot_slug_fkey FOREIGN KEY (snapshot_slug) REFERENCES public.snapshots(slug) ON DELETE CASCADE;


--
-- Name: file_set_members file_set_members_snapshot_slug_file_path_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.file_set_members
    ADD CONSTRAINT file_set_members_snapshot_slug_file_path_fkey FOREIGN KEY (snapshot_slug, file_path) REFERENCES public.snapshot_files(snapshot_slug, file_path) ON DELETE CASCADE;


--
-- Name: file_set_members file_set_members_snapshot_slug_files_hash_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.file_set_members
    ADD CONSTRAINT file_set_members_snapshot_slug_files_hash_fkey FOREIGN KEY (snapshot_slug, files_hash) REFERENCES public.file_sets(snapshot_slug, files_hash) ON DELETE CASCADE;


--
-- Name: file_sets file_sets_snapshot_slug_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.file_sets
    ADD CONSTRAINT file_sets_snapshot_slug_fkey FOREIGN KEY (snapshot_slug) REFERENCES public.snapshots(slug) ON DELETE RESTRICT;


--
-- Name: agent_definitions fk_agent_definitions_created_by; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_definitions
    ADD CONSTRAINT fk_agent_definitions_created_by FOREIGN KEY (created_by_agent_run_id) REFERENCES public.agent_runs(agent_run_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: false_positive_occurrences fk_fp_occ_matchable_files; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.false_positive_occurrences
    ADD CONSTRAINT fk_fp_occ_matchable_files FOREIGN KEY (snapshot_slug, match_file_restriction) REFERENCES public.file_sets(snapshot_slug, files_hash) ON DELETE RESTRICT;


--
-- Name: fp_occurrence_relevant_files fk_fp_relevant_file_snapshot_file; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fp_occurrence_relevant_files
    ADD CONSTRAINT fk_fp_relevant_file_snapshot_file FOREIGN KEY (snapshot_slug, file_path) REFERENCES public.snapshot_files(snapshot_slug, file_path) ON DELETE CASCADE;


--
-- Name: grading_edges fk_grading_edges_critique; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grading_edges
    ADD CONSTRAINT fk_grading_edges_critique FOREIGN KEY (critique_run_id, critique_issue_id) REFERENCES public.reported_issues(agent_run_id, issue_id) ON DELETE CASCADE;


--
-- Name: grading_edges fk_grading_edges_fp; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grading_edges
    ADD CONSTRAINT fk_grading_edges_fp FOREIGN KEY (snapshot_slug, fp_id, fp_occurrence_id) REFERENCES public.false_positive_occurrences(snapshot_slug, fp_id, occurrence_id) ON DELETE CASCADE;


--
-- Name: grading_edges fk_grading_edges_grader; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grading_edges
    ADD CONSTRAINT fk_grading_edges_grader FOREIGN KEY (grader_run_id) REFERENCES public.agent_runs(agent_run_id) ON DELETE CASCADE;


--
-- Name: grading_edges fk_grading_edges_tp; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grading_edges
    ADD CONSTRAINT fk_grading_edges_tp FOREIGN KEY (snapshot_slug, tp_id, tp_occurrence_id) REFERENCES public.true_positive_occurrences(snapshot_slug, tp_id, occurrence_id) ON DELETE CASCADE;


--
-- Name: llm_requests fk_llm_requests_agent_run_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_requests
    ADD CONSTRAINT fk_llm_requests_agent_run_id FOREIGN KEY (agent_run_id) REFERENCES public.agent_runs(agent_run_id) ON DELETE CASCADE;


--
-- Name: llm_requests fk_llm_requests_model; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_requests
    ADD CONSTRAINT fk_llm_requests_model FOREIGN KEY (model) REFERENCES public.model_metadata(model_id);


--
-- Name: occurrence_ranges fk_occurrence_range_fp; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.occurrence_ranges
    ADD CONSTRAINT fk_occurrence_range_fp FOREIGN KEY (snapshot_slug, fp_id, occurrence_id) REFERENCES public.false_positive_occurrences(snapshot_slug, fp_id, occurrence_id) ON DELETE CASCADE;


--
-- Name: occurrence_ranges fk_occurrence_range_snapshot_file; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.occurrence_ranges
    ADD CONSTRAINT fk_occurrence_range_snapshot_file FOREIGN KEY (snapshot_slug, file_path) REFERENCES public.snapshot_files(snapshot_slug, file_path) ON DELETE CASCADE;


--
-- Name: occurrence_ranges fk_occurrence_range_tp; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.occurrence_ranges
    ADD CONSTRAINT fk_occurrence_range_tp FOREIGN KEY (snapshot_slug, tp_id, occurrence_id) REFERENCES public.true_positive_occurrences(snapshot_slug, tp_id, occurrence_id) ON DELETE CASCADE;


--
-- Name: true_positive_occurrences fk_tp_occ_matchable_files; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.true_positive_occurrences
    ADD CONSTRAINT fk_tp_occ_matchable_files FOREIGN KEY (snapshot_slug, match_file_restriction) REFERENCES public.file_sets(snapshot_slug, files_hash) ON DELETE RESTRICT;


--
-- Name: fp_occurrence_relevant_files fp_occurrence_relevant_files_snapshot_slug_fp_id_occurrenc_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fp_occurrence_relevant_files
    ADD CONSTRAINT fp_occurrence_relevant_files_snapshot_slug_fp_id_occurrenc_fkey FOREIGN KEY (snapshot_slug, fp_id, occurrence_id) REFERENCES public.false_positive_occurrences(snapshot_slug, fp_id, occurrence_id) ON DELETE CASCADE;


--
-- Name: issue_cluster_members issue_cluster_members_critique_run_id_critique_issue_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issue_cluster_members
    ADD CONSTRAINT issue_cluster_members_critique_run_id_critique_issue_id_fkey FOREIGN KEY (critique_run_id, critique_issue_id) REFERENCES public.reported_issues(agent_run_id, issue_id) ON DELETE CASCADE;


--
-- Name: issue_cluster_members issue_cluster_members_grader_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issue_cluster_members
    ADD CONSTRAINT issue_cluster_members_grader_run_id_fkey FOREIGN KEY (grader_run_id) REFERENCES public.agent_runs(agent_run_id) ON DELETE CASCADE;


--
-- Name: issue_cluster_members issue_cluster_members_snapshot_slug_cluster_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issue_cluster_members
    ADD CONSTRAINT issue_cluster_members_snapshot_slug_cluster_id_fkey FOREIGN KEY (snapshot_slug, cluster_id) REFERENCES public.issue_clusters(snapshot_slug, cluster_id) ON DELETE CASCADE;


--
-- Name: issue_clusters issue_clusters_grader_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issue_clusters
    ADD CONSTRAINT issue_clusters_grader_run_id_fkey FOREIGN KEY (grader_run_id) REFERENCES public.agent_runs(agent_run_id) ON DELETE CASCADE;


--
-- Name: issue_clusters issue_clusters_snapshot_slug_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issue_clusters
    ADD CONSTRAINT issue_clusters_snapshot_slug_fkey FOREIGN KEY (snapshot_slug) REFERENCES public.snapshots(slug) ON DELETE CASCADE;


--
-- Name: reported_issue_occurrences reported_issue_occurrences_agent_run_id_reported_issue_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reported_issue_occurrences
    ADD CONSTRAINT reported_issue_occurrences_agent_run_id_reported_issue_id_fkey FOREIGN KEY (agent_run_id, reported_issue_id) REFERENCES public.reported_issues(agent_run_id, issue_id) ON DELETE CASCADE;


--
-- Name: reported_issues reported_issues_agent_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reported_issues
    ADD CONSTRAINT reported_issues_agent_run_id_fkey FOREIGN KEY (agent_run_id) REFERENCES public.agent_runs(agent_run_id) ON DELETE CASCADE;


--
-- Name: snapshot_files snapshot_files_snapshot_slug_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.snapshot_files
    ADD CONSTRAINT snapshot_files_snapshot_slug_fkey FOREIGN KEY (snapshot_slug) REFERENCES public.snapshots(slug) ON DELETE RESTRICT;


--
-- Name: true_positive_occurrences true_positive_occurrences_snapshot_slug_tp_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.true_positive_occurrences
    ADD CONSTRAINT true_positive_occurrences_snapshot_slug_tp_id_fkey FOREIGN KEY (snapshot_slug, tp_id) REFERENCES public.true_positives(snapshot_slug, tp_id) ON DELETE CASCADE;


--
-- Name: true_positives true_positives_snapshot_slug_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.true_positives
    ADD CONSTRAINT true_positives_snapshot_slug_fkey FOREIGN KEY (snapshot_slug) REFERENCES public.snapshots(slug) ON DELETE CASCADE;


--
-- Name: issue_cluster_members admin_all_cluster_members; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY admin_all_cluster_members ON public.issue_cluster_members USING (true) WITH CHECK (true);


--
-- Name: issue_clusters admin_all_clusters; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY admin_all_clusters ON public.issue_clusters USING (true) WITH CHECK (true);


--
-- Name: agent_definitions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.agent_definitions ENABLE ROW LEVEL SECURITY;

--
-- Name: agent_definitions agent_definitions_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY agent_definitions_insert ON public.agent_definitions FOR INSERT WITH CHECK ((public.current_agent_run_id() IS NULL));


--
-- Name: agent_definitions agent_definitions_select; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY agent_definitions_select ON public.agent_definitions FOR SELECT USING (true);


--
-- Name: agent_runs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.agent_runs ENABLE ROW LEVEL SECURITY;

--
-- Name: agent_runs agent_runs_agent_select; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY agent_runs_agent_select ON public.agent_runs FOR SELECT USING ((((public.current_agent_type() = 'critic_dev_optimize'::text) AND ((((type_config ->> 'agent_type'::text) = 'critic'::text) AND public.is_train_snapshot(((type_config -> 'example'::text) ->> 'snapshot_slug'::text))) OR (((type_config ->> 'agent_type'::text) = 'grader'::text) AND public.is_train_snapshot((type_config ->> 'snapshot_slug'::text))))) OR (agent_run_id = public.current_agent_run_id()) OR ((public.current_agent_type() = 'grader'::text) AND ((type_config ->> 'agent_type'::text) = 'critic'::text) AND (((type_config -> 'example'::text) ->> 'snapshot_slug'::text) = public.current_grader_snapshot_slug())) OR ((public.current_agent_type() = 'critic_dev_improve'::text) AND ((type_config ->> 'agent_type'::text) = ANY (ARRAY['critic'::text, 'grader'::text])) AND public.is_improvement_example_allowed(((type_config -> 'example'::text) ->> 'snapshot_slug'::text), (((type_config -> 'example'::text) ->> 'kind'::text))::public.example_kind_enum, ((type_config -> 'example'::text) ->> 'files_hash'::text)))));


--
-- Name: agent_runs agent_runs_select_descendants; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY agent_runs_select_descendants ON public.agent_runs FOR SELECT USING (public.is_agent_ancestor(public.current_agent_run_id(), agent_run_id));


--
-- Name: agent_runs agent_runs_select_own; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY agent_runs_select_own ON public.agent_runs FOR SELECT USING ((agent_run_id = public.current_agent_run_id()));


--
-- Name: critic_scopes_expected_to_recall; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.critic_scopes_expected_to_recall ENABLE ROW LEVEL SECURITY;

--
-- Name: critic_scopes_expected_to_recall critic_scopes_expected_to_recall_agent_select; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY critic_scopes_expected_to_recall_agent_select ON public.critic_scopes_expected_to_recall FOR SELECT USING (public.can_access_snapshot_ground_truth(snapshot_slug));


--
-- Name: agent_definitions evaluator_select_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY evaluator_select_all ON public.agent_definitions FOR SELECT TO evaluator USING (true);


--
-- Name: agent_runs evaluator_select_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY evaluator_select_all ON public.agent_runs FOR SELECT TO evaluator USING (true);


--
-- Name: critic_scopes_expected_to_recall evaluator_select_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY evaluator_select_all ON public.critic_scopes_expected_to_recall FOR SELECT TO evaluator USING (true);


--
-- Name: false_positive_occurrences evaluator_select_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY evaluator_select_all ON public.false_positive_occurrences FOR SELECT TO evaluator USING (true);


--
-- Name: false_positives evaluator_select_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY evaluator_select_all ON public.false_positives FOR SELECT TO evaluator USING (true);


--
-- Name: file_set_members evaluator_select_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY evaluator_select_all ON public.file_set_members FOR SELECT TO evaluator USING (true);


--
-- Name: file_sets evaluator_select_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY evaluator_select_all ON public.file_sets FOR SELECT TO evaluator USING (true);


--
-- Name: fp_occurrence_relevant_files evaluator_select_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY evaluator_select_all ON public.fp_occurrence_relevant_files FOR SELECT TO evaluator USING (true);


--
-- Name: grading_edges evaluator_select_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY evaluator_select_all ON public.grading_edges FOR SELECT TO evaluator USING (true);


--
-- Name: issue_cluster_members evaluator_select_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY evaluator_select_all ON public.issue_cluster_members FOR SELECT TO evaluator USING (true);


--
-- Name: issue_clusters evaluator_select_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY evaluator_select_all ON public.issue_clusters FOR SELECT TO evaluator USING (true);


--
-- Name: llm_requests evaluator_select_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY evaluator_select_all ON public.llm_requests FOR SELECT TO evaluator USING (true);


--
-- Name: occurrence_ranges evaluator_select_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY evaluator_select_all ON public.occurrence_ranges FOR SELECT TO evaluator USING (true);


--
-- Name: reported_issue_occurrences evaluator_select_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY evaluator_select_all ON public.reported_issue_occurrences FOR SELECT TO evaluator USING (true);


--
-- Name: reported_issues evaluator_select_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY evaluator_select_all ON public.reported_issues FOR SELECT TO evaluator USING (true);


--
-- Name: snapshots evaluator_select_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY evaluator_select_all ON public.snapshots FOR SELECT TO evaluator USING (true);


--
-- Name: true_positive_occurrences evaluator_select_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY evaluator_select_all ON public.true_positive_occurrences FOR SELECT TO evaluator USING (true);


--
-- Name: true_positives evaluator_select_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY evaluator_select_all ON public.true_positives FOR SELECT TO evaluator USING (true);


--
-- Name: false_positive_occurrences; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.false_positive_occurrences ENABLE ROW LEVEL SECURITY;

--
-- Name: false_positive_occurrences false_positive_occurrences_agent_select; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY false_positive_occurrences_agent_select ON public.false_positive_occurrences FOR SELECT USING (public.can_access_snapshot_ground_truth(snapshot_slug));


--
-- Name: false_positives; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.false_positives ENABLE ROW LEVEL SECURITY;

--
-- Name: false_positives false_positives_agent_select; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY false_positives_agent_select ON public.false_positives FOR SELECT USING (public.can_access_snapshot_ground_truth(snapshot_slug));


--
-- Name: file_set_members; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.file_set_members ENABLE ROW LEVEL SECURITY;

--
-- Name: file_set_members file_set_members_agent_select; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY file_set_members_agent_select ON public.file_set_members FOR SELECT USING ((((public.current_agent_type() = 'critic_dev_optimize'::text) AND public.can_list_snapshot_examples(snapshot_slug)) OR ((public.current_agent_type() = 'critic'::text) AND ((snapshot_slug)::text = ((public.current_agent_type_config() -> 'example'::text) ->> 'snapshot_slug'::text))) OR ((public.current_agent_type() = 'grader'::text) AND ((snapshot_slug)::text = public.current_grader_snapshot_slug())) OR ((public.current_agent_type() = 'critic_dev_improve'::text) AND public.is_improvement_snapshot_allowed((snapshot_slug)::text))));


--
-- Name: file_sets; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.file_sets ENABLE ROW LEVEL SECURITY;

--
-- Name: file_sets file_sets_agent_select; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY file_sets_agent_select ON public.file_sets FOR SELECT USING ((((public.current_agent_type() = 'critic_dev_optimize'::text) AND public.can_list_snapshot_examples(snapshot_slug)) OR ((public.current_agent_type() = 'critic'::text) AND ((snapshot_slug)::text = ((public.current_agent_type_config() -> 'example'::text) ->> 'snapshot_slug'::text)) AND ((files_hash)::text = ((public.current_agent_type_config() -> 'example'::text) ->> 'files_hash'::text))) OR ((public.current_agent_type() = 'grader'::text) AND ((snapshot_slug)::text = public.current_grader_snapshot_slug())) OR ((public.current_agent_type() = 'critic_dev_improve'::text) AND public.is_improvement_snapshot_allowed((snapshot_slug)::text))));


--
-- Name: fp_occurrence_relevant_files; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.fp_occurrence_relevant_files ENABLE ROW LEVEL SECURITY;

--
-- Name: fp_occurrence_relevant_files fp_occurrence_relevant_files_agent_select; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY fp_occurrence_relevant_files_agent_select ON public.fp_occurrence_relevant_files FOR SELECT USING (public.can_access_snapshot_ground_truth(snapshot_slug));


--
-- Name: issue_cluster_members grader_read_cluster_members; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY grader_read_cluster_members ON public.issue_cluster_members FOR SELECT USING (((snapshot_slug)::text = current_setting('props.grader_snapshot_slug'::text, true)));


--
-- Name: issue_clusters grader_read_clusters; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY grader_read_clusters ON public.issue_clusters FOR SELECT USING (((snapshot_slug)::text = current_setting('props.grader_snapshot_slug'::text, true)));


--
-- Name: reported_issue_occurrences grader_read_critique_occs; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY grader_read_critique_occs ON public.reported_issue_occurrences FOR SELECT USING (((public.current_agent_type() = 'grader'::text) AND public.is_critique_on_grader_snapshot(agent_run_id)));


--
-- Name: reported_issues grader_read_critiques; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY grader_read_critiques ON public.reported_issues FOR SELECT USING (((public.current_agent_type() = 'grader'::text) AND public.is_critique_on_grader_snapshot(agent_run_id)));


--
-- Name: issue_cluster_members grader_write_cluster_members; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY grader_write_cluster_members ON public.issue_cluster_members USING (((snapshot_slug)::text = current_setting('props.grader_snapshot_slug'::text, true))) WITH CHECK (((snapshot_slug)::text = current_setting('props.grader_snapshot_slug'::text, true)));


--
-- Name: issue_clusters grader_write_clusters; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY grader_write_clusters ON public.issue_clusters USING (((snapshot_slug)::text = current_setting('props.grader_snapshot_slug'::text, true))) WITH CHECK (((snapshot_slug)::text = current_setting('props.grader_snapshot_slug'::text, true)));


--
-- Name: grading_edges; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.grading_edges ENABLE ROW LEVEL SECURITY;

--
-- Name: grading_edges grading_edges_agent_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY grading_edges_agent_delete ON public.grading_edges FOR DELETE USING (public.is_own_run_as(grader_run_id, 'grader'::text));


--
-- Name: grading_edges grading_edges_agent_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY grading_edges_agent_insert ON public.grading_edges FOR INSERT WITH CHECK (public.is_own_run_as(grader_run_id, 'grader'::text));


--
-- Name: grading_edges grading_edges_agent_select; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY grading_edges_agent_select ON public.grading_edges FOR SELECT USING ((((public.current_agent_type() = 'grader'::text) AND public.is_critique_on_grader_snapshot(critique_run_id)) OR ((public.current_agent_type() = 'critic_dev_optimize'::text) AND public.is_train_agent_run(critique_run_id)) OR ((public.current_agent_type() = 'critic_dev_improve'::text) AND (critique_run_id IN ( SELECT public.get_improvement_allowed_agent_run_ids() AS get_improvement_allowed_agent_run_ids)))));


--
-- Name: grading_edges grading_edges_agent_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY grading_edges_agent_update ON public.grading_edges FOR UPDATE USING (public.is_own_run_as(grader_run_id, 'grader'::text));


--
-- Name: issue_cluster_members; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.issue_cluster_members ENABLE ROW LEVEL SECURITY;

--
-- Name: issue_clusters; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.issue_clusters ENABLE ROW LEVEL SECURITY;

--
-- Name: llm_requests; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.llm_requests ENABLE ROW LEVEL SECURITY;

--
-- Name: llm_requests llm_requests_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY llm_requests_insert ON public.llm_requests FOR INSERT WITH CHECK ((public.current_agent_run_id() IS NULL));


--
-- Name: llm_requests llm_requests_select; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY llm_requests_select ON public.llm_requests FOR SELECT USING (((public.current_agent_run_id() IS NULL) OR public.is_agent_ancestor(public.current_agent_run_id(), agent_run_id) OR ((public.current_agent_type() = 'critic_dev_optimize'::text) AND public.is_train_agent_run(agent_run_id)) OR ((public.current_agent_type() = 'critic_dev_improve'::text) AND (agent_run_id IN ( SELECT public.get_improvement_allowed_agent_run_ids() AS get_improvement_allowed_agent_run_ids)))));


--
-- Name: occurrence_ranges; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.occurrence_ranges ENABLE ROW LEVEL SECURITY;

--
-- Name: occurrence_ranges occurrence_ranges_agent_select; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY occurrence_ranges_agent_select ON public.occurrence_ranges FOR SELECT USING (public.can_access_snapshot_ground_truth(snapshot_slug));


--
-- Name: reported_issue_occurrences; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.reported_issue_occurrences ENABLE ROW LEVEL SECURITY;

--
-- Name: reported_issue_occurrences reported_issue_occurrences_agent_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY reported_issue_occurrences_agent_delete ON public.reported_issue_occurrences FOR DELETE USING (public.is_own_run_as(agent_run_id, 'critic'::text));


--
-- Name: reported_issue_occurrences reported_issue_occurrences_agent_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY reported_issue_occurrences_agent_insert ON public.reported_issue_occurrences FOR INSERT WITH CHECK (public.is_own_run_as(agent_run_id, 'critic'::text));


--
-- Name: reported_issue_occurrences reported_issue_occurrences_agent_select; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY reported_issue_occurrences_agent_select ON public.reported_issue_occurrences FOR SELECT USING (public.can_read_agent_run_data(agent_run_id));


--
-- Name: reported_issue_occurrences reported_issue_occurrences_agent_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY reported_issue_occurrences_agent_update ON public.reported_issue_occurrences FOR UPDATE USING (public.is_own_run_as(agent_run_id, 'critic'::text));


--
-- Name: reported_issues; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.reported_issues ENABLE ROW LEVEL SECURITY;

--
-- Name: reported_issues reported_issues_agent_delete; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY reported_issues_agent_delete ON public.reported_issues FOR DELETE USING (public.is_own_run_as(agent_run_id, 'critic'::text));


--
-- Name: reported_issues reported_issues_agent_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY reported_issues_agent_insert ON public.reported_issues FOR INSERT WITH CHECK (public.is_own_run_as(agent_run_id, 'critic'::text));


--
-- Name: reported_issues reported_issues_agent_select; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY reported_issues_agent_select ON public.reported_issues FOR SELECT USING (public.can_read_agent_run_data(agent_run_id));


--
-- Name: reported_issues reported_issues_agent_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY reported_issues_agent_update ON public.reported_issues FOR UPDATE USING (public.is_own_run_as(agent_run_id, 'critic'::text));


--
-- Name: snapshots; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.snapshots ENABLE ROW LEVEL SECURITY;

--
-- Name: snapshots snapshots_agent_select; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY snapshots_agent_select ON public.snapshots FOR SELECT USING ((public.current_agent_run_id() IS NOT NULL));


--
-- Name: true_positive_occurrences; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.true_positive_occurrences ENABLE ROW LEVEL SECURITY;

--
-- Name: true_positive_occurrences true_positive_occurrences_agent_select; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY true_positive_occurrences_agent_select ON public.true_positive_occurrences FOR SELECT USING (public.can_access_snapshot_ground_truth(snapshot_slug));


--
-- Name: true_positives; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.true_positives ENABLE ROW LEVEL SECURITY;

--
-- Name: true_positives true_positives_agent_select; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY true_positives_agent_select ON public.true_positives FOR SELECT USING (public.can_access_snapshot_ground_truth(snapshot_slug));


--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: -
--

GRANT USAGE ON SCHEMA public TO agent_base;
GRANT USAGE ON SCHEMA public TO evaluator_base;


--
-- Name: FUNCTION matchable_occurrences(p_snapshot_slug character varying, p_files character varying[]); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.matchable_occurrences(p_snapshot_slug character varying, p_files character varying[]) TO agent_base;
GRANT ALL ON FUNCTION public.matchable_occurrences(p_snapshot_slug character varying, p_files character varying[]) TO evaluator_base;


--
-- Name: TABLE agent_definitions; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.agent_definitions TO agent_base;
GRANT SELECT ON TABLE public.agent_definitions TO evaluator_base;


--
-- Name: TABLE agent_role_salt; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.agent_role_salt TO evaluator_base;


--
-- Name: TABLE agent_runs; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.agent_runs TO agent_base;
GRANT SELECT ON TABLE public.agent_runs TO evaluator_base;


--
-- Name: TABLE llm_requests; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.llm_requests TO agent_base;
GRANT SELECT ON TABLE public.llm_requests TO evaluator_base;


--
-- Name: TABLE model_metadata; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.model_metadata TO evaluator_base;
GRANT SELECT ON TABLE public.model_metadata TO agent_base;


--
-- Name: TABLE llm_request_costs; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.llm_request_costs TO agent_base;
GRANT SELECT ON TABLE public.llm_request_costs TO evaluator_base;


--
-- Name: TABLE agent_run_budget_status; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.agent_run_budget_status TO agent_base;
GRANT SELECT ON TABLE public.agent_run_budget_status TO evaluator_base;


--
-- Name: TABLE grading_edges; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.grading_edges TO agent_base;
GRANT SELECT ON TABLE public.grading_edges TO evaluator_base;


--
-- Name: TABLE reported_issue_occurrences; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.reported_issue_occurrences TO agent_base;
GRANT SELECT ON TABLE public.reported_issue_occurrences TO evaluator_base;


--
-- Name: TABLE reported_issues; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.reported_issues TO agent_base;
GRANT SELECT ON TABLE public.reported_issues TO evaluator_base;


--
-- Name: TABLE grading_pending; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.grading_pending TO agent_base;
GRANT SELECT ON TABLE public.grading_pending TO evaluator_base;


--
-- Name: TABLE issue_cluster_members; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.issue_cluster_members TO agent_base;
GRANT SELECT ON TABLE public.issue_cluster_members TO evaluator_base;


--
-- Name: TABLE clustering_pending; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.clustering_pending TO agent_base;
GRANT SELECT ON TABLE public.clustering_pending TO evaluator_base;


--
-- Name: TABLE critic_scopes_expected_to_recall; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.critic_scopes_expected_to_recall TO agent_base;
GRANT SELECT ON TABLE public.critic_scopes_expected_to_recall TO evaluator_base;


--
-- Name: TABLE file_sets; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.file_sets TO agent_base;
GRANT SELECT ON TABLE public.file_sets TO evaluator_base;


--
-- Name: TABLE snapshots; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.snapshots TO agent_base;
GRANT SELECT ON TABLE public.snapshots TO evaluator_base;


--
-- Name: TABLE true_positive_occurrences; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.true_positive_occurrences TO agent_base;
GRANT SELECT ON TABLE public.true_positive_occurrences TO evaluator_base;


--
-- Name: TABLE true_positives; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.true_positives TO agent_base;
GRANT SELECT ON TABLE public.true_positives TO evaluator_base;


--
-- Name: TABLE examples; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.examples TO agent_base;
GRANT SELECT ON TABLE public.examples TO evaluator_base;


--
-- Name: TABLE false_positive_occurrences; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.false_positive_occurrences TO agent_base;
GRANT SELECT ON TABLE public.false_positive_occurrences TO evaluator_base;


--
-- Name: TABLE false_positives; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.false_positives TO agent_base;
GRANT SELECT ON TABLE public.false_positives TO evaluator_base;


--
-- Name: TABLE file_set_members; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.file_set_members TO agent_base;
GRANT SELECT ON TABLE public.file_set_members TO evaluator_base;


--
-- Name: TABLE fp_occurrence_relevant_files; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.fp_occurrence_relevant_files TO agent_base;
GRANT SELECT ON TABLE public.fp_occurrence_relevant_files TO evaluator_base;


--
-- Name: TABLE grading_edge_credit_sums; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.grading_edge_credit_sums TO agent_base;
GRANT SELECT ON TABLE public.grading_edge_credit_sums TO evaluator_base;


--
-- Name: SEQUENCE grading_edges_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT USAGE ON SEQUENCE public.grading_edges_id_seq TO agent_base;


--
-- Name: TABLE issue_clusters; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.issue_clusters TO agent_base;
GRANT SELECT ON TABLE public.issue_clusters TO evaluator_base;


--
-- Name: SEQUENCE llm_requests_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT USAGE ON SEQUENCE public.llm_requests_id_seq TO agent_base;


--
-- Name: TABLE llm_run_costs; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.llm_run_costs TO agent_base;
GRANT SELECT ON TABLE public.llm_run_costs TO evaluator_base;


--
-- Name: TABLE occurrence_ranges; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.occurrence_ranges TO agent_base;
GRANT SELECT ON TABLE public.occurrence_ranges TO evaluator_base;


--
-- Name: SEQUENCE occurrence_ranges_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT USAGE ON SEQUENCE public.occurrence_ranges_id_seq TO agent_base;


--
-- Name: TABLE tp_occurrence_credits; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.tp_occurrence_credits TO agent_base;
GRANT SELECT ON TABLE public.tp_occurrence_credits TO evaluator_base;


--
-- Name: TABLE occurrence_statistics; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.occurrence_statistics TO agent_base;
GRANT SELECT ON TABLE public.occurrence_statistics TO evaluator_base;


--
-- Name: TABLE recall_by_run; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.recall_by_run TO agent_base;
GRANT SELECT ON TABLE public.recall_by_run TO evaluator_base;


--
-- Name: TABLE recall_by_definition_example; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.recall_by_definition_example TO agent_base;
GRANT SELECT ON TABLE public.recall_by_definition_example TO evaluator_base;


--
-- Name: TABLE pareto_frontier_by_example; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.pareto_frontier_by_example TO agent_base;
GRANT SELECT ON TABLE public.pareto_frontier_by_example TO evaluator_base;


--
-- Name: TABLE recall_by_definition_split_kind; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.recall_by_definition_split_kind TO agent_base;
GRANT SELECT ON TABLE public.recall_by_definition_split_kind TO evaluator_base;


--
-- Name: TABLE recall_by_example; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.recall_by_example TO agent_base;
GRANT SELECT ON TABLE public.recall_by_example TO evaluator_base;


--
-- Name: SEQUENCE reported_issue_occurrences_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT USAGE ON SEQUENCE public.reported_issue_occurrences_id_seq TO agent_base;


--
-- Name: TABLE snapshot_files; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.snapshot_files TO agent_base;
GRANT SELECT ON TABLE public.snapshot_files TO evaluator_base;


--
-- Name: TABLE validation_recall_by_definition; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.validation_recall_by_definition TO agent_base;
GRANT SELECT ON TABLE public.validation_recall_by_definition TO evaluator_base;


--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: public; Owner: -
--

ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO evaluator_base;


--
-- PostgreSQL database dump complete
--
"""
