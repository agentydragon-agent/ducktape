"""Add grading_edges table and snapshot_grader agent type.

Revision ID: 20251228000001
Revises: 20251228000000
Create Date: 2025-12-28

This migration adds:
1. grading_edges table - explicit bipartite graph representation of grading decisions
2. Helper functions for snapshot_grader agent type
3. matchable_occurrences() function for sparse graph matching
4. grading_pending view for drift detection
5. RLS policies for snapshot_grader agent type
6. pg_notify triggers for GT changes (daemon wake-up)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20251228000001"
down_revision = "20251228000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ============================================================================
    # 1. grading_edges table
    # ============================================================================
    op.create_table(
        "grading_edges",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        # Reference to the critique issue (from reported_issues)
        sa.Column("critique_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("critique_issue_id", sa.String(), nullable=False),
        # TP target (nullable - exactly one of TP or FP must be set)
        sa.Column("snapshot_slug", sa.String(), nullable=False),  # For FK validation
        sa.Column("tp_id", sa.String(), nullable=True),
        sa.Column("tp_occurrence_id", sa.String(), nullable=True),
        # FP target (nullable)
        sa.Column("fp_id", sa.String(), nullable=True),
        sa.Column("fp_occurrence_id", sa.String(), nullable=True),
        # Grading metadata
        sa.Column("credit", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("grader_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        # Primary key
        sa.PrimaryKeyConstraint("id"),
        # FK to reported_issues
        sa.ForeignKeyConstraint(
            ["critique_run_id", "critique_issue_id"],
            ["reported_issues.agent_run_id", "reported_issues.issue_id"],
            ondelete="CASCADE",
            name="fk_grading_edges_critique",
        ),
        # FK to agent_runs (grader)
        sa.ForeignKeyConstraint(
            ["grader_run_id"], ["agent_runs.agent_run_id"], ondelete="CASCADE", name="fk_grading_edges_grader"
        ),
        # FK to true_positive_occurrences (when TP target set)
        sa.ForeignKeyConstraint(
            ["snapshot_slug", "tp_id", "tp_occurrence_id"],
            [
                "true_positive_occurrences.snapshot_slug",
                "true_positive_occurrences.tp_id",
                "true_positive_occurrences.occurrence_id",
            ],
            ondelete="CASCADE",
            name="fk_grading_edges_tp",
        ),
        # FK to false_positive_occurrences (when FP target set)
        sa.ForeignKeyConstraint(
            ["snapshot_slug", "fp_id", "fp_occurrence_id"],
            [
                "false_positive_occurrences.snapshot_slug",
                "false_positive_occurrences.fp_id",
                "false_positive_occurrences.occurrence_id",
            ],
            ondelete="CASCADE",
            name="fk_grading_edges_fp",
        ),
        # Unique constraints to prevent duplicate edges
        sa.UniqueConstraint(
            "critique_run_id", "critique_issue_id", "tp_id", "tp_occurrence_id", name="uq_grading_edges_tp"
        ),
        sa.UniqueConstraint(
            "critique_run_id", "critique_issue_id", "fp_id", "fp_occurrence_id", name="uq_grading_edges_fp"
        ),
        # Exactly one of TP or FP must be set (same pattern as grading_decisions)
        sa.CheckConstraint(
            """(
                (tp_id IS NOT NULL AND tp_occurrence_id IS NOT NULL AND fp_id IS NULL AND fp_occurrence_id IS NULL)
                OR (fp_id IS NOT NULL AND fp_occurrence_id IS NOT NULL AND tp_id IS NULL AND tp_occurrence_id IS NULL)
            )""",
            name="exactly_one_target_edge",
        ),
        # Credit range
        sa.CheckConstraint("credit >= 0.0 AND credit <= 1.0", name="credit_range_edge"),
    )

    op.execute("""
        COMMENT ON TABLE grading_edges IS
        'Explicit bipartite graph edges from critique issues to GT occurrences.
Each edge represents a grader''s judgment about whether a critique issue matches a GT occurrence.

