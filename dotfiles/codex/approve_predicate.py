#!/usr/bin/env python3
"""
Custom auto-approval predicate for codex-rs.

This script reads the candidate shell command as its sole argument and prints exactly
one of: "allow", "deny", or "no-opinion" to stdout.
"""

import sys


def main(cmd: str) -> None:
    # Deny destructive commands
    if cmd.startswith("python3 -m pycompile "):
        print("allow")
        return
    if cmd.startswith("pre-commit run "):
        print("allow")
        return
    if cmd.startswith("cargo test"):
        print("allow")
        return
    # maybe pytest

    # if "--rf --no-preserve-root" in cmd:
    #    print("deny")
    #    return

    # Otherwise, no opinion → fall back to manual approval
    print("no-opinion")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: approve_predicate.py '<full command line>'")
    main(sys.argv[1])
