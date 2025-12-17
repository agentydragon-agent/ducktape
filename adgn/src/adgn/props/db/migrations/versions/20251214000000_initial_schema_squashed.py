"""Initial schema (squashed from multiple migrations)

Revision ID: 20251214000000
Revises: None
Create Date: 2025-12-14 00:00:00.000000

This migration consolidates all previous migrations into a single initial schema.

Key improvements over historical migrations:
1. Credit sum validation uses a view (grading_credit_sums) for cleaner logic
2. Simplified prompt_optimizer username parsing (consistent with other agents)
3. Removed soft-delete references from check_credit_sum trigger
4. grading_decisions has DEFAULT + WITH CHECK for RLS
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20251214000000"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create complete initial schema with improvements."""

    # 1. Custom types
    op.execute("CREATE TYPE split_enum AS ENUM ('train', 'valid', 'test')")

    # 2. Tables in dependency order

    # snapshots (no dependencies)
    op.create_table(
        "snapshots",
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column(
            "split", postgresql.ENUM("train", "valid", "test", name="split_enum", create_type=False), nullable=False
        ),
        sa.Column("source", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("bundle", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("slug"),
    )

    # prompts (no dependencies - but FK to prompt_optimization_runs)
    op.create_table(
        "prompts",
        sa.Column("prompt_sha256", sa.String(64), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("prompt_optimization_run_id", postgresql.UUID(), nullable=True),
        sa.Column("template_file_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("prompt_sha256"),
    )

    # prompt_optimization_runs (no dependencies)
    op.create_table(
        "prompt_optimization_runs",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("transcript_id", postgresql.UUID(), nullable=True),
        sa.Column("budget_limit", sa.Float(), nullable=False),
        sa.Column(
            "config", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Add FK from prompts to prompt_optimization_runs now
    op.create_foreign_key(
        None, "prompts", "prompt_optimization_runs", ["prompt_optimization_run_id"], ["id"], ondelete="CASCADE"
    )

    # model_metadata (no dependencies)
    op.create_table(
        "model_metadata",
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("input_usd_per_1m_tokens", sa.Float(), nullable=False),
        sa.Column("cached_input_usd_per_1m_tokens", sa.Float(), nullable=True),
        sa.Column("output_usd_per_1m_tokens", sa.Float(), nullable=False),
        sa.Column("context_window_tokens", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("model_id"),
    )

    # examples (depends on snapshots)
    op.create_table(
        "examples",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column("files_hash", sa.String(64), nullable=True),
        sa.Column("files", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_whole_snapshot", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(is_whole_snapshot = true AND files IS NULL AND files_hash IS NULL) OR "
            "(is_whole_snapshot = false AND files IS NOT NULL AND files_hash IS NOT NULL)",
            name="ck_examples_snapshot_type",
        ),
        sa.ForeignKeyConstraint(["snapshot_slug"], ["snapshots.slug"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("COMMENT ON COLUMN examples.files_hash IS 'SHA256 hash of normalized files field for uniqueness'")
    op.execute("COMMENT ON COLUMN examples.files IS 'List of file paths to review'")

    # true_positives (depends on snapshots)
    op.create_table(
        "true_positives",
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column("tp_id", sa.String(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("occurrences", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_slug"], ["snapshots.slug"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("snapshot_slug", "tp_id"),
    )

    # false_positives (depends on snapshots)
    op.create_table(
        "false_positives",
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column("fp_id", sa.String(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("occurrences", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_slug"], ["snapshots.slug"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("snapshot_slug", "fp_id"),
    )

    # clustering_runs (depends on snapshots)
    op.create_table(
        "clustering_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default=sa.text("'in_progress'"), nullable=False),
        sa.Column("transcript_id", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('in_progress', 'completed', 'abandoned')", name="clustering_runs_status_check"),
        sa.ForeignKeyConstraint(["snapshot_slug"], ["snapshots.slug"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # critiques (depends on snapshots)
    op.create_table(
        "critiques",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_slug"], ["snapshots.slug"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "COMMENT ON COLUMN critiques.payload IS 'Critique payload (DB model). Conversion to/from MCP model happens in critic layer.'"
    )

    # critic_runs (depends on prompts, snapshots, critiques, prompt_optimization_runs)
    op.create_table(
        "critic_runs",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("transcript_id", postgresql.UUID(), nullable=False),
        sa.Column("prompt_sha256", sa.String(64), nullable=False),
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("critique_id", postgresql.UUID(), nullable=True),
        sa.Column("prompt_optimization_run_id", postgresql.UUID(), nullable=True),
        sa.Column("files", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("files_hash", sa.String(64), nullable=False),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(), server_default=sa.text("'in_progress'"), nullable=False),
        sa.Column("completion_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["critique_id"], ["critiques.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prompt_optimization_run_id"], ["prompt_optimization_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prompt_sha256"], ["prompts.prompt_sha256"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_slug"], ["snapshots.slug"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transcript_id"),
    )

    # reported_issues (depends on critic_runs)
    op.create_table(
        "reported_issues",
        sa.Column("critic_run_id", postgresql.UUID(), nullable=False),
        sa.Column("issue_id", sa.String(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["critic_run_id"], ["critic_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("critic_run_id", "issue_id"),
    )

    # reported_issue_occurrences (depends on reported_issues composite FK)
    op.create_table(
        "reported_issue_occurrences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("critic_run_id", postgresql.UUID(), nullable=False),
        sa.Column("reported_issue_id", sa.String(), nullable=False),
        sa.Column("locations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("jsonb_array_length(locations) > 0", name="locations_not_empty"),
        sa.ForeignKeyConstraint(
            ["critic_run_id", "reported_issue_id"],
            ["reported_issues.critic_run_id", "reported_issues.issue_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # grader_runs (depends on critiques, snapshots, prompt_optimization_runs)
    op.create_table(
        "grader_runs",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("transcript_id", postgresql.UUID(), nullable=False),
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("critique_id", postgresql.UUID(), nullable=False),
        sa.Column("prompt_optimization_run_id", postgresql.UUID(), nullable=True),
        sa.Column("canonical_issues_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(), server_default=sa.text("'in_progress'"), nullable=False),
        sa.Column("completion_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["critique_id"], ["critiques.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prompt_optimization_run_id"], ["prompt_optimization_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_slug"], ["snapshots.slug"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transcript_id"),
    )
    op.execute(
        "COMMENT ON COLUMN grader_runs.canonical_issues_snapshot IS 'Snapshot of canonical TPs+FPs used at grading time'"
    )
    op.execute("COMMENT ON COLUMN grader_runs.output IS 'Grader output (DB model, flat structure).'")

    # grading_decisions (depends on grader_runs)
    op.create_table(
        "grading_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("grader_run_id", postgresql.UUID(), nullable=False),
        sa.Column("input_issue_id", sa.String(), nullable=False),
        sa.Column("target_tp_id", sa.String(), nullable=True),
        sa.Column("target_tp_occurrence_id", sa.String(), nullable=True),
        sa.Column("target_fp_id", sa.String(), nullable=True),
        sa.Column("target_fp_occurrence_id", sa.String(), nullable=True),
        sa.Column("credit", sa.Float(), nullable=False),
        sa.Column("match_type", sa.String(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("credit >= 0.0 AND credit <= 1.0", name="credit_in_range"),
        sa.CheckConstraint(
            "(target_tp_id IS NOT NULL AND target_tp_occurrence_id IS NOT NULL AND target_fp_id IS NULL AND target_fp_occurrence_id IS NULL) OR "
            "(target_tp_id IS NULL AND target_tp_occurrence_id IS NULL AND target_fp_id IS NOT NULL AND target_fp_occurrence_id IS NOT NULL) OR "
            "(target_tp_id IS NULL AND target_tp_occurrence_id IS NULL AND target_fp_id IS NULL AND target_fp_occurrence_id IS NULL)",
            name="exactly_one_target",
        ),
        sa.CheckConstraint(
            "(target_tp_id IS NOT NULL OR target_fp_id IS NOT NULL OR credit = 0.0)", name="no_match_zero_credit"
        ),
        sa.ForeignKeyConstraint(["grader_run_id"], ["grader_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # events (no FK dependencies, but logically after runs)
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transcript_id", postgresql.UUID(), nullable=False),
        sa.Column("sequence_num", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transcript_id", "sequence_num", name="uq_events_transcript_sequence"),
    )

    # unknown_clusters (depends on clustering_runs)
    op.create_table(
        "unknown_clusters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("clustering_run_id", sa.Integer(), nullable=False),
        sa.Column("cluster_name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["clustering_run_id"], ["clustering_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clustering_run_id", "cluster_name"),
    )

    # unknown_assignments (depends on unknown_clusters, clustering_runs, grader_runs)
    op.create_table(
        "unknown_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("clustering_run_id", sa.Integer(), nullable=False),
        sa.Column("grader_run_id", postgresql.UUID(), nullable=False),
        sa.Column("unknown_id", sa.String(), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=True),
        sa.Column("mapped_tp_id", sa.String(), nullable=True),
        sa.Column("mapped_fp_id", sa.String(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(cluster_id IS NOT NULL AND mapped_tp_id IS NULL AND mapped_fp_id IS NULL) OR "
            "(cluster_id IS NULL AND mapped_tp_id IS NOT NULL AND mapped_fp_id IS NULL) OR "
            "(cluster_id IS NULL AND mapped_tp_id IS NULL AND mapped_fp_id IS NOT NULL)",
            name="unknown_assignments_exactly_one_target_check",
        ),
        sa.ForeignKeyConstraint(["cluster_id"], ["unknown_clusters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["clustering_run_id"], ["clustering_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["grader_run_id"], ["grader_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "clustering_run_id", "grader_run_id", "unknown_id", "cancelled_at", name="unknown_assignments_unique_active"
        ),
    )

    # 3. RLS functions (before DEFAULT columns that reference them)

    # current_critic_run_id
    op.execute("""
        CREATE FUNCTION current_critic_run_id() RETURNS uuid
        LANGUAGE plpgsql STABLE
        AS $$
        DECLARE
            run_id_text TEXT;
        BEGIN
            run_id_text := SUBSTRING(current_user FROM 'critic_agent_([0-9a-f-]+)');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            RETURN run_id_text::UUID;
        END;
        $$
    """)

    # current_grader_run_id
    op.execute("""
        CREATE FUNCTION current_grader_run_id() RETURNS uuid
        LANGUAGE plpgsql STABLE
        AS $$
        DECLARE
            run_id_text TEXT;
        BEGIN
            run_id_text := SUBSTRING(current_user FROM 'grader_agent_([0-9a-f-]+)');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            RETURN run_id_text::UUID;
        END;
        $$
    """)

    # current_clustering_run_id
    op.execute("""
        CREATE FUNCTION current_clustering_run_id() RETURNS integer
        LANGUAGE plpgsql STABLE
        AS $$
        DECLARE
            run_id_text TEXT;
        BEGIN
            run_id_text := SUBSTRING(current_user FROM 'clustering_run_([0-9]+)_agent');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            RETURN run_id_text::INTEGER;
        END;
        $$
    """)

    # current_prompt_optimizer_run_id (IMPROVED - simplified parsing like other agents)
    op.execute("""
        CREATE FUNCTION current_prompt_optimizer_run_id() RETURNS uuid
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $$
        DECLARE
            username TEXT;
            run_id_text TEXT;
        BEGIN
            -- Use session_user instead of current_user because SECURITY DEFINER
            username := session_user;

            -- Simple extraction like critic/grader agents (username allows hyphens via quoting)
            run_id_text := SUBSTRING(username FROM 'prompt_optimizer_agent_([0-9a-f-]+)');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            RETURN run_id_text::UUID;
        END;
        $$
    """)

    # current_prompt_optimizer_target_metric
    op.execute("""
        CREATE FUNCTION current_prompt_optimizer_target_metric() RETURNS text
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $$
        DECLARE
            run_id UUID;
        BEGIN
            run_id := current_prompt_optimizer_run_id();
            IF run_id IS NULL THEN
                RETURN NULL;
            END IF;
            RETURN (
                SELECT config->>'target_metric'
                FROM prompt_optimization_runs
                WHERE id = run_id
            );
        END;
        $$
    """)
    op.execute("""
        COMMENT ON FUNCTION current_prompt_optimizer_target_metric() IS
        'Returns target_metric from prompt_optimization_runs.config for current user.
        Returns NULL if not a prompt optimizer user or run not found.
        Used by RLS policies to enforce mode-specific access rules.'
    """)

    # get_validation_run_aggregates (depends on occurrence_credits view, created later)
    # Will be created after views

    # 4. Add DEFAULT column values (after RLS functions exist)
    op.execute("ALTER TABLE reported_issues ALTER COLUMN critic_run_id SET DEFAULT current_critic_run_id()")
    op.execute("ALTER TABLE reported_issue_occurrences ALTER COLUMN critic_run_id SET DEFAULT current_critic_run_id()")
    op.execute("ALTER TABLE grading_decisions ALTER COLUMN grader_run_id SET DEFAULT current_grader_run_id()")

    # 5. Indexes (after tables)

    # prompts indexes
    op.create_index("ix_prompts_prompt_optimization_run_id", "prompts", ["prompt_optimization_run_id"])
    op.create_index("ix_prompts_template_file_path", "prompts", ["template_file_path"])

    # prompt_optimization_runs indexes
    op.create_index("ix_prompt_optimization_runs_transcript_id", "prompt_optimization_runs", ["transcript_id"])

    # examples indexes
    op.create_index("ix_examples_snapshot_slug", "examples", ["snapshot_slug"])
    op.execute(
        "CREATE UNIQUE INDEX uq_examples_file_set ON examples (snapshot_slug, files_hash) WHERE is_whole_snapshot = false"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_examples_whole_snapshot ON examples (snapshot_slug) WHERE is_whole_snapshot = true"
    )

    # true_positives indexes
    op.create_index("ix_true_positives_snapshot_slug", "true_positives", ["snapshot_slug"])

    # false_positives indexes
    op.create_index("ix_false_positives_snapshot_slug", "false_positives", ["snapshot_slug"])

    # clustering_runs indexes
    op.create_index("ix_clustering_runs_snapshot_slug", "clustering_runs", ["snapshot_slug"])
    op.create_index("ix_clustering_runs_status", "clustering_runs", ["status"])

    # critiques indexes
    op.create_index("ix_critiques_snapshot_slug", "critiques", ["snapshot_slug"])

    # critic_runs indexes
    op.create_index("ix_critic_runs_prompt_sha256", "critic_runs", ["prompt_sha256"])
    op.create_index("ix_critic_runs_snapshot_slug", "critic_runs", ["snapshot_slug"])
    op.create_index("ix_critic_runs_files_hash", "critic_runs", ["files_hash"])

    # reported_issues indexes
    op.create_index("ix_reported_issues_critic_run", "reported_issues", ["critic_run_id"])

    # reported_issue_occurrences indexes
    op.create_index(
        "ix_reported_issue_occurrences_reported_issue",
        "reported_issue_occurrences",
        ["critic_run_id", "reported_issue_id"],
    )

    # grader_runs indexes
    op.create_index("ix_grader_runs_snapshot_slug", "grader_runs", ["snapshot_slug"])

    # grading_decisions indexes
    op.create_index("ix_grading_decisions_grader_run", "grading_decisions", ["grader_run_id"])
    op.create_index("ix_grading_decisions_input_issue", "grading_decisions", ["grader_run_id", "input_issue_id"])
    op.create_index(
        "ix_grading_decisions_tp_occurrence",
        "grading_decisions",
        ["grader_run_id", "target_tp_id", "target_tp_occurrence_id"],
    )
    op.create_index(
        "ix_grading_decisions_fp_occurrence",
        "grading_decisions",
        ["grader_run_id", "target_fp_id", "target_fp_occurrence_id"],
    )

    # events indexes
    op.create_index("ix_events_transcript_id", "events", ["transcript_id"])

    # unknown_clusters indexes
    op.create_index("ix_unknown_clusters_clustering_run_id", "unknown_clusters", ["clustering_run_id"])

    # unknown_assignments indexes
    op.create_index("ix_unknown_assignments_clustering_run_id", "unknown_assignments", ["clustering_run_id"])
    op.create_index("ix_unknown_assignments_grader_run_id", "unknown_assignments", ["grader_run_id"])
    op.create_index("ix_unknown_assignments_grader_unknown", "unknown_assignments", ["grader_run_id", "unknown_id"])
    op.execute(
        "CREATE INDEX ix_unknown_assignments_active ON unknown_assignments (clustering_run_id, grader_run_id, unknown_id) WHERE cancelled_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_unknown_assignments_cluster_active ON unknown_assignments (cluster_id) WHERE cancelled_at IS NULL"
    )

    # 6. grading_credit_sums view (IMPROVEMENT - used by check_credit_sum trigger)
    op.execute("""
        CREATE VIEW grading_credit_sums AS
        SELECT
            grader_run_id,
            target_tp_id,
            target_tp_occurrence_id,
            target_fp_id,
            target_fp_occurrence_id,
            SUM(credit) as total_credit,
            COUNT(*) as num_decisions
        FROM grading_decisions
        WHERE (target_tp_id IS NOT NULL OR target_fp_id IS NOT NULL)
        GROUP BY grader_run_id, target_tp_id, target_tp_occurrence_id, target_fp_id, target_fp_occurrence_id
    """)

    # 7. check_credit_sum function (IMPROVED - uses view, no cancelled_at checks)
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
                WHERE grader_run_id = NEW.grader_run_id
                  AND target_tp_id = NEW.target_tp_id
                  AND target_tp_occurrence_id = NEW.target_tp_occurrence_id;

                -- On UPDATE, subtract old credit from current total
                IF TG_OP = 'UPDATE' THEN
                    current_total := current_total - OLD.credit;
                END IF;
            ELSE
                SELECT COALESCE(total_credit, 0.0) INTO current_total
                FROM grading_credit_sums
                WHERE grader_run_id = NEW.grader_run_id
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

    # 8. Trigger (after function and table)
    op.execute("""
        CREATE TRIGGER enforce_credit_sum
        BEFORE INSERT OR UPDATE ON grading_decisions
        FOR EACH ROW
        EXECUTE FUNCTION check_credit_sum()
    """)

    # 9. RLS policies (after tables and functions)

    # Enable RLS on tables
    for table in [
        "snapshots",
        "examples",
        "true_positives",
        "false_positives",
        "clustering_runs",
        "critiques",
        "critic_runs",
        "reported_issues",
        "reported_issue_occurrences",
        "grader_runs",
        "grading_decisions",
        "events",
        "unknown_clusters",
        "unknown_assignments",
    ]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    # Force RLS for specific tables
    for table in [
        "snapshots",
        "examples",
        "true_positives",
        "false_positives",
        "clustering_runs",
        "critiques",
        "critic_runs",
        "reported_issues",
        "reported_issue_occurrences",
        "grader_runs",
        "events",
        "unknown_clusters",
        "unknown_assignments",
    ]:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # Admin policies (postgres user)
    for table in [
        "snapshots",
        "examples",
        "true_positives",
        "false_positives",
        "critiques",
        "critic_runs",
        "grader_runs",
        "events",
    ]:
        op.execute(f"""
            CREATE POLICY admin_full_access_{table} ON {table}
            TO postgres
            USING (true)
            WITH CHECK (true)
        """)

    # Critic agent policies
    op.execute("""
        CREATE POLICY reported_issues_rls ON reported_issues
        USING (critic_run_id = current_critic_run_id())
        WITH CHECK (critic_run_id = current_critic_run_id())
    """)

    op.execute("""
        CREATE POLICY reported_issue_occurrences_rls ON reported_issue_occurrences
        USING (critic_run_id = current_critic_run_id())
        WITH CHECK (critic_run_id = current_critic_run_id())
    """)

    op.execute("""
        CREATE POLICY critic_agent_own_run ON critic_runs
        FOR SELECT
        USING (id = current_critic_run_id())
    """)

    # Grader agent policies (IMPROVED - added WITH CHECK)
    op.execute("""
        CREATE POLICY grading_decisions_rls ON grading_decisions
        USING (grader_run_id = current_grader_run_id())
        WITH CHECK (grader_run_id = current_grader_run_id())
    """)

    # Clustering agent policies
    op.execute("""
        CREATE POLICY clustering_user_clustering_runs_policy ON clustering_runs
        USING (CURRENT_USER ~ '^clustering_run_[0-9]+_agent$' AND id = current_clustering_run_id())
    """)

    op.execute("""
        CREATE POLICY clustering_user_unknown_clusters_policy ON unknown_clusters
        USING (CURRENT_USER ~ '^clustering_run_[0-9]+_agent$' AND clustering_run_id = current_clustering_run_id())
    """)

    op.execute("""
        CREATE POLICY clustering_user_unknown_assignments_policy ON unknown_assignments
        USING (CURRENT_USER ~ '^clustering_run_[0-9]+_agent$' AND clustering_run_id = current_clustering_run_id())
    """)

    for table in [
        "snapshots",
        "true_positives",
        "false_positives",
        "critiques",
        "critic_runs",
        "grader_runs",
        "events",
    ]:
        op.execute(f"""
            CREATE POLICY clustering_user_{table}_policy ON {table}
            FOR SELECT
            USING (CURRENT_USER ~ '^clustering_run_[0-9]+_agent$')
        """)

    # Prompt optimizer agent policies
    op.execute("""
        CREATE POLICY prompt_optimizer_snapshots ON snapshots
        FOR SELECT
        USING (current_prompt_optimizer_run_id() IS NOT NULL AND split IN ('train', 'valid'))
    """)

    op.execute("""
        CREATE POLICY prompt_optimizer_examples ON examples
        FOR SELECT
        USING (
            current_prompt_optimizer_run_id() IS NOT NULL AND (
                snapshot_slug IN (SELECT slug FROM snapshots WHERE split = 'train') OR
                (current_prompt_optimizer_target_metric() = 'targeted' AND
                 snapshot_slug IN (SELECT slug FROM snapshots WHERE split = 'valid'))
            )
        )
    """)
    op.execute("""
        COMMENT ON POLICY prompt_optimizer_examples ON examples IS
        'Prompt optimizer access to examples table:
        - TRAIN split: always accessible (both whole-repo and targeted modes)
        - VALID split: only accessible in targeted mode (filenames only - no ground truth)
        - TEST split: never accessible (off-limits)'
    """)

    for table in ["true_positives", "false_positives", "critiques", "critic_runs", "grader_runs"]:
        op.execute(f"""
            CREATE POLICY prompt_optimizer_{table} ON {table}
            FOR SELECT
            USING (
                current_prompt_optimizer_run_id() IS NOT NULL AND
                snapshot_slug IN (SELECT slug FROM snapshots WHERE split = 'train')
            )
        """)

    op.execute("""
        CREATE POLICY prompt_optimizer_events ON events
        FOR SELECT
        USING (
            current_prompt_optimizer_run_id() IS NOT NULL AND
            transcript_id IN (
                SELECT transcript_id FROM critic_runs WHERE snapshot_slug IN (SELECT slug FROM snapshots WHERE split = 'train')
                UNION
                SELECT transcript_id FROM grader_runs WHERE snapshot_slug IN (SELECT slug FROM snapshots WHERE split = 'train')
            )
        )
    """)

    # 10. Views (after all tables exist - complex aggregations)

    # occurrence_credits (complex, needs many tables)
    op.execute("""
        CREATE VIEW occurrence_credits AS
        -- Successful grader runs
        SELECT
            gr.id AS grader_run_id,
            gr.transcript_id AS grader_transcript_id,
            gr.created_at AS graded_at,
            gr.snapshot_slug,
            s.split,
            ex.files_hash,
            ex.is_whole_snapshot,
            ex.files AS reviewed_files,
            gr.critique_id,
            cr.id AS critic_run_id,
            cr.transcript_id AS critic_transcript_id,
            cr.prompt_sha256,
            p.prompt_text,
            p.prompt_optimization_run_id,
            cr.model AS critic_model,
            gr.model AS grader_model,
            occ_result.value->>'tp_id' AS tp_id,
            occ_result.value->>'occurrence_id' AS occurrence_id,
            (occ_result.value->>'found_credit')::float AS found_credit,
            occ_result.value->'matched_by' AS matched_by_json,
            occ_result.value->>'rationale' AS grader_rationale
        FROM grader_runs gr
        JOIN critiques c ON gr.critique_id = c.id
        JOIN critic_runs cr ON c.id = cr.critique_id
        JOIN snapshots s ON gr.snapshot_slug = s.slug
        JOIN examples ex ON (
            cr.snapshot_slug = ex.snapshot_slug AND
            (cr.files_hash = ex.files_hash OR ex.is_whole_snapshot = true)
        )
        JOIN prompts p ON cr.prompt_sha256 = p.prompt_sha256
        CROSS JOIN LATERAL jsonb_array_elements(gr.output->'occurrence_results') occ_result
        WHERE gr.output->>'tag' = 'success'

        UNION ALL

        -- Critic failures (max_turns, context_length) as zero-credit
        SELECT
            NULL AS grader_run_id,
            NULL AS grader_transcript_id,
            cr.created_at AS graded_at,
            cr.snapshot_slug,
            s.split,
            ex.files_hash,
            ex.is_whole_snapshot,
            ex.files AS reviewed_files,
            NULL AS critique_id,
            cr.id AS critic_run_id,
            cr.transcript_id AS critic_transcript_id,
            cr.prompt_sha256,
            p.prompt_text,
            p.prompt_optimization_run_id,
            cr.model AS critic_model,
            NULL AS grader_model,
            tp.tp_id,
            occ_data.value->>'occurrence_id' AS occurrence_id,
            0.0 AS found_credit,
            NULL AS matched_by_json,
            'Critic failed: ' || (cr.output->>'tag') AS grader_rationale
        FROM critic_runs cr
        JOIN snapshots s ON cr.snapshot_slug = s.slug
        JOIN examples ex ON (
            cr.snapshot_slug = ex.snapshot_slug AND
            (cr.files_hash = ex.files_hash OR ex.is_whole_snapshot = true)
        )
        JOIN prompts p ON cr.prompt_sha256 = p.prompt_sha256
        JOIN true_positives tp ON tp.snapshot_slug = ex.snapshot_slug
        CROSS JOIN LATERAL jsonb_array_elements(tp.occurrences) occ_data
        WHERE cr.output->>'tag' IN ('max_turns_exceeded', 'context_length_exceeded')
          AND cr.critique_id IS NULL
          AND (
              ex.is_whole_snapshot = true OR
              EXISTS (
                  SELECT 1 FROM jsonb_array_elements(occ_data.value->'expect_caught_from') trigger_set
                  WHERE (
                      SELECT bool_and(file_elem.value IN (SELECT jsonb_array_elements_text(ex.files)))
                      FROM jsonb_array_elements_text(trigger_set.value) file_elem
                  )
              )
          )
    """)

    # occurrence_run_credits (depends on occurrence_credits)
    op.execute("""
        CREATE VIEW occurrence_run_credits AS
        SELECT
            split,
            snapshot_slug,
            files_hash,
            is_whole_snapshot,
            tp_id,
            occurrence_id,
            critic_run_id,
            critic_model,
            prompt_sha256,
            AVG(found_credit) AS avg_credit,
            bool_or(grader_run_id IS NULL AND grader_rationale LIKE '%max_turns_exceeded%') AS is_max_turns_failure,
            bool_or(grader_run_id IS NULL AND grader_rationale LIKE '%context_length_exceeded%') AS is_context_failure
        FROM occurrence_credits
        GROUP BY split, snapshot_slug, files_hash, is_whole_snapshot, tp_id, occurrence_id, critic_run_id, critic_model, prompt_sha256
    """)

    # aggregated_recall_by_example (depends on occurrence_run_credits)
    op.execute("""
        CREATE VIEW aggregated_recall_by_example AS
        SELECT
            split,
            snapshot_slug,
            files_hash,
            critic_model,
            SUM(avg_credit) AS total_credit,
            COUNT(*) AS n_occurrences,
            SUM(avg_credit) / NULLIF(COUNT(*), 0) AS recall,
            COUNT(DISTINCT critic_run_id) AS n_critic_runs,
            COUNT(DISTINCT CASE WHEN is_max_turns_failure THEN critic_run_id END) AS n_max_turns_exceeded,
            COUNT(DISTINCT CASE WHEN is_context_failure THEN critic_run_id END) AS n_context_length_exceeded
        FROM occurrence_run_credits
        GROUP BY split, snapshot_slug, files_hash, critic_model
    """)

    # aggregated_recall_by_prompt (depends on occurrence_run_credits)
    op.execute("""
        CREATE VIEW aggregated_recall_by_prompt AS
        WITH per_run_recalls AS (
            SELECT
                split,
                prompt_sha256,
                critic_model,
                is_whole_snapshot,
                snapshot_slug,
                files_hash,
                critic_run_id,
                SUM(avg_credit) AS total_credit,
                COUNT(*) AS n_occurrences,
                SUM(avg_credit) / NULLIF(COUNT(*), 0) AS recall,
                bool_or(is_max_turns_failure) AS is_max_turns_failure,
                bool_or(is_context_failure) AS is_context_failure
            FROM occurrence_run_credits
            GROUP BY split, prompt_sha256, critic_model, is_whole_snapshot, snapshot_slug, files_hash, critic_run_id
        )
        SELECT
            split,
            prompt_sha256,
            critic_model,
            is_whole_snapshot,
            SUM(total_credit) AS total_credit,
            SUM(n_occurrences) AS n_occurrences,
            AVG(recall) AS recall,
            COUNT(DISTINCT snapshot_slug) AS n_snapshots,
            COUNT(DISTINCT files_hash) AS n_examples,
            COUNT(DISTINCT critic_run_id) AS n_runs,
            stddev(recall) AS recall_stddev,
            AVG(recall) + COALESCE(stddev(recall) / sqrt(COUNT(DISTINCT critic_run_id)), 0.0) AS ucb,
            AVG(recall) - COALESCE(stddev(recall) / sqrt(COUNT(DISTINCT critic_run_id)), 0.0) AS lcb,
            COUNT(DISTINCT CASE WHEN is_max_turns_failure THEN critic_run_id END) AS n_max_turns_exceeded,
            COUNT(DISTINCT CASE WHEN is_context_failure THEN critic_run_id END) AS n_context_length_exceeded
        FROM per_run_recalls
        GROUP BY split, prompt_sha256, critic_model, is_whole_snapshot
    """)
    op.execute("""
        COMMENT ON VIEW aggregated_recall_by_prompt IS
        'Aggregates recall metrics by prompt across all examples and runs.
        Includes sample size (n_examples, n_runs) and confidence bounds (ucb, lcb) for variance awareness.
        Per-run recall is computed first, then aggregated (stddev is stddev of per-run recalls).'
    """)

    # occurrence_statistics (depends on occurrence_run_credits)
    op.execute("""
        CREATE VIEW occurrence_statistics AS
        SELECT
            split,
            tp_id,
            occurrence_id,
            critic_model,
            AVG(avg_credit) AS mean_credit,
            stddev(avg_credit) AS stddev_credit,
            MIN(avg_credit) AS min_credit,
            MAX(avg_credit) AS max_credit,
            COUNT(*) AS n_critic_runs,
            COUNT(DISTINCT prompt_sha256) AS n_prompts,
            SUM(CASE WHEN avg_credit = 1.0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) AS full_catch_rate
        FROM occurrence_run_credits
        GROUP BY split, tp_id, occurrence_id, critic_model
    """)

    # run_costs (needs events + model_metadata)
    op.execute("""
        CREATE VIEW run_costs AS
        SELECT
            (events.payload->'response_id')::text AS response_id,
            events.transcript_id,
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
        JOIN model_metadata ON ((events.payload->'usage'->'model')::text = model_metadata.model_id)
        WHERE events.event_type = 'response' AND events.payload->'usage' IS NOT NULL
    """)

    # snapshot_files_with_issues (needs TPs/FPs + snapshots)
    op.execute("""
        CREATE VIEW snapshot_files_with_issues AS
        SELECT
            anon_1.snapshot_slug,
            array_agg(DISTINCT anon_1.file_path) AS files_with_issues
        FROM (
            SELECT
                true_positives.snapshot_slug,
                jsonb_object_keys(jsonb_array_elements(true_positives.occurrences)->'files') AS file_path
            FROM true_positives
            UNION ALL
            SELECT
                false_positives.snapshot_slug,
                jsonb_object_keys(jsonb_array_elements(false_positives.occurrences)->'files') AS file_path
            FROM false_positives
        ) anon_1
        JOIN snapshots ON anon_1.snapshot_slug = snapshots.slug
        GROUP BY anon_1.snapshot_slug
    """)

    # get_validation_run_aggregates function (depends on occurrence_credits view)
    op.execute("""
        CREATE FUNCTION get_validation_run_aggregates()
        RETURNS TABLE(
            snapshot_slug text,
            prompt_sha256 text,
            critic_model text,
            grader_model text,
            critic_run_id uuid,
            grader_run_id uuid,
            total_credit double precision,
            n_occurrences integer
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path TO 'public'
        AS $$
          WITH occurrence_avg_credits AS (
            SELECT
                oc.snapshot_slug,
                oc.prompt_sha256,
                oc.critic_model,
                oc.grader_model,
                oc.critic_run_id,
                oc.grader_run_id,
                oc.tp_id,
                oc.occurrence_id,
                AVG(oc.found_credit) as avg_credit
            FROM occurrence_credits oc
            JOIN snapshots s ON oc.snapshot_slug = s.slug
            WHERE s.split = 'valid'::split_enum
              AND oc.is_whole_snapshot = true
            GROUP BY oc.snapshot_slug, oc.prompt_sha256, oc.critic_model, oc.grader_model,
                     oc.critic_run_id, oc.grader_run_id, oc.tp_id, oc.occurrence_id
          )
          SELECT
            snapshot_slug,
            prompt_sha256,
            critic_model,
            grader_model,
            critic_run_id,
            grader_run_id,
            SUM(avg_credit) as total_credit,
            CAST(COUNT(*) AS integer) as n_occurrences
          FROM occurrence_avg_credits
          GROUP BY snapshot_slug, prompt_sha256, critic_model, grader_model,
                   critic_run_id, grader_run_id
          ORDER BY grader_run_id DESC
        $$
    """)
    op.execute("""
        COMMENT ON FUNCTION get_validation_run_aggregates() IS
        'Returns per-run aggregated validation performance for all full-snapshot runs on ''valid'' split only (''test'' split is off-limits).
        Accessible by prompt optimizer agents via SECURITY DEFINER privilege escalation.
        Individual prompt optimizer users receive EXECUTE permission via PromptOptimizerUserManager.
        Returns one row per (snapshot_slug, prompt_sha256, critic_model, grader_model, critic_run_id, grader_run_id).
        Rows ordered by grader_run_id DESC so most recent runs appear first.
        Agent can filter with WHERE clauses: WHERE prompt_sha256 = ''abc123...'' OR critic_run_id = 123'
    """)

    # 11. Materialized views (after regular views)
    op.execute("""
        CREATE MATERIALIZED VIEW grading_credit_totals AS
        SELECT
            grader_run_id,
            target_tp_id,
            target_tp_occurrence_id,
            target_fp_id,
            target_fp_occurrence_id,
            SUM(credit) AS total_credit,
            COUNT(*) AS num_inputs_matched
        FROM grading_decisions
        WHERE target_tp_id IS NOT NULL OR target_fp_id IS NOT NULL
        GROUP BY grader_run_id, target_tp_id, target_tp_occurrence_id, target_fp_id, target_fp_occurrence_id
        WITH NO DATA
    """)

    # 12. Indexes on materialized views
    op.execute(
        "CREATE UNIQUE INDEX ix_grading_credit_totals_tp ON grading_credit_totals (grader_run_id, target_tp_id, target_tp_occurrence_id) WHERE target_tp_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_grading_credit_totals_fp ON grading_credit_totals (grader_run_id, target_fp_id, target_fp_occurrence_id) WHERE target_fp_id IS NOT NULL"
    )


def downgrade() -> None:
    """Drop complete schema in reverse order."""

    # 1. Drop indexes on materialized views
    op.execute("DROP INDEX IF EXISTS ix_grading_credit_totals_fp")
    op.execute("DROP INDEX IF EXISTS ix_grading_credit_totals_tp")

    # 2. Drop materialized views
    op.execute("DROP MATERIALIZED VIEW IF EXISTS grading_credit_totals CASCADE")

    # 3. Drop regular views
    op.execute("DROP VIEW IF EXISTS snapshot_files_with_issues CASCADE")
    op.execute("DROP VIEW IF EXISTS run_costs CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_statistics CASCADE")
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE")
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_run_credits CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_credits CASCADE")
    op.execute("DROP VIEW IF EXISTS grading_credit_sums CASCADE")

    # 4. Drop functions
    op.execute("DROP FUNCTION IF EXISTS get_validation_run_aggregates() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS check_credit_sum() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS current_prompt_optimizer_target_metric() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS current_prompt_optimizer_run_id() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS current_clustering_run_id() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS current_grader_run_id() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS current_critic_run_id() CASCADE")

    # 5. Drop triggers (CASCADE from function drops will handle this)
    # (Triggers are dropped automatically when functions are dropped)

    # 6. Drop RLS policies (CASCADE from table drops will handle these)
    # (Policies are dropped automatically when tables are dropped)

    # 7. Disable RLS (will be dropped with tables)

    # 8. Drop tables (reverse dependency order, CASCADE handles FKs)
    op.drop_table("unknown_assignments")
    op.drop_table("unknown_clusters")
    op.drop_table("events")
    op.drop_table("grading_decisions")
    op.drop_table("grader_runs")
    op.drop_table("reported_issue_occurrences")
    op.drop_table("reported_issues")
    op.drop_table("critic_runs")
    op.drop_table("critiques")
    op.drop_table("clustering_runs")
    op.drop_table("false_positives")
    op.drop_table("true_positives")
    op.drop_table("examples")
    op.drop_table("model_metadata")
    op.drop_table("prompts")
    op.drop_table("prompt_optimization_runs")
    op.drop_table("snapshots")

    # 9. Drop custom types
    op.execute("DROP TYPE IF EXISTS split_enum CASCADE")

    # Note: Sequences are dropped automatically via CASCADE on tables
