#!/usr/bin/env python3

"""CLI to run the gitea_mirror MCP server via stdio transport."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .server import make_gitea_mirror_mcp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run gitea_mirror MCP over stdio")
    parser.add_argument("--base-url", default=os.environ.get("GITEA_BASE_URL"), help="Gitea base URL")
    parser.add_argument("--token", default=os.environ.get("GITEA_TOKEN"), help="Gitea API token")
    parser.add_argument(
        "--token-file",
        default=os.environ.get("GITEA_TOKEN_FILE"),
        help="Path to file containing Gitea API token",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.environ.get("GITEA_POLL_INTERVAL_SECS", 2.0)),
        help="Polling interval in seconds (default: 2.0)",
    )
    parser.add_argument(
        "--poll-timeout",
        type=float,
        default=float(os.environ.get("GITEA_POLL_TIMEOUT_SECS", 60.0)),
        help="Polling timeout in seconds (default: 60.0)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    token = args.token
    if not token and args.token_file:
        token_path = Path(args.token_file)
        if not token_path.exists():
            parser.error(f"Token file not found: {token_path}")
        token = token_path.read_text(encoding="utf-8").strip()

    if not token:
        parser.error("Gitea token is required via --token or --token-file")

    server = make_gitea_mirror_mcp(
        base_url=args.base_url,
        token=token,
        poll_interval_secs=args.poll_interval,
        poll_timeout_secs=args.poll_timeout,
    )

    server.run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
