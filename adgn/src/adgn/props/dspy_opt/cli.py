"""CLI for DSPy-based critic optimization."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import click

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@click.group()
def cli():
    """DSPy-based critic prompt optimization."""
    pass


@cli.command()
@click.option("--output", "-o", type=click.Path(), default="optimized_critic.json", help="Output path for optimized prompt")
@click.option("--max-demos", type=int, default=4, help="Max bootstrapped demos")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def optimize(output: str, max_demos: int, verbose: bool):
    """Optimize critic prompt using DSPy on training specimens."""
    import dspy

    from adgn.props.dspy_opt.optimize import optimize_critic, save_optimized_prompt
    from adgn.props.specimens.registry import SpecimenRegistry

    # Configure DSPy with your LLM
    # TODO: Make this configurable
    lm = dspy.LM("openai/gpt-4o")  # or "anthropic/claude-3-5-sonnet"
    dspy.configure(lm=lm)

    registry = SpecimenRegistry.from_package_resources()

    async def run():
        result = await optimize_critic(
            registry,
            max_bootstrapped_demos=max_demos,
            verbose=verbose,
        )
        save_optimized_prompt(result.optimized_module, Path(output))
        click.echo(f"Train avg: {result.train_avg:.2%}")
        click.echo(f"Valid avg: {result.valid_avg:.2%}")

    asyncio.run(run())


@cli.command()
@click.argument("prompt_path", type=click.Path(exists=True))
@click.option("--split", type=click.Choice(["train", "valid", "test"]), default="valid", help="Split to evaluate on")
@click.option("--full-grader", is_flag=True, help="Use full LLM grader (slower but more accurate)")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def evaluate(prompt_path: str, split: str, full_grader: bool, verbose: bool):
    """Evaluate an optimized prompt on specimens."""
    import dspy

    from adgn.props.dspy_opt.examples import load_specimens_as_examples
    from adgn.props.dspy_opt.optimize import evaluate_on_examples, load_optimized_prompt
    from adgn.props.specimens.registry import SpecimenRegistry
    from adgn.props.splits import Split

    # Configure DSPy
    lm = dspy.LM("openai/gpt-4o")
    dspy.configure(lm=lm)

    critic = load_optimized_prompt(Path(prompt_path))
    registry = SpecimenRegistry.from_package_resources()
    split_enum = Split(split)

    async def run():
        examples = await load_specimens_as_examples(registry, split_enum)
        scores = await evaluate_on_examples(
            critic,
            examples,
            registry,
            use_full_grader=full_grader,
            verbose=verbose,
        )
        avg = sum(scores) / len(scores) if scores else 0.0
        click.echo(f"Average score on {split}: {avg:.2%}")
        for ex, score in zip(examples, scores):
            click.echo(f"  {ex.slug}: {score:.2%}")

    asyncio.run(run())


@cli.command()
@click.option("--split", type=click.Choice(["train", "valid", "test", "all"]), default="all", help="Split to list")
def list_specimens(split: str):
    """List available specimens."""
    from adgn.props.specimens.registry import SpecimenRegistry
    from adgn.props.splits import Split

    registry = SpecimenRegistry.from_package_resources()

    if split == "all":
        slugs = list(registry.list_specimens())
    else:
        slugs = registry.get_specimens_by_split(Split(split))

    for slug in sorted(slugs):
        specimen_split = registry.get_split(slug)
        click.echo(f"{slug} [{specimen_split}]")


if __name__ == "__main__":
    cli()
