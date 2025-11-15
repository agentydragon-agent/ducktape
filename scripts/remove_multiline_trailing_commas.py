#!/usr/bin/env python3
"""Remove trailing commas from multi-line constructs to enable one-line formatting.

This pre-commit hook removes trailing commas before closing brackets, allowing
Ruff formatter to collapse multi-line constructs to one line when they fit.
"""

import argparse
import re
import sys
from pathlib import Path


def remove_trailing_commas(content: str) -> str:
    """Remove trailing commas before closing brackets/parens/braces."""
    # Match: comma, optional whitespace and newlines, then closing ), ], or }
    # This handles multi-line constructs like:
    #   arg3="value3",
    # )
    patterns = [
        (r',(\s*)\)', r'\1)'),  # Before closing paren
        (r',(\s*)\]', r'\1]'),  # Before closing bracket
        (r',(\s*)\}', r'\1}'),  # Before closing brace
    ]

    result = content
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result)

    return result


def main():
    """Process Python files to remove trailing commas."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='*', help='Files to process')
    args = parser.parse_args()

    modified = False
    for file_path in args.files:
        path = Path(file_path)
        if path.suffix != '.py':
            continue

        content = path.read_text()
        new_content = remove_trailing_commas(content)

        if content != new_content:
            path.write_text(new_content)
            modified = True

    return 1 if modified else 0


if __name__ == "__main__":
    sys.exit(main())
