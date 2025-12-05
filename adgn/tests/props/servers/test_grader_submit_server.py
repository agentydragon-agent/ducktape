"""Tests for the grader submit server.

Tests server creation and basic validation.
"""

from __future__ import annotations

from adgn.props.grader.grader import GRADER_SUBMIT_INSTRUCTIONS


class TestGraderSubmitServerConstants:
    """Tests for grader submit server constants."""

    def test_instructions_are_non_empty(self):
        """Server instructions should be defined."""
        assert GRADER_SUBMIT_INSTRUCTIONS
        assert "submit_result" in GRADER_SUBMIT_INSTRUCTIONS
