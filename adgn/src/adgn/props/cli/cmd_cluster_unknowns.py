"""CLI commands for clustering unknown issues."""

from __future__ import annotations

import logging
from pathlib import Path
import tempfile
from typing import Annotated

import aiodocker
from rich.console import Console
from rich.table import Table
from sqlalchemy import select
from typer import Argument, Option
from typer_di import Depends, TyperDI

from adgn.cli_utils import async_run
from adgn.openai_utils.client_factory import build_client
from adgn.props.cli import common_options as opt
from adgn.props.cli.resources import get_hydrator
from adgn.props.clustering.cluster_agent import OutcomeSuccess, run_clustering_agent
from adgn.props.db import get_session
from adgn.props.db.clustering_models import ClusteringRun, UnknownAssignment, UnknownCluster
from adgn.props.db.config import get_database_config
from adgn.props.display import ellipticize
from adgn.props.hydration import SnapshotHydrator, SnapshotSlug

logger = logging.getLogger(__name__)
console = Console()

app = TyperDI(help="Clustering commands for unknown issues")


@app.command("run")
@async_run
async def cmd_run(
    snapshot_slug: SnapshotSlug = opt.ARG_SNAPSHOT,
    resume_clustering_run_id: Annotated[
        int | None, Option("--resume-clustering-run-id", help="Resume existing clustering run")
    ] = None,
    model: str = opt.OPT_MODEL,
    output_dir: Annotated[Path | None, Option(help="Output directory for workspace/logs (defaults to temp)")] = None,
    verbose: bool = opt.OPT_VERBOSE,
    hydrator: SnapshotHydrator = Depends(get_hydrator),
) -> None:
    """Run clustering agent on a snapshot (create new run or resume existing).

    Creates a clustering run (or resumes an existing one), hydrates the snapshot,
    and runs the clustering agent to group unknown issues into clusters.

    The agent has RLS-scoped database access and will automatically terminate when
    all unknowns are assigned to clusters or mapped to existing TPs/FPs.

    Examples:
        # Start new clustering run
        adgn-properties cluster-unknowns run ducktape/2025-11-20-00

        # Resume existing run
        adgn-properties cluster-unknowns run ducktape/2025-11-20-00 --resume-clustering-run-id 42

        # Use different model
        adgn-properties cluster-unknowns run ducktape/2025-11-20-00 --model gpt-4o
    """
    db_config = get_database_config()

    # 1. Get or create clustering run
    with get_session() as session:
        if resume_clustering_run_id:
            # Resume existing run
            run = session.get(ClusteringRun, resume_clustering_run_id)
            if not run:
                console.print(f"[red]Error:[/red] Run {resume_clustering_run_id} not found")
                raise SystemExit(1)

            if run.snapshot_slug != snapshot_slug:
                console.print(
                    f"[red]Error:[/red] Run {resume_clustering_run_id} is for {run.snapshot_slug}, not {snapshot_slug}"
                )
                raise SystemExit(1)

            if run.status != "in_progress":
                console.print(
                    f"[red]Error:[/red] Run {resume_clustering_run_id} has status {run.status}, expected 'in_progress'"
                )
                raise SystemExit(1)

            run_id = resume_clustering_run_id
            console.print(f"[cyan]Resuming clustering run {run_id} for {snapshot_slug}[/cyan]")
        else:
            # Create new run
            run = ClusteringRun(snapshot_slug=snapshot_slug, status="in_progress")
            session.add(run)
            session.flush()
            run_id = run.id
            session.commit()

            console.print(f"[green]Created clustering run {run_id} for {snapshot_slug}[/green]")

    # 2. Set up dependencies
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix=f"cluster_run_{run_id}_"))

    docker_client = aiodocker.Docker()

    try:
        # 3. Run clustering agent
        client = build_client(model)
        console.print(f"[cyan]Starting clustering agent (model={client.model})...[/cyan]")
        result = await run_clustering_agent(
            run_id=run_id,
            hydrator=hydrator,
            docker_client=docker_client,
            db_config=db_config,
            client=client,
            output_dir=output_dir,
            verbose=verbose,
        )

        # 4. Display outcome
        console.print("\n[bold]Clustering Run Complete[/bold]")
        console.print(f"Run ID: {result.run_id}")
        console.print(f"Transcript ID: {result.transcript_id}")
        console.print(f"Output directory: {output_dir}")

        if isinstance(result.outcome, OutcomeSuccess):
            console.print("\n[green]✓ Success[/green]")
            console.print(f"  Total unknowns: {result.outcome.total_unknowns}")
            console.print(f"  Clusters created: {result.outcome.clusters_created}")
            console.print(f"  Mapped to existing: {result.outcome.mapped_to_existing}")
        else:
            console.print("\n[yellow]⚠ Incomplete[/yellow]")
            console.print(f"  Remaining unknowns: {result.outcome.remaining_unknowns}")
            console.print(f"  Message: {result.outcome.message}")

        console.print(f"\nView details: adgn-properties cluster-unknowns show {result.run_id}")

    finally:
        await docker_client.close()