Key invariants:
- Every (critique_issue, matchable_occurrence) pair must have an edge (complete coverage)
- Exactly one of (tp_id, tp_occurrence_id) or (fp_id, fp_occurrence_id) is set
- credit: 0.0-1.0 for TP matches, 0.0 for FP matches (FP credit = anti-credit, penalty)
- No-match decisions still create edges with credit=0.0

Drift = missing edges. Query grading_pending view to see what''s missing.'
    """)

    # Index for finding edges by critique
    op.create_index("idx_grading_edges_critique", "grading_edges", ["critique_run_id", "critique_issue_id"])
    # Index for finding edges by GT occurrence
    op.create_index("idx_grading_edges_tp", "grading_edges", ["snapshot_slug", "tp_id", "tp_occurrence_id"])
    op.create_index("idx_grading_edges_fp", "grading_edges", ["snapshot_slug", "fp_id", "fp_occurrence_id"])
    # Index for grader's own edges
    op.create_index("idx_grading_edges_grader", "grading_edges", ["grader_run_id"])

    # ============================================================================
    # 2. Helper functions for snapshot_grader agent type
    # ============================================================================
    op.execute("""
        CREATE FUNCTION current_grader_snapshot_slug() RETURNS TEXT
        LANGUAGE SQL STABLE SECURITY DEFINER AS $$
            SELECT (type_config->>'snapshot_slug')::text
            FROM agent_runs
            WHERE agent_run_id = current_agent_run_id()
              AND (type_config->>'agent_type') = 'snapshot_grader'
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION current_grader_snapshot_slug() IS
        'Returns snapshot_slug for snapshot_grader agents. NULL for other agent types.
Used by RLS to scope snapshot-wide access for grader daemons.'
    """)

    op.execute("""
        CREATE FUNCTION is_critique_on_grader_snapshot(p_critique_run_id UUID) RETURNS BOOLEAN
        LANGUAGE SQL STABLE SECURITY DEFINER AS $$
            SELECT EXISTS (
                SELECT 1 FROM agent_runs critique
                WHERE critique.agent_run_id = p_critique_run_id
                  AND (critique.type_config->>'agent_type') = 'critic'
                  AND (critique.type_config->'example'->>'snapshot_slug') = current_grader_snapshot_slug()
            )
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION is_critique_on_grader_snapshot(UUID) IS
        'Returns TRUE if the given critique run is on the current snapshot_grader daemon''s snapshot.
Used by RLS to allow daemon access to all critiques for its snapshot.'
    """)

    # ============================================================================
    # 3. matchable_occurrences() function for sparse graph matching
    # ============================================================================
    op.execute("""
        CREATE FUNCTION matchable_occurrences(
            p_snapshot_slug VARCHAR,
            p_files VARCHAR[]
        ) RETURNS TABLE (
            tp_id VARCHAR,
            tp_occurrence_id VARCHAR,
            fp_id VARCHAR,
            fp_occurrence_id VARCHAR
        ) AS $$
            -- TPs: cross-cutting (NULL) or file overlap
            SELECT tpo.tp_id, tpo.occurrence_id, NULL::VARCHAR, NULL::VARCHAR
            FROM true_positive_occurrences tpo
            WHERE tpo.snapshot_slug = p_snapshot_slug
              AND (
                  tpo.match_filter_hash IS NULL
                  OR EXISTS (
                      SELECT 1 FROM file_set_members fsm
                      WHERE fsm.snapshot_slug = tpo.snapshot_slug
                        AND fsm.files_hash = tpo.match_filter_hash
                        AND fsm.file_path = ANY(p_files)
                  )
              )
            UNION ALL
            -- FPs: cross-cutting (NULL) or file overlap
            SELECT NULL, NULL, fpo.fp_id, fpo.occurrence_id
            FROM false_positive_occurrences fpo
            WHERE fpo.snapshot_slug = p_snapshot_slug
              AND (
                  fpo.match_filter_hash IS NULL
                  OR EXISTS (
                      SELECT 1 FROM file_set_members fsm
                      WHERE fsm.snapshot_slug = fpo.snapshot_slug
                        AND fsm.files_hash = fpo.match_filter_hash
                        AND fsm.file_path = ANY(p_files)
                  )
              )
        $$ LANGUAGE SQL STABLE
    """)

    op.execute("""
        COMMENT ON FUNCTION matchable_occurrences(VARCHAR, VARCHAR[]) IS
        'Returns GT occurrences matchable from given files for a snapshot.
