"""Detector commands: run-detector, detector-coverage."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import aiodocker
from rich.console import Console
from rich.table import Table
from sqlalchemy import func
import typer
from typer_di import Depends

from adgn.cli_utils import async_run
from adgn.llm.rendering.rich_renderers import render_to_rich
from adgn.openai_utils.client_factory import build_client
from adgn.openai_utils.model import OpenAIModelProto
from adgn.props.cli import common_options as opt
from adgn.props.cli.resources import get_hydrator
from adgn.props.cli.shared import filter_files
from adgn.props.critic.critic import run_critic
from adgn.props.critic.models import CriticInput, CriticSuccess
from adgn.props.critic.prompts import list_critic_system_prompts
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, Snapshot
from adgn.props.db.prompts import load_and_upsert_detector_prompt
from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import AllFilesScope


@dataclass
class DetectorCoverage:
    """Coverage data for a single detector prompt."""

    filename: str
    prompt_sha256: str
    total_runs: int
    evaluated_snapshots: list[SnapshotSlug]
    missing_snapshots: list[SnapshotSlug]


@dataclass
class CoverageSummary:
    """Overall coverage statistics."""

    total_detectors: int
    total_specimens: int
    total_possible_pairs: int
    evaluated_pairs: int
    missing_pairs: int

    @property
    def coverage_pct(self) -> float:
        """Calculate coverage percentage."""
        return (self.evaluated_pairs / self.total_possible_pairs * 100) if self.total_possible_pairs > 0 else 0

    @classmethod
    def from_coverage_data(cls, coverage_data: list[DetectorCoverage], total_specimens: int) -> CoverageSummary:
        """Compute overall coverage statistics from detector coverage data."""
        total_possible = len(coverage_data) * total_specimens
        total_evaluated = sum(len(d.evaluated_snapshots) for d in coverage_data)
        missing = total_possible - total_evaluated

        return cls(
            total_detectors=len(coverage_data),
            total_specimens=total_specimens,
            total_possible_pairs=total_possible,
            evaluated_pairs=total_evaluated,
            missing_pairs=missing,
        )


def fetch_coverage_data(
    detector_prompts: list[tuple[str, str]], all_snapshots: set[SnapshotSlug]
) -> list[DetectorCoverage]:
    """Query database for (detector, snapshot) pair coverage."""
    with get_session() as session:
        return [
            _build_detector_coverage(session, filename, prompt_sha256, all_snapshots)
            for filename, prompt_sha256 in detector_prompts
        ]


def _build_detector_coverage(
    session, filename: str, prompt_sha256: str, all_snapshots: set[SnapshotSlug]
) -> DetectorCoverage:
    """Build coverage data for a single detector."""
    # Get all snapshots this detector has been run against
    evaluated_snapshots_raw = (
        session.query(CriticRun.snapshot_slug).filter(CriticRun.prompt_sha256 == prompt_sha256).distinct().all()
    )
    evaluated_set = {SnapshotSlug(row[0]) for row in evaluated_snapshots_raw}
    missing_snapshots = [s for s in all_snapshots if s not in evaluated_set]

    # Get total run count
    total_runs = session.query(func.count(CriticRun.id)).filter(CriticRun.prompt_sha256 == prompt_sha256).scalar() or 0

    return DetectorCoverage(
        filename=filename,
        prompt_sha256=prompt_sha256,
        total_runs=total_runs,
        evaluated_snapshots=sorted(evaluated_set, key=str),
        missing_snapshots=missing_snapshots,
    )


def build_coverage_table(coverage_data: list[DetectorCoverage], total_specimens: int) -> Table:
    """Build Rich table for coverage display."""
    table = Table(title="Detector Prompt Coverage (by Snapshot)")
    table.add_column("Detector", style="cyan")
    table.add_column("Hash", style="dim")
    table.add_column("Total Runs", justify="right")
    table.add_column("Snapshots", justify="right")
    table.add_column("Coverage", justify="right")
    table.add_column("Missing Snapshots", style="yellow")

    for data in coverage_data:
        evaluated_count = len(data.evaluated_snapshots)
        coverage_pct = (evaluated_count / total_specimens * 100) if total_specimens > 0 else 0

        coverage_style = "green" if evaluated_count == total_specimens else "red" if evaluated_count == 0 else "yellow"
        missing_display = ", ".join(data.missing_snapshots[:3])
        if len(data.missing_snapshots) > 3:
            missing_display += f" (+{len(data.missing_snapshots) - 3} more)"

        table.add_row(
            data.filename,
            data.prompt_sha256[:12],
            str(data.total_runs),
            f"{evaluated_count}/{total_specimens}",
            f"[{coverage_style}]{coverage_pct:.0f}%[/{coverage_style}]",
            missing_display if data.missing_snapshots else "-",
        )

    return table


def collect_missing_pairs(coverage_data: list[DetectorCoverage]) -> list[tuple[str, SnapshotSlug]]:
    """Extract all missing (detector, snapshot) pairs."""
    return [(data.filename, SnapshotSlug(snapshot)) for data in coverage_data for snapshot in data.missing_snapshots]


async def run_detector_on_specimen(
    detector_filename: str,
    snapshot_slug: SnapshotSlug,
    *,
    client: OpenAIModelProto,
    docker_client: aiodocker.Docker,
    verbose: bool,
    hydrator: SnapshotHydrator,
) -> tuple[str, str, bool]:
    """Run a single detector on a snapshot.

    Returns:
        (detector_filename, snapshot_slug, success)
    """
    prompt_sha256 = load_and_upsert_detector_prompt(detector_filename)
    await run_critic(
        input_data=CriticInput(snapshot_slug=snapshot_slug, files=AllFilesScope(), prompt_sha256=prompt_sha256),
        client=client,
        docker_client=docker_client,
        hydrator=hydrator,
        prompt_optimization_run_id=None,
        mount_properties=False,
        verbose=verbose,
        max_turns=100,
    )
    return (detector_filename, snapshot_slug, True)


async def run_missing_evaluations(
    missing_pairs: list[tuple[str, SnapshotSlug]],
    *,
    client: OpenAIModelProto,
    docker_client: aiodocker.Docker,
    verbose: bool,
    hydrator: SnapshotHydrator,
) -> int:
    """Run all missing (detector, snapshot) pairs in parallel.

    Returns:
        Number of successful evaluations.
    """
    if not missing_pairs:
        return 0

    console = Console()
    console.print(f"\n[yellow]Running {len(missing_pairs)} missing evaluations in parallel...[/yellow]")

    tasks = [
        run_detector_on_specimen(
            detector, snapshot, client=client, docker_client=docker_client, verbose=verbose, hydrator=hydrator
        )
        for detector, snapshot in missing_pairs
    ]
    results = await asyncio.gather(*tasks)

    successes = sum(1 for _, _, success in results if success)
    failures = len(results) - successes

    console.print(f"[green]✓ {successes} evaluations completed[/green]")
    if failures > 0:
        console.print(f"[red]✗ {failures} evaluations failed[/red]")

    return successes


async def run_detector_coverage(
    *, run_missing: bool, model: str, verbose: bool, docker_client: aiodocker.Docker, hydrator: SnapshotHydrator
) -> None:
    """Main entry point for detector-coverage command."""
    console = Console()

    # Discover all critic system prompts and specimens
    detector_filenames = list_critic_system_prompts()
    detector_prompts = [(f, load_and_upsert_detector_prompt(f)) for f in detector_filenames]

    # Get all snapshots from database
    with get_session() as session:
        snapshots = session.query(Snapshot).all()
        all_snapshots = {s.slug for s in snapshots}

    # Fetch current coverage
    coverage_data = fetch_coverage_data(detector_prompts, all_snapshots)
    summary = CoverageSummary.from_coverage_data(coverage_data, len(all_snapshots))

    # Display initial table and summary
    table = build_coverage_table(coverage_data, len(all_snapshots))
    console.print(table)

    typer.echo(f"\nTotal detectors: {summary.total_detectors}")
    typer.echo(f"Total specimens: {summary.total_specimens}")
    typer.echo(f"Total possible pairs: {summary.total_possible_pairs}")
    typer.echo(f"Evaluated pairs: {summary.evaluated_pairs} ({summary.coverage_pct:.1f}%)")
    typer.echo(f"Missing pairs: {summary.missing_pairs}")

    # Optionally run missing evaluations
    if run_missing:
        missing_pairs = collect_missing_pairs(coverage_data)
        if missing_pairs:
            client = build_client(model)
            successes = await run_missing_evaluations(
                missing_pairs, client=client, docker_client=docker_client, verbose=verbose, hydrator=hydrator
            )

            if successes > 0:
                # Re-fetch and display updated coverage
                typer.echo("\n" + "=" * 60)
                typer.echo("Updated coverage after running missing evaluations:")
                typer.echo("=" * 60 + "\n")

                updated_coverage = fetch_coverage_data(detector_prompts, all_snapshots)
                updated_summary = CoverageSummary.from_coverage_data(updated_coverage, len(all_snapshots))
                updated_table = build_coverage_table(updated_coverage, len(all_snapshots))

                console.print(updated_table)

                typer.echo(f"\nTotal detectors: {updated_summary.total_detectors}")
                typer.echo(f"Total specimens: {updated_summary.total_specimens}")
                typer.echo(f"Total possible pairs: {updated_summary.total_possible_pairs}")
                typer.echo(f"Evaluated pairs: {updated_summary.evaluated_pairs} ({updated_summary.coverage_pct:.1f}%)")
                typer.echo(f"Missing pairs: {updated_summary.missing_pairs}")
        else:
            typer.echo("\n✓ All (detector, snapshot) pairs already evaluated!")


# ---------- CLI command wrappers ----------


@async_run
async def cmd_run_detector(
    filename: str = typer.Argument(..., help="Detector filename (e.g., 'dead_code.md')"),
    snapshot: SnapshotSlug = opt.OPT_SNAPSHOT_REQUIRED,
    files: list[str] | None = opt.OPT_FILES_FILTER,
    model: str = opt.OPT_MODEL,
    verbose: bool = opt.OPT_VERBOSE,
    hydrator: SnapshotHydrator = Depends(get_hydrator),
) -> None:
    """Run detector (always structured mode)."""
    docker_client = aiodocker.Docker()
    try:
        # Load current file content and upsert to DB (auto-sync)
        prompt_sha256 = load_and_upsert_detector_prompt(filename)

        # Execute critic (fetches system+user prompts internally via prompt_sha256)
        async with hydrator.hydrate(snapshot) as hydrated:
            files_spec = filter_files(hydrated.all_discovered_files, files)
        critic_output, run_id, critique_id = await run_critic(
            input_data=CriticInput(snapshot_slug=snapshot, files=files_spec, prompt_sha256=prompt_sha256),
            client=build_client(model),
            docker_client=docker_client,
            hydrator=hydrator,
            prompt_optimization_run_id=None,
            mount_properties=False,
            verbose=verbose,
            max_turns=100,
        )

        # Output structured critique
        if isinstance(critic_output, CriticSuccess):
            Console().print(render_to_rich(critic_output.result))
            typer.echo(f"\nRun: {run_id} | Critique: {critique_id}")
        else:
            typer.echo(f"Critic exceeded max turns limit. Run: {run_id}", err=True)
    finally:
        await docker_client.close()


@async_run
async def cmd_detector_coverage(
    run_missing: bool = typer.Option(False, "--run-missing", help="Run missing (detector, snapshot) pairs"),
    model: str = opt.OPT_MODEL,
    verbose: bool = opt.OPT_VERBOSE,
    hydrator: SnapshotHydrator = Depends(get_hydrator),
) -> None:
    """Check evaluation coverage for all (detector, snapshot) pairs.

    Shows which detector prompts have been evaluated against which snapshots.
    Use --run-missing to automatically evaluate all missing (detector, snapshot) pairs.
    """
    docker_client = aiodocker.Docker()
    try:
        await run_detector_coverage(
            run_missing=run_missing, model=model, verbose=verbose, docker_client=docker_client, hydrator=hydrator
        )
    finally:
        await docker_client.close()
