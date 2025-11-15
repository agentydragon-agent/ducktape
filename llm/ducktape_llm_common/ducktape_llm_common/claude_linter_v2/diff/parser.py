"""Parse diff information from Claude tool responses."""

from dataclasses import dataclass
from typing import Literal


@dataclass
class DiffLine:
    """A single line in a diff."""

    line_number: int  # Line number in final file
    content: str
    change_type: Literal["added", "removed", "context"]
    hunk_index: int  # Which hunk this belongs to


@dataclass
class DiffHunk:
    """A contiguous section of changes in a diff."""

    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: list[DiffLine]


@dataclass
class ParsedDiff:
    """Parsed diff information from a tool response."""

    file_path: str
    hunks: list[DiffHunk]
    added_lines: set[int]  # Line numbers in final file
    removed_lines: set[int]  # Line numbers in original file
    context_lines: set[int]  # Unchanged lines near changes


class DiffParser:
    """Parse structured patches from Claude tool responses."""

    def parse_tool_response(self, tool_name: str, tool_input: dict, tool_response: dict | None) -> ParsedDiff | None:
        """
        Parse Edit/MultiEdit tool response into ParsedDiff.

        Returns None if no diff information available (e.g., PreToolUse hook).
        """
        file_path = tool_input.get("file_path", "")

        if tool_name == "Edit":
            if tool_response is None:
                return None  # PreToolUse has no response
            return self._parse_edit_tool(file_path, tool_response)
        if tool_name == "MultiEdit":
            if tool_response is None:
                return None  # PreToolUse has no response
            return self._parse_multiedit_tool(file_path, tool_response)
        return None

    def _parse_edit_tool(self, file_path: str, tool_response: dict) -> ParsedDiff | None:
        """Parse Edit tool response."""
        structured_patch = tool_response.get("structuredPatch")
        if structured_patch is None:
            return None

        return self._parse_structured_patch(file_path, structured_patch)

    def _parse_multiedit_tool(self, file_path: str, tool_response: dict) -> ParsedDiff | None:
        """Parse MultiEdit tool response."""
        structured_patch = tool_response.get("structuredPatch")
        if structured_patch is None:
            return None

        return self._parse_structured_patch(file_path, structured_patch)

    def _parse_structured_patch(self, file_path: str, structured_patch: list[dict]) -> ParsedDiff:
        """Parse structured patch format from Claude."""
        hunks = []
        added_lines = set()
        removed_lines = set()
        context_lines = set()

        # Handle empty patch list
        if not structured_patch:
            return ParsedDiff(
                file_path=file_path, hunks=[], added_lines=set(), removed_lines=set(), context_lines=set()
            )

        for hunk_idx, hunk_data in enumerate(structured_patch):
            hunk = self._parse_hunk(hunk_data, hunk_idx)
            hunks.append(hunk)

            # Track line numbers
            current_new_line = hunk.new_start
            current_old_line = hunk.old_start

            for line in hunk.lines:
                if line.change_type == "added":
                    added_lines.add(line.line_number)
                    current_new_line += 1
                elif line.change_type == "removed":
                    removed_lines.add(current_old_line)
                    current_old_line += 1
                else:  # context
                    context_lines.add(line.line_number)
                    current_new_line += 1
                    current_old_line += 1

        return ParsedDiff(
            file_path=file_path,
            hunks=hunks,
            added_lines=added_lines,
            removed_lines=removed_lines,
            context_lines=context_lines,
        )

    def _parse_hunk(self, hunk_data: dict, hunk_idx: int) -> DiffHunk:
        """Parse a single hunk from structured patch."""
        old_start = hunk_data.get("oldStart", 1)
        old_lines = hunk_data.get("oldLines", 0)
        new_start = hunk_data.get("newStart", 1)
        new_lines = hunk_data.get("newLines", 0)
        raw_lines = hunk_data.get("lines", [])

        parsed_lines = []
        current_new_line = new_start

        for raw_line in raw_lines:
            if raw_line.startswith("\\"):  # Special marker
                continue

            if raw_line.startswith("-"):
                change_type = "removed"
                content = raw_line[1:]
                line_number = -1  # Not in final file
            elif raw_line.startswith("+"):
                change_type = "added"
                content = raw_line[1:]
                line_number = current_new_line
                current_new_line += 1
            else:
                # Context line (may start with space or nothing)
                change_type = "context"
                content = raw_line.removeprefix(" ")
                line_number = current_new_line
                current_new_line += 1

            parsed_lines.append(
                DiffLine(
                    line_number=line_number,
                    content=content,
                    change_type=change_type,  # type: ignore[arg-type]
                    hunk_index=hunk_idx,
                )
            )

        return DiffHunk(
            old_start=old_start, old_lines=old_lines, new_start=new_start, new_lines=new_lines, lines=parsed_lines
        )
