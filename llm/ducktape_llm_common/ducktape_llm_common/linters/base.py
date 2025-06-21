"""Base classes for linters."""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List


@dataclass
class LintError:
    """Represents a single lint error or warning."""

    line: int
    column: int
    message: str
    rule: str
    file: Path | None = None

    def __post_init__(self):
        """Ensure file is a Path object."""
        if self.file is not None and not isinstance(self.file, Path):
            self.file = Path(self.file)


@dataclass
class LintResult:
    """Result of linting a single file."""

    file: Path
    errors: List[LintError] = field(default_factory=list)
    warnings: List[LintError] = field(default_factory=list)

    def __post_init__(self):
        """Ensure file is a Path object."""
        if not isinstance(self.file, Path):
            self.file = Path(self.file)

    @property
    def has_errors(self) -> bool:
        """Check if there are any errors."""
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return len(self.warnings) > 0

    @property
    def total_issues(self) -> int:
        """Get total number of issues (errors + warnings)."""
        return len(self.errors) + len(self.warnings)


class BaseLinter(ABC):
    """Abstract base class for all linters."""

    def __init__(self):
        """Initialize the base linter."""
        self.errors: List[LintError] = []
        self.warnings: List[LintError] = []

    @abstractmethod
    def lint_file(self, filepath: Path) -> LintResult:
        """Lint a single file.

        Args:
            filepath: Path to the file to lint

        Returns:
            LintResult containing errors and warnings
        """
        pass

    def lint_directory(self, directory: Path, pattern: str = "*") -> List[LintResult]:
        """Lint all matching files in a directory.

        Args:
            directory: Directory to search for files
            pattern: Glob pattern for files to lint

        Returns:
            List of LintResult objects
        """
        results = []
        for filepath in directory.glob(pattern):
            if filepath.is_file():
                results.append(self.lint_file(filepath))
        return results

    def format_standard(self, results: List[LintResult]) -> str:
        """Format results in standard output format.

        Args:
            results: List of lint results

        Returns:
            Formatted string
        """
        output = []

        for result in results:
            for error in result.errors:
                output.append(
                    f"ERROR: {result.file}:{error.line}:{error.column}: {error.message} [{error.rule}]"
                )

            for warning in result.warnings:
                output.append(
                    f"WARNING: {result.file}:{warning.line}:{warning.column}: {warning.message} [{warning.rule}]"
                )

        # Summary
        total_errors = sum(len(r.errors) for r in results)
        total_warnings = sum(len(r.warnings) for r in results)

        if total_errors > 0:
            output.append(f"\n{total_errors} errors found")
        if total_warnings > 0:
            output.append(f"{total_warnings} warnings found")

        if total_errors == 0 and total_warnings == 0:
            output.append("All files valid")

        return "\n".join(output)

    def format_github(self, results: List[LintResult]) -> str:
        """Format results for GitHub Actions annotations.

        Args:
            results: List of lint results

        Returns:
            Formatted string with GitHub annotation syntax
        """
        output = []

        for result in results:
            for error in result.errors:
                output.append(
                    f"::error file={result.file},line={error.line},col={error.column}::{error.message}"
                )

            for warning in result.warnings:
                output.append(
                    f"::warning file={result.file},line={warning.line},col={warning.column}::{warning.message}"
                )

        return "\n".join(output)

    def format_json(self, results: List[LintResult]) -> str:
        """Format results as JSON.

        Args:
            results: List of lint results

        Returns:
            JSON string
        """
        data = []

        for result in results:
            file_data = {
                "file": str(result.file),
                "errors": [
                    {
                        "line": error.line,
                        "column": error.column,
                        "message": error.message,
                        "rule": error.rule,
                    }
                    for error in result.errors
                ],
                "warnings": [
                    {
                        "line": warning.line,
                        "column": warning.column,
                        "message": warning.message,
                        "rule": warning.rule,
                    }
                    for warning in result.warnings
                ],
            }
            data.append(file_data)

        return json.dumps(data, indent=2)

    def get_formatter(self, format_type: str) -> Callable[[List[LintResult]], str]:
        """Get formatter function by type.

        Args:
            format_type: Type of formatter (standard, github, json)

        Returns:
            Formatter function
        """
        formatters = {
            "standard": self.format_standard,
            "github": self.format_github,
            "json": self.format_json,
        }
        return formatters.get(format_type, self.format_standard)
