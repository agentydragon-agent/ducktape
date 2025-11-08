#!/usr/bin/env python3
"""
Harbor OIDC Integration - SCIENTIST MODE Data Collection (Modular Version)
GATHER ALL THE LOGS, TURN ON ALL THE KNOBS

Comprehensive, parallelized data collection using Kubernetes Python SDK.
"""

import asyncio
import sys

from collect.orchestrator import ScientistMode


async def main() -> None:
    """Main entry point."""
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        output_dir = sys.argv[1]
    else:
        output_dir = None

    collector = ScientistMode(output_dir)
    await collector.run_full_collection()


if __name__ == "__main__":
    asyncio.run(main())
