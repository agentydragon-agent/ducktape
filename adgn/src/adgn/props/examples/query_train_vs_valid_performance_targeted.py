"""Example: Query train vs validation performance in targeted mode.

In targeted mode, validation includes both per-file and full-snapshot examples.
The examples table IS accessible (filenames only - no ground truth or traces).
All performance metrics are queried via the aggregated_recall_by_prompt view.

Key difference from whole-repo mode:
- Both splits: Use aggregated_recall_by_prompt view (includes n_examples, n_runs, ucb, lcb)
- Validation: Can see example filenames (but not ground truth or traces)

IMPORTANT: Check n_examples >= 5 before trusting validation metrics. Small sample
sizes have high variance. The ucb/lcb bounds quantify uncertainty.
"""

from sqlalchemy import text

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session


def main():
    """Display train vs validation performance comparison for targeted mode."""
    setup_agent_database()

    with get_session() as session:
        # Example: Get validation performance with sample size checks
        valid_results = session.execute(
            text("""
            SELECT
                prompt_sha256,
                critic_model,
                is_whole_snapshot,
                recall,
                n_examples,
                n_runs,
                ucb,
                lcb
            FROM aggregated_recall_by_prompt
            WHERE split = 'valid'
            ORDER BY recall DESC
            LIMIT 20
            """)
        ).fetchall()

        print("Validation Performance (targeted mode - per-file + full-snapshot):")
        print(
            f"{'Prompt SHA':<12} {'Model':<15} {'Type':<10} {'Examples':<9} {'Runs':<6} {'Recall':<8} {'UCB':<8} {'LCB':<8}"
        )
        print("-" * 100)
        for row in valid_results:
            sha = row.prompt_sha256[:8]
            model = row.critic_model[:12]
            ex_type = "full" if row.is_whole_snapshot else "per-file"
            sample_warning = " ⚠️ " if row.n_examples < 5 else ""
            print(
                f"{sha:<12} {model:<15} {ex_type:<10} {row.n_examples:<9} {row.n_runs:<6} "
                f"{row.recall * 100:>6.1f}% {row.ucb * 100:>6.1f}% {row.lcb * 100:>6.1f}%{sample_warning}"
            )

        print()

        # Example: Get training performance for comparison
        train_results = session.execute(
            text("""
            SELECT
                prompt_sha256,
                critic_model,
                is_whole_snapshot,
                recall,
                n_examples,
                n_runs,
                ucb,
                lcb
            FROM aggregated_recall_by_prompt
            WHERE split = 'train'
            ORDER BY recall DESC
            LIMIT 20
            """)
        ).fetchall()

        print("Training Performance (per-file + full-snapshot):")
        print(
            f"{'Prompt SHA':<12} {'Model':<15} {'Type':<10} {'Examples':<9} {'Runs':<6} {'Recall':<8} {'UCB':<8} {'LCB':<8}"
        )
        print("-" * 100)
        for row in train_results:
            sha = row.prompt_sha256[:8]
            model = row.critic_model[:12]
            ex_type = "full" if row.is_whole_snapshot else "per-file"
            print(
                f"{sha:<12} {model:<15} {ex_type:<10} {row.n_examples:<9} {row.n_runs:<6} "
                f"{row.recall * 100:>6.1f}% {row.ucb * 100:>6.1f}% {row.lcb * 100:>6.1f}%"
            )

        print()
        print("⚠️  = Warning: n_examples < 5 (small sample size, high variance)")
        print()
        print("Note: In targeted mode, you can see validation example filenames:")
        print("  SELECT files FROM examples WHERE snapshot_slug IN")
        print("    (SELECT slug FROM snapshots WHERE split = 'valid')")
        print()
        print("But ground truth (true_positives, false_positives) and execution")
        print("traces (events) remain hidden for validation split.")


if __name__ == "__main__":
    main()
