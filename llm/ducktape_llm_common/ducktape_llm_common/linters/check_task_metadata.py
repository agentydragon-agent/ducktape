#!/usr/bin/env python3
"""
Linter to check correctness of structured task metadata (METADATA.yaml, TASK_GRAPH.md, etc.).
Validates schema compliance, required fields, and consistency.
"""

import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set

import yaml

from ducktape_llm_common.linters.base import BaseLinter, LintError, LintResult


class MetadataLinter(BaseLinter):
    """Linter for task metadata files."""

    # Required fields for METADATA.yaml
    REQUIRED_METADATA_FIELDS = {
        "task": {
            "id": str,
            "title": str,
            "type": str,
            "state": str,
            "priority": str,
            "assigned_to": str,
            "created_at": str,
        }
    }

    # Valid values for enum fields
    VALID_VALUES = {
        "type": [
            "feature",
            "bug",
            "investigation",
            "refactor",
            "perf",
            "docs",
            "test",
            "chore",
        ],
        "state": [
            "BACKLOG",
            "PLANNED",
            "IN_PROGRESS",
            "BLOCKED",
            "IN_REVIEW",
            "COMPLETED",
            "CANCELLED",
            "REOPENED",
        ],
        "priority": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
        "risk_level": ["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"],
    }

    # State transition rules
    VALID_STATE_TRANSITIONS = {
        "BACKLOG": ["PLANNED", "CANCELLED"],
        "PLANNED": ["IN_PROGRESS", "BLOCKED", "CANCELLED"],
        "IN_PROGRESS": ["BLOCKED", "IN_REVIEW", "CANCELLED"],
        "BLOCKED": ["IN_PROGRESS", "CANCELLED"],
        "IN_REVIEW": ["COMPLETED", "IN_PROGRESS", "BLOCKED", "CANCELLED"],
        "COMPLETED": ["REOPENED"],
        "REOPENED": ["IN_PROGRESS", "CANCELLED"],
        "CANCELLED": [],  # Terminal state
    }

    def __init__(self):
        super().__init__()
        self.task_ids: Set[str] = set()
        self.dependencies: Dict[str, Dict] = {}

    def lint_file(self, filepath: Path) -> LintResult:
        """Lint a single file based on its type."""
        if filepath.name == "METADATA.yaml" or filepath.suffix == ".yaml":
            return self._lint_metadata_file(filepath)
        elif filepath.name == "TASK_GRAPH.md":
            return self._lint_task_graph(filepath)
        else:
            # Unknown file type, return empty result
            return LintResult(filepath)

    def _lint_metadata_file(self, filepath: Path) -> LintResult:
        """Lint a METADATA.yaml file."""
        result = LintResult(filepath)

        if not filepath.exists():
            result.errors.append(
                LintError(
                    line=0,
                    column=0,
                    message=f"File not found: {filepath}",
                    rule="file-exists",
                )
            )
            return result

        try:
            with open(filepath) as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            result.errors.append(
                LintError(
                    line=0, column=0, message=f"Invalid YAML - {e}", rule="valid-yaml"
                )
            )
            return result

        if not data:
            result.errors.append(
                LintError(
                    line=0, column=0, message="Empty metadata file", rule="non-empty"
                )
            )
            return result

        # Validate required fields
        self._validate_required_fields(data, result)

        # Validate enum values
        self._validate_enum_values(data, result)

        # Validate dates
        self._validate_dates(data, result)

        # Validate dependencies
        self._validate_dependencies(data, result)

        # Validate estimates and tracking
        self._validate_estimates(data, result)

        # Check for duplicate task IDs
        if "task" in data and "id" in data["task"]:
            task_id = data["task"]["id"]
            if task_id in self.task_ids:
                result.errors.append(
                    LintError(
                        line=0,
                        column=0,
                        message=f"Duplicate task ID: {task_id}",
                        rule="unique-task-id",
                    )
                )
            self.task_ids.add(task_id)

        return result

    def _lint_task_graph(self, filepath: Path) -> LintResult:
        """Lint a TASK_GRAPH.md file."""
        result = LintResult(filepath)

        if not filepath.exists():
            result.errors.append(
                LintError(
                    line=0,
                    column=0,
                    message=f"File not found: {filepath}",
                    rule="file-exists",
                )
            )
            return result

        content = filepath.read_text(encoding="utf-8")

        # Check for mermaid graph
        if "```mermaid" in content:
            self._validate_mermaid_graph(content, result)

        # Check for task status table
        if "| ID | Task |" in content:
            self._validate_status_table(content, result)

        # Check for dependency references
        self._validate_graph_dependencies(content, result)

        return result

    def _validate_required_fields(self, data: Dict, result: LintResult) -> None:
        """Validate required fields are present."""
        for section, fields in self.REQUIRED_METADATA_FIELDS.items():
            if section not in data:
                result.errors.append(
                    LintError(
                        line=0,
                        column=0,
                        message=f"Missing required section: {section}",
                        rule="required-section",
                    )
                )
                continue

            for field, expected_type in fields.items():
                if field not in data[section]:
                    result.errors.append(
                        LintError(
                            line=0,
                            column=0,
                            message=f"Missing required field: {section}.{field}",
                            rule="required-field",
                        )
                    )
                elif not isinstance(data[section][field], expected_type):
                    result.errors.append(
                        LintError(
                            line=0,
                            column=0,
                            message=(
                                f"Field {section}.{field} should be {expected_type.__name__}, "
                                f"got {type(data[section][field]).__name__}"
                            ),
                            rule="field-type",
                        )
                    )

    def _validate_enum_values(self, data: Dict, result: LintResult) -> None:
        """Validate enum field values."""
        if "task" in data:
            task = data["task"]

            # Check type
            if "type" in task and task["type"] not in self.VALID_VALUES["type"]:
                result.errors.append(
                    LintError(
                        line=0,
                        column=0,
                        message=(
                            f"Invalid task type '{task['type']}'. "
                            f"Valid values: {', '.join(self.VALID_VALUES['type'])}"
                        ),
                        rule="valid-task-type",
                    )
                )

            # Check state
            if "state" in task and task["state"] not in self.VALID_VALUES["state"]:
                result.errors.append(
                    LintError(
                        line=0,
                        column=0,
                        message=(
                            f"Invalid task state '{task['state']}'. "
                            f"Valid values: {', '.join(self.VALID_VALUES['state'])}"
                        ),
                        rule="valid-task-state",
                    )
                )

            # Check priority
            if (
                "priority" in task
                and task["priority"] not in self.VALID_VALUES["priority"]
            ):
                result.errors.append(
                    LintError(
                        line=0,
                        column=0,
                        message=(
                            f"Invalid priority '{task['priority']}'. "
                            f"Valid values: {', '.join(self.VALID_VALUES['priority'])}"
                        ),
                        rule="valid-priority",
                    )
                )

        # Check risk level if present
        if "risk_assessment" in data and "level" in data["risk_assessment"]:
            level = data["risk_assessment"]["level"]
            if level not in self.VALID_VALUES["risk_level"]:
                result.errors.append(
                    LintError(
                        line=0,
                        column=0,
                        message=(
                            f"Invalid risk level '{level}'. "
                            f"Valid values: {', '.join(self.VALID_VALUES['risk_level'])}"
                        ),
                        rule="valid-risk-level",
                    )
                )

    def _validate_dates(self, data: Dict, result: LintResult) -> None:
        """Validate date formats and logic."""
        if "task" not in data:
            return

        task = data["task"]
        date_fields = [
            "created_at",
            "started_at",
            "blocked_at",
            "completed_at",
            "due_date",
        ]

        dates = {}
        for field in date_fields:
            if field in task and task[field]:
                try:
                    dates[field] = datetime.fromisoformat(
                        task[field].replace("Z", "+00:00")
                    )
                except ValueError:
                    result.errors.append(
                        LintError(
                            line=0,
                            column=0,
                            message=(
                                f"Invalid date format for {field}: {task[field]}. "
                                "Use ISO format (YYYY-MM-DDTHH:MM:SSZ)"
                            ),
                            rule="valid-date-format",
                        )
                    )

        # Validate date logic
        if "created_at" in dates and "started_at" in dates:
            if dates["started_at"] < dates["created_at"]:
                result.errors.append(
                    LintError(
                        line=0,
                        column=0,
                        message="started_at cannot be before created_at",
                        rule="date-logic",
                    )
                )

        if "started_at" in dates and "completed_at" in dates:
            if dates["completed_at"] < dates["started_at"]:
                result.errors.append(
                    LintError(
                        line=0,
                        column=0,
                        message="completed_at cannot be before started_at",
                        rule="date-logic",
                    )
                )

        # Check if completed tasks have completion date
        if task.get("state") == "COMPLETED" and not task.get("completed_at"):
            result.warnings.append(
                LintError(
                    line=0,
                    column=0,
                    message="Completed task missing completed_at date",
                    rule="completed-date",
                )
            )

    def _validate_dependencies(self, data: Dict, result: LintResult) -> None:
        """Validate dependency structure."""
        if "dependencies" not in data:
            return

        deps = data["dependencies"]
        task_id = data.get("task", {}).get("id", "unknown")

        # Check for self-dependencies
        for dep_type in ["blocks", "depends_on"]:
            if dep_type in deps:
                if task_id in deps[dep_type]:
                    result.errors.append(
                        LintError(
                            line=0,
                            column=0,
                            message="Task cannot depend on itself",
                            rule="no-self-dependency",
                        )
                    )

        # Check for circular dependencies (simplified check)
        if "depends_on" in deps and "blocks" in deps:
            overlap = set(deps["depends_on"]) & set(deps["blocks"])
            if overlap:
                result.errors.append(
                    LintError(
                        line=0,
                        column=0,
                        message=f"Task cannot both depend on and block: {', '.join(overlap)}",
                        rule="no-circular-dependency",
                    )
                )

        # Store dependencies for cross-file validation
        self.dependencies[task_id] = deps

    def _validate_estimates(self, data: Dict, result: LintResult) -> None:
        """Validate time estimates and tracking."""
        if "task" not in data:
            return

        task = data["task"]

        # Check estimate vs actual
        if "estimated_hours" in task and "actual_hours" in task:
            if task["actual_hours"] > task["estimated_hours"] * 3:
                result.warnings.append(
                    LintError(
                        line=0,
                        column=0,
                        message=(
                            f"Actual hours ({task['actual_hours']}) "
                            f"significantly exceeds estimate ({task['estimated_hours']})"
                        ),
                        rule="estimate-exceeded",
                    )
                )

        # Check percent complete
        if "percent_complete" in task:
            percent = task["percent_complete"]
            if not (0 <= percent <= 100):
                result.errors.append(
                    LintError(
                        line=0,
                        column=0,
                        message=f"percent_complete must be between 0 and 100, got {percent}",
                        rule="valid-percent",
                    )
                )

            # Check consistency with state
            if task.get("state") == "COMPLETED" and percent != 100:
                result.warnings.append(
                    LintError(
                        line=0,
                        column=0,
                        message=f"Completed task should have 100% completion, got {percent}%",
                        rule="completion-consistency",
                    )
                )
            elif task.get("state") == "BACKLOG" and percent > 0:
                result.warnings.append(
                    LintError(
                        line=0,
                        column=0,
                        message=f"Backlog task should have 0% completion, got {percent}%",
                        rule="backlog-consistency",
                    )
                )

    def _validate_mermaid_graph(self, content: str, result: LintResult) -> None:
        """Validate mermaid graph syntax."""
        # Extract mermaid content
        mermaid_match = re.search(r"```mermaid\n(.*?)\n```", content, re.DOTALL)
        if not mermaid_match:
            return

        mermaid_content = mermaid_match.group(1)

        # Basic syntax checks
        if "graph" not in mermaid_content and "flowchart" not in mermaid_content:
            result.errors.append(
                LintError(
                    line=0,
                    column=0,
                    message="Mermaid graph missing 'graph' or 'flowchart' declaration",
                    rule="mermaid-syntax",
                )
            )

        # Check for common issues
        if "-->" in mermaid_content or "--->" in mermaid_content:
            # Check balanced nodes
            arrows = re.findall(r"(\w+)\s*--+>\s*(\w+)", mermaid_content)
            nodes = set()
            for source, target in arrows:
                nodes.add(source)
                nodes.add(target)

            # Check for undefined nodes (simplified)
            defined_nodes = re.findall(r"^(\w+)\[", mermaid_content, re.MULTILINE)
            undefined = nodes - set(defined_nodes)
            if undefined and not any(node in ["A", "B", "C"] for node in undefined):
                result.warnings.append(
                    LintError(
                        line=0,
                        column=0,
                        message=f"Potentially undefined nodes in graph: {', '.join(undefined)}",
                        rule="undefined-nodes",
                    )
                )

    def _validate_status_table(self, content: str, result: LintResult) -> None:
        """Validate task status table."""
        # Find table
        table_match = re.search(
            r"\| ID \|.*?\n\|[-|\s]+\n((?:\|.*?\n)+)", content, re.MULTILINE
        )
        if not table_match:
            return

        table_rows = table_match.group(1).strip().split("\n")

        for row in table_rows:
            if not row.strip():
                continue

            parts = [p.strip() for p in row.split("|") if p.strip()]
            if len(parts) < 3:
                result.warnings.append(
                    LintError(
                        line=0,
                        column=0,
                        message=f"Malformed table row: {row}",
                        rule="table-format",
                    )
                )
                continue

            # task_id = parts[0]  # Not used currently
            status = parts[2] if len(parts) > 2 else ""

            # Validate status emoji mapping
            status_emoji_map = {
                "✅ DONE": "COMPLETED",
                "🔄 ACTIVE": "IN_PROGRESS",
                "📋 TODO": "BACKLOG",
                "⏸️ BLOCKED": "BLOCKED",
            }

            for emoji_status, state in status_emoji_map.items():
                if emoji_status in status and state not in self.VALID_VALUES["state"]:
                    result.errors.append(
                        LintError(
                            line=0,
                            column=0,
                            message=f"Invalid status in table: {status}",
                            rule="invalid-status",
                        )
                    )

    def _validate_graph_dependencies(self, content: str, result: LintResult) -> None:
        """Validate dependency references in graph."""
        # Find dependency arrows
        dep_pattern = re.compile(r"(\w+(?:\.\d+)*)\s*--+>\s*(\w+(?:\.\d+)*)")

        dependencies = dep_pattern.findall(content)

        # Check for cycles (simplified - only direct cycles)
        for source, target in dependencies:
            if (target, source) in dependencies:
                result.errors.append(
                    LintError(
                        line=0,
                        column=0,
                        message=f"Circular dependency detected: {source} <-> {target}",
                        rule="circular-dependency",
                    )
                )

    def validate_cross_file_consistency(self) -> List[LintError]:
        """Validate consistency across multiple files."""
        warnings = []

        # Check dependency references
        for task_id, deps in self.dependencies.items():
            for dep_list in ["depends_on", "blocks"]:
                if dep_list in deps:
                    for dep_id in deps[dep_list]:
                        if dep_id not in self.task_ids:
                            warnings.append(
                                LintError(
                                    line=0,
                                    column=0,
                                    message=f"Task {task_id} references non-existent task: {dep_id}",
                                    rule="missing-dependency",
                                )
                            )

        return warnings


