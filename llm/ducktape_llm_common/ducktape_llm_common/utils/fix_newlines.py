#!/usr/bin/env python3
"""Fix newline issues in files - ensures files end with exactly one newline."""

import argparse
import sys
from pathlib import Path
from typing import List


def fix_newlines_in_file(filepath: Path) -> bool:
    """
    Fix newline issues in a single file.

    Ensures file ends with exactly one newline character.

    Args:
        filepath: Path to the file to fix

    Returns:
        True if file was modified, False otherwise
    """
    try:
        # Read file content
        with open(filepath, "rb") as f:
            content = f.read()

        if not content:
            # Empty file, no changes needed
            return False

        # Check if file already ends with exactly one newline
        if content.endswith(b"\n") and not content.endswith(b"\n\n"):
            return False

        # Fix the content
        # Remove all trailing whitespace (including newlines)
        content = content.rstrip()

        # Add exactly one newline
        content += b"\n"

        # Write back
        with open(filepath, "wb") as f:
            f.write(content)

        return True

    except Exception as e:
        print(f"Error processing {filepath}: {e}", file=sys.stderr)
        return False


def main() -> int:
    """Main entry point for the fix-newlines command."""
    parser = argparse.ArgumentParser(
        description="Fix newline issues in files - ensures files end with exactly one newline"
    )
    parser.add_argument("files", nargs="+", help="Files to fix")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check mode - exit with error if files need fixing",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true", help="Quiet mode - only output errors"
    )

    args = parser.parse_args()

    files_needing_fix: List[str] = []
    files_fixed: List[str] = []

    for filepath_str in args.files:
        filepath = Path(filepath_str)

        if not filepath.is_file():
            if not args.quiet:
                print(f"Skipping non-file: {filepath}")
            continue

        if args.check:
            # In check mode, just see if file needs fixing
            original_content = filepath.read_bytes()
            if original_content and not (
                original_content.endswith(b"\n")
                and not original_content.endswith(b"\n\n")
            ):
                files_needing_fix.append(str(filepath))
        else:
            # Fix mode
            if fix_newlines_in_file(filepath):
                files_fixed.append(str(filepath))
                if not args.quiet:
                    print(f"Fixed: {filepath}")

    if args.check:
        if files_needing_fix:
            print(
                f"ERROR: {len(files_needing_fix)} file(s) need newline fixes:",
                file=sys.stderr,
            )
            for f in files_needing_fix:
                print(f"  - {f}", file=sys.stderr)
            return 1
        else:
            if not args.quiet:
                print("All files have correct newlines")
            return 0
    else:
        if files_fixed:
            if not args.quiet:
                print(f"\nFixed {len(files_fixed)} file(s)")
            return 0
        else:
            if not args.quiet:
                print("No files needed fixing")
            return 0


if __name__ == "__main__":
    sys.exit(main())
