#!/usr/bin/env python3
"""
Linter to check correctness of custom work URLs (task://, inv://, work://).
Validates URL format and optionally checks if referenced items exist.

This linter is part of the ducktape-llm-common package and can be used
standalone or integrated with pre-commit hooks.
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

try:
    from ducktape_llm_common.utils import is_valid_url_scheme
except ImportError:
    # Fallback for when running as script
    import os

    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    from ducktape_llm_common.utils import is_valid_url_scheme


class WorkURLLinter:
    """Linter for custom work URL schemas."""

    # URL patterns
    TASK_URL_PATTERN = re.compile(
        r"task://(?P<type>feat|fix|debug|refactor|perf|docs|test|chore)/"
        r"(?P<date>\d{4}-\d{2}-\d{2})-(?P<name>[a-z0-9-]+)"
        r"(?:/(?P<subtask>[A-Z]\d+\.\d+(?:\.\d+)?(?:-[a-z0-9-]+)?)"
        r"|/(?P<component>artifacts|timeline|evidence|experiments)(?:/(?P<path>[^?#]+))?)?"
        r"(?:\?(?P<params>[^#]+))?(?:#(?P<anchor>.+))?"
    )

    INV_URL_PATTERN = re.compile(
        r"inv://(?P<date>\d{4}-\d{2}-\d{2})-(?P<issue>[a-z0-9-]+)"
        r"(?:/(?P<component>evidence|hypotheses|experiments|timeline|artifacts)(?:/(?P<path>[^?#]+))?)?"
        r"(?:#(?P<anchor>.+))?"
    )

    WORK_URL_PATTERN = re.compile(
        r"work://(?P<project>[a-z0-9-]+)/(?P<item_type>[a-z-]+)/(?P<item_id>[a-z0-9-]+)"
        r"(?:#(?P<anchor>.+))?"
    )

    # Subtask ID pattern
    SUBTASK_PATTERN = re.compile(
        r"^(?P<phase>[PSBFID])(?P<level>\d+)\.(?P<sequence>\d+)"
        r"(?:\.(?P<subsub>\d+))?(?P<variant>[a-z])?(?:-(?P<desc>[a-z0-9-]+))?$"
    )

    # Supported URL schemes
    SUPPORTED_SCHEMES = ["task", "inv", "work"]

    def __init__(
        self,
        work_logs_dir: str = "work-logs",
        investigations_dir: str = "investigations",
    ):
        """Initialize the linter with directories to check against.

        Args:
            work_logs_dir: Directory containing work logs (default: work-logs)
            investigations_dir: Directory containing investigations (default: investigations)
        """
        self.work_logs_dir = Path(work_logs_dir)
        self.investigations_dir = Path(investigations_dir)
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def lint_file(self, filepath: Path) -> Tuple[List[str], List[str]]:
        """Lint a single file for work URLs.

        Args:
            filepath: Path to the file to lint

        Returns:
            Tuple of (errors, warnings) found in the file
        """
        self.errors = []
        self.warnings = []

        if not filepath.exists():
            self.errors.append(f"File not found: {filepath}")
            return self.errors, self.warnings

        content = filepath.read_text(encoding="utf-8")

        # Find all URLs in the content
        urls = self._find_urls(content)

        for line_num, url in urls:
            self._validate_url(url, filepath, line_num)

        return self.errors, self.warnings

    def _find_urls(self, content: str) -> List[Tuple[int, str]]:
        """Find all work URLs in content.

        Args:
            content: The file content to search

        Returns:
            List of (line_number, url) tuples
        """
        urls = []

        # Match URLs in various contexts
        url_contexts = [
            r"\[([^\]]+)\]\((task://[^)]+)\)",  # Markdown links
            r"\[([^\]]+)\]\((inv://[^)]+)\)",
            r"\[([^\]]+)\]\((work://[^)]+)\)",
            r'(?:^|[\s"])((task|inv|work)://[^\s"]+)',  # Standalone URLs
        ]

        lines = content.split("\n")
        for line_num, line in enumerate(lines, 1):
            for pattern in url_contexts:
                for match in re.finditer(pattern, line):
                    url = (
                        match.group(2)
                        if match.lastindex and match.lastindex > 1
                        else match.group(1)
                    )
                    urls.append((line_num, url))

        return urls

    def _validate_url(self, url: str, filepath: Path, line_num: int) -> None:
        """Validate a single URL.

        Args:
            url: The URL to validate
            filepath: Path to the file containing the URL
            line_num: Line number where the URL was found
        """
        if not is_valid_url_scheme(url, self.SUPPORTED_SCHEMES):
            self.errors.append(f"{filepath}:{line_num}: Unknown URL scheme: {url}")
            return

        if url.startswith("task://"):
            self._validate_task_url(url, filepath, line_num)
        elif url.startswith("inv://"):
            self._validate_inv_url(url, filepath, line_num)
        elif url.startswith("work://"):
            self._validate_work_url(url, filepath, line_num)

    def _validate_task_url(self, url: str, filepath: Path, line_num: int) -> None:
        """Validate task:// URL.

        Args:
            url: The task URL to validate
            filepath: Path to the file containing the URL
            line_num: Line number where the URL was found
        """
        match = self.TASK_URL_PATTERN.match(url)
        if not match:
            self.errors.append(f"{filepath}:{line_num}: Invalid task URL format: {url}")
            return

        # Validate date format
        date_str = match.group("date")
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            self.errors.append(
                f"{filepath}:{line_num}: Invalid date in URL: {date_str}"
            )

        # Validate subtask ID if present
        subtask = match.group("subtask")
        if subtask:
            if not self.SUBTASK_PATTERN.match(subtask):
                self.errors.append(
                    f"{filepath}:{line_num}: Invalid subtask ID format: {subtask}"
                )

        # Check if task exists (optional)
        if self.work_logs_dir.exists():
            task_type = match.group("type")
            task_date = match.group("date")
            task_name = match.group("name")
            task_id = f"{task_type}-{task_date}-{task_name}"

            # Check in various states
            task_exists = False
            for state_dir in ["ACTIVE", "BLOCKED", "BACKLOG"]:
                if (self.work_logs_dir / state_dir / task_id).exists():
                    task_exists = True
                    break

            # Check in completed with date structure
            completed_dir = self.work_logs_dir / "COMPLETED"
            if completed_dir.exists():
                for month_dir in completed_dir.iterdir():
                    if (month_dir / task_id).exists():
                        task_exists = True
                        break

            if not task_exists:
                self.warnings.append(
                    f"{filepath}:{line_num}: Task not found: {task_id}"
                )

    def _validate_inv_url(self, url: str, filepath: Path, line_num: int) -> None:
        """Validate inv:// URL.

        Args:
            url: The investigation URL to validate
            filepath: Path to the file containing the URL
            line_num: Line number where the URL was found
        """
        match = self.INV_URL_PATTERN.match(url)
        if not match:
            self.errors.append(
                f"{filepath}:{line_num}: Invalid investigation URL format: {url}"
            )
            return

        # Validate date format
        date_str = match.group("date")
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            self.errors.append(
                f"{filepath}:{line_num}: Invalid date in URL: {date_str}"
            )

        # Check if investigation exists
        if self.investigations_dir.exists():
            inv_date = match.group("date")
            inv_issue = match.group("issue")
            inv_id = f"{inv_date}-{inv_issue}"

            if not (self.investigations_dir / inv_id).exists():
                self.warnings.append(
                    f"{filepath}:{line_num}: Investigation not found: {inv_id}"
                )

    def _validate_work_url(self, url: str, filepath: Path, line_num: int) -> None:
        """Validate work:// URL.

        Args:
            url: The work URL to validate
            filepath: Path to the file containing the URL
            line_num: Line number where the URL was found
        """
        match = self.WORK_URL_PATTERN.match(url)
        if not match:
            self.errors.append(f"{filepath}:{line_num}: Invalid work URL format: {url}")
            return

        # Basic validation - could be extended
        project = match.group("project")
        if not project:
            self.errors.append(
                f"{filepath}:{line_num}: Missing project in work URL: {url}"
            )


def main() -> None:
    """Main entry point for the command-line linter."""
    parser = argparse.ArgumentParser(
        description="Lint custom work URLs (task://, inv://, work://)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s README.md                     # Check single file
  %(prog)s *.md                          # Check all markdown files
  %(prog)s --no-warnings doc.md          # Only show errors

URL Formats:
  task://TYPE/DATE-NAME[/SUBTASK][/COMPONENT][?PARAMS][#ANCHOR]
  inv://DATE-ISSUE[/COMPONENT][#ANCHOR]
  work://PROJECT/ITEM-TYPE/ITEM-ID[#ANCHOR]
        """,
    )
    parser.add_argument("files", nargs="+", help="Files to lint")
    parser.add_argument(
        "--work-logs-dir",
        default="work-logs",
        help="Directory containing work logs (default: work-logs)",
    )
    parser.add_argument(
        "--investigations-dir",
        default="investigations",
        help="Directory containing investigations (default: investigations)",
    )
    parser.add_argument(
        "--no-warnings", action="store_true", help="Only show errors, not warnings"
    )

    args = parser.parse_args()

    linter = WorkURLLinter(args.work_logs_dir, args.investigations_dir)

    total_errors = 0
    total_warnings = 0

    for filepath in args.files:
        path = Path(filepath)
        if path.is_file():
            errors, warnings = linter.lint_file(path)
            total_errors += len(errors)
            total_warnings += len(warnings)

            for error in errors:
                print(f"ERROR: {error}")

            if not args.no_warnings:
                for warning in warnings:
                    print(f"WARNING: {warning}")

    if total_errors > 0:
        print(f"\n{total_errors} errors found")
        sys.exit(1)
    elif total_warnings > 0 and not args.no_warnings:
        print(f"\n{total_warnings} warnings found")
        sys.exit(0)
    else:
        print("All URLs valid")
        sys.exit(0)


if __name__ == "__main__":
    main()
