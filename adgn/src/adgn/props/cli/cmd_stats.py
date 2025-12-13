"""CLI command for prompt statistics and evaluation metrics."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import statistics

import plotext as plt  # type: ignore[import-untyped]
from rich import box
from rich.console import Console
from rich.table import Table
from sqlalchemy import func, select

from adgn.props.db import get_session
from adgn.props.db.datapoints import count_available_examples_for_split
from adgn.props.db.models import CriticRun, Event, Example, GraderRun
from adgn.props.db.query_builders import SplitPerformanceStats, query_prompt_performance_stats
from adgn.props.db.snapshots import DBGraderSuccess
from adgn.props.display import SHORT_SHA_LENGTH, short_sha
from adgn.props.grader.staleness import check_staleness
from adgn.props.splits import Split

# Stats table column legend (shared between CLI and examples)
STATS_TABLE_LEGEND = """
[bold]Column Legend:[/bold]
  [cyan]Recall%[/cyan]: Mean recall over all runs (failures count as 0.0)
  [cyan]LCB[/cyan]: Lower confidence bound (mean - 1σ/√n), — if n < 2
    - Penalizes high variance, useful for selecting reliable prompts
    - ~84% confidence the true mean is above this value
  [cyan]N / {total}[/cyan]: Number of examples evaluated out of total available
  [cyan]Z%[/cyan]: Percentage of successful runs with 0% recall
  [cyan]S%[/cyan]: Percentage of all runs that exceeded max turns (stuck)
  [cyan]C%[/cyan]: Percentage of all runs that exceeded context length

[bold]Notes:[/bold]
  - Results sorted by valid LCB (descending), then train LCB, then age
  - Success count is implicit from Z%, S%, C% (they sum to explain N)
  - Green recall means fully evaluated (N = total available)
  - Many prompts have no valid data (— in Valid columns)