Used by:
- grading_pending view (drift detection)
- Edge validation trigger
- Workload estimation

NULL match_filter_hash = cross-cutting (any critique can match)
Non-NULL = file-local (only critiques touching those files can match)'
    """)

    # Index for efficient file-local lookups
    op.create_index("idx_file_set_members_file_path", "file_set_members", ["snapshot_slug", "file_path"])

    # ============================================================================
    # 4. grading_pending view for drift detection
    # ============================================================================
    op.execute("""
        CREATE VIEW grading_pending AS
        WITH critique_issues AS (
            -- Get all critique issues with their files and snapshot
            SELECT
                ri.agent_run_id AS critique_run_id,
                ri.issue_id AS critique_issue_id,
                (ar.type_config->'example'->>'snapshot_slug') AS snapshot_slug,
                array_agg(DISTINCT loc->>'file') FILTER (WHERE loc->>'file' IS NOT NULL) AS reported_files
            FROM reported_issues ri
            JOIN agent_runs ar ON ar.agent_run_id = ri.agent_run_id
            LEFT JOIN reported_issue_occurrences rio ON rio.agent_run_id = ri.agent_run_id AND rio.reported_issue_id = ri.issue_id
            LEFT JOIN LATERAL jsonb_array_elements(rio.locations) AS loc ON true
            WHERE (ar.type_config->>'agent_type') = 'critic'
              AND ar.status = 'completed'
            GROUP BY ri.agent_run_id, ri.issue_id, ar.type_config
        )
        -- Find missing TP edges
        SELECT
            ci.critique_run_id,
            ci.critique_issue_id,
            ci.snapshot_slug,
            mo.tp_id,
            mo.tp_occurrence_id,
            NULL::VARCHAR AS fp_id,
            NULL::VARCHAR AS fp_occurrence_id
        FROM critique_issues ci
        CROSS JOIN LATERAL matchable_occurrences(ci.snapshot_slug, ci.reported_files) mo
        WHERE mo.tp_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM grading_edges ge
              WHERE ge.critique_run_id = ci.critique_run_id
                AND ge.critique_issue_id = ci.critique_issue_id
                AND ge.tp_id = mo.tp_id
                AND ge.tp_occurrence_id = mo.tp_occurrence_id
          )
        UNION ALL
        -- Find missing FP edges
        SELECT
            ci.critique_run_id,
            ci.critique_issue_id,
            ci.snapshot_slug,
            NULL::VARCHAR AS tp_id,
            NULL::VARCHAR AS tp_occurrence_id,
            mo.fp_id,
            mo.fp_occurrence_id
        FROM critique_issues ci
        CROSS JOIN LATERAL matchable_occurrences(ci.snapshot_slug, ci.reported_files) mo
        WHERE mo.fp_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM grading_edges ge
              WHERE ge.critique_run_id = ci.critique_run_id
                AND ge.critique_issue_id = ci.critique_issue_id
                AND ge.fp_id = mo.fp_id
                AND ge.fp_occurrence_id = mo.fp_occurrence_id
          )
    """)

    op.execute("""
        COMMENT ON VIEW grading_pending IS
        'Shows missing grading edges (drift).
Each row represents a (critique_issue, gt_occurrence) pair that needs grading.

Query patterns:
- All drift: SELECT * FROM grading_pending
- By snapshot: WHERE snapshot_slug = ''...''
- By critique: WHERE critique_run_id = ''...''
- By GT: WHERE tp_id = ''...'' AND tp_occurrence_id = ''...''

