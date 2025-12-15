"""CLI command for prompt statistics and evaluation metrics."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import statistics
from typing import cast

import plotext as plt  # type: ignore[import-untyped]
from rich import box
from rich.console import Console
from rich.table import Table
from sqlalchemy import func
import typer

from adgn.props.db import get_session
from adgn.props.db.datapoints import count_available_examples_by_scope_all, count_available_examples_for_split
from adgn.props.db.models import (
    AggregatedRecallByExample,
    AggregatedRecallByPrompt,
    CriticRun,
    Critique,
    Event,
    GraderRun,
    OccurrenceCredit,
    OccurrenceStatistics,
    Snapshot,
)
from adgn.props.db.query_builders import SplitPerformanceStats, query_prompt_performance_stats, query_recall_by_example
from adgn.props.display import SHORT_SHA_LENGTH, short_sha
from adgn.props.grader.staleness import check_staleness
from adgn.props.ids import SnapshotSlug
from adgn.props.splits import Split

# Stats subcommand group
stats_app = typer.Typer(help="Statistics and metrics commands")


# ============================================================================
# Formatting Helpers
# ============================================================================


def fmt_pct(value: float | None) -> str:
    """Format value as percentage (0 decimal places) or dash if None."""
    return f"{value:.0%}" if value is not None else "—"


def fmt_float(value: float | None, decimals: int = 2) -> str:
    """Format float with N decimal places or dash if None."""
    return f"{value:.{decimals}f}" if value is not None else "—"


def fmt_model(model: str, max_length: int = 12) -> str:
    """Truncate model name to max_length characters."""
    return model[:max_length]


def fmt_hash(hash_value: str | None) -> str:
    """Format hash as short SHA prefix or dash if None."""
    return short_sha(hash_value) if hash_value else "—"


# Stats table column legend (shared between CLI and examples)
STATS_TABLE_LEGEND = """
[bold]Column Legend:[/bold]
  [cyan]Recall%[/cyan]: Mean recall over all runs (failures count as 0.0)
  [cyan]LCB[/cyan]: Lower confidence bound (mean - 1σ/√n), — if n < 2
    - Penalizes high variance, useful for selecting reliable prompts
    - ~84% confidence the true mean is above this value
  [cyan]N / {total}[/cyan]: Number of examples evaluated out of total available
  [cyan]Z[/cyan]: Count of examples with 0% recall
  [cyan]S[/cyan]: Count of runs that exceeded max turns (stuck)
  [cyan]C[/cyan]: Count of runs that exceeded context length

[bold]Split Groups:[/bold]
  [cyan]Valid[/cyan]: Validation split (whole-snapshot only, terminal metric)
  [yellow]Tr-W[/yellow]: Train whole-snapshot (comprehensive full-repo review)
  [magenta]Tr-P[/magenta]: Train partial (per-file and multi-file examples)

[bold]Notes:[/bold]
  - Results sorted by valid LCB, then train-whole LCB, then train-partial LCB, then age
  - Success count is implicit from Z, S, C (their sum explains run distribution)
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
        - Success count is implicit from Z, S, C counts (they sum to explain the N)
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
        zero=str(stats.zero_count),
        stuck=str(stats.stuck_count),
        context=str(stats.context_count),
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
    sample_results: dict[tuple[SnapshotSlug, str | None], dict[str, float]],
    tp_counts_per_sample: dict[tuple[SnapshotSlug, str | None], int],
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
    # Column order: Recall, LCB, N/{total}, Z, S, C
    table.add_column(f"[{color}]{split_name} Recall[/{color}]", justify="right", width=11)
    table.add_column(f"[{color}]LCB[/{color}]", justify="right", width=7)
    table.add_column(f"[{color}]N/{total_examples}[/{color}]", justify="right", width=4)
    table.add_column(f"[{color}]Z[/{color}]", justify="right", width=4)
    table.add_column(f"[{color}]S[/{color}]", justify="right", width=4)
    table.add_column(f"[{color}]C[/{color}]", justify="right", width=4)


