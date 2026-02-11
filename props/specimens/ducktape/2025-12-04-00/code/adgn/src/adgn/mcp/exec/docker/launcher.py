#!/usr/bin/env python3


"""CLI to run the docker_exec MCP server via stdio transport."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .._shared.container_session import ContainerOptions, NetworkMode
from .server import make_container_exec_server


def _parse_volumes(values: list[str] | None) -> dict[str, dict[str, str]] | None:
    if not values:
        return None
    result: dict[str, dict[str, str]] = {}
    entries: list[str] = []
    for value in values:
        entries.extend(value.split(","))
    for entry in entries:
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) < 2:
            raise argparse.ArgumentTypeError(f"Invalid volume spec '{entry}'. Use host:container[:mode].")
        host, container, *mode = parts
        spec: dict[str, str] = {"bind": container}
        if mode:
            spec["mode"] = mode[0]
        result[str(Path(host).resolve())] = spec
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run docker_exec MCP over stdio")
    parser.add_argument("--image", required=True, help="Docker image for session containers")
    parser.add_argument(
        "--working-dir", default="/workspace", help="Working directory inside the container (default: /workspace)"
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
            "Volume specification host:container[:mode]. May be supplied multiple times or as comma-separated entries."
        ),
    )
    parser.add_argument(
        "--label",
        action="append",
        default=None,
        help="Docker label to apply to the container (key=value). May be repeated.",
    )
    parser.add_argument("--describe", action="store_true", help="Include Docker image history in server description")
    parser.add_argument(
        "--ephemeral",
        action="store_true",
        help="Run each command in a fresh ephemeral container with host-enforced timeouts",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    volumes = _parse_volumes(args.volumes)
    network_mode = NetworkMode(args.network_mode)

    labels: dict[str, str] | None = None
    if args.label:
        labels = {}
        for raw_label in args.label:
            if "=" not in raw_label:
                parser.error(f"Invalid label '{raw_label}'. Expected key=value format.")
            key, value = raw_label.split("=", 1)
            labels[key] = value

    opts = ContainerOptions(
        image=args.image,
        working_dir=args.working_dir,
        volumes=volumes,
        network_mode=network_mode,
        labels=labels,
        describe=args.describe,
        ephemeral=args.ephemeral,
    )
    server = make_container_exec_server(opts)

    asyncio.run(server.run_stdio_async())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
