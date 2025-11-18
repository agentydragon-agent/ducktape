"""Main diff intelligence module for smart violation filtering."""

from collections import defaultdict
from typing import Any

from ..config.models import Violation
from .categorizer import CategorizedViolation, ViolationCategorizer, ViolationCategory
from .parser import DiffParser


class DiffIntelligence:
    """
    Smart violation filtering based on diff context for Edit/MultiEdit tools.

    This module analyzes Edit and MultiEdit tool responses to understand what
    code Claude just changed vs existing code, allowing smarter violation reporting.

    Only applies to Edit and MultiEdit tools - other tools like Write, Read, etc
    are not affected by this intelligence.
    """

    def __init__(self, context_distance: int = 3):
        """
        Initialize diff intelligence.

        Args:
            context_distance: Lines away from change to consider "near"
        """
        self.parser = DiffParser()
        self.categorizer = ViolationCategorizer(context_distance)

    def analyze(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_response: dict[str, Any] | None,
        violations: list[Violation],
    ) -> defaultdict[ViolationCategory, list[CategorizedViolation]]:
        """
        Analyze violations in context of tool changes.

        Args:
            tool_name: Name of the tool (Edit, MultiEdit, Write)
            tool_input: Tool input parameters
            tool_response: Tool response (None for PreToolUse)
            violations: List of violations found

        Returns:
            defaultdict mapping violation categories to lists of categorized violations
        """
        # Parse diff information
        parsed_diff = self.parser.parse_tool_response(tool_name, tool_input, tool_response)

        # Categorize violations
        categorized = self.categorizer.categorize_violations(violations, parsed_diff)

        # Group by category
        return self.categorizer.group_by_category(categorized)

    def get_priority_violations(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_response: dict[str, Any] | None,
        violations: list[Violation],
        max_violations: int = 10,
    ) -> list[CategorizedViolation]:
        """
        Get violations prioritized by their relationship to changes.

        In-diff violations (code Claude just added) are shown first,
        followed by near-diff, then out-of-diff.

        Args:
            tool_name: Name of the tool
            tool_input: Tool input parameters
            tool_response: Tool response (None for PreToolUse)
            violations: List of violations found
            max_violations: Maximum number to return

        Returns:
            Prioritized list of categorized violations
        """
        # Parse and categorize
        parsed_diff = self.parser.parse_tool_response(tool_name, tool_input, tool_response)
        categorized = self.categorizer.categorize_violations(violations, parsed_diff)

        # Filter by priority
        return self.categorizer.filter_by_priority(categorized, max_violations)

    def format_violations_by_category(
        self, categorized_groups: defaultdict[ViolationCategory, list[CategorizedViolation]]
    ) -> str:
        """
        Format categorized violations for display.

        Args:
            categorized_groups: Violations grouped by category

        Returns:
            Formatted string for display
        """
        parts = []

        # In-diff violations (most important)
        if in_diff := categorized_groups[ViolationCategory.IN_DIFF]:
            parts.append("Issues in code you just added:")
            for cv in in_diff:
                v = cv.violation
                parts.append(f"  Line {v.line}: {v.message}")

        # Near-diff violations
        if near_diff := categorized_groups[ViolationCategory.NEAR_DIFF]:
            if parts:
                parts.append("")  # Blank line
            parts.append("Issues near your changes:")
            for cv in near_diff:
                v = cv.violation
                distance = cv.distance_from_change
                parts.append(f"  Line {v.line} ({distance} lines away): {v.message}")

        # Out-of-diff violations (least important)
        if (out_diff := categorized_groups[ViolationCategory.OUT_OF_DIFF]) and len(parts) < 20:
            if parts:
                parts.append("")  # Blank line
            parts.append("Existing issues in file:")
            for cv in out_diff[:3]:  # Show max 3
                v = cv.violation
                parts.append(f"  Line {v.line}: {v.message}")
            if len(out_diff) > 3:
                parts.append(f"  ... and {len(out_diff) - 3} more")

        return "\n".join(parts)
