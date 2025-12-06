"""CLI command for prompt statistics and evaluation metrics."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
import statistics

import plotext as plt  # type: ignore[import-untyped]
from rich import box
from rich.console import Console
from rich.table import Table
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from adgn.props.db import get_session, init_db
from adgn.props.db.models import CriticRun, CriticScopeDB, GraderRun, Prompt, Snapshot
from adgn.props.splits import Split

# Display constants
SHORT_SHA_LENGTH = 6


def _generate_buckets(
    values: Sequence[float | int], num_buckets: int = 7
) -> list[tuple[str, float | int, float | int]]:
    """Generate bucket ranges automatically based on data distribution.

    Args:
        values: List of numeric values
        num_buckets: Desired number of buckets (default 7)

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

    initiated: int = 0  # Critic runs initiated
    completed: int = 0  # Grader runs completed
    recalls: list[float] = None  # type: ignore[assignment]
    total_available: int = 0  # Total training examples available in this split

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


def cmd_stats() -> None:
    """Display prompt statistics: count, runs per split, recall metrics."""
    init_db()

    console = Console()
    max_recalls_per_sample: list[float] = []
    tp_counts_per_sample: dict[tuple[str, str], int] = {}  # (snapshot_slug, files_hash) -> TP count

    with get_session() as session:
        # First, compute total available training examples per split
        # Training examples = critic_scopes (explicit) + snapshots without scopes (1 implicit example each)
        total_samples_by_split: dict[Split, int] = {}
        for split in [Split.TRAIN, Split.VALID, Split.TEST]:
            # Count explicit critic scopes for this split
            critic_scopes_count = (
                session.execute(
                    select(func.count(CriticScopeDB.id)).join(CriticScopeDB.snapshot_obj).where(Snapshot.split == split)
                ).scalar()
                or 0
            )

            # Count snapshots without any critic scopes (they have 1 implicit full-snapshot example)
            snapshots_without_scopes = (
                session.execute(
                    select(func.count(Snapshot.slug))
                    .where(Snapshot.split == split)
                    .where(~select(CriticScopeDB.id).where(CriticScopeDB.snapshot_slug == Snapshot.slug).exists())
                ).scalar()
                or 0
            )

            total_samples_by_split[split] = critic_scopes_count + snapshots_without_scopes

        # Query all prompts with their critic runs
        prompts_query = (
            select(Prompt)
            .options(joinedload(Prompt.critic_runs).joinedload(CriticRun.snapshot_obj))
            .order_by(Prompt.created_at)
        )
        prompts = session.execute(prompts_query).unique().scalars().all()

        if not prompts:
            console.print("[yellow]No prompts found in database.[/yellow]")
            return

        # Build stats for each prompt
        prompt_stats_list: list[PromptStats] = []

        for prompt in prompts:
            stats = PromptStats(
                prompt_sha256=prompt.prompt_sha256,
                prompt_length=len(prompt.prompt_text),
                created_at=prompt.created_at,
                splits={
                    Split.TRAIN: SplitStats(total_available=total_samples_by_split[Split.TRAIN]),
                    Split.VALID: SplitStats(total_available=total_samples_by_split[Split.VALID]),
                    Split.TEST: SplitStats(total_available=total_samples_by_split[Split.TEST]),
                },
            )

            # Count critic runs by split
            for critic_run in prompt.critic_runs:
                split = critic_run.snapshot_obj.split
                stats.splits[split].initiated += 1

            # Query grader runs for this prompt's critiques
            # Join: critique → critic_run → prompt, filter by prompt_sha256
            grader_query = (
                select(GraderRun)
                .join(GraderRun.critique_obj)
                .join(CriticRun, CriticRun.critique_id == GraderRun.critique_id)
                .where(CriticRun.prompt_sha256 == prompt.prompt_sha256)
                .options(joinedload(GraderRun.snapshot_obj))
            )
            grader_runs = session.execute(grader_query).unique().scalars().all()

            # Accumulate grader metrics by split
            for grader_run in grader_runs:
                split = grader_run.snapshot_obj.split

                # Skip grader runs with no output (incomplete/failed)
                if grader_run.output is None:
                    continue

                stats.splits[split].completed += 1

                # Extract recall from grader output (grade.recall is in [0,1])
                recall_pct = grader_run.output.grade.recall * 100.0
                stats.splits[split].recalls.append(recall_pct)

            prompt_stats_list.append(stats)

        # Compute valid_best_count: how many valid samples each prompt is best on (or tied for best)
        # Query all valid grader runs with their critic runs
        valid_graders_query = (
            select(GraderRun, CriticRun)
            .join(GraderRun.critique_obj)
            .join(CriticRun, CriticRun.critique_id == GraderRun.critique_id)
            .join(GraderRun.snapshot_obj)
            .where(GraderRun.snapshot_obj.has(split=Split.VALID))
            .where(GraderRun.output.isnot(None))
        )
        valid_graders = session.execute(valid_graders_query).all()

        # Group by training example (snapshot + files combination)
        # Key: (snapshot_slug, files_hash) -> {prompt_sha: recall}
        sample_results: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
        for grader_run, critic_run in valid_graders:
            # Skip grader runs with no output (should be filtered by query, but check again)
            if grader_run.output is None:
                continue
            recall_pct = grader_run.output.grade.recall * 100.0
            sample_key = (critic_run.snapshot_slug, critic_run.files_hash)
            sample_results[sample_key][critic_run.prompt_sha256] = recall_pct

            # Collect TP count for this sample (only need to record once per sample)
            if sample_key not in tp_counts_per_sample:
                tp_count = len(grader_run.output.grade.canonical_tp_coverage)
                tp_counts_per_sample[sample_key] = tp_count

        # For each sample, find which prompt(s) achieved max recall
        prompt_best_counts: dict[str, int] = defaultdict(int)
        for sample_recalls in sample_results.values():
            if not sample_recalls:
                continue
            max_recall = max(sample_recalls.values())
            max_recalls_per_sample.append(max_recall)
            # All prompts that achieved max recall on this sample
            best_prompts = [sha for sha, recall in sample_recalls.items() if recall == max_recall]
            for sha in best_prompts:
                prompt_best_counts[sha] += 1

        # Update stats with best counts
        for stats in prompt_stats_list:
            stats.valid_best_count = prompt_best_counts.get(stats.prompt_sha256, 0)

    # Sort by valid recall (descending), then by created_at (newest first)
    def sort_key(s: PromptStats) -> tuple[float, float]:
        recall = s.splits[Split.VALID].mean_recall
        return (-(recall if recall is not None else -1.0), -s.created_at.timestamp())

    prompt_stats_list.sort(key=sort_key)

    # Display summary
    console.print(f"\n[bold]Prompt Statistics[/bold] ({len(prompt_stats_list)} prompts)\n")

    # Create table
    table = Table(show_header=True, header_style="bold cyan", box=box.HORIZONTALS, show_edge=False, padding=(0, 1))
    table.add_column("SHA", style="dim", width=SHORT_SHA_LENGTH)
    table.add_column("Created", width=19)
    table.add_column("Chars", justify="right", width=6)
    table.add_column("Split", width=5)
    table.add_column("Runs (B/C/I)", justify="right", width=14)
    table.add_column("Mean Recall", justify="right", width=11)
    table.add_column("Zero Rate", justify="right", width=10)

    for idx, stats in enumerate(prompt_stats_list):
        sha_short = stats.prompt_sha256[:SHORT_SHA_LENGTH]
        created_str = stats.created_at.strftime("%Y-%m-%dT%H:%M:%S")

        # Format length as "11k" for > 1000, otherwise just the number
        length_str = f"{stats.prompt_length // 1000}k" if stats.prompt_length >= 1000 else str(stats.prompt_length)

        first_row = True

        # Process each split (train, valid, test)
        for split in [Split.TRAIN, Split.VALID, Split.TEST]:
            split_stats = stats.splits[split]

            # Skip if no data for this split
            if split_stats.initiated == 0:
                continue

            # Format metrics
            recall = f"{split_stats.mean_recall:.1f}%" if split_stats.mean_recall is not None else "—"
            zero_rate = f"{split_stats.zero_rate:.0f}%" if split_stats.zero_rate is not None else "—"

            # Format runs as best/completed/initiated (best count only for valid split)
            if split == Split.VALID and stats.valid_best_count > 0:
                runs = f"{stats.valid_best_count}/{split_stats.completed}/{split_stats.initiated}"
            else:
                runs = f"{split_stats.completed}/{split_stats.initiated}"

            table.add_row(
                sha_short if first_row else "",
                created_str if first_row else "",
                length_str if first_row else "",
                split.value,  # Use split.value to get "train", "valid", "test"
                runs,
                recall,
                zero_rate,
                style="bright_blue" if split == Split.VALID and split_stats.mean_recall else "",
            )
            first_row = False

        # Separator between prompts (only if we added at least one row and not the last prompt)
        if not first_row and idx < len(prompt_stats_list) - 1:
            table.add_row("", "", "", "", "", "", "")

    console.print(table)

    # Summary statistics
    total_initiated = sum(
        s.splits[Split.TRAIN].initiated + s.splits[Split.VALID].initiated + s.splits[Split.TEST].initiated
        for s in prompt_stats_list
    )
    total_completed = sum(
        s.splits[Split.TRAIN].completed + s.splits[Split.VALID].completed + s.splits[Split.TEST].completed
        for s in prompt_stats_list
    )

    # Get total available from any prompt's stats (they're all the same)
    if prompt_stats_list:
        train_total = prompt_stats_list[0].splits[Split.TRAIN].total_available
        valid_total = prompt_stats_list[0].splits[Split.VALID].total_available
        test_total = prompt_stats_list[0].splits[Split.TEST].total_available
    else:
        train_total = valid_total = test_total = 0

    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Total prompts: {len(prompt_stats_list)}")
    console.print(f"  Total critic runs initiated: {total_initiated}")
    console.print(f"  Total grader runs completed: {total_completed}")
    console.print("\n  Available training examples:")
    console.print(f"    Train: {train_total}")
    console.print(f"    Valid: {valid_total}")
    console.print(f"    Test: {test_total}")

    # Find best prompt by valid recall
    valid_prompts = [
        (s, s.splits[Split.VALID].mean_recall)
        for s in prompt_stats_list
        if s.splits[Split.VALID].mean_recall is not None
    ]
    if valid_prompts:
        best = max(valid_prompts, key=lambda x: x[1])  # type: ignore[arg-type, return-value]
        console.print(
            f"\n[bold green]Best prompt (valid):[/bold green] "
            f"{best[0].prompt_sha256[:SHORT_SHA_LENGTH]} with {best[1]:.1f}% recall "  # type: ignore[index]
            f"({best[0].splits[Split.VALID].completed} samples)"
        )

    # Display distribution of max recall scores per validation example
    if max_recalls_per_sample:
        recall_buckets = _generate_buckets(max_recalls_per_sample, num_buckets=10)
        _display_distribution(
            console,
            max_recalls_per_sample,
            "Max Recall Distribution (Valid Examples)",
            recall_buckets,
            value_format="{:.1f}%",
        )

    # Display distribution of TP counts per validation example
    if tp_counts_per_sample:
        tp_counts = list(tp_counts_per_sample.values())
        tp_buckets = _generate_buckets(tp_counts, num_buckets=10)
        _display_distribution(
            console, tp_counts, "True Positive Count Distribution (Valid Examples)", tp_buckets, value_format="{:.0f}"
        )
