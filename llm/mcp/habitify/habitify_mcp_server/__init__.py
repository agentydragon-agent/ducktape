"""
Habitify MCP Server package.
"""

from .habitify_client import HabitifyClient, HabitifyError
from .server import create_habitify_mcp_server
from .types import (
    DeleteResult,
    ErrorResponse,
    Habit,
    HabitResult,
    HabitsResult,
    HabitStatus,
    LogResult,
    ResolvedHabit,
    ResultType,
    Status,
    StatusResult,
    UnitType,
    UpdateResult,
)

__all__ = [
    "DeleteResult",
    "ErrorResponse",
    # Types
    "Habit",
    "HabitResult",
    "HabitStatus",
    # Client
    "HabitifyClient",
    "HabitifyError",
    "HabitsResult",
    "LogResult",
    "ResolvedHabit",
    "ResultType",
    "Status",
    "StatusResult",
    "UnitType",
    "UpdateResult",
    # Server factory
    "create_habitify_mcp_server",
]
