"""initial_schema_squashed

Complete initial schema including tables, RLS policies, grants, and views.

Revision ID: 20251214000000
Revises:
Create Date: 2025-12-14 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from adgn.props.db.query_builders import compile_to_sql, snapshot_files_with_issues_select

# revision identifiers, used by Alembic.
revision: str = "20251214000000"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create complete initial schema from scratch.

    Includes:
    - All tables (from ORM models)
    - Enums (split_enum)
    - current_clustering_run_id() function
    - RLS policies (clustering_user)
    - Views (snapshot_files_with_issues, valid_metrics)
    """

    # =============================================================================
    # 1. ENUMS
    # =============================================================================

    # Create enum type manually to avoid double-creation
    op.execute("CREATE TYPE split_enum AS ENUM ('train', 'valid', 'test')")

    # =============================================================================
    # 2. TABLES (in dependency order)
    # =============================================================================

    # Create model_metadata table
    op.create_table(
        "model_metadata",
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("input_usd_per_1m_tokens", sa.Float(), nullable=False),
        sa.Column("cached_input_usd_per_1m_tokens", sa.Float(), nullable=True),
        sa.Column("output_usd_per_1m_tokens", sa.Float(), nullable=False),
        sa.Column("context_window_tokens", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("model_id"),
    )

    # Create prompt_optimization_runs table
    op.create_table(
        "prompt_optimization_runs",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("transcript_id", sa.UUID(), nullable=True),
        sa.Column("budget_limit", sa.Float(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prompt_optimization_runs_transcript_id", "prompt_optimization_runs", ["transcript_id"])

    # Create snapshots table
    op.create_table(
        "snapshots",
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column(
            "split", postgresql.ENUM("train", "valid", "test", name="split_enum", create_type=False), nullable=False
        ),
        sa.Column("source", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("bundle", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("slug"),
    )

    # Create prompts table
    op.create_table(
        "prompts",
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("prompt_optimization_run_id", sa.UUID(), nullable=True),
        sa.Column("template_file_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["prompt_optimization_run_id"], ["prompt_optimization_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("prompt_sha256"),
    )
    op.create_index("ix_prompts_prompt_optimization_run_id", "prompts", ["prompt_optimization_run_id"])
    op.create_index("ix_prompts_template_file_path", "prompts", ["template_file_path"])

    # Create critiques table
    op.create_table(
        "critiques",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Critique payload (DB model). Conversion to/from MCP model happens in critic layer.",
        ),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["snapshot_slug"], ["snapshots.slug"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_critiques_snapshot_slug", "critiques", ["snapshot_slug"])

    # Create examples table (formerly critic_scopes)
    op.create_table(
        "examples",
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column(
            "files_hash",
            sa.String(length=64),
            nullable=False,
            comment="SHA256 hash of normalized files field for uniqueness",
        ),
        sa.Column(
            "files", postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment="List of file paths to review"
        ),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["snapshot_slug"], ["snapshots.slug"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("snapshot_slug", "files_hash"),
    )
    op.create_index("ix_examples_snapshot_slug", "examples", ["snapshot_slug"])

    # Create true_positives table
    op.create_table(
        "true_positives",
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column("tp_id", sa.String(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("occurrences", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["snapshot_slug"], ["snapshots.slug"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("snapshot_slug", "tp_id"),
    )
    op.create_index("ix_true_positives_snapshot_slug", "true_positives", ["snapshot_slug"])

    # Create false_positives table
    op.create_table(
        "false_positives",
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column("fp_id", sa.String(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("occurrences", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["snapshot_slug"], ["snapshots.slug"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("snapshot_slug", "fp_id"),
    )
    op.create_index("ix_false_positives_snapshot_slug", "false_positives", ["snapshot_slug"])

    # Create critic_runs table
    op.create_table(
        "critic_runs",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("transcript_id", sa.UUID(), nullable=False),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("critique_id", sa.UUID(), nullable=True),
        sa.Column("prompt_optimization_run_id", sa.UUID(), nullable=True),
        sa.Column("files", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("files_hash", sa.String(length=64), nullable=False),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["critique_id"], ["critiques.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prompt_optimization_run_id"], ["prompt_optimization_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prompt_sha256"], ["prompts.prompt_sha256"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_slug"], ["snapshots.slug"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transcript_id"),
    )
    op.create_index("ix_critic_runs_prompt_sha256", "critic_runs", ["prompt_sha256"])
    op.create_index("ix_critic_runs_snapshot_slug", "critic_runs", ["snapshot_slug"])
    op.create_index("ix_critic_runs_files_hash", "critic_runs", ["files_hash"])

    # Create grader_runs table
    op.create_table(
        "grader_runs",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("transcript_id", sa.UUID(), nullable=False),
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("critique_id", sa.UUID(), nullable=False),
        sa.Column("prompt_optimization_run_id", sa.UUID(), nullable=True),
        sa.Column(
            "canonical_issues_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Snapshot of canonical TPs+FPs used at grading time",
        ),
        sa.Column(
            "output",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Grader output (DB model, flat structure).",
        ),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["critique_id"], ["critiques.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prompt_optimization_run_id"], ["prompt_optimization_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_slug"], ["snapshots.slug"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transcript_id"),
    )
    op.create_index("ix_grader_runs_snapshot_slug", "grader_runs", ["snapshot_slug"])

    # Create events table
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transcript_id", sa.UUID(), nullable=False),
        sa.Column("sequence_num", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("timestamp", sa.TIMESTAMP(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transcript_id", "sequence_num", name="uq_events_transcript_sequence"),
    )
    op.create_index("ix_events_transcript_id", "events", ["transcript_id"])

    # Create clustering_runs table
    op.create_table(
        "clustering_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_slug", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="in_progress"),
        sa.Column("transcript_id", sa.String(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(
            ["snapshot_slug"], ["snapshots.slug"], name="clustering_runs_snapshot_slug_fkey", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('in_progress', 'completed', 'abandoned')", name="clustering_runs_status_check"),
    )
    op.create_index("ix_clustering_runs_snapshot_slug", "clustering_runs", ["snapshot_slug"])
    op.create_index("ix_clustering_runs_status", "clustering_runs", ["status"])

    # Create unknown_clusters table
    op.create_table(
        "unknown_clusters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("clustering_run_id", sa.Integer(), nullable=False),
        sa.Column("cluster_name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["clustering_run_id"], ["clustering_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "clustering_run_id", "cluster_name", name="unknown_clusters_clustering_run_id_cluster_name_key"
        ),
    )
    op.create_index("ix_unknown_clusters_clustering_run_id", "unknown_clusters", ["clustering_run_id"])

    # Create unknown_assignments table
    op.create_table(
        "unknown_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("clustering_run_id", sa.Integer(), nullable=False),
        sa.Column("grader_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("unknown_id", sa.String(), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=True),
        sa.Column("mapped_tp_id", sa.String(), nullable=True),
        sa.Column("mapped_fp_id", sa.String(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.Column("cancelled_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["cluster_id"], ["unknown_clusters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["clustering_run_id"], ["clustering_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["grader_run_id"], ["grader_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "clustering_run_id", "grader_run_id", "unknown_id", "cancelled_at", name="unknown_assignments_unique_active"
        ),
        sa.CheckConstraint(
            """
            (cluster_id IS NOT NULL AND mapped_tp_id IS NULL AND mapped_fp_id IS NULL) OR
            (cluster_id IS NULL AND mapped_tp_id IS NOT NULL AND mapped_fp_id IS NULL) OR
            (cluster_id IS NULL AND mapped_tp_id IS NULL AND mapped_fp_id IS NOT NULL)
            """,
            name="unknown_assignments_exactly_one_target_check",
        ),
    )
    op.create_index("ix_unknown_assignments_clustering_run_id", "unknown_assignments", ["clustering_run_id"])
    op.create_index("ix_unknown_assignments_grader_run_id", "unknown_assignments", ["grader_run_id"])
    op.create_index("ix_unknown_assignments_grader_unknown", "unknown_assignments", ["grader_run_id", "unknown_id"])

    # Partial indexes for active (non-cancelled) assignments
    op.execute("""
        CREATE INDEX ix_unknown_assignments_active
        ON unknown_assignments (clustering_run_id, grader_run_id, unknown_id)
        WHERE cancelled_at IS NULL
    """)
    op.execute("""
        CREATE INDEX ix_unknown_assignments_cluster_active
        ON unknown_assignments (cluster_id)
        WHERE cancelled_at IS NULL
    """)

    # =============================================================================
    # 3. RLS HELPER FUNCTION
    # =============================================================================

    op.execute("""
        CREATE OR REPLACE FUNCTION current_clustering_run_id() RETURNS INTEGER AS $$
        DECLARE
            run_id_text TEXT;
        BEGIN
            -- Extract run_id from username pattern: clustering_run_{run_id}_agent
            run_id_text := SUBSTRING(current_user FROM 'clustering_run_([0-9]+)_agent');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            RETURN run_id_text::INTEGER;
        EXCEPTION
            WHEN OTHERS THEN
                RETURN NULL;
        END;
        $$ LANGUAGE plpgsql STABLE SECURITY DEFINER;
    """)

    # =============================================================================
    # 4. ENABLE RLS
    # =============================================================================

    rls_tables = [
        "snapshots",
        "true_positives",
        "false_positives",
        "critiques",
        "critic_runs",
        "grader_runs",
        "events",
        "clustering_runs",
        "unknown_clusters",
        "unknown_assignments",
    ]

    for table_name in rls_tables:
        op.execute(f"""
            DO $$
            BEGIN
                ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;
                ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;
            EXCEPTION
                WHEN OTHERS THEN
                    -- Already enabled, skip
                    NULL;
            END $$;
        """)

    # =============================================================================
    # 5. CREATE RLS POLICIES
    # =============================================================================

    def create_policy(table: str, policy_name: str, rule: str) -> None:
        """Helper: create RLS policy if it doesn't exist."""
        clean_rule = " ".join(rule.split())
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE schemaname = 'public'
                    AND tablename = '{table}'
                    AND policyname = '{policy_name}'
                ) THEN
                    CREATE POLICY {policy_name} ON {table} {clean_rule};
                END IF;
            END $$;
        """)

    # clustering_user policies (FOR PUBLIC with username pattern)
    # Pattern: scoped temporary user matching ^clustering_run_[0-9]+_agent$
    clustering_username_check = "current_user ~ '^clustering_run_[0-9]+_agent$'"

    clustering_user_policies = {
        "clustering_runs": f"""
            FOR ALL TO PUBLIC
            USING ({clustering_username_check} AND id = current_clustering_run_id())
        """,
        "unknown_clusters": f"""
            FOR ALL TO PUBLIC
            USING ({clustering_username_check} AND clustering_run_id = current_clustering_run_id())
        """,
        "unknown_assignments": f"""
            FOR ALL TO PUBLIC
            USING ({clustering_username_check} AND clustering_run_id = current_clustering_run_id())
        """,
    }

    # Read-only access to reference tables for clustering users
    clustering_readonly_tables = [
        "snapshots",
        "true_positives",
        "false_positives",
        "critiques",
        "critic_runs",
        "grader_runs",
        "events",
    ]
    for table_name in clustering_readonly_tables:
        clustering_user_policies[table_name] = f"FOR SELECT TO PUBLIC USING ({clustering_username_check})"

    for table_name, rule in clustering_user_policies.items():
        create_policy(table_name, f"clustering_user_{table_name}_policy", rule)

    # =============================================================================
    # 6. GRANTS
    # =============================================================================

    def grant_select_to_user(table: str, user: str) -> None:
        """Helper: grant SELECT on table to user if table exists."""
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = '{table}') THEN
                    EXECUTE 'GRANT SELECT ON TABLE {table} TO {user}';
                END IF;
            END $$;
        """)

    # =============================================================================
    # 7. CREATE VIEWS
    # =============================================================================

    # Build view SELECT queries
    snapshot_files_sql = compile_to_sql(snapshot_files_with_issues_select())

    # Drop old view names if they exist (migration from older schema)
    op.execute("DROP VIEW IF EXISTS valid_grader_metrics")
    op.execute("DROP VIEW IF EXISTS valid_full_snapshot_grader_metrics")
    op.execute(
        "DROP VIEW IF EXISTS valid_metrics"
    )  # Obsolete view, replaced by occurrence views in migration 20251215000002

    # Create snapshot_files_with_issues view
    op.execute("DROP VIEW IF EXISTS snapshot_files_with_issues CASCADE")
    op.execute(f"CREATE VIEW snapshot_files_with_issues AS {snapshot_files_sql}")

    # Create run_costs view (aggregates token usage and costs from Event table)
    # Note: This view was previously created via SQLAlchemy event hook, now managed by Alembic
    op.execute("DROP TABLE IF EXISTS run_costs CASCADE")  # Drop old table from earlier schema versions
    op.execute("DROP VIEW IF EXISTS run_costs CASCADE")
    op.execute("""
        CREATE VIEW run_costs AS
        SELECT
            (events.payload -> 'response_id')::text AS response_id,
            events.transcript_id,
            (events.payload -> 'usage' -> 'model')::text AS model,
            ((events.payload -> 'usage' -> 'input_tokens')::text)::integer AS input_tokens,
            COALESCE(((events.payload -> 'usage' -> 'input_tokens_details' -> 'cached_tokens')::text)::integer, 0) AS cached_tokens,
            ((events.payload -> 'usage' -> 'output_tokens')::text)::integer AS output_tokens,
            COALESCE(((events.payload -> 'usage' -> 'output_tokens_details' -> 'reasoning_tokens')::text)::integer, 0) AS reasoning_tokens,
            (
                (((events.payload -> 'usage' -> 'input_tokens')::text)::integer - COALESCE(((events.payload -> 'usage' -> 'input_tokens_details' -> 'cached_tokens')::text)::integer, 0))
                * model_metadata.input_usd_per_1m_tokens / 1000000.0
                + COALESCE(((events.payload -> 'usage' -> 'input_tokens_details' -> 'cached_tokens')::text)::integer, 0)
                * model_metadata.cached_input_usd_per_1m_tokens / 1000000.0
                + ((events.payload -> 'usage' -> 'output_tokens')::text)::integer
                * model_metadata.output_usd_per_1m_tokens / 1000000.0
            ) AS cost_usd,
            events.timestamp
        FROM events
        JOIN model_metadata ON (events.payload -> 'usage' -> 'model')::text = model_metadata.model_id
        WHERE events.event_type = 'response' AND events.payload -> 'usage' IS NOT NULL
    """)


def downgrade() -> None:
    """Drop all schema objects.

    Note: This is destructive and should only be used in development.
    """
    # Drop views
    op.execute("DROP VIEW IF EXISTS valid_metrics")
    op.execute("DROP VIEW IF EXISTS snapshot_files_with_issues CASCADE")
    op.execute("DROP VIEW IF EXISTS run_costs")

    # Drop tables (in reverse dependency order)
    op.drop_table("unknown_assignments")
    op.drop_table("unknown_clusters")
    op.drop_table("clustering_runs")
    op.drop_table("events")
    op.drop_table("grader_runs")
    op.drop_table("critic_runs")
    op.drop_table("false_positives")
    op.drop_table("true_positives")
    op.drop_table("examples")
    op.drop_table("critiques")
    op.drop_table("prompts")
    op.drop_table("snapshots")
    op.drop_table("prompt_optimization_runs")
    op.drop_table("model_metadata")

    # Drop function
    op.execute("DROP FUNCTION IF EXISTS current_clustering_run_id()")

    # Drop enum
    op.execute("DROP TYPE IF EXISTS split_enum")
