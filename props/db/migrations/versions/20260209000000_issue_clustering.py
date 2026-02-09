"""Add issue clustering tables, constraints, triggers, and view.

Issue clusters group unmatched critique issues (credit=0 across all GT) that
report the same underlying problem across different critic runs. This gives the
grader a way to organize novel findings that ground truth doesn't yet cover.

Invariants enforced at DB level:
- A clustered issue must have no grading edges with credit > 0
- A grading edge with credit > 0 cannot be added for an already-clustered issue
- Each critique issue belongs to at most one cluster (UNIQUE constraint)
- Every cluster must have at least one member (trigger on DELETE)

Revision ID: 20260209000000
Revises: 20251228000000
Create Date: 2026-02-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260209000000"
down_revision: str | Sequence[str] | None = "20251228000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- 1. issue_clusters table ---
    op.execute("""
        CREATE TABLE issue_clusters (
            snapshot_slug VARCHAR NOT NULL REFERENCES snapshots(slug) ON DELETE CASCADE,
            cluster_id VARCHAR NOT NULL,
            rationale TEXT NOT NULL,
            grader_run_id UUID NOT NULL REFERENCES agent_runs(agent_run_id) ON DELETE CASCADE,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            PRIMARY KEY (snapshot_slug, cluster_id)
        );
        COMMENT ON TABLE issue_clusters IS
            'Clusters of unmatched critique issues reporting the same novel finding.';
    """)

    # --- 2. issue_cluster_members table ---
    op.execute("""
        CREATE TABLE issue_cluster_members (
            snapshot_slug VARCHAR NOT NULL,
            cluster_id VARCHAR NOT NULL,
            critique_run_id UUID NOT NULL,
            critique_issue_id VARCHAR NOT NULL,
            rationale TEXT NOT NULL,
            grader_run_id UUID NOT NULL REFERENCES agent_runs(agent_run_id) ON DELETE CASCADE,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            PRIMARY KEY (snapshot_slug, cluster_id, critique_run_id, critique_issue_id),
            FOREIGN KEY (snapshot_slug, cluster_id)
                REFERENCES issue_clusters(snapshot_slug, cluster_id) ON DELETE CASCADE,
            FOREIGN KEY (critique_run_id, critique_issue_id)
                REFERENCES reported_issues(agent_run_id, issue_id) ON DELETE CASCADE,
            CONSTRAINT uq_issue_cluster_member_issue
                UNIQUE (critique_run_id, critique_issue_id)
        );
        COMMENT ON TABLE issue_cluster_members IS
            'Membership of critique issues in clusters. Each issue belongs to at most one cluster.';
    """)

    # --- 3. Constraint: clustered issues must have no positive grading edges ---
    op.execute("""
        CREATE FUNCTION check_cluster_member_no_positive_edges() RETURNS trigger AS $$
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
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_check_cluster_member_no_positive_edges
            BEFORE INSERT OR UPDATE ON issue_cluster_members
            FOR EACH ROW EXECUTE FUNCTION check_cluster_member_no_positive_edges();
    """)

    # --- 4. Reverse guard: positive grading edge rejects if issue is clustered ---
    op.execute("""
        CREATE FUNCTION check_positive_edge_not_clustered() RETURNS trigger AS $$
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
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_check_positive_edge_not_clustered
            BEFORE INSERT OR UPDATE ON grading_edges
            FOR EACH ROW EXECUTE FUNCTION check_positive_edge_not_clustered();
    """)

    # --- 5. Constraint: every cluster must have at least one member ---
    op.execute("""
        CREATE FUNCTION check_cluster_not_empty() RETURNS trigger AS $$
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
        $$ LANGUAGE plpgsql;

        CREATE CONSTRAINT TRIGGER trg_check_cluster_not_empty
            AFTER DELETE ON issue_cluster_members
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION check_cluster_not_empty();
    """)

    # --- 6. clustering_pending view ---
    op.execute("""
        CREATE VIEW clustering_pending AS
        SELECT
            ri.agent_run_id AS critique_run_id,
            ri.issue_id AS critique_issue_id,
            (ar.type_config->'example'->>'snapshot_slug') AS snapshot_slug
        FROM reported_issues ri
        JOIN agent_runs ar ON ar.agent_run_id = ri.agent_run_id
        WHERE (ar.type_config->>'agent_type') = 'critic'
          -- All grading edges exist (no pending edges)
          AND NOT EXISTS (
              SELECT 1 FROM grading_pending gp
              WHERE gp.critique_run_id = ri.agent_run_id
                AND gp.critique_issue_id = ri.issue_id
          )
          -- No positive grading edge exists
          AND NOT EXISTS (
              SELECT 1 FROM grading_edges ge
              WHERE ge.critique_run_id = ri.agent_run_id
                AND ge.critique_issue_id = ri.issue_id
                AND ge.credit > 0
          )
          -- Not yet in a cluster
          AND NOT EXISTS (
              SELECT 1 FROM issue_cluster_members icm
              WHERE icm.critique_run_id = ri.agent_run_id
                AND icm.critique_issue_id = ri.issue_id
          );

        COMMENT ON VIEW clustering_pending IS
            'Critique issues fully graded with no positive match and not yet clustered. '
            'When empty for a snapshot, all unmatched issues have been assigned to clusters.';
    """)

    # --- 7. RLS policies for grader access ---
    op.execute("""
        ALTER TABLE issue_clusters ENABLE ROW LEVEL SECURITY;
        ALTER TABLE issue_cluster_members ENABLE ROW LEVEL SECURITY;

        -- Graders can read clusters for their snapshot
        CREATE POLICY grader_read_clusters ON issue_clusters
            FOR SELECT
            USING (snapshot_slug = current_setting('props.grader_snapshot_slug', true));

        -- Graders can insert/update/delete clusters for their snapshot
        CREATE POLICY grader_write_clusters ON issue_clusters
            FOR ALL
            USING (snapshot_slug = current_setting('props.grader_snapshot_slug', true))
            WITH CHECK (snapshot_slug = current_setting('props.grader_snapshot_slug', true));

        -- Graders can read cluster members for their snapshot
        CREATE POLICY grader_read_cluster_members ON issue_cluster_members
            FOR SELECT
            USING (snapshot_slug = current_setting('props.grader_snapshot_slug', true));

        -- Graders can write cluster members for their snapshot
        CREATE POLICY grader_write_cluster_members ON issue_cluster_members
            FOR ALL
            USING (snapshot_slug = current_setting('props.grader_snapshot_slug', true))
            WITH CHECK (snapshot_slug = current_setting('props.grader_snapshot_slug', true));

        -- Admin bypass
        CREATE POLICY admin_all_clusters ON issue_clusters FOR ALL USING (true) WITH CHECK (true);
        CREATE POLICY admin_all_cluster_members ON issue_cluster_members FOR ALL USING (true) WITH CHECK (true);
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS clustering_pending;")
    op.execute("DROP TRIGGER IF EXISTS trg_check_cluster_not_empty ON issue_cluster_members;")
    op.execute("DROP FUNCTION IF EXISTS check_cluster_not_empty();")
    op.execute("DROP TRIGGER IF EXISTS trg_check_positive_edge_not_clustered ON grading_edges;")
    op.execute("DROP FUNCTION IF EXISTS check_positive_edge_not_clustered();")
    op.execute("DROP TRIGGER IF EXISTS trg_check_cluster_member_no_positive_edges ON issue_cluster_members;")
    op.execute("DROP FUNCTION IF EXISTS check_cluster_member_no_positive_edges();")
    op.execute("DROP TABLE IF EXISTS issue_cluster_members;")
    op.execute("DROP TABLE IF EXISTS issue_clusters;")