def main():
    """Console script entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Lint task metadata files")
    parser.add_argument("files", nargs="+", help="Files to lint")
    parser.add_argument(
        "--no-warnings", action="store_true", help="Only show errors, not warnings"
    )
    parser.add_argument(
        "--cross-file", action="store_true", help="Enable cross-file consistency checks"
    )
    parser.add_argument(
        "--format",
        choices=["standard", "github", "json"],
        default="standard",
        help="Output format (default: standard)",
    )

    args = parser.parse_args()

    linter = MetadataLinter()

    total_errors = 0
    total_warnings = 0
    all_results = []

    for filepath in args.files:
        path = Path(filepath)
        if not path.is_file():
            print(f"Skipping non-file: {filepath}")
            continue

        result = linter.lint_file(path)
        all_results.append(result)

        total_errors += len(result.errors)
        total_warnings += len(result.warnings)

    # Cross-file validation if requested
    if args.cross_file:
        cross_file_warnings = linter.validate_cross_file_consistency()
        if cross_file_warnings:
            # Add to a dummy result
            cross_result = LintResult(Path("cross-file"))
            cross_result.warnings.extend(cross_file_warnings)
            all_results.append(cross_result)
            total_warnings += len(cross_file_warnings)

    # Format and print results
    formatter = linter.get_formatter(args.format)
    print(formatter(all_results))

    if total_errors > 0:
        sys.exit(1)
    elif total_warnings > 0 and not args.no_warnings:
        sys.exit(0)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