@stats_app.command("prompt")
def cmd_stats_prompt(
    split: Split | None = None,
    critic_model: str | None = None,
    whole_snapshot_only: bool = False,
    top: int | None = typer.Option(None, help="Show top N results by recall"),
    bottom: int | None = typer.Option(None, help="Show bottom N results by recall"),
) -> None:
    """Query aggregated recall metrics by prompt.

    Shows recall metrics aggregated by (split, prompt_sha256, critic_model, scope).
    By default shows top 50 results. Use --top/--bottom to customize.
    """
    console = Console()

    # Default to showing top 50 if neither top nor bottom is specified
    if top is None and bottom is None:
        top = 50

    with get_session() as session:
        # Build base query with filters
        base_query = session.query(AggregatedRecallByPrompt)
        if split:
            base_query = base_query.filter(AggregatedRecallByPrompt.split == split)
        if critic_model:
            base_query = base_query.filter(AggregatedRecallByPrompt.critic_model == critic_model)
        if whole_snapshot_only:
            base_query = base_query.filter(AggregatedRecallByPrompt.is_whole_snapshot)

        # Fetch top and/or bottom results
        sections_to_show: list[tuple[str, list[AggregatedRecallByPrompt]]] = []

        if top is not None:
            top_results: list[AggregatedRecallByPrompt] = (
                base_query.order_by(AggregatedRecallByPrompt.recall.desc()).limit(top).all()
            )
            sections_to_show.append((f"Top {top} by Recall", top_results))

        if bottom is not None:
            bottom_results: list[AggregatedRecallByPrompt] = (
                base_query.order_by(AggregatedRecallByPrompt.recall.asc()).limit(bottom).all()
            )
            sections_to_show.append((f"Bottom {bottom} by Recall", bottom_results))

        # Display each section
        for section_title, prompt_results in sections_to_show:
            console.print(
                f"\n[bold]Aggregated Recall by Prompt: {section_title}[/bold] ({len(prompt_results)} results)\n"
            )
            table = Table(show_header=True, header_style="bold cyan", box=box.SIMPLE)
            table.add_column("Prompt", width=SHORT_SHA_LENGTH)
            table.add_column("Split", width=6)
            table.add_column("Critic Model", width=15)
            table.add_column("Scope", width=5)
            table.add_column("Recall %", justify="right", width=9)
            table.add_column("Credit", justify="right", width=7)
            table.add_column("N Occ", justify="right", width=6)
            table.add_column("N Snap", justify="right", width=7)
            table.add_column("N Ex", justify="right", width=5)

            for r_prompt in prompt_results:
                scope_str = "whole" if r_prompt.is_whole_snapshot else "part"
                table.add_row(
                    short_sha(r_prompt.prompt_sha256),
                    r_prompt.split.value,
                    r_prompt.critic_model,
                    scope_str,
                    fmt_pct(r_prompt.recall),
                    fmt_float(r_prompt.total_credit, decimals=1),
                    str(r_prompt.n_occurrences),
                    str(r_prompt.n_snapshots),
                    str(r_prompt.n_examples),
                )

            console.print(table)