When this view returns no rows for a grader''s scope, grading is complete.'
    """)

    # ============================================================================
    # 5. RLS policies for grading_edges
    # ============================================================================
    op.execute("ALTER TABLE grading_edges ENABLE ROW LEVEL SECURITY")

    # Per-critique grader (existing pattern) - writes edges for graded critique only
    op.execute("""
        CREATE POLICY grader_insert_edges ON grading_edges FOR INSERT WITH CHECK (
            current_agent_type() = 'grader'
            AND grader_run_id = current_agent_run_id()
            AND critique_run_id = current_graded_agent_run_id()
        )
    """)

    op.execute("""
        CREATE POLICY grader_select_edges ON grading_edges FOR SELECT USING (
            current_agent_type() = 'grader'
            AND (
                grader_run_id = current_agent_run_id()
                OR critique_run_id = current_graded_agent_run_id()
            )
        )
    """)

    op.execute("""
        CREATE POLICY grader_update_edges ON grading_edges FOR UPDATE USING (
            current_agent_type() = 'grader'
            AND grader_run_id = current_agent_run_id()
        )
    """)

    op.execute("""
        CREATE POLICY grader_delete_edges ON grading_edges FOR DELETE USING (
            current_agent_type() = 'grader'
            AND grader_run_id = current_agent_run_id()
        )
    """)

    # Snapshot grader (daemon) - writes edges for any critique on its snapshot
    op.execute("""
        CREATE POLICY snapshot_grader_insert_edges ON grading_edges FOR INSERT WITH CHECK (
            current_agent_type() = 'snapshot_grader'
            AND grader_run_id = current_agent_run_id()
            AND is_critique_on_grader_snapshot(critique_run_id)
        )
    """)

    op.execute("""
        CREATE POLICY snapshot_grader_select_edges ON grading_edges FOR SELECT USING (
            current_agent_type() = 'snapshot_grader'
            AND is_critique_on_grader_snapshot(critique_run_id)
        )
    """)

    op.execute("""
        CREATE POLICY snapshot_grader_update_edges ON grading_edges FOR UPDATE USING (
            current_agent_type() = 'snapshot_grader'
            AND grader_run_id = current_agent_run_id()
        )
    """)

    op.execute("""
        CREATE POLICY snapshot_grader_delete_edges ON grading_edges FOR DELETE USING (
            current_agent_type() = 'snapshot_grader'
            AND grader_run_id = current_agent_run_id()
        )
    """)

    # Prompt optimizer - read TRAIN edges
    op.execute("""
        CREATE POLICY prompt_optimizer_select_edges ON grading_edges FOR SELECT USING (
            current_agent_type() = 'prompt_optimizer'
            AND is_train_snapshot(snapshot_slug)
        )
    """)

    # Improvement agent - read allowed edges
    op.execute("""
        CREATE POLICY improvement_select_edges ON grading_edges FOR SELECT USING (
            current_agent_type() = 'improvement'
            AND is_improvement_snapshot_allowed(snapshot_slug)
        )
    """)

    # Admin full access
    op.execute("""
        CREATE POLICY admin_full_access_edges ON grading_edges FOR ALL USING (
            current_user = 'postgres'
        )
    """)

    # Grant permissions
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE grading_edges TO agent_base")

    # ============================================================================
    # 6. RLS policies for snapshot_grader on reported_issues
    # ============================================================================
    op.execute("""
        CREATE POLICY snapshot_grader_read_critiques ON reported_issues FOR SELECT USING (
            current_agent_type() = 'snapshot_grader'
            AND is_critique_on_grader_snapshot(agent_run_id)
        )
    """)

    op.execute("""
        CREATE POLICY snapshot_grader_read_critique_occs ON reported_issue_occurrences FOR SELECT USING (
            current_agent_type() = 'snapshot_grader'
            AND is_critique_on_grader_snapshot(agent_run_id)
        )
    """)

    # ============================================================================
    # 7. RLS policy for snapshot_grader on agent_runs
    # ============================================================================
    op.execute("""
        CREATE POLICY snapshot_grader_read_runs ON agent_runs FOR SELECT USING (
            current_agent_type() = 'snapshot_grader'
            AND (
                agent_run_id = current_agent_run_id()
                OR (
                    (type_config->>'agent_type') = 'critic'
                    AND (type_config->'example'->>'snapshot_slug') = current_grader_snapshot_slug()
                )
            )
        )
    """)

    # ============================================================================
    # 8. Update can_access_snapshot() for snapshot_grader
    # ============================================================================
    # Drop and recreate the function to add snapshot_grader support
    op.execute("DROP FUNCTION IF EXISTS can_access_snapshot(VARCHAR)")

    op.execute("""
        CREATE FUNCTION can_access_snapshot(p_slug VARCHAR) RETURNS BOOLEAN
        LANGUAGE plpgsql STABLE SECURITY DEFINER AS $$
        BEGIN
            RETURN (
                (current_agent_type() = 'prompt_optimizer' AND is_train_snapshot(p_slug))
                OR (current_agent_type() = 'grader' AND p_slug = get_graded_snapshot_slug(current_agent_run_id()))
                OR (current_agent_type() = 'snapshot_grader' AND p_slug = current_grader_snapshot_slug())
                OR (current_agent_type() = 'improvement' AND is_improvement_snapshot_allowed(p_slug))
            );
        END;
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION can_access_snapshot(VARCHAR) IS
        'Checks if current agent can access a snapshot''s ground truth.
