"""Tests for the grader submit HTTP server.

Tests server creation, tool registration, and auth configuration.

Note: Full integration tests for create_grader_submit_http_server
require database initialization. These tests focus on constants
and basic validation. The HTTP infrastructure is validated by
test_http_launcher.py tests.
"""

from __future__ import annotations

from adgn.props.servers.grader_submit_server import GRADER_SUBMIT_INSTRUCTIONS


class TestGraderSubmitServerConstants:
    """Tests for grader submit server constants (no DB required)."""

    def test_instructions_are_non_empty(self):
        """Server instructions should be defined."""
        assert GRADER_SUBMIT_INSTRUCTIONS
        assert "submit_result" in GRADER_SUBMIT_INSTRUCTIONS.lower()

    def test_instructions_describe_tool(self):
        """Instructions should describe the submit_result tool."""
        assert "canonical_tp_coverage" in GRADER_SUBMIT_INSTRUCTIONS
        assert "recall" in GRADER_SUBMIT_INSTRUCTIONS
