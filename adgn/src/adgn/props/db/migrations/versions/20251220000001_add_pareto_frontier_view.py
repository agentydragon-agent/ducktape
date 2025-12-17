"""Add pareto_frontier_by_example view

Revision ID: 20251220000001
Revises: 20251220000000
Create Date: 2025-12-20 00:00:01.000000

Adds a view that computes the Pareto frontier: for each validation example,
identifies the best recall achieved by any prompt and which prompts achieved it.

Useful for prompt optimization agents to see which prompts win on which examples.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251220000001"
down_revision: str | None = "20251220000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create pareto_frontier_by_example view
    op.execute("""
        CREATE VIEW pareto_frontier_by_example AS
        WITH per_run_recalls AS (
            -- Compute per-run recall for each (snapshot, scope_hash, prompt, critic_run)
            -- TODO: Currently aggregates across grader models. May want to filter by grader_model in future.
            SELECT
                orc.split,
                orc.snapshot_slug,
                orc.scope_hash,
                orc.scope_kind,
                orc.prompt_sha256,
                orc.critic_run_id,
                orc.critic_model,
                SUM(orc.avg_credit) / NULLIF(COUNT(*), 0) AS recall
            FROM occurrence_run_credits orc
            GROUP BY
                orc.split, orc.snapshot_slug, orc.scope_hash, orc.scope_kind,
                orc.prompt_sha256, orc.critic_run_id, orc.critic_model
        ),
        avg_recall_per_prompt_example AS (
            -- Average recall across runs for each (snapshot, scope_hash, prompt)
            SELECT
                split,
                snapshot_slug,
                scope_hash,
                scope_kind,
                prompt_sha256,
                critic_model,
                AVG(recall) AS avg_recall,
                COUNT(DISTINCT critic_run_id) AS n_runs
            FROM per_run_recalls
            GROUP BY split, snapshot_slug, scope_hash, scope_kind, prompt_sha256, critic_model
        ),
        best_scores AS (
            -- Find best recall per example
            SELECT
                split,
                snapshot_slug,
                scope_hash,
                scope_kind,
                critic_model,
                MAX(avg_recall) AS best_recall
            FROM avg_recall_per_prompt_example
            GROUP BY split, snapshot_slug, scope_hash, scope_kind, critic_model
        )
        SELECT
            bs.split,
            bs.snapshot_slug,
            bs.scope_hash,
            bs.scope_kind,
            bs.critic_model,
            bs.best_recall,
            array_agg(arppe.prompt_sha256 ORDER BY arppe.prompt_sha256) AS winning_prompt_shas,
            array_agg(arppe.n_runs ORDER BY arppe.prompt_sha256) AS winning_prompt_n_runs
        FROM best_scores bs
        JOIN avg_recall_per_prompt_example arppe ON
            bs.split = arppe.split AND
            bs.snapshot_slug = arppe.snapshot_slug AND
            bs.scope_hash = arppe.scope_hash AND
            bs.scope_kind = arppe.scope_kind AND
            bs.critic_model = arppe.critic_model AND
            bs.best_recall = arppe.avg_recall
        GROUP BY bs.split, bs.snapshot_slug, bs.scope_hash, bs.scope_kind, bs.critic_model, bs.best_recall
    """)

    op.execute("""
        COMMENT ON VIEW pareto_frontier_by_example IS
        'Pareto frontier: best recall achieved on each validation example and which prompt SHAs achieved it.
        For each (split, snapshot_slug, scope_hash, critic_model), shows the best average recall
        across all prompts and lists all prompt SHAs (SHA256 hashes) that achieved this best score.

        Useful for prompt optimization to identify which prompts excel on specific examples.
        Not filtered by split - works for train/valid/test.

        TODO: Currently aggregates across grader models. Future enhancement may filter by grader_model.'
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS pareto_frontier_by_example CASCADE")