- prompt_optimizer: TRAIN snapshots only
- grader: snapshot of the critique being graded
- snapshot_grader: the daemon''s assigned snapshot
- improvement: allowed snapshots from config'
    """)

    # ============================================================================
    # 9. pg_notify triggers for GT changes (daemon wake-up)
    # ============================================================================
    op.execute("""
        CREATE FUNCTION notify_gt_changed() RETURNS TRIGGER AS $$
        BEGIN
            PERFORM pg_notify('grading_pending', json_build_object(
                'event', TG_OP || '_' || TG_TABLE_NAME,
                'snapshot_slug', COALESCE(NEW.snapshot_slug, OLD.snapshot_slug)
            )::text);
            RETURN COALESCE(NEW, OLD);
        END;
        $$ LANGUAGE plpgsql
    """)

    op.execute("""
        COMMENT ON FUNCTION notify_gt_changed() IS
        'Sends pg_notify when ground truth changes. Used to wake snapshot_grader daemons.
Fires on INSERT/DELETE of TPs/FPs (not UPDATE - minor wording fixes don''t need re-grade).'
    """)

    # Triggers on TP/FP tables (INSERT/DELETE only)
    op.execute("""
        CREATE TRIGGER trg_notify_tp_changed
        AFTER INSERT OR DELETE ON true_positives
        FOR EACH ROW EXECUTE FUNCTION notify_gt_changed()
    """)

    op.execute("""
        CREATE TRIGGER trg_notify_tp_occ_changed
        AFTER INSERT OR DELETE ON true_positive_occurrences
        FOR EACH ROW EXECUTE FUNCTION notify_gt_changed()
    """)

    op.execute("""
        CREATE TRIGGER trg_notify_fp_changed
        AFTER INSERT OR DELETE ON false_positives
        FOR EACH ROW EXECUTE FUNCTION notify_gt_changed()
    """)

    op.execute("""
        CREATE TRIGGER trg_notify_fp_occ_changed
        AFTER INSERT OR DELETE ON false_positive_occurrences
        FOR EACH ROW EXECUTE FUNCTION notify_gt_changed()
    """)

    # ============================================================================
    # 10. Credit sum enforcement for grading_edges
    # ============================================================================
    # View to aggregate credit sums per (critique_run, gt_occurrence)
    op.execute("""
        CREATE VIEW grading_edge_credit_sums AS
        SELECT
            critique_run_id,
            tp_id, tp_occurrence_id,
            fp_id, fp_occurrence_id,
            SUM(credit) AS total_credit
        FROM grading_edges
        GROUP BY critique_run_id, tp_id, tp_occurrence_id, fp_id, fp_occurrence_id
    """)

    op.execute("""
        COMMENT ON VIEW grading_edge_credit_sums IS
        'Aggregate credit sums per (critique_run, occurrence) for enforcing credit <= 1.0 constraint.
