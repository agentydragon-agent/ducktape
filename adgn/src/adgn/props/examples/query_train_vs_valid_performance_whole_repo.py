"""Example: Query train vs validation performance in whole-repo mode.

In whole-repo mode, validation uses full-snapshot examples only and the examples
table is NOT accessible (RLS blocks). Validation performance is queried via the
get_validation_run_aggregates() SECURITY DEFINER function.

This function returns per-run aggregates for validation, which you can then
aggregate further to compare with training performance.

Key difference from targeted mode:
- Validation: Use get_validation_run_aggregates() function (per-run results)
- Training: Use aggregated_recall_by_prompt view (pre-aggregated stats)
"""

from sqlalchemy import text

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session


def main():
    """Display train vs validation performance comparison for whole-repo mode."""
    setup_agent_database()

    with get_session() as session:
        # Example: Get all validation run aggregates
        valid_results = session.execute(
            text("""
            SELECT
                prompt_sha256,
                critic_model,
                snapshot_slug,
                COUNT(*) as n_runs,
                AVG(total_credit / n_occurrences) as mean_recall
            FROM get_validation_run_aggregates()
            GROUP BY prompt_sha256, critic_model, snapshot_slug
            ORDER BY mean_recall DESC
            LIMIT 10
            """)
        ).fetchall()

        print("Validation Performance (whole-repo mode - full-snapshot only):")
        print(f"{'Prompt SHA':<12} {'Model':<15} {'Snapshot':<25} {'Runs':<6} {'Recall':<8}")
        print("-" * 80)
        for row in valid_results:
            sha = row.prompt_sha256[:8]
            model = row.critic_model[:12]
            snapshot = row.snapshot_slug[:22]
            print(f"{sha:<12} {model:<15} {snapshot:<25} {row.n_runs:<6} {row.mean_recall * 100:>6.1f}%")

        print()

        # Example: Get training performance for comparison
        train_results = session.execute(
            text("""
            SELECT
                prompt_sha256,
                critic_model,
                recall,
                n_examples,
                n_runs,
                ucb,
                lcb
            FROM aggregated_recall_by_prompt
            WHERE split = 'train' AND is_whole_snapshot = true
            ORDER BY recall DESC
            LIMIT 10
            """)
        ).fetchall()

        print("Training Performance (full-snapshot examples only):")
        print(f"{'Prompt SHA':<12} {'Model':<15} {'Examples':<9} {'Runs':<6} {'Recall':<8} {'UCB':<8} {'LCB':<8}")
        print("-" * 90)
        for row in train_results:
            sha = row.prompt_sha256[:8]
            model = row.critic_model[:12]
            print(
                f"{sha:<12} {model:<15} {row.n_examples:<9} {row.n_runs:<6} "
                f"{row.recall * 100:>6.1f}% {row.ucb * 100:>6.1f}% {row.lcb * 100:>6.1f}%"
            )

        print()
        print("Note: In whole-repo mode, validation examples table is NOT accessible.")
        print("Use get_validation_run_aggregates() to query validation performance.")


if __name__ == "__main__":
    main()
