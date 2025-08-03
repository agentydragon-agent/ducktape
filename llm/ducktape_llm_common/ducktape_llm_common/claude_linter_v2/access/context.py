"""Context object for predicate evaluation."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..types import SessionID


@dataclass
class PredicateContext:
    """
    Context provided to predicate functions for evaluation.

    Simple structure with tool name, arguments, session info, and timestamp.
    """

    tool: str  # Tool name: Write, Edit, MultiEdit, Read, Bash, etc.
    args: dict[str, Any]  # Tool arguments as key-value pairs
    session_id: SessionID
    timestamp: datetime = datetime.now()
