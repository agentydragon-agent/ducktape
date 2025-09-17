#!/usr/bin/env python3
"""
Extract all #issue nodes (where Status != Done/Cancelled) from a Tana export and output TanaPaste to stdout.

Usage: python tana_issues_to_tanapaste.py <input.json>
"""

from pathlib import Path
import sys

from .convert import RenderContext
from .tana_lib import filter_open_issues, load_tana_export

EXPECTED_ARGS = 2


def main():
    if len(sys.argv) != EXPECTED_ARGS:
        print("Usage: python tana_issues_to_tanapaste.py <input.json>", file=sys.stderr)
        print(
            "\nExtracts all #issue nodes (where Status != Done/Cancelled) and outputs TanaPaste to stdout",
            file=sys.stderr,
        )
        sys.exit(1)

    input_path = Path(sys.argv[1])

    if not input_path.exists():
        print(f"Error: Input file '{input_path}' not found.", file=sys.stderr)
        sys.exit(1)

    # Load and process
    store = load_tana_export(input_path)
    issue_ids = list(filter_open_issues(store))

    # Export the given issues as a flat TanaPaste document
    lines = ["%%tana%%"]
    ctx = RenderContext(store, "tana")
    for issue_id in issue_ids:
        lines.extend(ctx.render_node(store[issue_id]))
        lines.append("")  # Empty line between issues

    # Output to stdout
    print("\n".join(lines).rstrip())

    # Report to stderr
    print(f"Open issues exported: {len(issue_ids)}", file=sys.stderr)


if __name__ == "__main__":
    main()