@stats_app.command("example")
def cmd_stats_example(
    split: Split | None = None,
    critic_model: str | None = None,
    grader_model: str | None = None,
    top: int | None = typer.Option(None, help="Show top N results by recall"),
    bottom: int | None = typer.Option(None, help="Show bottom N results by recall"),
) -> None:
    """Query aggregated recall metrics by example.

    Shows recall metrics aggregated by (split, snapshot_slug, files_hash, critic_model, grader_model).
    By default shows top 50 results. Use --top/--bottom to customize.
    """
    console = Console()

    # Default to showing top 50 if neither top nor bottom is specified
    if top is None and bottom is None:
        top = 50

    with get_session() as session:
        # Build base query with filters
        base_query = session.query(AggregatedRecallByExample)
        if split:
            base_query = base_query.filter(AggregatedRecallByExample.split == split)
        if critic_model:
            base_query = base_query.filter(AggregatedRecallByExample.critic_model == critic_model)
        if grader_model:
            base_query = base_query.filter(AggregatedRecallByExample.grader_model == grader_model)

        # Fetch top and/or bottom results
        sections_to_show: list[tuple[str, list[AggregatedRecallByExample]]] = []

        if top is not None:
            top_results = cast(
                list[AggregatedRecallByExample],
                base_query.order_by(AggregatedRecallByExample.recall.desc()).limit(top).all(),
            )
            sections_to_show.append((f"Top {top} by Recall", top_results))

        if bottom is not None:
            bottom_results = cast(
                list[AggregatedRecallByExample],
                base_query.order_by(AggregatedRecallByExample.recall.asc()).limit(bottom).all(),
            )
            sections_to_show.append((f"Bottom {bottom} by Recall", bottom_results))

        # Display each section
        for section_title, example_results in sections_to_show:
            console.print(
                f"\n[bold]Aggregated Recall by Example: {section_title}[/bold] ({len(example_results)} results)\n"
            )
            table = Table(show_header=True, header_style="bold cyan", box=box.SIMPLE)
            table.add_column("Snapshot", width=25)
            table.add_column("Files Hash", width=12)
            table.add_column("Split", width=6)
            table.add_column("Critic", width=12)
            table.add_column("Grader", width=12)
            table.add_column("Recall %", justify="right", width=9)
            table.add_column("Credit", justify="right", width=7)
            table.add_column("N Occ", justify="right", width=6)

            for r_example in example_results:
                table.add_row(
                    r_example.snapshot_slug,
                    fmt_hash(r_example.files_hash),
                    r_example.split.value,
                    fmt_model(r_example.critic_model),
                    fmt_model(r_example.grader_model),
                    fmt_pct(r_example.recall),
                    fmt_float(r_example.total_credit, decimals=1),
                    str(r_example.n_occurrences),
                )

            console.print(table)


@stats_app.command("occurrence")
def cmd_stats_occurrence(
    split: Split | None = None,
    critic_model: str | None = None,
    grader_model: str | None = None,
    top: int | None = typer.Option(None, help="Show top N results by mean credit"),
    bottom: int | None = typer.Option(None, help="Show bottom N results by mean credit"),
) -> None:
    """Query per-occurrence statistics.

    Shows statistics for individual occurrences: mean/stddev/min/max credit, catch rate.
    By default shows top 50 results. Use --top/--bottom to customize.
    """
    console = Console()

    # Default to showing top 50 if neither top nor bottom is specified
    if top is None and bottom is None:
        top = 50

    with get_session() as session:
        # Build base query with filters
        base_query = session.query(OccurrenceStatistics)
        if split:
            base_query = base_query.filter(OccurrenceStatistics.split == split)
        if critic_model:
            base_query = base_query.filter(OccurrenceStatistics.critic_model == critic_model)
        if grader_model:
            base_query = base_query.filter(OccurrenceStatistics.grader_model == grader_model)

        # Fetch top and/or bottom results
        sections_to_show: list[tuple[str, list[OccurrenceStatistics]]] = []

        if top is not None:
            top_results = cast(
                list[OccurrenceStatistics],
                base_query.order_by(OccurrenceStatistics.mean_credit.desc()).limit(top).all(),
            )
            sections_to_show.append((f"Top {top} by Mean Credit", top_results))

        if bottom is not None:
            bottom_results = cast(
                list[OccurrenceStatistics],
                base_query.order_by(OccurrenceStatistics.mean_credit.asc()).limit(bottom).all(),
            )
            sections_to_show.append((f"Bottom {bottom} by Mean Credit", bottom_results))

        # Display each section
        for section_title, occurrence_results in sections_to_show:
            console.print(
                f"\n[bold]Occurrence Statistics: {section_title}[/bold] ({len(occurrence_results)} results)\n"
            )
            table = Table(show_header=True, header_style="bold cyan", box=box.SIMPLE)
            table.add_column("TP ID", width=20)
            table.add_column("Occ ID", width=15)
            table.add_column("Split", width=6)
            table.add_column("Critic", width=12)
            table.add_column("Grader", width=12)
            table.add_column("Mean", justify="right", width=6)
            table.add_column("σ", justify="right", width=6)
            table.add_column("Min", justify="right", width=5)
            table.add_column("Max", justify="right", width=5)
            table.add_column("N Runs", justify="right", width=6)
            table.add_column("Catch%", justify="right", width=7)

            for r_occ in occurrence_results:
                table.add_row(
                    r_occ.tp_id[:20],
                    r_occ.occurrence_id[:15],
                    r_occ.split.value,
                    fmt_model(r_occ.critic_model),
                    fmt_model(r_occ.grader_model),
                    fmt_float(r_occ.mean_credit, decimals=2),
                    fmt_float(r_occ.stddev_credit, decimals=2),
                    fmt_float(r_occ.min_credit, decimals=2),
                    fmt_float(r_occ.max_credit, decimals=2),
                    str(r_occ.n_runs),
                    fmt_pct(r_occ.full_catch_rate),
                )

            console.print(table)


