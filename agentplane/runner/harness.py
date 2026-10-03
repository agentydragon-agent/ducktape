"""Persisted harness names shared by configuration and the app archive."""

from enum import StrEnum


class Harness(StrEnum):
    """The runner protocol Harness enum names, reused by configuration and session projections."""

    CLAUDE = "HARNESS_CLAUDE"
    CODEX = "HARNESS_CODEX"


