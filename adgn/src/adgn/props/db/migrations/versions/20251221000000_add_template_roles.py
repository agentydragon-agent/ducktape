"""Add template roles for agent user managers.

Revision ID: 20251221000000
Revises: 20251220000012
Create Date: 2025-12-21

Creates NOLOGIN template roles for Critic, Grader, Clustering, and PromptOptimizer
agents. User managers grant these roles to temp users instead of looping through
individual GRANT statements.

Existing RLS policies (function-based) continue to handle per-run filtering.
ImprovementUserManager is unchanged (uses per-user RLS policies).
"""

from alembic import op

revision = "20251221000000"
down_revision = "20251220000012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CRITIC template role
    # - Can write to reported_issues and reported_issue_occurrences (INSERT, SELECT, UPDATE - NO DELETE)
    # - Can read critic_runs (for FK validation)
    # - NO access to ground truth tables
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'critic_agent_template') THEN
                CREATE ROLE critic_agent_template NOLOGIN;
            END IF;
        END
        $$
    """)
    op.execute("GRANT USAGE ON SCHEMA public TO critic_agent_template")
    op.execute("GRANT SELECT, INSERT, UPDATE ON TABLE reported_issues TO critic_agent_template")
    op.execute("GRANT SELECT, INSERT, UPDATE ON TABLE reported_issue_occurrences TO critic_agent_template")
    op.execute("GRANT SELECT ON TABLE critic_runs TO critic_agent_template")
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO critic_agent_template")

    # GRADER template role
    # - Can read ground truth (true_positives, false_positives)
    # - Can read critic input (critic_runs, reported_issues, reported_issue_occurrences, snapshots, grader_runs)
    # - Can read grading_credit_sums view
    # - Full DML on grading_decisions (including DELETE for decision revision)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'grader_agent_template') THEN
                CREATE ROLE grader_agent_template NOLOGIN;
            END IF;
        END
        $$
    """)
    op.execute("GRANT USAGE ON SCHEMA public TO grader_agent_template")
    op.execute("GRANT SELECT ON TABLE true_positives TO grader_agent_template")
    op.execute("GRANT SELECT ON TABLE false_positives TO grader_agent_template")
    op.execute("GRANT SELECT ON TABLE critic_runs TO grader_agent_template")
    op.execute("GRANT SELECT ON TABLE reported_issues TO grader_agent_template")
    op.execute("GRANT SELECT ON TABLE reported_issue_occurrences TO grader_agent_template")
    op.execute("GRANT SELECT ON TABLE snapshots TO grader_agent_template")
    op.execute("GRANT SELECT ON TABLE grader_runs TO grader_agent_template")
    op.execute("GRANT SELECT ON grading_credit_sums TO grader_agent_template")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE grading_decisions TO grader_agent_template")
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO grader_agent_template")

    # CLUSTERING template role
    # - Full DML on clustering tables (clustering_runs, unknown_clusters, unknown_assignments)
    # - Read-only on reference tables
    # - Read-only on aggregate views
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'clustering_agent_template') THEN
                CREATE ROLE clustering_agent_template NOLOGIN;
            END IF;
        END
        $$
    """)
    op.execute("GRANT USAGE ON SCHEMA public TO clustering_agent_template")
    # Clustering tables (read-write)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE clustering_runs TO clustering_agent_template")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE unknown_clusters TO clustering_agent_template")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE unknown_assignments TO clustering_agent_template")
    # Reference tables (read-only)
    op.execute("GRANT SELECT ON TABLE snapshots TO clustering_agent_template")
    op.execute("GRANT SELECT ON TABLE true_positives TO clustering_agent_template")
    op.execute("GRANT SELECT ON TABLE false_positives TO clustering_agent_template")
    op.execute("GRANT SELECT ON TABLE grader_runs TO clustering_agent_template")
    op.execute("GRANT SELECT ON TABLE critic_runs TO clustering_agent_template")
    op.execute("GRANT SELECT ON TABLE reported_issues TO clustering_agent_template")
    op.execute("GRANT SELECT ON TABLE reported_issue_occurrences TO clustering_agent_template")
    op.execute("GRANT SELECT ON TABLE grading_decisions TO clustering_agent_template")
    op.execute("GRANT SELECT ON TABLE examples TO clustering_agent_template")
    op.execute("GRANT SELECT ON TABLE prompts TO clustering_agent_template")
    # Aggregate views (read-only)
    op.execute("GRANT SELECT ON occurrence_credits TO clustering_agent_template")
    op.execute("GRANT SELECT ON occurrence_run_credits TO clustering_agent_template")
    op.execute("GRANT SELECT ON aggregated_recall_by_prompt TO clustering_agent_template")
    op.execute("GRANT SELECT ON aggregated_recall_by_example TO clustering_agent_template")
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO clustering_agent_template")

    # PROMPT OPTIMIZER template role
    # - Read-only on training data tables (RLS filters to TRAIN split)
    # - Read-only on aggregate views
    # - EXECUTE on validation aggregation function
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'prompt_optimizer_agent_template') THEN
                CREATE ROLE prompt_optimizer_agent_template NOLOGIN;
            END IF;
        END
        $$
    """)
    op.execute("GRANT USAGE ON SCHEMA public TO prompt_optimizer_agent_template")
    # RLS-filtered tables (read-only, train split only via RLS)
    op.execute("GRANT SELECT ON TABLE snapshots TO prompt_optimizer_agent_template")
    op.execute("GRANT SELECT ON TABLE true_positives TO prompt_optimizer_agent_template")
    op.execute("GRANT SELECT ON TABLE false_positives TO prompt_optimizer_agent_template")
    op.execute("GRANT SELECT ON TABLE examples TO prompt_optimizer_agent_template")
    op.execute("GRANT SELECT ON TABLE critic_runs TO prompt_optimizer_agent_template")
    op.execute("GRANT SELECT ON TABLE grader_runs TO prompt_optimizer_agent_template")
    op.execute("GRANT SELECT ON TABLE events TO prompt_optimizer_agent_template")
    op.execute("GRANT SELECT ON TABLE prompts TO prompt_optimizer_agent_template")
    # Aggregate views (read-only)
    op.execute("GRANT SELECT ON occurrence_credits TO prompt_optimizer_agent_template")
    op.execute("GRANT SELECT ON occurrence_run_credits TO prompt_optimizer_agent_template")
    op.execute("GRANT SELECT ON aggregated_recall_by_prompt TO prompt_optimizer_agent_template")
    op.execute("GRANT SELECT ON aggregated_recall_by_example TO prompt_optimizer_agent_template")
    # Validation function (SECURITY DEFINER, provides VALID split aggregates)
    op.execute("GRANT EXECUTE ON FUNCTION get_validation_run_aggregates() TO prompt_optimizer_agent_template")


def downgrade() -> None:
    # Drop template roles (CASCADE handles dependent grants)
    op.execute("DROP ROLE IF EXISTS prompt_optimizer_agent_template")
    op.execute("DROP ROLE IF EXISTS clustering_agent_template")
    op.execute("DROP ROLE IF EXISTS grader_agent_template")
    op.execute("DROP ROLE IF EXISTS critic_agent_template")
