#!/usr/bin/env python3
"""
Generate a Headscale preauth key and print it to stdout.

Usage:
    headscale_generate_authkey.py (--user-id <id> | --user-name <name>) [--ephemeral] [-- ...]

Any additional arguments after the options are forwarded to the `headscale`
command. The script exits with a non-zero status and descriptive message if the
command fails or the output is not in the expected JSON format.

Environment:
    HEADSCALE_CMD (optional) - override the path to the `headscale` binary
                               (default: /usr/local/bin/headscale)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def fail(message: str) -> None:
    """Print *message* to stderr and exit with status 1."""
    print(message, file=sys.stderr)
    sys.exit(1)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a headscale preauth key and print it.",
        allow_abbrev=False,
    )
    user_group = parser.add_mutually_exclusive_group(required=True)
    user_group.add_argument("--user-id", help="Numeric headscale user ID")
    user_group.add_argument("--user-name", help="Headscale user name (namespace)")
    parser.add_argument(
        "--ephemeral",
        action="store_true",
        help="Create an ephemeral key",
    )
    parser.add_argument(
        "extra_args",
        nargs=argparse.REMAINDER,
        help="Additional arguments forwarded to headscale",
    )
    return parser.parse_args(argv[1:])


def run_headscale(args: argparse.Namespace) -> dict | list:
    headscale_cmd = Path(os.environ.get("HEADSCALE_CMD", "/usr/local/bin/headscale"))
    if not headscale_cmd.exists():
        fail(f"headscale binary not found at {headscale_cmd}")

    cmd = [str(headscale_cmd), "preauthkeys", "create", "--output", "json"]
    if args.user_id:
        cmd.extend(["--user", args.user_id])
    else:
        cmd.extend(["--user", args.user_name])
    if args.ephemeral:
        cmd.append("--ephemeral")
    if args.extra_args:
        cmd.extend(args.extra_args)

    try:
        completed = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        fail(
            f"headscale command failed with exit code {exc.returncode}: "
            f"{exc.stderr.strip() or exc.stdout.strip()}"
        )

    stdout = completed.stdout.strip()
    if not stdout:
        fail("headscale command produced no output")

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        fail(f"Failed to parse headscale output as JSON: {exc}; output was: {stdout}")


def extract_key(payload: dict | list) -> str:
    if isinstance(payload, dict):
        data = payload
    elif isinstance(payload, list):
        if not payload:
            fail("headscale returned an empty list; no preauth key generated")
        item = payload[0]
        if not isinstance(item, dict):
            fail(f"Unexpected item type in headscale output: {type(item)}")
        data = item
    else:
        fail(f"Unexpected JSON type from headscale: {type(payload)}")

    key = data.get("key")
    if not isinstance(key, str):
        fail(f"headscale output missing 'key' field: {data}")
    key = key.strip()
    if not key:
        fail(f"headscale returned empty 'key' value: {data}")
    return key


def main() -> None:
    args = parse_args(sys.argv)
    payload = run_headscale(args)
    key = extract_key(payload)
    print(key)


if __name__ == "__main__":
    main()
