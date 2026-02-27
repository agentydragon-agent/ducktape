"""Standalone entry point for DirectExecServer over streamable-http.

This is the privileged exec backend for the approval gate. Run in a container
with the required secrets/credentials mounted. The approval gate connects to
this server over HTTP and forwards approved tool calls.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from mcp_infra.exec.direct import DirectExecServer

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="DirectExecServer — streamable-http backend")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--cwd", default=None, help="Default working directory for commands")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    default_cwd = Path(args.cwd) if args.cwd else None
    server = DirectExecServer(default_cwd=default_cwd)
    logger.info("starting DirectExecServer on %s:%d", args.host, args.port)
    server.run("streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