@app.command("show")
def cmd_show(run_id: Annotated[int, Argument(help="Clustering run ID to display")]) -> None:
    """Display clustering run status, clusters, and assignments.

    Shows comprehensive information about a clustering run including:
    - Run metadata (snapshot, status, timestamps)
    - Clusters created (with assignment counts)
    - Recent assignments

    Example:
        adgn-properties cluster-unknowns show 42
    """
    with get_session() as session:
        # 1. Get run info
        run = session.get(ClusteringRun, run_id)
        if not run:
            console.print(f"[red]Error:[/red] Run {run_id} not found")
            raise SystemExit(1)

        # 2. Display run metadata
        console.print(f"\n[bold]Clustering Run {run_id}[/bold]")
        console.print(f"Snapshot: {run.snapshot_slug}")
        console.print(f"Status: {run.status}")
        console.print(f"Started: {run.started_at}")
        if run.completed_at:
            console.print(f"Completed: {run.completed_at}")
        if run.transcript_id:
            console.print(f"Transcript ID: {run.transcript_id}")

        # 3. Get clusters
        clusters = (
            session.execute(
                select(UnknownCluster)
                .where(UnknownCluster.clustering_run_id == run_id)
                .order_by(UnknownCluster.cluster_name)
            )
            .scalars()
            .all()
        )

        if clusters:
            console.print(f"\n[bold]Clusters ({len(clusters)})[/bold]")
            cluster_table = Table(show_header=True, header_style="bold")
            cluster_table.add_column("ID", style="cyan")
            cluster_table.add_column("Name", style="green")
            cluster_table.add_column("Description")
            cluster_table.add_column("Assignments", justify="right", style="yellow")

            for cluster in clusters:
                # Count active assignments
                assignment_count = (
                    session.execute(
                        select(UnknownAssignment).where(
                            UnknownAssignment.cluster_id == cluster.id, UnknownAssignment.cancelled_at.is_(None)
                        )
                    )
                    .scalars()
                    .all()
                )

                cluster_table.add_row(
                    str(cluster.id), cluster.cluster_name, cluster.description or "", str(len(assignment_count))
                )

            console.print(cluster_table)
        else:
            console.print("\n[dim]No clusters created yet[/dim]")

        # 4. Get recent assignments
        assignments = (
            session.execute(
                select(UnknownAssignment)
                .where(UnknownAssignment.clustering_run_id == run_id, UnknownAssignment.cancelled_at.is_(None))
                .order_by(UnknownAssignment.created_at.desc())
                .limit(10)
            )
            .scalars()
            .all()
        )

        if assignments:
            console.print(f"\n[bold]Recent Assignments ({len(assignments)})[/bold]")
            assignment_table = Table(show_header=True, header_style="bold")
            assignment_table.add_column("ID", style="cyan")
            assignment_table.add_column("Unknown ID", style="yellow")
            assignment_table.add_column("Target", style="green")
            assignment_table.add_column("Rationale")

            for assignment in assignments:
                # Determine target
                if assignment.cluster_id:
                    assigned_cluster: UnknownCluster | None = session.get(UnknownCluster, assignment.cluster_id)
                    target = f"Cluster: {assigned_cluster.cluster_name if assigned_cluster else '?'}"
                elif assignment.mapped_tp_id:
                    target = f"TP: {assignment.mapped_tp_id}"
                elif assignment.mapped_fp_id:
                    target = f"FP: {assignment.mapped_fp_id}"
                else:
                    target = "?"

                # Truncate rationale for display
                rationale = ellipticize(assignment.rationale, 60)

                assignment_table.add_row(str(assignment.id), assignment.unknown_id, target, rationale)

            console.print(assignment_table)
        else:
            console.print("\n[dim]No assignments yet[/dim]")

        # 5. Summary stats
        total_assignments = (
            session.execute(
                select(UnknownAssignment).where(
                    UnknownAssignment.clustering_run_id == run_id, UnknownAssignment.cancelled_at.is_(None)
                )
            )
            .scalars()
            .all()
        )

        console.print("\n[bold]Summary[/bold]")
        console.print(f"Total active assignments: {len(total_assignments)}")
        console.print(f"Total clusters: {len(clusters)}")

        # Count mapped to existing
        mapped_count = sum(1 for a in total_assignments if a.mapped_tp_id is not None or a.mapped_fp_id is not None)
        console.print(f"Mapped to existing TPs/FPs: {mapped_count}")