Used by check_edge_credit_sum trigger function.'
    """)

    # Trigger function to enforce credit sum <= 1.0 per occurrence
    op.execute("""
        CREATE FUNCTION check_edge_credit_sum() RETURNS trigger
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
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION check_edge_credit_sum() IS
        'Trigger function that validates credit sums per (critique_run, occurrence) do not exceed 1.0.'
    """)

    op.execute("""
        CREATE TRIGGER enforce_edge_credit_sum
        BEFORE INSERT OR UPDATE ON grading_edges
        FOR EACH ROW EXECUTE FUNCTION check_edge_credit_sum()
    """)

    # ============================================================================
    # 11. Drop grading_decisions and its dependencies
    # ============================================================================
    # First drop views that depend on grading_decisions (CASCADE would do this, but explicit is safer)
    op.execute("DROP VIEW IF EXISTS validation_recall_by_definition CASCADE")
    op.execute("DROP VIEW IF EXISTS pareto_frontier_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS recall_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS recall_by_definition_split_kind CASCADE")
    op.execute("DROP VIEW IF EXISTS recall_by_definition_example CASCADE")
    op.execute("DROP VIEW IF EXISTS recall_by_run CASCADE")
    op.execute("DROP VIEW IF EXISTS grading_credit_sums CASCADE")

    # Drop triggers on grading_decisions
    op.execute("DROP TRIGGER IF EXISTS enforce_credit_sum ON grading_decisions")
    op.execute("DROP TRIGGER IF EXISTS check_input_issue_exists_trigger ON grading_decisions")
    op.execute("DROP TRIGGER IF EXISTS check_target_exists_trigger ON grading_decisions")

    # Drop trigger functions (only those specific to grading_decisions)
    op.execute("DROP FUNCTION IF EXISTS check_credit_sum()")
    op.execute("DROP FUNCTION IF EXISTS check_input_issue_exists()")
    op.execute("DROP FUNCTION IF EXISTS check_target_exists()")

    # Drop the grading_decisions table
    op.execute("DROP TABLE IF EXISTS grading_decisions CASCADE")

    # ============================================================================
    # 12. Recreate recall views using grading_edges
    # ============================================================================
    # recall_by_run view - based on grading_edges
    op.execute("""
        CREATE VIEW recall_by_run AS
        WITH grader_stats AS (
            SELECT
                ge.grader_run_id,
                ge.critique_run_id,
                COALESCE(SUM(ge.credit) FILTER (WHERE ge.tp_id IS NOT NULL), 0.0) AS total_credit,
                COUNT(DISTINCT (ge.tp_id, ge.tp_occurrence_id))
                    FILTER (WHERE ge.tp_id IS NOT NULL) AS recall_denominator
            FROM grading_edges ge
            GROUP BY ge.grader_run_id, ge.critique_run_id
        ),
        per_run AS (
            SELECT
                cr.type_config->'example'->>'snapshot_slug' AS snapshot_slug,
                e.example_kind,
                e.files_hash,
                s.split,
                e.recall_denominator,
                cr.agent_run_id AS critic_run_id,
                cr.agent_definition_id AS critic_definition_id,
                cr.model AS critic_model,
                cr.status AS critic_status,
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
            LEFT JOIN grader_stats gs ON gs.critique_run_id = cr.agent_run_id
            WHERE (cr.type_config->>'agent_type') = 'critic'
              AND cr.status != 'in_progress'
            GROUP BY cr.agent_run_id, cr.type_config, cr.agent_definition_id, cr.model, cr.status,
                     e.example_kind, e.files_hash, e.recall_denominator, s.split
        )
        SELECT
            snapshot_slug, example_kind, files_hash, split, recall_denominator,
            critic_run_id, critic_definition_id, critic_model, critic_status,
            credit_stats,
            scale_stats(credit_stats, recall_denominator) AS recall_stats
        FROM per_run
    """)

    op.execute("""
        COMMENT ON VIEW recall_by_run IS
        'Per-critic-run recall using grading_edges. Base view for all recall aggregates.'
    """)

    # recall_by_definition_example view
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
                MAX(rbr.recall_denominator)::integer AS recall_denominator,
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
            recall_denominator, n_runs, status_counts, credit_stats,
            scale_stats(credit_stats, recall_denominator) AS recall_stats
        FROM raw_stats
    """)

    op.execute("""
        COMMENT ON VIEW recall_by_definition_example IS
        'Recall aggregated by (definition, example). Uses grading_edges.'
    """)

    # recall_by_definition_split_kind view
    op.execute("""
        CREATE VIEW recall_by_definition_split_kind AS
        WITH
        example_counts AS (
            SELECT
                split, example_kind, critic_definition_id, critic_model,
                COUNT(*)::integer AS n_examples,
                SUM(recall_denominator)::integer AS recall_denominator
            FROM (
                SELECT DISTINCT
                    split, example_kind, files_hash, recall_denominator,
                    critic_definition_id, critic_model
                FROM recall_by_definition_example
            ) per_example
            GROUP BY split, example_kind, critic_definition_id, critic_model
        ),
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
            ec.n_examples, rs.n_runs, ec.recall_denominator,
            rs.status_counts, rs.credit_stats,
            scale_stats(rs.credit_stats, ec.recall_denominator) AS recall_stats,
            rs.zero_count
        FROM run_stats rs
        JOIN example_counts ec USING (split, example_kind, critic_definition_id, critic_model)
    """)

    op.execute("""
        COMMENT ON VIEW recall_by_definition_split_kind IS
        'Recall aggregated by (definition, split, example_kind). Uses grading_edges.'
    """)

    # recall_by_example view
    op.execute("""
        CREATE VIEW recall_by_example AS
        WITH raw_stats AS (
            SELECT
                rbde.snapshot_slug,
                rbde.example_kind,
                rbde.files_hash,
                rbde.split,
                MAX(rbde.recall_denominator)::integer AS recall_denominator,
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
            recall_denominator, critic_model, n_runs, status_counts, credit_stats,
            scale_stats(credit_stats, recall_denominator) AS recall_stats
        FROM raw_stats
    """)

    op.execute("""
        COMMENT ON VIEW recall_by_example IS
        'Recall aggregated by example (across all definitions). Uses grading_edges.'
    """)

    # pareto_frontier_by_example view
    op.execute("""
        CREATE VIEW pareto_frontier_by_example AS
        WITH best_scores AS (
            SELECT
                snapshot_slug,
                example_kind,
                files_hash,
                split,
                MAX(recall_denominator) AS recall_denominator,
                critic_model,
                MAX(COALESCE((credit_stats).mean, 0.0)) AS best_mean_credit
            FROM recall_by_definition_example
            GROUP BY snapshot_slug, example_kind, files_hash, split, critic_model
        ),
        ranked AS (
            SELECT
                rbde.*,
                (rbde.credit_stats).mean AS mean_credit,
                bs.best_mean_credit
            FROM recall_by_definition_example rbde
            JOIN best_scores bs USING (snapshot_slug, example_kind, files_hash, split, critic_model)
            WHERE COALESCE((rbde.credit_stats).mean, 0.0) = bs.best_mean_credit
        )
        SELECT
            snapshot_slug, example_kind, files_hash, split,
            MAX(recall_denominator)::integer AS recall_denominator,
            critic_model,
            array_agg(DISTINCT critic_definition_id) AS winning_critic_definition_ids,
            best_mean_credit
        FROM ranked
        GROUP BY snapshot_slug, example_kind, files_hash, split, critic_model, best_mean_credit
    """)

    op.execute("""
        COMMENT ON VIEW pareto_frontier_by_example IS
        'Best definitions per example. Uses grading_edges.'
    """)

    # validation_recall_by_definition view
    op.execute("""
        CREATE VIEW validation_recall_by_definition AS
        SELECT
            critic_definition_id,
            critic_model,
            compute_stats_with_ci(array_agg(
                total_credit / NULLIF(n_occurrences, 0)
            )) AS recall_stats
        FROM get_validation_full_snapshot_aggregates()
        GROUP BY critic_definition_id, critic_model
    """)

    op.execute("""
        COMMENT ON VIEW validation_recall_by_definition IS
        'Aggregated validation recall by definition. Uses grading_edges.'
    """)

    # Grant permissions on recreated views
    op.execute("GRANT SELECT ON TABLE recall_by_run TO agent_base")
    op.execute("GRANT SELECT ON TABLE recall_by_definition_example TO agent_base")
    op.execute("GRANT SELECT ON TABLE recall_by_definition_split_kind TO agent_base")
    op.execute("GRANT SELECT ON TABLE recall_by_example TO agent_base")
    op.execute("GRANT SELECT ON TABLE pareto_frontier_by_example TO agent_base")
    op.execute("GRANT SELECT ON TABLE validation_recall_by_definition TO agent_base")


