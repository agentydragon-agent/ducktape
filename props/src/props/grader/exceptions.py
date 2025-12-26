"""Custom exceptions for grader failures."""

from __future__ import annotations


class GraderDidNotSubmitError(Exception):
    """Raised when grader agent completes without calling submit()."""
