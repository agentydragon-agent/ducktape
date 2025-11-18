"""Tests for diff intelligence module."""

from ducktape_llm_common.claude_linter_v2.config.models import Violation
from ducktape_llm_common.claude_linter_v2.diff.categorizer import CategorizedGroups, CategorizedViolation, ViolationCategorizer
from ducktape_llm_common.claude_linter_v2.diff.intelligence import DiffIntelligence
from ducktape_llm_common.claude_linter_v2.diff.parser import DiffParser, ParsedDiff


class TestDiffParser:
    """Test diff parsing functionality."""

    def test_parse_edit_tool(self):
        """Test parsing Edit tool response."""
        parser = DiffParser()

        tool_input = {"file_path": "/test.py", "old_string": "def foo():", "new_string": "def bar():"}

        tool_response = {
            "structuredPatch": [
                {"oldStart": 10, "oldLines": 1, "newStart": 10, "newLines": 1, "lines": ["-def foo():", "+def bar():"]}
            ]
        }

        parsed = parser.parse_tool_response("Edit", tool_input, tool_response)

        assert parsed is not None
        assert parsed.added_lines == {10}
        assert len(parsed.hunks) == 1
        assert parsed.hunks[0].new_start == 10

    def test_parse_multiedit_tool(self):
        """Test parsing MultiEdit tool with multiple hunks."""
        parser = DiffParser()

        tool_input = {
            "file_path": "/test.py",
            "edits": [{"old_string": "foo", "new_string": "bar"}, {"old_string": "baz", "new_string": "qux"}],
        }

        tool_response = {
            "structuredPatch": [
                {"oldStart": 10, "oldLines": 1, "newStart": 10, "newLines": 1, "lines": ["-foo", "+bar"]},
                {"oldStart": 20, "oldLines": 1, "newStart": 20, "newLines": 1, "lines": ["-baz", "+qux"]},
            ]
        }

        parsed = parser.parse_tool_response("MultiEdit", tool_input, tool_response)

        assert parsed is not None
        assert parsed.added_lines == {10, 20}
        assert len(parsed.hunks) == 2

    def test_parse_other_tools_returns_none(self):
        """Test that non-Edit/MultiEdit tools return None."""
        parser = DiffParser()

        # Write tool should return None
        write_input = {"file_path": "/test.py", "content": "hello"}
        assert parser.parse_tool_response("Write", write_input, None) is None

        # Read tool should return None
        read_input = {"file_path": "/test.py"}
        assert parser.parse_tool_response("Read", read_input, None) is None

        # Bash tool should return None
        bash_input = {"command": "ls"}
        assert parser.parse_tool_response("Bash", bash_input, None) is None


class TestViolationCategorizer:
    """Test violation categorization."""

    def test_categorize_in_diff(self):
        """Test categorizing violations in changed lines."""
        categorizer = ViolationCategorizer(context_distance=3)

        violations = [
            Violation(rule="E722", line=10, column=0, message="Bare except"),
            Violation(rule="E722", line=20, column=0, message="Bare except"),
        ]

        parsed_diff = ParsedDiff(
            file_path="/test.py", hunks=[], added_lines={10}, removed_lines=set(), context_lines=set()
        )

        categorized = categorizer.categorize_violations(violations, parsed_diff)

        assert len(categorized) == 2
        assert categorized[0].category == "in-diff"
        assert categorized[0].distance_from_change == 0
        assert categorized[1].category == "out-of-diff"
        assert categorized[1].distance_from_change is None

    def test_categorize_near_diff(self):
        """Test categorizing violations near changed lines."""
        categorizer = ViolationCategorizer(context_distance=3)

        violations = [
            Violation(rule="E722", line=8, column=0, message="Near change"),
            Violation(rule="E722", line=13, column=0, message="Also near"),
            Violation(rule="E722", line=20, column=0, message="Far away"),
        ]

        parsed_diff = ParsedDiff(
            file_path="/test.py", hunks=[], added_lines={10}, removed_lines=set(), context_lines=set()
        )

        categorized = categorizer.categorize_violations(violations, parsed_diff)

        assert categorized[0].category == "near-diff"
        assert categorized[0].distance_from_change == 2
        assert categorized[1].category == "near-diff"
        assert categorized[1].distance_from_change == 3
        assert categorized[2].category == "out-of-diff"

    def test_filter_by_priority(self):
        """Test filtering violations by priority."""
        categorizer = ViolationCategorizer()

        categorized = [
            CategorizedViolation(
                violation=Violation(rule="E1", line=1, column=0, message="Out"),
                category="out-of-diff",
                distance_from_change=None,
            ),
            CategorizedViolation(
                violation=Violation(rule="E2", line=10, column=0, message="In"),
                category="in-diff",
                distance_from_change=0,
            ),
            CategorizedViolation(
                violation=Violation(rule="E3", line=8, column=0, message="Near"),
                category="near-diff",
                distance_from_change=2,
            ),
        ]

        filtered = categorizer.filter_by_priority(categorized, max_violations=2)

        assert len(filtered) == 2
        assert filtered[0].category == "in-diff"
        assert filtered[1].category == "near-diff"


class TestDiffIntelligence:
    """Test the main diff intelligence module."""

    def test_format_violations_by_category(self):
        """Test formatting categorized violations."""
        di = DiffIntelligence()

        groups = CategorizedGroups(
            in_diff=[
                CategorizedViolation(
                    violation=Violation(rule="E722", line=10, column=0, message="Bare except"),
                    category="in-diff",
                    distance_from_change=0,
                )
            ],
            near_diff=[
                CategorizedViolation(
                    violation=Violation(rule="W293", line=8, column=0, message="Trailing whitespace"),
                    category="near-diff",
                    distance_from_change=2,
                )
            ],
            out_of_diff=[],
        )

        formatted = di.format_violations_by_category(groups)

        assert "Issues in code you just added:" in formatted
        assert "Line 10: Bare except" in formatted
        assert "Issues near your changes:" in formatted
        assert "Line 8 (2 lines away): Trailing whitespace" in formatted
