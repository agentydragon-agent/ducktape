"""Migrate clustering tables to use agent_run_id.

This migration:
1. Adds agent_run_id UUID column to unknown_clusters and unknown_assignments
2. Adds FK to agent_runs for both tables
3. Drops old clustering_run_id integer FK
4. Drops the clustering_runs table (replaced by agent_runs with CLUSTERING type)
5. Updates RLS policies for clustering tables to use agent_run_id

NOTE: This is a destructive migration - existing clustering data is not preserved.
Run this only after migrating to the new clustering agent code.

Revision ID: 20251228000000
Revises: 20251227000000
Create Date: 2025-12-28
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20251228000000"
down_revision: str | Sequence[str] | None = "20251227000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Migrate clustering tables from clustering_run_id to agent_run_id."""
    # Step 1: Drop RLS policies that reference old columns/functions
    op.execute("""
        DROP POLICY IF EXISTS clustering_user_unknown_clusters_policy ON unknown_clusters;
        DROP POLICY IF EXISTS clustering_user_unknown_assignments_policy ON unknown_assignments;
        DROP POLICY IF EXISTS clustering_user_clustering_runs_policy ON clustering_runs;
    """)

    # Step 2: Drop old indexes
    op.execute("""
        DROP INDEX IF EXISTS ix_unknown_clusters_clustering_run_id;
        DROP INDEX IF EXISTS ix_unknown_assignments_clustering_run_id;
        DROP INDEX IF EXISTS ix_unknown_assignments_active;
    """)

    # Step 3: Drop FK constraints before modifying columns
    op.execute("""
        ALTER TABLE unknown_clusters
            DROP CONSTRAINT IF EXISTS unknown_clusters_clustering_run_id_fkey;
        ALTER TABLE unknown_assignments
            DROP CONSTRAINT IF EXISTS unknown_assignments_clustering_run_id_fkey;
        -- Also drop old grader_run_id FK that pointed to grader_runs table
        ALTER TABLE unknown_assignments
            DROP CONSTRAINT IF EXISTS unknown_assignments_grader_run_id_fkey;
    """)

    # Step 4: Drop unique constraints that reference clustering_run_id
    op.execute("""
        ALTER TABLE unknown_clusters
            DROP CONSTRAINT IF EXISTS unknown_clusters_clustering_run_id_cluster_name_key;
        ALTER TABLE unknown_assignments
            DROP CONSTRAINT IF EXISTS unknown_assignments_unique_active;
    """)

    # Step 5: Drop old clustering_run_id columns
    op.execute("ALTER TABLE unknown_clusters DROP COLUMN IF EXISTS clustering_run_id")
    op.execute("ALTER TABLE unknown_assignments DROP COLUMN IF EXISTS clustering_run_id")

    # Step 6: Add new agent_run_id UUID columns
    op.add_column("unknown_clusters", sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=False))
    op.add_column("unknown_assignments", sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=False))

    # Step 7: Add FK constraints to agent_runs
    op.create_foreign_key(
        "fk_unknown_clusters_agent_run_id",
        "unknown_clusters",
        "agent_runs",
        ["agent_run_id"],
        ["agent_run_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_unknown_assignments_agent_run_id",
        "unknown_assignments",
        "agent_runs",
        ["agent_run_id"],
        ["agent_run_id"],
        ondelete="CASCADE",
    )
    # grader_run_id now also references agent_runs (grader's agent_run_id)
    op.create_foreign_key(
        "fk_unknown_assignments_grader_run_id",
        "unknown_assignments",
        "agent_runs",
        ["grader_run_id"],
        ["agent_run_id"],
        ondelete="CASCADE",
    )

    # Step 8: Create new indexes
    op.create_index("ix_unknown_clusters_agent_run_id", "unknown_clusters", ["agent_run_id"])
    op.create_index("ix_unknown_assignments_agent_run_id", "unknown_assignments", ["agent_run_id"])
    op.execute("""
        CREATE INDEX ix_unknown_assignments_active
            ON unknown_assignments (agent_run_id, grader_run_id, unknown_id)
            WHERE cancelled_at IS NULL
    """)

    # Step 9: Create new unique constraints
    op.create_unique_constraint(
        "uq_unknown_clusters_agent_run_cluster_name", "unknown_clusters", ["agent_run_id", "cluster_name"]
    )
    op.create_unique_constraint(
        "uq_unknown_assignments_unique_active",
        "unknown_assignments",
        ["agent_run_id", "grader_run_id", "unknown_id", "cancelled_at"],
    )

    # Step 10: Create new RLS policies using current_agent_run_id()
    op.execute("""
        CREATE POLICY unknown_clusters_agent_select ON unknown_clusters
            FOR SELECT
            USING (agent_run_id = current_agent_run_id());

        CREATE POLICY unknown_clusters_agent_insert ON unknown_clusters
            FOR INSERT
            WITH CHECK (agent_run_id = current_agent_run_id());

        CREATE POLICY unknown_clusters_agent_update ON unknown_clusters
            FOR UPDATE
            USING (agent_run_id = current_agent_run_id());
    """)

    op.execute("""
        CREATE POLICY unknown_assignments_agent_select ON unknown_assignments
            FOR SELECT
            USING (agent_run_id = current_agent_run_id());

        CREATE POLICY unknown_assignments_agent_insert ON unknown_assignments
            FOR INSERT
            WITH CHECK (agent_run_id = current_agent_run_id());

        CREATE POLICY unknown_assignments_agent_update ON unknown_assignments
            FOR UPDATE
            USING (agent_run_id = current_agent_run_id());
    """)

    # Step 11: Grant permissions to agent_base role
    op.execute("""
        GRANT SELECT, INSERT, UPDATE ON unknown_clusters TO agent_base;
        GRANT SELECT, INSERT, UPDATE ON unknown_assignments TO agent_base;
        GRANT USAGE, SELECT ON SEQUENCE unknown_clusters_id_seq TO agent_base;
        GRANT USAGE, SELECT ON SEQUENCE unknown_assignments_id_seq TO agent_base;
    """)

    # Step 12: Drop clustering_runs table (no longer needed)
    op.execute("DROP TABLE IF EXISTS clustering_runs CASCADE")


def downgrade() -> None:
    """Revert clustering tables to use clustering_run_id."""
    # Step 1: Recreate clustering_runs table
    op.execute("""
        CREATE TABLE clustering_runs (
            id SERIAL PRIMARY KEY,
            snapshot_slug TEXT NOT NULL REFERENCES snapshots(slug) ON DELETE CASCADE,
            status VARCHAR NOT NULL DEFAULT 'in_progress'
                CHECK (status IN ('in_progress', 'completed', 'abandoned')),
            transcript_id TEXT,
            started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMP WITH TIME ZONE
        );

        ALTER TABLE clustering_runs ENABLE ROW LEVEL SECURITY;
    """)

    # Step 2: Drop new RLS policies
    op.execute("""
        DROP POLICY IF EXISTS unknown_clusters_agent_select ON unknown_clusters;
        DROP POLICY IF EXISTS unknown_clusters_agent_insert ON unknown_clusters;
        DROP POLICY IF EXISTS unknown_clusters_agent_update ON unknown_clusters;
        DROP POLICY IF EXISTS unknown_assignments_agent_select ON unknown_assignments;
        DROP POLICY IF EXISTS unknown_assignments_agent_insert ON unknown_assignments;
        DROP POLICY IF EXISTS unknown_assignments_agent_update ON unknown_assignments;
    """)

    # Step 3: Revoke permissions from agent_base
    op.execute("""
        REVOKE SELECT, INSERT, UPDATE ON unknown_clusters FROM agent_base;
        REVOKE SELECT, INSERT, UPDATE ON unknown_assignments FROM agent_base;
        REVOKE USAGE, SELECT ON SEQUENCE unknown_clusters_id_seq FROM agent_base;
        REVOKE USAGE, SELECT ON SEQUENCE unknown_assignments_id_seq FROM agent_base;
    """)

    # Step 4: Drop new unique constraints
    op.drop_constraint("uq_unknown_clusters_agent_run_cluster_name", "unknown_clusters", type_="unique")
    op.drop_constraint("uq_unknown_assignments_unique_active", "unknown_assignments", type_="unique")

    # Step 5: Drop new indexes
    op.drop_index("ix_unknown_clusters_agent_run_id", table_name="unknown_clusters")
    op.drop_index("ix_unknown_assignments_agent_run_id", table_name="unknown_assignments")
    op.execute("DROP INDEX IF EXISTS ix_unknown_assignments_active")

    # Step 6: Drop new FK constraints
    op.drop_constraint("fk_unknown_clusters_agent_run_id", "unknown_clusters", type_="foreignkey")
    op.drop_constraint("fk_unknown_assignments_agent_run_id", "unknown_assignments", type_="foreignkey")
    op.drop_constraint("fk_unknown_assignments_grader_run_id", "unknown_assignments", type_="foreignkey")

    # Step 7: Drop agent_run_id columns
    op.drop_column("unknown_clusters", "agent_run_id")
    op.drop_column("unknown_assignments", "agent_run_id")

    # Step 8: Add back clustering_run_id columns
    op.add_column("unknown_clusters", sa.Column("clustering_run_id", sa.Integer(), nullable=False))
    op.add_column("unknown_assignments", sa.Column("clustering_run_id", sa.Integer(), nullable=False))

    # Step 9: Add back FK constraints
    op.create_foreign_key(
        "unknown_clusters_clustering_run_id_fkey",
        "unknown_clusters",
        "clustering_runs",
        ["clustering_run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "unknown_assignments_clustering_run_id_fkey",
        "unknown_assignments",
        "clustering_runs",
        ["clustering_run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # Restore grader_run_id FK to grader_runs table
    op.create_foreign_key(
        "unknown_assignments_grader_run_id_fkey",
        "unknown_assignments",
        "grader_runs",
        ["grader_run_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Step 10: Recreate old unique constraints
    op.create_unique_constraint(
        "unknown_clusters_clustering_run_id_cluster_name_key", "unknown_clusters", ["clustering_run_id", "cluster_name"]
    )
    op.create_unique_constraint(
        "unknown_assignments_unique_active",
        "unknown_assignments",
        ["clustering_run_id", "grader_run_id", "unknown_id", "cancelled_at"],
    )

    # Step 11: Recreate old indexes
    op.create_index("ix_unknown_clusters_clustering_run_id", "unknown_clusters", ["clustering_run_id"])
    op.create_index("ix_unknown_assignments_clustering_run_id", "unknown_assignments", ["clustering_run_id"])
    op.execute("""
        CREATE INDEX ix_unknown_assignments_active
            ON unknown_assignments (clustering_run_id, grader_run_id, unknown_id)
            WHERE cancelled_at IS NULL
    """)

    # Step 12: Recreate old RLS policies
    op.execute("""
        CREATE POLICY clustering_user_clustering_runs_policy ON clustering_runs
            USING (CURRENT_USER ~ '^clustering_run_[0-9]+_agent$' AND id = current_clustering_run_id());

        CREATE POLICY clustering_user_unknown_clusters_policy ON unknown_clusters
            USING (CURRENT_USER ~ '^clustering_run_[0-9]+_agent$' AND clustering_run_id = current_clustering_run_id());

        CREATE POLICY clustering_user_unknown_assignments_policy ON unknown_assignments
            USING (CURRENT_USER ~ '^clustering_run_[0-9]+_agent$' AND clustering_run_id = current_clustering_run_id());
    """)
