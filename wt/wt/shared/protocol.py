"""JSON-RPC 2.0 protocol for GitStatusd daemon communication.

Uses standard JSON-RPC 2.0 for type-safe, standardized RPC communication
between clients and the GitStatusd multiplexing daemon.
"""

import json
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from ..shared.github_models import PRInfo


class DaemonHealthStatus(str, Enum):
    """Daemon health status levels."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


class DaemonHealth(BaseModel):
    """Daemon health information."""

    status: DaemonHealthStatus
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    github_errors: int = 0
    gitstatusd_errors: int = 0


class Request(BaseModel):
    """JSON-RPC 2.0 request."""

    model_config = {"extra": "forbid"}

    jsonrpc: str = "2.0"
    method: str = Field(..., description="Method name to call")
    params: Dict[str, Any] = Field(default_factory=dict, description="Method parameters")
    id: uuid.UUID = Field(..., description="Request ID")


class Response(BaseModel):
    """JSON-RPC 2.0 successful response."""

    model_config = {"extra": "forbid"}

    jsonrpc: str = "2.0"
    result: Union["StatusResponse", "PingResult", str] = Field(..., description="Result data")
    id: uuid.UUID = Field(..., description="Request ID from original request")


class Error(BaseModel):
    """JSON-RPC 2.0 error object."""

    model_config = {"extra": "forbid"}

    code: int = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    data: Any = Field(default=None, description="Additional error data")


class ErrorResponse(BaseModel):
    """JSON-RPC 2.0 error response."""

    model_config = {"extra": "forbid"}

    jsonrpc: str = "2.0"
    error: Error = Field(..., description="Error details")
    id: uuid.UUID = Field(..., description="Request ID from original request")


# Standard JSON-RPC error codes
class ErrorCodes:
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    # Custom error codes (application-specific)
    WORKTREE_NOT_FOUND = -32001
    GITSTATUSD_ERROR = -32002


# Method parameter schemas
class StatusParams(BaseModel):
    """Parameters for status requests."""

    model_config = {"extra": "forbid"}

    worktree_paths: List[Path] = Field(
        default_factory=list,
        description="List of absolute paths to worktree directories. If empty, returns all discovered worktrees.",
    )


# Method result schemas
class CommitInfo(BaseModel):
    """Git commit information."""

    hash: str = Field(..., description="Full commit hash")
    short_hash: str = Field(..., description="Short commit hash")
    message: str = Field(..., description="Commit message")
    author: str = Field(..., description="Commit author")
    date: str = Field(..., description="Commit date in ISO format")


class StatusResult(BaseModel):
    """Result for individual worktree status."""

    worktree_path: str = Field(..., description="Path that was queried")
    worktree_name: str = Field(..., description="Name of the worktree")
    branch: str = Field(..., description="Branch name")
    has_dirty_files: bool = Field(..., description="Whether there are modified files")
    has_untracked_files: bool = Field(..., description="Whether there are untracked files")
    processing_time_ms: float = Field(..., description="Processing time in milliseconds")
    last_updated_at: datetime = Field(
        ..., description="When gitstatusd was last queried for this worktree"
    )
    is_cached: bool = Field(default=False, description="Whether this result came from cache")
    # Commit and branch info
    commit_info: CommitInfo = Field(..., description="Latest commit information")
    ahead_count: int = Field(default=0, description="Number of commits ahead of default branch")
    behind_count: int = Field(default=0, description="Number of commits behind default branch")
    is_main: bool = Field(default=False, description="Whether this is the main repository")
    # GitHub PR info
    pr_info: Optional[PRInfo] = Field(
        default=None, description="GitHub pull request information if available"
    )


class StatusResponse(BaseModel):
    """Unified response for get_status method (always returns results for multiple worktrees)."""

    results: Dict[str, StatusResult] = Field(
        ..., description="Map of worktree path to status results"
    )
    total_processing_time_ms: float = Field(
        ..., description="Total processing time in milliseconds"
    )
    individual_processing_times_ms: Dict[str, float] = Field(
        default_factory=dict, description="Detailed processing time per worktree"
    )
    discovery_time_ms: float = Field(default=0.0, description="Time spent on worktree discovery")
    concurrent_requests: int = Field(
        default=1, description="Number of requests processed concurrently"
    )
    daemon_health: DaemonHealth = Field(
        ..., description="Current daemon health status and error information"
    )


class PingResult(BaseModel):
    """Result for ping method."""

    message: str = "pong"
    daemon_pid: int = Field(..., description="Process ID of the daemon")
    started_at: datetime = Field(..., description="When the daemon was started")
    discovered_worktrees: List[Path] = Field(
        default_factory=list, description="List of discovered worktree paths"
    )


def create_error_response(
    code: int, message: str, request_id: Union[uuid.UUID, None] = None, data: Any = None
) -> ErrorResponse:
    """Create a JSON-RPC 2.0 error response."""
    error = Error(code=code, message=message, data=data)
    return ErrorResponse(error=error, id=request_id)


def parse_request(data: str) -> Request:
    """Parse JSON string into JSON-RPC request."""
    try:
        raw_data = json.loads(data)
        return Request.model_validate(raw_data)
    except (json.JSONDecodeError, Exception) as e:
        raise ValueError(f"Invalid JSON-RPC request: {e}")


# Method registry for type safety
SUPPORTED_METHODS = {
    "get_status": (StatusParams, StatusResponse),
    "ping": (None, PingResult),  # No parameters
    "shutdown": (None, str),  # No parameters, simple string response
}