"""


def format_age(dt: datetime) -> str:
    """Format datetime as relative age string (e.g., '2d', '3h', '15m').

    Args:
        dt: Datetime to format (assumed UTC or naive)

    Returns:
        Age string like '2y', '3mo', '5d', '12h', '45m', or 'now'
    """
    now = datetime.now(UTC) if dt.tzinfo else datetime.now()
    delta = now - dt

    if delta.days >= 365:
        return f"{delta.days // 365}y"
    if delta.days >= 30:
        return f"{delta.days // 30}mo"
    if delta.days > 0:
        return f"{delta.days}d"
    if delta.seconds >= 3600:
        return f"{delta.seconds // 3600}h"
    if delta.seconds >= 60:
        return f"{delta.seconds // 60}m"
    return "now"


@dataclass
class FormattedSplitStats:
    """Pre-formatted display strings for a single split's statistics.

    Field order defines canonical column ordering for display:
    recall, lcb, n, zero, stuck, context
    """

    recall: str
    lcb: str
    n: str
    zero: str
    stuck: str
    context: str

    def as_row_fields(self) -> tuple[str, str, str, str, str, str]:
        """Return fields in canonical column order for table display."""
        return (self.recall, self.lcb, self.n, self.zero, self.stuck, self.context)


def format_split_stats(stats: SplitPerformanceStats | None, fully_computed: bool = False) -> FormattedSplitStats:
    """Format split statistics for display.

    Args:
        stats: Split performance statistics or None
        fully_computed: If True, apply green color to recall

    Returns:
        FormattedSplitStats with display-ready strings

    Note:
        - N shows total_count (how many examples evaluated), not success/total
        - Success count is implicit from Z%, S%, C% (they sum to explain the N)
    """
    if stats is None:
        return FormattedSplitStats("—", "—", "—", "—", "—", "—")

    recall_str = f"{stats.mean_recall:.0f}%"
    if fully_computed:
        recall_str = f"[green]{recall_str}[/green]"

    return FormattedSplitStats(
        recall=recall_str,
        lcb=f"{stats.lcb:.0f}%" if stats.lcb is not None else "—",
        n=str(stats.total_count),  # Just the count of examples evaluated
        zero=f"{stats.zero_pct:.0f}%",
        stuck=f"{stats.stuck_pct:.0f}%",
        context=f"{stats.context_pct:.0f}%",
    )


def _generate_buckets(
    values: Sequence[float | int], num_buckets: int = 7, equal_width: bool = False
) -> list[tuple[str, float | int, float | int]]:
    """Generate bucket ranges automatically based on data distribution.

    Args:
        values: List of numeric values
        num_buckets: Desired number of buckets (default 7)
        equal_width: If True, use equal-width bins; if False, use percentile-based (default False)

    Returns:
        List of (label, low, high) tuples defining bucket ranges
    """
    if not values:
        return []

    min_val = min(values)
    max_val = max(values)

    # If all values are the same, create a single bucket
    if min_val == max_val:
        return [(str(min_val), min_val, min_val + 1)]

    if equal_width:
        # Use equal-width bins
        bin_width = (max_val - min_val) / num_buckets
        unique_bounds = [min_val + i * bin_width for i in range(num_buckets + 1)]
    else:
        # Use percentile-based buckets for better distribution
        sorted_vals = sorted(values)
        n = len(sorted_vals)

        # Calculate bucket boundaries using percentiles
        percentiles = [i * 100 / num_buckets for i in range(num_buckets + 1)]
        bounds = []
        for p in percentiles:
            idx = int(n * p / 100)
            if idx >= n:
                idx = n - 1
            bounds.append(sorted_vals[idx])

        # Deduplicate consecutive boundaries
        unique_bounds = [bounds[0]]
        for b in bounds[1:]:
            if b != unique_bounds[-1]:
                unique_bounds.append(b)

        # If we have fewer unique bounds than buckets, fall back to equal-width bins
        if len(unique_bounds) < num_buckets:
            bin_width = (max_val - min_val) / num_buckets
            unique_bounds = [min_val + i * bin_width for i in range(num_buckets + 1)]

    # Create bucket tuples with labels
    buckets = []
    for i in range(len(unique_bounds) - 1):
        low = unique_bounds[i]
        high = unique_bounds[i + 1]

        # Format label based on value type and range
        if isinstance(low, int) and isinstance(high, int):
            label = str(low) if low == high - 1 else f"{low}-{high - 1}"
        else:
            label = f"{low:.1f}-{high:.1f}"

        # Adjust high boundary to be exclusive for the last bucket
        if i == len(unique_bounds) - 2:
            high = max_val + 1  # Make last bucket inclusive

        buckets.append((label, low, high))

    return buckets


def _display_distribution(
    console: Console,
    values: Sequence[float | int],
    title: str,
    buckets: Sequence[tuple[str, float | int, float | int]],
    value_format: str = "{:.1f}%",
) -> None:
    """Display a bucketed distribution with percentiles and histogram using plotext.

    Args:
        console: Rich console for output
        values: List of numeric values to visualize
        title: Section title
        buckets: List of (label, low, high) tuples defining bucket ranges
        value_format: Format string for displaying values (default: percentage)
    """
    if not values:
        return

    # Convert to list for statistics functions
    values_list = list(values)
    mean_val = statistics.mean(values_list)
    median_val = statistics.median(values_list)

    console.print(f"\n[bold]{title}:[/bold]")
    console.print(f"  N={len(values)} μ={value_format.format(mean_val)} median={value_format.format(median_val)}")

    # Show percentiles for skewed distributions on one line
    sorted_vals = sorted(values_list)
    n = len(sorted_vals)
    percentiles = [10, 25, 50, 75, 90, 95, 99]
    percentile_strs = []
    for p in percentiles:
        idx = int(n * p / 100)
        if idx >= n:
            idx = n - 1
        percentile_strs.append(f"P{p}={value_format.format(sorted_vals[idx])}")
    console.print(f"  Percentiles: {' '.join(percentile_strs)}")

    # Create histogram using plotext
    # Compute bucket counts
    bucket_labels = [label for label, _, _ in buckets]
    bucket_counts = [sum(1 for v in values_list if low <= v < high) for _, low, high in buckets]

    # Use plotext for simple horizontal bar chart with default colors
    plt.clear_figure()
    plt.clear_color()  # Reset to default colors
    plt.simple_bar(bucket_labels, bucket_counts, width=50, title="")
    plt.show()
    console.print()


@dataclass
class SplitStats:
    """Statistics for a prompt on a specific split."""

    completed: int = 0  # Unique examples evaluated (with grader runs completed)
    recalls: list[float] = None  # type: ignore[assignment]
    total_available: int = 0  # Total training examples available in this split
    critic_max_turns: int = 0  # Number of critic runs that exceeded max turns

    def __post_init__(self) -> None:
        if self.recalls is None:
            self.recalls = []

    @property
    def mean_recall(self) -> float | None:
        """Mean recall percentage (0-100) or None if no data."""
        if not self.recalls:
            return None
        return statistics.mean(self.recalls)

    @property
    def zero_rate(self) -> float | None:
        """Percentage of samples with 0% recall, or None if no data."""
        if not self.recalls:
            return None
        zeros = sum(1 for r in self.recalls if r == 0.0)
        return 100.0 * zeros / len(self.recalls)


@dataclass
class PromptStats:
    """Statistics for a single prompt across all splits."""

    prompt_sha256: str
    prompt_length: int
    created_at: datetime
    splits: dict[Split, SplitStats]
    valid_best_count: int = 0  # Number of valid samples where this prompt is best (or tied)


def _display_split_analysis(
    console: Console,
    split_name: str,
    sample_results: dict[tuple[str, str], dict[str, float]],
    tp_counts_per_sample: dict[tuple[str, str], int],
    total_available: int,
    show_all_prompts: bool = False,
) -> None:
    """Display analysis of which prompts are best on which examples for a split.

    Args:
        console: Rich console for output
        split_name: Name of the split (e.g., "Training", "Validation")
        sample_results: Dict mapping (snapshot_slug, files_hash) -> {prompt_sha: recall_pct}
        tp_counts_per_sample: Dict mapping (snapshot_slug, files_hash) -> TP count
        total_available: Total number of examples available in this split
        show_all_prompts: If True, show all prompts instead of top 15
    """
    num_evaluated = len(sample_results)
    num_unknown = total_available - num_evaluated

    console.print(f"\n[bold]{split_name} Split Analysis[/bold] ({total_available} examples total)\n")

    # Categorize examples by best recall
    zero_recall_samples = []
    nonzero_recall_samples = []
    evaluated_sample_keys = set()  # Track which samples have been evaluated
    for sample_key, recalls in sample_results.items():
        evaluated_sample_keys.add(sample_key)
        max_recall = max(recalls.values())
        if max_recall == 0:
            zero_recall_samples.append((sample_key, recalls))
        else:
            nonzero_recall_samples.append((sample_key, recalls, max_recall))

    console.print(f"  Examples evaluated: {num_evaluated}")
    console.print(f"  Examples with best recall = 0: {len(zero_recall_samples)}")
    console.print(f"  Examples with best recall > 0: {len(nonzero_recall_samples)}")
    console.print(f"  [dim]Examples not evaluated (unknown): {num_unknown}[/dim]")

    # For zero-recall examples, show which prompts have been tried most
    if zero_recall_samples:
        console.print(f"\n[bold]Zero-Recall Examples ({split_name}):[/bold]")
        prompt_counts_zero: Counter[str] = Counter()
        for _, recalls in zero_recall_samples:
            prompt_counts_zero.update(recalls.keys())

        # Show top prompts tried on zero-recall examples
        for sha, count in prompt_counts_zero.most_common(10):
            pct = 100.0 * count / len(zero_recall_samples)
            console.print(f"  {short_sha(sha)}: evaluated on {count}/{len(zero_recall_samples)} ({pct:.0f}%)")

    # For nonzero-recall examples, show prompt best-coverage heatmap
    if nonzero_recall_samples:
        console.print(f"\n[bold]Nonzero-Recall Examples ({split_name} - Prompt Best Coverage):[/bold]")

        # Build matrix: for each prompt, which examples is it best on?
        # Also track which prompts have evaluated which examples
        prompt_best_on = defaultdict(list)  # sha -> [(example_idx, recall, tp_count)]
        prompt_evaluated_on = defaultdict(set)  # sha -> set of example indices evaluated

        for idx, (sample_key, recalls, max_recall) in enumerate(nonzero_recall_samples):
            tp_count = tp_counts_per_sample.get(sample_key, 0)
            for sha, recall in recalls.items():
                prompt_evaluated_on[sha].add(idx)
                if recall == max_recall:  # This prompt is best (or tied) on this example
                    prompt_best_on[sha].append((idx, recall, tp_count))

        # Sort prompts by number of examples they're best on
        sorted_prompts = sorted(
            prompt_best_on.items(), key=lambda x: (len(x[1]), sum(r for _, r, _ in x[1])), reverse=True
        )

        # Create table
        # Show one character per example (not bucketed) since we have relatively few
        coverage_width = len(nonzero_recall_samples) + 2  # +2 for brackets
        coverage_table = Table(
            show_header=True, header_style="bold cyan", box=box.SIMPLE, show_edge=False, padding=(0, 1)
        )
        coverage_table.add_column("Prompt", style="dim", width=SHORT_SHA_LENGTH)
        coverage_table.add_column("Best On", justify="right", width=7)
        coverage_table.add_column("Pct", justify="right", width=5)
        coverage_table.add_column("Coverage", width=coverage_width)

        # Display each prompt's coverage
        prompts_to_show = sorted_prompts if show_all_prompts else sorted_prompts[:15]
        for sha, best_examples in prompts_to_show:
            count = len(best_examples)
            pct = 100.0 * count / len(nonzero_recall_samples)

            # Create visual bar: one character per example
            # Three states: not evaluated (' '), evaluated but not best ('░'), best ('▓')
            best_example_indices = {idx for idx, _, _ in best_examples}
            evaluated_indices = prompt_evaluated_on.get(sha, set())
            visual_chars = []
            for idx in range(len(nonzero_recall_samples)):
                if idx in best_example_indices:
                    visual_chars.append("▓")
                elif idx in evaluated_indices:
                    visual_chars.append("░")
                else:
                    visual_chars.append(" ")
            visual = "".join(visual_chars)

            coverage_table.add_row(
                short_sha(sha), f"{count}/{len(nonzero_recall_samples)}", f"{pct:.0f}%", f"[{visual}]"
            )

        console.print(coverage_table)


def _add_split_columns(table: Table, split_name: str, color: str, total_examples: int) -> None:
    """Add columns for a single split (Valid or Train) with consistent formatting.

    Args:
        table: Rich Table to add columns to
        split_name: Name of split (e.g., "Valid", "Train")
        color: Rich color name (e.g., "cyan", "yellow")
        total_examples: Total available examples for this split
    """
    # Column order: Recall, LCB, N/{total}, Z%, S%, C%
    table.add_column(f"[{color}]{split_name} Recall[/{color}]", justify="right", width=11)
    table.add_column(f"[{color}]LCB[/{color}]", justify="right", width=7)
    table.add_column(f"[{color}]N/{total_examples}[/{color}]", justify="right", width=4)
    table.add_column(f"[{color}]Z%[/{color}]", justify="right", width=4)
    table.add_column(f"[{color}]S%[/{color}]", justify="right", width=4)
    table.add_column(f"[{color}]C%[/{color}]", justify="right", width=4)


def cmd_stats() -> None:
    """Display prompt statistics: count, runs per split, recall metrics.

    TODO: Add multi-level column headers (valid/train grouping) when Rich supports it.
    Currently Rich doesn't support column spanning (Issue #1529, #164), so we use
    prefixed column names. Workarounds: color-coded headers, visual separators, or
    wait for upstream support.
    """
    console = Console()
    max_recalls_per_sample: dict[Split, list[float]] = defaultdict(list)
    tp_counts_per_sample: dict[Split, dict[tuple[str, str], int]] = defaultdict(dict)

    # Track critic and grader run statuses
    critic_status_counts: Counter[str] = Counter()
    grader_status_counts: Counter[str] = Counter()

    with get_session() as session:
        # Compute total available training examples per split using shared logic
        # IMPORTANT: Uses same logic as GEPA's dataset loading:
        # - TRAIN: all critic scopes (per-file + full-specimen for tighter feedback loops)
        # - VALID/TEST: only full-specimen scopes (terminal metric - comprehensive review)
        total_samples_by_split: dict[Split, int] = {
            split: count_available_examples_for_split(session, split)
            for split in [Split.TRAIN, Split.VALID, Split.TEST]
        }

        # No longer building prompt_stats_list here - using query builder instead

        # Compute best_count per split: how many samples each prompt is best on (or tied for best)
        # Query all grader runs with their critic runs, grouped by split
        sample_results_by_split: dict[Split, dict[tuple[str, str], dict[str, float]]] = {
            Split.TRAIN: defaultdict(dict),
            Split.VALID: defaultdict(dict),
            Split.TEST: defaultdict(dict),
        }

        for split in [Split.TRAIN, Split.VALID, Split.TEST]:
            # Only include grader runs that match current critic scopes
            # This filters out stale runs from when valid/test used per-file scopes
            graders_query = (
                select(GraderRun, CriticRun)
                .join(GraderRun.critique_obj)
                .join(CriticRun, CriticRun.critique_id == GraderRun.critique_id)
                .join(GraderRun.snapshot_obj)
                .join(
                    Example,
                    (Example.snapshot_slug == CriticRun.snapshot_slug) & (Example.files_hash == CriticRun.files_hash),
                )
                .where(GraderRun.snapshot_obj.has(split=split))
                .where(GraderRun.output.isnot(None))
            )
            graders = session.execute(graders_query).all()

            # Group by training example (snapshot + files combination)
            for grader_run, critic_run in graders:
                sample_key = (critic_run.snapshot_slug, critic_run.files_hash)

                # Failed critic runs (no output or non-success) count as 0% recall
                if grader_run.output is None or not isinstance(grader_run.output, DBGraderSuccess):
                    recall_pct = 0.0
                    # Skip TP count collection for failed runs
                else:
                    recall_pct = grader_run.output.recall * 100.0
                    # Collect TP count for this sample (only need to record once per sample)
                    if sample_key not in tp_counts_per_sample[split]:
                        tp_count = len(grader_run.output.canonical_tp_coverage)
                        tp_counts_per_sample[split][sample_key] = tp_count

                sample_results_by_split[split][sample_key][critic_run.prompt_sha256] = recall_pct

        # For each split and sample, find which prompt(s) achieved max recall
        prompt_best_counts: Counter[str] = Counter()
        for split in [Split.TRAIN, Split.VALID, Split.TEST]:
            for sample_recalls in sample_results_by_split[split].values():
                if not sample_recalls:
                    continue
                max_recall = max(sample_recalls.values())
                max_recalls_per_sample[split].append(max_recall)

                # Count best prompts for valid split only (for table display)
                if split == Split.VALID:
                    best_prompts = [sha for sha, recall in sample_recalls.items() if recall == max_recall]
                    prompt_best_counts.update(best_prompts)

        # Count critic and grader run statuses using SQL aggregation
        critic_status_rows = (
            session.query(CriticRun.output["tag"].astext, func.count(CriticRun.id))
            .filter(CriticRun.output.isnot(None))
            .group_by(CriticRun.output["tag"].astext)
            .all()
        )
        for status, count in critic_status_rows:
            critic_status_counts[status] = count

        grader_status_rows = (
            session.query(GraderRun.output["tag"].astext, func.count(GraderRun.id))
            .filter(GraderRun.output.isnot(None))
            .group_by(GraderRun.output["tag"].astext)
            .all()
        )
        for status, count in grader_status_rows:
            grader_status_counts[status] = count

    # Use query builder to get comprehensive prompt performance stats (already sorted by created_at DESC)
    prompt_perf_rows = query_prompt_performance_stats(session, limit=100)

    # Display summary
    console.print(f"\n[bold]Prompt Statistics[/bold] ({len(prompt_perf_rows)} prompts)\n")

    # Get total available examples for headers
    valid_total = total_samples_by_split[Split.VALID]
    train_total = total_samples_by_split[Split.TRAIN]

    # Create new table with requested columns
    table = Table(show_header=True, header_style="bold cyan", box=box.HORIZONTALS, show_edge=False, padding=(0, 0))
    table.add_column("SHA", style="dim", width=SHORT_SHA_LENGTH)
    table.add_column("Age", justify="right", width=4)
    table.add_column("Chars", justify="right", width=6)
    # Add Valid and Train split columns using helper
    _add_split_columns(table, "Valid", "cyan", valid_total)
    _add_split_columns(table, "Train", "yellow", train_total)

    for row in prompt_perf_rows:
        sha_short = short_sha(row.prompt_sha256)
        age_str = format_age(row.created_at)

        # Format length as "11k" for > 1000, otherwise just the number
        length_str = f"{row.prompt_length // 1000}k" if row.prompt_length >= 1000 else str(row.prompt_length)

        # Format valid stats (green if fully computed)
        fully_computed = row.valid is not None and row.valid.success_count == valid_total
        valid_stats = format_split_stats(row.valid, fully_computed=fully_computed)

        # Format train stats (never marked as fully computed)
        train_stats = format_split_stats(row.train, fully_computed=False)

        table.add_row(
            sha_short,
            age_str,
            length_str,
            # Valid stats (canonical ordering via as_row_fields)
            *valid_stats.as_row_fields(),
            # Train stats (same canonical ordering)
            *train_stats.as_row_fields(),
        )

    console.print(table)

    # Display legend
    console.print(STATS_TABLE_LEGEND)

    # Get total available from counts computed earlier
    test_total = total_samples_by_split[Split.TEST]

    console.print("[bold]Summary:[/bold]")
    console.print(f"  Total prompts: {len(prompt_perf_rows)}")
    console.print("\n  Available examples per split:")
    console.print(f"    Train: {train_total}")
    console.print(f"    Valid: {valid_total}")
    console.print(f"    Test: {test_total}")

    # Find best prompt by valid recall
    valid_prompts = [(row, row.valid.mean_recall) for row in prompt_perf_rows if row.valid is not None]
    if valid_prompts:
        best = max(valid_prompts, key=lambda x: x[1])
        best_valid_stats = best[0].valid
        assert best_valid_stats is not None  # Filtered above
        console.print(
            f"\n[bold green]Best prompt (valid):[/bold green] "
            f"{short_sha(best[0].prompt_sha256)} with {best[1]:.1f}% recall "
            f"({best_valid_stats.success_count}/{best_valid_stats.total_count} runs)"
        )

    # Display run status statistics
    console.print("\n[bold cyan]Run Status Statistics[/bold cyan]")

    # Critic runs
    total_critic = sum(critic_status_counts.values())
    if total_critic > 0:
        console.print(f"\n  Critic runs (total: {total_critic}):")
        for status in sorted(critic_status_counts.keys(), key=lambda x: (x is None, x)):
            count = critic_status_counts[status]
            pct = count / total_critic
            status_label = status if status is not None else "(no tag)"
            console.print(f"    {status_label}: {count} ({pct:.1%})")
    else:
        console.print("  No critic runs found")

    # Grader runs
    total_grader = sum(grader_status_counts.values())
    if total_grader > 0:
        console.print(f"\n  Grader runs (total: {total_grader}):")
        for status in sorted(grader_status_counts.keys(), key=lambda x: (x is None, x)):
            count = grader_status_counts[status]
            pct = count / total_grader
            status_label = status if status is not None else "(no tag)"
            console.print(f"    {status_label}: {count} ({pct:.1%})")
    else:
        console.print("  No grader runs found")

    # Display distributions for each split
    for split in [Split.TRAIN, Split.VALID, Split.TEST]:
        split_name = split.value.capitalize()

        # Display distribution of max recall scores
        if max_recalls_per_sample[split]:
            recall_buckets = _generate_buckets(max_recalls_per_sample[split], num_buckets=10)
            _display_distribution(
                console,
                max_recalls_per_sample[split],
                f"Max Recall Distribution ({split_name} Examples)",
                recall_buckets,
                value_format="{:.1f}%",
            )

        # Display distribution of TP counts
        if tp_counts_per_sample[split]:
            tp_counts = list(tp_counts_per_sample[split].values())
            tp_buckets = _generate_buckets(tp_counts, num_buckets=10)
            _display_distribution(
                console,
                tp_counts,
                f"True Positive Count Distribution ({split_name} Examples)",
                tp_buckets,
                value_format="{:.0f}",
            )

        # Display split analysis (zero-recall and best coverage)
        # Show all prompts for training split, top 15 for others
        show_all = split == Split.TRAIN
        split_total = train_total if split == Split.TRAIN else (valid_total if split == Split.VALID else test_total)
        _display_split_analysis(
            console,
            split_name,
            sample_results_by_split[split],
            tp_counts_per_sample[split],
            total_available=split_total,
            show_all_prompts=show_all,
        )

    # Display tool call count distributions for successful runs
    with get_session() as session:
        # Query tool call counts for successful critic runs
        critic_tool_calls = (
            session.query(Event.transcript_id, func.count(Event.id).label("tool_call_count"))
            .join(CriticRun, CriticRun.transcript_id == Event.transcript_id)
            .where(Event.event_type == "tool_call")
            .where(CriticRun.critique_id.isnot(None))  # Only successful runs
            .group_by(Event.transcript_id)
            .all()
        )

        # Query tool call counts for successful grader runs
        grader_tool_calls = (
            session.query(Event.transcript_id, func.count(Event.id).label("tool_call_count"))
            .join(GraderRun, GraderRun.transcript_id == Event.transcript_id)
            .where(Event.event_type == "tool_call")
            .where(GraderRun.output.isnot(None))  # Only successful runs
            .group_by(Event.transcript_id)
            .all()
        )

    # Display critic tool call distribution
    if critic_tool_calls:
        critic_counts = [count for _, count in critic_tool_calls]
        critic_buckets = _generate_buckets(critic_counts, num_buckets=10, equal_width=True)
        _display_distribution(
            console, critic_counts, "Tool Calls per Successful Critic Run", critic_buckets, value_format="{:.0f}"
        )

    # Display grader tool call distribution
    if grader_tool_calls:
        grader_counts = [count for _, count in grader_tool_calls]
        grader_buckets = _generate_buckets(grader_counts, num_buckets=10, equal_width=True)
        _display_distribution(
            console, grader_counts, "Tool Calls per Successful Grader Run", grader_buckets, value_format="{:.0f}"
        )

    # Check for stale grader runs
    console.print("\n[bold cyan]Grader Run Staleness Check[/bold cyan]")
    console.print("=" * 60)

    total_runs, stale_runs, by_snapshot = check_staleness()

    if total_runs == 0:
        console.print("No grader runs found in database")
    else:
        stale_pct = (stale_runs / total_runs * 100) if total_runs > 0 else 0
        console.print(f"\nTotal grader runs: {total_runs}")
        console.print(f"Stale runs: {stale_runs} ({stale_pct:.1f}%)")
        console.print(f"Up-to-date runs: {total_runs - stale_runs} ({100 - stale_pct:.1f}%)")

        if stale_runs > 0:
            console.print("\n[bold]Stale runs by snapshot:[/bold]")
            table = Table(box=box.SIMPLE, show_header=True)
            table.add_column("Snapshot", style="cyan")
            table.add_column("Total", justify="right")
            table.add_column("Stale", justify="right")
            table.add_column("Stale %", justify="right")

            for slug in sorted(by_snapshot.keys()):
                snapshot_stats = by_snapshot[slug]
                if snapshot_stats["stale"] > 0:
                    pct = (
                        (snapshot_stats["stale"] / snapshot_stats["total"] * 100) if snapshot_stats["total"] > 0 else 0
                    )
                    table.add_row(str(slug), str(snapshot_stats["total"]), str(snapshot_stats["stale"]), f"{pct:.1f}%")

            console.print(table)
