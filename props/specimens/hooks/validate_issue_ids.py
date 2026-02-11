#!/usr/bin/env python3
"""Pre-commit hook to validate issue ID lengths and format.

Issue IDs are derived from .yaml filenames in issues/ directories.
They must:
- Be 5-40 characters long
- Match pattern: ^[a-z0-9_-]+$
- Not contain colons (reserved for namespace separator)
"""

import re
import subprocess
import sys
from pathlib import Path

ISSUE_ID_PATTERN = re.compile(r"^[a-z0-9_-]+$")
MIN_LENGTH = 5
MAX_LENGTH = 40
SPECIMENS_PREFIX = "props/specimens/"


def get_staged_files():
    """Get files staged for commit."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"], capture_output=True, text=True, check=True
    )
    return [f for f in result.stdout.strip().split("\n") if f]


def is_issue_file(file_path: str) -> bool:
    """Check if file is an issue definition (.yaml in issues/ directory under specimens)."""
    path = Path(file_path)
    return file_path.startswith(SPECIMENS_PREFIX) and path.suffix == ".yaml" and "issues" in path.parts


def validate_issue_id(issue_id: str) -> list[str]:
    """Validate issue ID format and length."""
    errors = []

    if len(issue_id) < MIN_LENGTH:
        errors.append(f"too short ({len(issue_id)} chars, min {MIN_LENGTH})")

    if len(issue_id) > MAX_LENGTH:
        errors.append(f"too long ({len(issue_id)} chars, max {MAX_LENGTH})")

    if ":" in issue_id:
        errors.append("contains colon (reserved for namespace separator)")

    if not ISSUE_ID_PATTERN.match(issue_id):
        errors.append("invalid format (must match: ^[a-z0-9_-]+$)")

    return errors


def main():
    staged_files = get_staged_files()
    issue_files = [f for f in staged_files if is_issue_file(f)]

    violations = []
    for file_path in issue_files:
        issue_id = Path(file_path).stem
        errors = validate_issue_id(issue_id)
        if errors:
            violations.append((file_path, issue_id, errors))

    if violations:
        print("ERROR: Invalid issue IDs detected.", file=sys.stderr)
        print(file=sys.stderr)
        print("Issue IDs must:", file=sys.stderr)
        print(f"  - Be {MIN_LENGTH}-{MAX_LENGTH} characters long", file=sys.stderr)
        print("  - Match pattern: ^[a-z0-9_-]+$", file=sys.stderr)
        print("  - Not contain colons (reserved)", file=sys.stderr)
        print(file=sys.stderr)
        print("Validation failures:", file=sys.stderr)
        for file_path, issue_id, errors in violations:
            print(f"  {file_path}", file=sys.stderr)
            print(f"    Issue ID: {issue_id}", file=sys.stderr)
            for error in errors:
                print(f"    - {error}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
