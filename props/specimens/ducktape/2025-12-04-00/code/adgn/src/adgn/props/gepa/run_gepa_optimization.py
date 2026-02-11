#!/usr/bin/env python
"""Run GEPA-based prompt optimization for props critic.

This script runs the GEPA evolutionary optimization workflow to improve
the critic system prompt.
"""

import asyncio
import logging
from pathlib import Path
import sys

from adgn.llm.logging_config import configure_logging
from adgn.openai_utils.client_factory import build_client
from adgn.props.db import init_db
from adgn.props.db.config import get_production_config
from adgn.props.gepa import optimize_with_gepa
from adgn.props.snapshot_registry import SnapshotRegistry

logger = logging.getLogger(__name__)


async def main():
    """Run GEPA optimization."""
    configure_logging()

    # Get database URL via production config (same path as adgn-properties CLI)
    # Defaults to: postgresql://postgres:postgres@localhost:5433/eval_results
    # Override with PROPS_DB_URL environment variable if needed
    config = get_production_config()
    logger.info(f"Using database: {config.admin_url.split('@')[-1]}")  # Log without credentials

    # Initialize database with admin URL
    logger.info("Initializing database...")
    init_db(url=config.admin_url)

    # Configuration
    model = "gpt-5-codex"  # Model for critic/grader execution
    reflection_model = "gpt-5-codex"  # Model for GEPA's reflection/evolution
    max_metric_calls = 100  # Budget for evaluations

    logger.info("Starting GEPA optimization workflow")
    logger.info(f"Model: {model}")
    logger.info(f"Reflection model: {reflection_model}")
    logger.info(f"Max metric calls: {max_metric_calls}")

    # Simple one-line initial prompt for testing GEPA
    initial_prompt = "Review the code."
    logger.info(f"Using simple hardcoded prompt ({len(initial_prompt)} chars)")

    # Create specimen registry
    logger.info("Creating specimen registry")
    registry = SnapshotRegistry.from_package_resources()

    # Create OpenAI client
    logger.info(f"Creating OpenAI client with model: {model}")
    client = build_client(model)

    # Run GEPA optimization
    logger.info("Starting GEPA optimization...")
    optimized_prompt, result = await optimize_with_gepa(
        initial_prompt=initial_prompt,
        registry=registry,
        client=client,
        reflection_model=reflection_model,
        max_metric_calls=max_metric_calls,
        verbose=True,
    )

    # Save results
    output_dir = Path("gepa_output")
    output_dir.mkdir(exist_ok=True)

    optimized_file = output_dir / "optimized_prompt.md"
    optimized_file.write_text(optimized_prompt)
    logger.info(f"Optimized prompt saved to: {optimized_file}")

    # Log summary
    logger.info("=" * 80)
    logger.info("GEPA Optimization Complete!")
    logger.info(f"Best candidate score: {result.best_score}")
    logger.info(f"Total evaluations: {result.metric_calls}")
    logger.info(f"Output directory: {output_dir.absolute()}")
    logger.info("=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
