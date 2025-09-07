#!/usr/bin/env python3
"""CLI to run the docker_exec MCP server via stdio transport."""

from __future__ import annotations

import argparse
import os
from typing import Dict

import asyncio

from .._shared.container_session import NetworkMode
from .server import make_container_exec_mcp


def _parse_volumes(values: list[str] | None) -> Dict[str, Dict[str, str]] | None:
    if not values:
        return None
    result: Dict[str, Dict[str, str]] = {}
    entries: list[str] = []
    for value in values:
        entries.extend(value.split(","))
    for entry in entries:
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) < 2:
            raise argparse.ArgumentTypeError(
                f"Invalid volume spec '{entry}'. Use host:container[:mode]."
            )
        host, container, *mode = parts
        spec: Dict[str, str] = {"bind": container}
        if mode:
            spec["mode"] = mode[0]
        result[os.path.abspath(host)] = spec
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run docker_exec MCP over stdio")
    parser.add_argument("--image", required=True, help="Docker image for session containers")
    parser.add_argument(
        "--working-dir",
        default="/workspace",
        help="Working directory inside the container (default: /workspace)",
    )
    parser.add_argument(
        "--network-mode",
        default=NetworkMode.NONE.value,
        choices=[m.value for m in NetworkMode],
        help="Docker network mode (default: none)",
    )
    parser.add_argument(
        "--volumes",
        action="append",
        default=None,
        help=(
            "Volume specification host:container[:mode]. "
            "May be supplied multiple times or as comma-separated entries."
        ),
    )
    parser.add_argument(
        "--label",
        action="append",
        default=None,
        help="Docker label to apply to the container (key=value). May be repeated.",
    )
    parser.add_argument(
        "--describe",
        action="store_true",
        help="Include Docker image history in server description",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    volumes = _parse_volumes(args.volumes)
    network_mode = NetworkMode(args.network_mode)

    labels: Dict[str, str] | None = None
    if args.label:
        labels = {}
        for raw_label in args.label:
            if "=" not in raw_label:
                parser.error(f"Invalid label '{raw_label}'. Expected key=value format.")
            key, value = raw_label.split("=", 1)
            labels[key] = value

    server = make_container_exec_mcp(
        image=args.image,
        working_dir=args.working_dir,
        volumes=volumes,
        network_mode=network_mode,
        describe=args.describe,
        labels=labels,
    )

    asyncio.run(server.run_stdio_async())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
