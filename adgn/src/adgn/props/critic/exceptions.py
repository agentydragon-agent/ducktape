"""Custom exceptions for critic failures."""

from __future__ import annotations


class CriticExecutionError(Exception):
    """Raised when critic agent encounters an error during execution."""


class CriticDidNotSubmitError(Exception):
    """Raised when critic agent completes without calling submit()."""
