"""
Habitify MCP Server package.
"""

from .habitify_client import HabitifyClient, HabitifyError
from .server import create_habitify_mcp_server
from .types import (DeleteResult, ErrorResponse, Habit, HabitResult,
                    HabitsResult, HabitStatus, LogResult, ResolvedHabit,
                    ResultType, Status, StatusResult, UnitType, UpdateResult)

__all__ = [
    # Server factory
    "create_habitify_mcp_server",

    # Client
    "HabitifyClient",
    "HabitifyError",

    # Types
    "Habit",
    "HabitStatus",
    "Status",
    "UnitType",
    "ErrorResponse",
    "ResolvedHabit",
    "HabitsResult",
    "HabitResult",
    "StatusResult",
    "LogResult",
    "UpdateResult",
    "DeleteResult",
    "ResultType",
]
