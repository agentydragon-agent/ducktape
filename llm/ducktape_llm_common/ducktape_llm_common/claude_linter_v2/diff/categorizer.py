"""Categorize violations based on their proximity to diff changes."""

from dataclasses import dataclass, field
from typing import Literal

from ..config.models import Violation
from .parser import ParsedDiff


@dataclass
class CategorizedViolation:
    """A violation categorized by its relationship to diff changes."""

    violation: Violation
    category: Literal["in-diff", "near-diff", "out-of-diff"]
    distance_from_change: int | None  # For near-diff


@dataclass
class CategorizedGroups:
    """Groups of violations categorized by their relationship to diff changes."""

    in_diff: list[CategorizedViolation] = field(default_factory=list)
    near_diff: list[CategorizedViolation] = field(default_factory=list)
    out_of_diff: list[CategorizedViolation] = field(default_factory=list)


class ViolationCategorizer:
    """Categorize violations based on their proximity to changes."""

    def __init__(self, context_distance: int = 3):
        """
        Initialize categorizer.

        Args:
            context_distance: Lines away from change to consider "near"
        """
        self.context_distance = context_distance

    def categorize_violations(
        self, violations: list[Violation], parsed_diff: ParsedDiff | None
    ) -> list[CategorizedViolation]:
        """
        Categorize violations based on their proximity to changes.

        Args:
            violations: List of violations with line numbers
            parsed_diff: Parsed diff information (None for PreToolUse)

        Returns:
            List of categorized violations
        """
        if parsed_diff is None:
            # No diff info - all violations are out-of-diff
            return [
                CategorizedViolation(violation=v, category="out-of-diff", distance_from_change=None) for v in violations
            ]

        # Build set of all changed lines and their neighbors
        changed_lines = parsed_diff.added_lines
        near_lines = set()

        for line in changed_lines:
            for offset in range(-self.context_distance, self.context_distance + 1):
                if offset != 0:  # Don't include the changed line itself
                    near_line = line + offset
                    if near_line > 0:  # Line numbers start at 1
                        near_lines.add(near_line)

        categorized = []

        for violation in violations:
            if violation.line in changed_lines:
                category = "in-diff"
                distance = 0
            elif violation.line in near_lines:
                category = "near-diff"
                # Calculate minimum distance to any changed line
                distance = min(abs(violation.line - changed_line) for changed_line in changed_lines)
            else:
                category = "out-of-diff"
                distance = None

            categorized.append(
                CategorizedViolation(
                    violation=violation,
                    category=category,  # type: ignore[arg-type]
                    distance_from_change=distance,
                )
            )

        return categorized

    def group_by_category(self, categorized: list[CategorizedViolation]) -> CategorizedGroups:
        """Group categorized violations by their category."""
        groups = CategorizedGroups()

        for cv in categorized:
            if cv.category == "in-diff":
                groups.in_diff.append(cv)
            elif cv.category == "near-diff":
                groups.near_diff.append(cv)
            else:  # "out-of-diff"
                groups.out_of_diff.append(cv)

        # Sort near-diff by distance
        groups.near_diff.sort(key=lambda cv: cv.distance_from_change or 0)

        return groups

    def filter_by_priority(
        self, categorized: list[CategorizedViolation], max_violations: int = 10
    ) -> list[CategorizedViolation]:
        """
        Filter violations by priority.

        Priority order:
        1. All in-diff violations
        2. Near-diff violations (closest first)
        3. Out-of-diff violations

        Args:
            categorized: List of categorized violations
            max_violations: Maximum number to return

        Returns:
            Filtered list of violations
        """
        groups = self.group_by_category(categorized)

        result = []

        # Add all in-diff violations
        result.extend(groups.in_diff)

        # Add near-diff violations if room
        remaining = max_violations - len(result)
        if remaining > 0:
            result.extend(groups.near_diff[:remaining])

        # Add out-of-diff violations if room
        remaining = max_violations - len(result)
        if remaining > 0:
            result.extend(groups.out_of_diff[:remaining])

        return result[:max_violations]