def downgrade() -> None:
    # Drop credit sum trigger
    op.execute("DROP TRIGGER IF EXISTS enforce_edge_credit_sum ON grading_edges")
    op.execute("DROP FUNCTION IF EXISTS check_edge_credit_sum()")
    op.execute("DROP VIEW IF EXISTS grading_edge_credit_sums")
    # Drop triggers
    op.execute("DROP TRIGGER IF EXISTS trg_notify_fp_occ_changed ON false_positive_occurrences")
    op.execute("DROP TRIGGER IF EXISTS trg_notify_fp_changed ON false_positives")
    op.execute("DROP TRIGGER IF EXISTS trg_notify_tp_occ_changed ON true_positive_occurrences")
    op.execute("DROP TRIGGER IF EXISTS trg_notify_tp_changed ON true_positives")
    op.execute("DROP FUNCTION IF EXISTS notify_gt_changed()")

    # Drop RLS policies
    op.execute("DROP POLICY IF EXISTS snapshot_grader_read_runs ON agent_runs")
    op.execute("DROP POLICY IF EXISTS snapshot_grader_read_critique_occs ON reported_issue_occurrences")
    op.execute("DROP POLICY IF EXISTS snapshot_grader_read_critiques ON reported_issues")

    # Restore original can_access_snapshot (without snapshot_grader)
    op.execute("DROP FUNCTION IF EXISTS can_access_snapshot(VARCHAR)")
    op.execute("""
        CREATE FUNCTION can_access_snapshot(p_slug VARCHAR) RETURNS BOOLEAN
        LANGUAGE plpgsql STABLE SECURITY DEFINER AS $$
        BEGIN
            RETURN (
                (current_agent_type() = 'prompt_optimizer' AND is_train_snapshot(p_slug))
                OR (current_agent_type() = 'grader' AND p_slug = get_graded_snapshot_slug(current_agent_run_id()))
                OR (current_agent_type() = 'improvement' AND is_improvement_snapshot_allowed(p_slug))
            );
        END;
        $$
    """)

    # Drop grading_pending view
    op.execute("DROP VIEW IF EXISTS grading_pending")

    # Drop matchable_occurrences function
    op.execute("DROP FUNCTION IF EXISTS matchable_occurrences(VARCHAR, VARCHAR[])")

    # Drop index
    op.execute("DROP INDEX IF EXISTS idx_file_set_members_file_path")

    # Drop helper functions
    op.execute("DROP FUNCTION IF EXISTS is_critique_on_grader_snapshot(UUID)")
    op.execute("DROP FUNCTION IF EXISTS current_grader_snapshot_slug()")

    # Drop grading_edges table (drops policies automatically)
    op.drop_table("grading_edges")