@stats_app.callback(invoke_without_command=True)
def cmd_stats(ctx: typer.Context) -> None:
    """Display prompt statistics: count, runs per split, recall metrics.

    Run without subcommand to see overall statistics, or use subcommands for specific views:
    - prompt: View aggregated recall by prompt
    - example: View aggregated recall by example
    - occurrence: View per-occurrence statistics

    TODO: Add multi-level column headers (valid/train grouping) when Rich supports it.
    Currently Rich doesn't support column spanning (Issue #1529, #164), so we use
    prefixed column names. Workarounds: color-coded headers, visual separators, or
    wait for upstream support.
    """
    # Only run default stats if no subcommand was invoked
    if ctx.invoked_subcommand is not None:
        return

    console = Console()
    max_recalls_per_sample: dict[Split, list[float]] = defaultdict(list)
    tp_counts_per_sample: dict[Split, dict[tuple[SnapshotSlug, str | None], int]] = defaultdict(dict)

    # Track run statuses by type
    status_counts: dict[str, defaultdict[str | None, int]] = {"Critic": defaultdict(int), "Grader": defaultdict(int)}
    # Track example counts by (split, is_whole_snapshot)
    example_counts: dict[tuple[Split, bool], int] = {}

    with get_session() as session:
        # Compute total available training examples per split using shared logic
        # IMPORTANT: Uses same logic as GEPA's dataset loading:
        # - TRAIN: all critic scopes (per-file + full-specimen for tighter feedback loops)
        # - VALID/TEST: only full-specimen scopes (terminal metric - comprehensive review)
        total_samples_by_split: dict[Split, int] = {
            split: count_available_examples_for_split(session, split)
            for split in [Split.TRAIN, Split.VALID, Split.TEST]
        }

        # Get counts for train and valid splits broken down by scope (single query)
        example_counts = count_available_examples_by_scope_all(session, [Split.TRAIN, Split.VALID])

        # No longer building prompt_stats_list here - using query builder instead

        # Compute best_count per split: how many samples each prompt is best on (or tied for best)
        # Query aggregated recall by example view (occurrence-weighted)
        sample_results_by_split: dict[Split, dict[tuple[SnapshotSlug, str | None], dict[str, float]]] = {
            Split.TRAIN: defaultdict(dict),
            Split.VALID: defaultdict(dict),
            Split.TEST: defaultdict(dict),
        }

        for split in [Split.TRAIN, Split.VALID, Split.TEST]:
            # Query occurrence-weighted recall per (example, prompt) using helper
            results = query_recall_by_example(session, split=split)

            for recall_row in results:
                sample_key = (recall_row.snapshot_slug, recall_row.files_hash)
                sample_results_by_split[split][sample_key][recall_row.prompt_sha256] = recall_row.recall

            # Get TP counts per sample (constant per example, not per prompt/run)
            tp_count_results = (
                session.query(
                    OccurrenceCredit.snapshot_slug,
                    OccurrenceCredit.files_hash,
                    func.count(func.distinct(OccurrenceCredit.occurrence_id)).label("n_occurrences"),
                )
                .filter(OccurrenceCredit.split == split)
                .group_by(OccurrenceCredit.snapshot_slug, OccurrenceCredit.files_hash)
                .all()
            )

            for result in tp_count_results:
                sample_key = (result.snapshot_slug, result.files_hash)
                tp_counts_per_sample[split][sample_key] = result.n_occurrences

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

        # Count run statuses using SQL aggregation
        # Filter to same scope as per-prompt stats: TRAIN + VALID (all examples)
        critic_status_rows = (
            session.query(CriticRun.output["tag"].astext, func.count(CriticRun.id))
            .join(Snapshot, Snapshot.slug == CriticRun.snapshot_slug)
            .filter(CriticRun.output.isnot(None), (Snapshot.split == Split.TRAIN) | (Snapshot.split == Split.VALID))
            .group_by(CriticRun.output["tag"].astext)
            .all()
        )
        for status, count in critic_status_rows:
            status_counts["Critic"][status] = count

        grader_status_rows = (
            session.query(GraderRun.output["tag"].astext, func.count(GraderRun.id))
            .join(Critique, Critique.id == GraderRun.critique_id)
            .join(CriticRun, CriticRun.critique_id == Critique.id)
            .join(Snapshot, Snapshot.slug == CriticRun.snapshot_slug)
            .filter(GraderRun.output.isnot(None), (Snapshot.split == Split.TRAIN) | (Snapshot.split == Split.VALID))
            .group_by(GraderRun.output["tag"].astext)
            .all()
        )
        for status, count in grader_status_rows:
            status_counts["Grader"][status] = count

    # Use query builder to get comprehensive prompt performance stats (already sorted by created_at DESC)
    prompt_perf_rows = query_prompt_performance_stats(session, limit=100)

    # Display summary
    console.print(f"\n[bold]Prompt Statistics[/bold] ({len(prompt_perf_rows)} prompts)\n")

    # Create new table with requested columns
    table = Table(show_header=True, header_style="bold cyan", box=box.HORIZONTALS, show_edge=False, padding=(0, 0))
    table.add_column("SHA", style="dim", width=SHORT_SHA_LENGTH)
    table.add_column("Age", justify="right", width=4)
    table.add_column("Chars", justify="right", width=6)
    # Add Valid (whole and partial), Train Whole, and Train Partial split columns using helper
    _add_split_columns(table, "Val-W", "cyan", example_counts[(Split.VALID, True)])
    _add_split_columns(table, "Val-P", "blue", example_counts[(Split.VALID, False)])
    _add_split_columns(table, "Tr-W", "yellow", example_counts[(Split.TRAIN, True)])
    _add_split_columns(table, "Tr-P", "magenta", example_counts[(Split.TRAIN, False)])

    for row in prompt_perf_rows:
        sha_short = short_sha(row.prompt_sha256)
        age_str = format_age(row.created_at)

        # Format length as "11k" for > 1000, otherwise just the number
        length_str = f"{row.prompt_length // 1000}k" if row.prompt_length >= 1000 else str(row.prompt_length)

        # Get stats from dict using (split, is_whole_snapshot) keys
        valid_whole = row.stats.get((Split.VALID, True))
        valid_partial = row.stats.get((Split.VALID, False))
        train_whole = row.stats.get((Split.TRAIN, True))
        train_partial = row.stats.get((Split.TRAIN, False))

        # Format valid whole stats (green if fully computed)
        fully_computed_valid_whole = (
            valid_whole is not None and valid_whole.success_count == example_counts[(Split.VALID, True)]
        )
        valid_whole_stats = format_split_stats(valid_whole, fully_computed=fully_computed_valid_whole)

        # Format valid partial stats (green if fully computed)
        fully_computed_valid_partial = (
            valid_partial is not None and valid_partial.success_count == example_counts[(Split.VALID, False)]
        )
        valid_partial_stats = format_split_stats(valid_partial, fully_computed=fully_computed_valid_partial)

        # Format train whole-snapshot stats (green if fully computed)
        fully_computed_train_whole = (
            train_whole is not None and train_whole.success_count == example_counts[(Split.TRAIN, True)]
        )
        train_whole_stats = format_split_stats(train_whole, fully_computed=fully_computed_train_whole)

        # Format train partial stats (green if fully computed)
        fully_computed_train_partial = (
            train_partial is not None and train_partial.success_count == example_counts[(Split.TRAIN, False)]
        )
        train_partial_stats = format_split_stats(train_partial, fully_computed=fully_computed_train_partial)

        table.add_row(
            sha_short,
            age_str,
            length_str,
            # Valid whole stats (canonical ordering via as_row_fields)
            *valid_whole_stats.as_row_fields(),
            # Valid partial stats (same canonical ordering)
            *valid_partial_stats.as_row_fields(),
            # Train whole stats (same canonical ordering)
            *train_whole_stats.as_row_fields(),
            # Train partial stats (same canonical ordering)
            *train_partial_stats.as_row_fields(),
        )

    console.print(table)

    # Display legend
    console.print(STATS_TABLE_LEGEND)

    console.print("[bold]Summary:[/bold]")
    console.print(f"  Total prompts: {len(prompt_perf_rows)}")
    console.print("\n  Available examples per split:")
    for split in [Split.VALID, Split.TRAIN]:
        console.print(
            f"    {split.value.capitalize()}: {total_samples_by_split[split]} total "
            f"(whole: {example_counts[(split, True)]}, partial: {example_counts[(split, False)]})"
        )
    console.print(f"    Test: {total_samples_by_split[Split.TEST]}")

    # Find best prompt by valid whole-snapshot recall (terminal metric)
    valid_whole_prompts = []
    for row in prompt_perf_rows:
        stats = row.stats.get((Split.VALID, True))
        if stats is not None:
            valid_whole_prompts.append((row, stats))

    if valid_whole_prompts:
        best = max(valid_whole_prompts, key=lambda x: x[1].mean_recall)
        best_row, best_valid_stats = best
        console.print(
            f"\n[bold green]Best prompt (valid whole-snapshot):[/bold green] "
            f"{short_sha(best_row.prompt_sha256)} with {best_valid_stats.mean_recall:.1f}% recall "
            f"({best_valid_stats.success_count}/{best_valid_stats.total_count} runs)"
        )

    # Display run status statistics as table
    console.print("\n[bold cyan]Run Status Statistics[/bold cyan]")

    # Collect all unique statuses across all run types
    all_statuses = sorted(
        set().union(*(counts.keys() for counts in status_counts.values())),
        key=lambda x: (x is None, x),  # None (no tag) sorts last
    )

    # Build table with dynamic columns
    status_table = Table(show_header=True, box=box.SIMPLE)
    status_table.add_column("Type", style="bold")
    status_table.add_column("Total", justify="right")

    for status in all_statuses:
        label = "(no tag)" if status is None else status
        status_table.add_column(label, justify="right")

    # Add rows for each run type
    for run_type, counts in status_counts.items():
        total = sum(counts.values())
        if total > 0:
            row_data = [run_type, str(total)]
            for status in all_statuses:
                count = counts[status]
                pct = count / total
                row_data.append(f"{count} ({pct:.1%})")
            status_table.add_row(*row_data)

    console.print(status_table)

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
        split_total = total_samples_by_split[split]
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
