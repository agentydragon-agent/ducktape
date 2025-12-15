"""Example: Query comprehensive prompt performance statistics with LCB-based ranking.

This script demonstrates how to get an overview of all prompts with their
performance on train and validation splits, similar to `adgn-properties stats`.
Prompts are sorted by Lower Confidence Bound (LCB) to prioritize consistent performers.

For each prompt, shows:
- Created timestamp and size
- Valid performance: mean recall, LCB, success/total counts, zero%, stuck%, context%
- Train performance: mean recall, LCB, success/total counts, zero%, stuck%, context%

Metrics:
- Mean recall: averaged over all runs (failures count as 0.0)
- LCB: lower confidence bound (mean - 1σ/√n), NULL if n < 2
- Success/total: successful runs vs all runs
- Zero%: percentage of successful runs with 0.0 recall (excludes failures)
- Stuck%: percentage of all runs that exceeded max_turns
- Context%: percentage of all runs that exceeded context_length

This helps identify:
- Which prompts have been evaluated on validation (many haven't)
- Which prompts show consistent, reliable performance (high LCB)
- Which prompts have high variance (low LCB despite good mean)
- Which prompts frequently get stuck (max_turns) or fail completely (zero-recall)
"""

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.cli.cmd_stats import STATS_TABLE_LEGEND
from adgn.props.db import get_session
from adgn.props.db.query_builders import query_prompt_performance_stats


def main():
    """Display comprehensive prompt statistics across splits."""
    setup_agent_database()

    with get_session() as session:
        results = query_prompt_performance_stats(session, limit=50)

        if not results:
            print("No prompts found in database.")
            return

        print(f"Prompt Performance Overview ({len(results)} most recent prompts, sorted by LCB)")
        print()
        print(f"{'SHA':<10} {'Created':<12} {'Len':<5} {'Valid':<40} {'Train':<40}")
        print("-" * 110)

        def format_stats(stats):
            """Format split statistics as: recall% lcb% (N) Zz Ss Cc"""
            if stats is None:
                return "—"
            lcb_str = f"{stats.lcb:.1f}%" if stats.lcb is not None else "—"
            return (
                f"{stats.mean_recall:.1f}% "
                f"lcb:{lcb_str} "
                f"({stats.total_count}) "
                f"{stats.zero_count}z "
                f"{stats.stuck_count}s "
                f"{stats.context_count}c"
            )

        for row in results:
            sha = row.prompt_sha256[:8]
            created = row.created_at.strftime("%m-%d %H:%M")
            length = f"{row.prompt_length // 1000}k"

            valid_str = format_stats(row.valid)
            train_str = format_stats(row.train)

            print(f"{sha:<10} {created:<12} {length:<5} {valid_str:<40} {train_str:<40}")

        print()
        print("Format: recall% lcb:X% (N) Zz Ss Cc")
        print(STATS_TABLE_LEGEND)


if __name__ == "__main__":
    main()
