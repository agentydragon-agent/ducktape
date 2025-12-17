"""Update pareto_frontier_by_example for occurrence-based weighting

Revision ID: 20251217000002
Revises: 20251217000001
Create Date: 2025-12-17 00:00:02.000000

Updates pareto_frontier_by_example view to:
1. Use critic_run_occurrence_stats (already aggregates over graders)
2. Compute recall with occurrence-based weighting (occurrences caught / catchable)
3. Handle failed critic runs correctly (NULL avg_occurrences_caught)

This makes the pareto view consistent with aggregated_recall_by_prompt/example.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251217000002"
down_revision: str | None = "20251217000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop existing view
    op.execute("DROP VIEW IF EXISTS pareto_frontier_by_example CASCADE")

    # Recreate with occurrence-based weighting
    op.execute("""
        CREATE VIEW pareto_frontier_by_example AS
        WITH per_run_recalls AS (
            -- Compute per-run recall using occurrence-based weighting
            -- Uses critic_run_occurrence_stats which already aggregates over graders
            SELECT
                cros.split,
                cros.snapshot_slug,
                cros.scope_hash,
                e.scope->>'kind' AS scope_kind,
                cros.prompt_sha256,
                cros.critic_run_id,
                cros.critic_model,
                -- Occurrence-based recall: occurrences caught / catchable occurrences
                -- Failed runs have NULL avg_occurrences_caught, treated as 0.0 for recall
                CASE
                    WHEN cros.n_catchable_occurrences > 0
                    THEN COALESCE(cros.avg_occurrences_caught, 0.0) / cros.n_catchable_occurrences
                    ELSE 0.0
                END AS recall
            FROM critic_run_occurrence_stats cros
            JOIN examples e ON (cros.snapshot_slug, cros.scope_hash) = (e.snapshot_slug, e.scope_hash)
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
        'Pareto frontier: best recall achieved on each example and which prompt SHAs achieved it.

        Uses occurrence-based weighting: recall = occurrences_caught / catchable_occurrences.
        This naturally weights examples by their issue density (20 occurrences = 20x weight of 1 occurrence).

        For each (split, snapshot_slug, scope_hash, critic_model), shows the best average recall
        across all prompts and lists all prompt SHAs (SHA256 hashes) that achieved this best score.

        Built on critic_run_occurrence_stats, which already aggregates over grader models.
        Failed critic runs (max_turns/context_length) count as 0.0 recall.

        Use cases:
        - Prompt optimization: Which prompts excel on specific examples?
        - Ensemble analysis: Combine best prompts for different patterns
        - Training diagnostics: Where do all prompts struggle?'
    """)


def downgrade() -> None:
    # Drop new view
    op.execute("DROP VIEW IF EXISTS pareto_frontier_by_example CASCADE")

    # Recreate old view using occurrence_run_credits
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
