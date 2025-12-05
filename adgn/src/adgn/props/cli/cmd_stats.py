"""CLI command for prompt statistics and evaluation metrics."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import statistics

from rich.console import Console
from rich.table import Table
from sqlalchemy import distinct, func, select, tuple_
from sqlalchemy.orm import joinedload

from adgn.props.db import get_session, init_db
from adgn.props.db.models import CriticRun, GraderRun, Prompt
from adgn.props.splits import Split


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
    train: SplitStats
    valid: SplitStats
    test: SplitStats
    valid_best_count: int = 0  # Number of valid samples where this prompt is best (or tied)


def cmd_stats() -> None:
    """Display prompt statistics: count, runs per split, recall metrics."""
    init_db()

    console = Console()

    with get_session() as session:
        # First, compute total available training examples per split
        # Count distinct (snapshot_slug, files_hash) combinations per split
        total_samples_by_split: dict[Split, int] = {}
        for split in [Split.TRAIN, Split.VALID, Split.TEST]:
            count_query = (
                select(func.count(distinct(tuple_(CriticRun.snapshot_slug, CriticRun.files_hash))))
                .join(CriticRun.snapshot_obj)
                .where(CriticRun.snapshot_obj.has(split=split))
            )
            total_samples_by_split[split] = session.execute(count_query).scalar() or 0

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
                train=SplitStats(total_available=total_samples_by_split[Split.TRAIN]),
                valid=SplitStats(total_available=total_samples_by_split[Split.VALID]),
                test=SplitStats(total_available=total_samples_by_split[Split.TEST]),
            )

            # Count critic runs by split
            for critic_run in prompt.critic_runs:
                split = critic_run.snapshot_obj.split
                split_stats = _get_split_stats(stats, split)
                split_stats.initiated += 1

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
                split_stats = _get_split_stats(stats, split)

                # Skip grader runs with no output (incomplete/failed)
                if grader_run.output is None:
                    continue

                split_stats.completed += 1

                # Extract recall from grader output (grade.recall is in [0,1])
                recall_pct = grader_run.output.grade.recall * 100.0
                split_stats.recalls.append(recall_pct)

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

        # For each sample, find which prompt(s) achieved max recall
        prompt_best_counts: dict[str, int] = defaultdict(int)
        for sample_recalls in sample_results.values():
            if not sample_recalls:
                continue
            max_recall = max(sample_recalls.values())
            # All prompts that achieved max recall on this sample
            best_prompts = [sha for sha, recall in sample_recalls.items() if recall == max_recall]
            for sha in best_prompts:
                prompt_best_counts[sha] += 1

        # Update stats with best counts
        for stats in prompt_stats_list:
            stats.valid_best_count = prompt_best_counts.get(stats.prompt_sha256, 0)

    # Display summary
    console.print(f"\n[bold]Prompt Statistics[/bold] ({len(prompt_stats_list)} prompts)\n")

    # Create table
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("SHA (short)", style="dim", width=12)
    table.add_column("Length", justify="right", width=7)
    table.add_column("Split", width=5)
    table.add_column("Runs (C/I)", justify="right", width=12)
    table.add_column("Best", justify="right", width=6)
    table.add_column("Mean Recall", justify="right", width=11)
    table.add_column("Zero Rate", justify="right", width=10)

    for stats in prompt_stats_list:
        sha_short = stats.prompt_sha256[:12]

        # Train row
        train_recall = f"{stats.train.mean_recall:.1f}%" if stats.train.mean_recall is not None else "—"
        train_zero = f"{stats.train.zero_rate:.0f}%" if stats.train.zero_rate is not None else "—"
        train_runs = f"{stats.train.completed}/{stats.train.initiated}" if stats.train.initiated > 0 else "—"
        table.add_row(
            sha_short,
            f"{stats.prompt_length:,}",
            "train",
            train_runs,
            "",  # Best column (only shown for valid)
            train_recall,
            train_zero,
        )

        # Valid row
        valid_recall = f"{stats.valid.mean_recall:.1f}%" if stats.valid.mean_recall is not None else "—"
        valid_zero = f"{stats.valid.zero_rate:.0f}%" if stats.valid.zero_rate is not None else "—"
        valid_runs = f"{stats.valid.completed}/{stats.valid.initiated}" if stats.valid.initiated > 0 else "—"
        valid_best = str(stats.valid_best_count) if stats.valid_best_count > 0 else "—"
        table.add_row(
            "",
            "",
            "valid",
            valid_runs,
            valid_best,
            valid_recall,
            valid_zero,
            style="bright_blue" if stats.valid.mean_recall else "",
        )

        # Test row
        test_recall = f"{stats.test.mean_recall:.1f}%" if stats.test.mean_recall is not None else "—"
        test_zero = f"{stats.test.zero_rate:.0f}%" if stats.test.zero_rate is not None else "—"
        test_runs = f"{stats.test.completed}/{stats.test.initiated}" if stats.test.initiated > 0 else "—"
        table.add_row("", "", "test", test_runs, "", test_recall, test_zero)

        # Separator between prompts
        table.add_row("", "", "", "", "", "", "")

    console.print(table)

    # Summary statistics
    total_initiated = sum(s.train.initiated + s.valid.initiated + s.test.initiated for s in prompt_stats_list)
    total_completed = sum(s.train.completed + s.valid.completed + s.test.completed for s in prompt_stats_list)

    # Get total available from any prompt's stats (they're all the same)
    if prompt_stats_list:
        train_total = prompt_stats_list[0].train.total_available
        valid_total = prompt_stats_list[0].valid.total_available
        test_total = prompt_stats_list[0].test.total_available
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
    valid_prompts = [(s, s.valid.mean_recall) for s in prompt_stats_list if s.valid.mean_recall is not None]
    if valid_prompts:
        best = max(valid_prompts, key=lambda x: x[1])  # type: ignore[arg-type, return-value]
        console.print(
            f"\n[bold green]Best prompt (valid):[/bold green] "
            f"{best[0].prompt_sha256[:12]} with {best[1]:.1f}% recall "  # type: ignore[index]
            f"({best[0].valid.completed} samples)"
        )


def _get_split_stats(stats: PromptStats, split: Split) -> SplitStats:
    """Get the SplitStats for a given split."""
    if split == Split.TRAIN:
        return stats.train
    if split == Split.VALID:
        return stats.valid
    if split == Split.TEST:
        return stats.test
    raise ValueError(f"Unknown split: {split}")
