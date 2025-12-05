"""GEPA optimization command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from rich.console import Console
import typer

from adgn.openai_utils.client_factory import build_client
from adgn.props.cli.decorators import async_run
from adgn.props.db import init_db
from adgn.props.db.config import get_production_config
from adgn.props.gepa.gepa_adapter import optimize_with_gepa
from adgn.props.snapshot_hydrator import SnapshotHydrator


@async_run
async def cmd_gepa(
    critic_model: Annotated[str, typer.Option(help="Model for critic execution")] = "gpt-5.1-codex-mini",
    grader_model: Annotated[str, typer.Option(help="Model for grader execution")] = "gpt-5.1-codex-mini",
    reflection_model: Annotated[str, typer.Option(help="Model for GEPA's reflection/evolution")] = "gpt-5.1",
    initial_prompt: Annotated[
        str | None, typer.Option(help="Initial prompt (ignored if warm-start loads historical data)")
    ] = None,
    max_metric_calls: Annotated[
        int, typer.Option(help="Budget for evaluations in this run (not counting historical)")
    ] = 100,
    output_dir: Annotated[Path, typer.Option(help="Output directory for results")] = Path("gepa_output"),
    warm_start: Annotated[
        bool, typer.Option(help="Load historical Pareto frontier from database to start from known good prompts")
    ] = True,
    max_parallelism: Annotated[int, typer.Option(help="Maximum concurrent critic/grader evaluations")] = 20,
    verbose: Annotated[bool, typer.Option(help="Enable verbose logging")] = False,
) -> None:
    """Run GEPA optimization to evolve the critic system prompt.

    GEPA (Genetic Prompt Adaptation) uses evolutionary search with rich feedback
    from execution traces and grader output to optimize the critic prompt.

    Example:
        adgn-properties gepa --critic-model gpt-4o-mini --grader-model gpt-4o --reflection-model gpt-4o
    """
    console = Console()

    # Load initial prompt
    if initial_prompt is None:
        initial_prompt = "You are a code critic."
        console.print(f"[dim]Using default initial prompt: {initial_prompt}[/dim]")

    console.print("\n[bold cyan]GEPA Optimization Configuration[/bold cyan]")
    console.print(f"  Critic model: {critic_model}")
    console.print(f"  Grader model: {grader_model}")
    console.print(f"  Reflection model: {reflection_model}")
    console.print(f"  Max metric calls: {max_metric_calls} (this run only)")
    console.print(f"  Max parallelism: {max_parallelism} concurrent evaluations")
    console.print("  Training examples: per-file mode (from database critic_scopes)")
    console.print(f"  Warm start: {'enabled' if warm_start else 'disabled'}")
    console.print(f"  Output directory: {output_dir}")
    console.print(f"  Initial prompt length: {len(initial_prompt)} chars\n")

    # Initialize database
    config = get_production_config()
    console.print(f"[dim]Database: {config.host}:{config.port}/{config.database}[/dim]")
    init_db(config=config)

    # Create hydrator
    hydrator = SnapshotHydrator.from_package_resources()

    # Run optimization
    console.print("\n[bold green]Starting GEPA optimization...[/bold green]\n")
    optimized_prompt, result = await optimize_with_gepa(
        initial_prompt=initial_prompt,
        hydrator=hydrator,
        critic_client=build_client(critic_model),
        grader_client=build_client(grader_model),
        reflection_model=reflection_model,
        max_metric_calls=max_metric_calls,
        max_parallelism=max_parallelism,
        verbose=verbose,
        warm_start=warm_start,
    )

    # Save results
    output_dir.mkdir(exist_ok=True, parents=True)
    optimized_file = output_dir / "optimized_prompt.md"
    optimized_file.write_text(optimized_prompt)

    # Print summary
    best_score = result.val_aggregate_scores[result.best_idx]
    metric_calls = result.total_metric_calls or 0
    console.print("\n" + "=" * 80)
    console.print("[bold green]GEPA Optimization Complete![/bold green]")
    console.print(f"  Best candidate score: [cyan]{best_score:.3f}[/cyan]")
    console.print(f"  Total evaluations: [cyan]{metric_calls}[/cyan]")
    console.print(f"  Optimized prompt saved to: [cyan]{optimized_file.absolute()}[/cyan]")
    console.print("=" * 80 + "\n")
