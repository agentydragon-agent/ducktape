"""Cron entrypoint for the Plaid v0 full-refresh sync."""

from __future__ import annotations

import asyncio
import logging
import sys

from plaid_utils.mcp_server.app import PlaidWebSettings, run_sync


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s", stream=sys.stderr)
    run_ids = asyncio.run(run_sync(PlaidWebSettings()))
    for run_id in run_ids:
        print(run_id)


if __name__ == "__main__":
    main()
