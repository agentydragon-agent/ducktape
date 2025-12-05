#!/usr/bin/env python
"""Run GEPA-based prompt optimization for props critic.

This script runs the GEPA evolutionary optimization workflow to improve
the critic system prompt.
"""

import argparse
import asyncio
import logging
from pathlib import Path
import sys

from adgn.llm.logging_config import configure_logging
from adgn.openai_utils.client_factory import build_client
from adgn.props.db import init_db
from adgn.props.db.config import get_production_config
from adgn.props.gepa import optimize_with_gepa
from adgn.props.snapshot_hydrator import SnapshotHydrator
from adgn.props.snapshot_registry import SnapshotRegistry

logger = logging.getLogger(__name__)


async def main():
    """Run GEPA optimization."""
    parser = argparse.ArgumentParser(description="Run GEPA-based prompt optimization for props critic")
    parser.add_argument("--max-metric-calls", type=int, default=100, help="Budget for evaluations (default: 100)")
    args = parser.parse_args()

    configure_logging()

    # Get database config via production config (same path as adgn-properties CLI)
    # Defaults to: postgresql://postgres:postgres@localhost:5433/eval_results
    # Override with PROPS_DB_* environment variables if needed
    config = get_production_config()
    logger.info(f"Using database: {config.host}:{config.port}/{config.database}")

    # Initialize database with structured config
    logger.info("Initializing database...")
    init_db(config)

    # Configuration
    critic_model = "gpt-5.1-codex-mini"  # Model for critic execution
    grader_model = "gpt-5.1-codex-mini"  # Model for grader execution
    reflection_model = "gpt-5.1"  # Model for GEPA's reflection/evolution

    logger.info("Starting GEPA optimization workflow")
    logger.info(f"Critic model: {critic_model}")
    logger.info(f"Grader model: {grader_model}")
    logger.info(f"Reflection model: {reflection_model}")
    logger.info(f"Max metric calls: {args.max_metric_calls}")
    logger.info("Training examples: per-file mode (from database critic_scopes)")

    # Simple one-line initial prompt for testing GEPA
    initial_prompt = "You are a code critic."
    logger.info(f"Using default initial prompt: {initial_prompt}")

    # Create hydrator and registry
    logger.info("Creating hydrator and registry")
    hydrator = SnapshotHydrator.from_package_resources()
    registry = SnapshotRegistry.from_package_resources()

    # Run GEPA optimization
    logger.info("Starting GEPA optimization...")
    optimized_prompt, result = await optimize_with_gepa(
        initial_prompt=initial_prompt,
        hydrator=hydrator,
        registry=registry,
        critic_client=build_client(critic_model),
        grader_client=build_client(grader_model),
        reflection_model=reflection_model,
        max_metric_calls=args.max_metric_calls,
        verbose=True,
    )

    # Save results
    output_dir = Path("gepa_output")
    output_dir.mkdir(exist_ok=True)

    optimized_file = output_dir / "optimized_prompt.md"
    optimized_file.write_text(optimized_prompt)
    logger.info(f"Optimized prompt saved to: {optimized_file}")

    # Log summary
    best_score = result.val_aggregate_scores[result.best_idx]
    metric_calls = result.total_metric_calls or 0
    logger.info("=" * 80)
    logger.info("GEPA Optimization Complete!")
    logger.info(f"Best candidate score: {best_score}")
    logger.info(f"Total evaluations: {metric_calls}")
    logger.info(f"Output directory: {output_dir.absolute()}")
    logger.info("=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
