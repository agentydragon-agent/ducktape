"""JSON-RPC 2.0 protocol for GitStatusd daemon communication.

Uses standard JSON-RPC 2.0 for type-safe, standardized RPC communication
between clients and the GitStatusd multiplexing daemon.
"""

import json
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, NewType, Union

from pydantic import BaseModel, Field

from .github_models import PRInfo
from .models import CommitInfo

# WorktreeID: Deliberately scrambled identifier to prevent accidental misuse
WorktreeID = NewType('WorktreeID', str)  # Format: 'wtid:<dirname>'


# make_worktree_id moved to server-only module to prevent client access


def parse_worktree_id(wtid: WorktreeID) -> str:
    """Extract directory name from worktree ID."""
    if not wtid.startswith("wtid:"):
        raise ValueError(f"Invalid worktree ID format: {wtid}")
    return wtid[5:]  # Remove 'wtid:' prefix


class DaemonHealthStatus(str, Enum):
    """Daemon health status levels."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


class DaemonHealth(BaseModel):
    """Daemon health information."""

    status: DaemonHealthStatus
    last_error: str | None = None
    last_error_time: datetime | None = None
    github_errors: int = 0
    gitstatusd_errors: int = 0


class Request(BaseModel):
    """JSON-RPC 2.0 request."""

    model_config = {"extra": "forbid"}

    jsonrpc: str = "2.0"
    method: str = Field(..., description="Method name to call")
    params: dict[str, Any] = Field(default_factory=dict, description="Method parameters")
    id: uuid.UUID = Field(..., description="Request ID")


class Response(BaseModel):
    """JSON-RPC 2.0 successful response."""

    model_config = {"extra": "forbid"}

    jsonrpc: str = "2.0"
    result: Union[
        "StatusResponse", 
        "PingResult", 
        "WorktreeCreateResult",
        "WorktreeDeleteResult", 
        "WorktreeListResult",
        "WorktreeIdentifyResult",
        "WorktreeGetByNameResult",
        "WorktreeResolvePathResult",
        "WorktreeTeleportTargetResult",
        str,
    ] = Field(..., description="Result data")
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

    worktree_ids: list[WorktreeID] = Field(
        default_factory=list,
        description="List of worktree IDs. If empty, returns all discovered worktrees.",
    )


class WorktreeCreateParams(BaseModel):
    """Parameters for worktree creation."""

    model_config = {"extra": "forbid"}

    name: str = Field(..., description="Simple worktree name (no slashes)")
    source_branch: str | None = Field(None, description="Source branch for copying")


class WorktreeDeleteParams(BaseModel):
    """Parameters for worktree deletion."""

    model_config = {"extra": "forbid"}

    wtid: WorktreeID = Field(..., description="Worktree identifier to delete")
    force: bool = Field(default=False, description="Force deletion")


class WorktreeIdentifyParams(BaseModel):
    """Parameters for worktree identification."""

    model_config = {"extra": "forbid"}

    absolute_path: str = Field(..., description="Absolute filesystem path")


class WorktreeGetByNameParams(BaseModel):
    """Parameters for worktree lookup by name."""

    model_config = {"extra": "forbid"}

    name: str = Field(..., description="Worktree name to look up")


class WorktreeResolvePathParams(BaseModel):
    """Parameters for path resolution within worktrees."""

    model_config = {"extra": "forbid"}

    worktree_name: str | None = Field(default=None, description="Target worktree name, or None for current")
    path_spec: str = Field(..., description="Path to resolve (/, ./, or unprefixed)")
    current_path: str = Field(..., description="Current working directory for relative resolution")


class WorktreeTeleportTargetParams(BaseModel):
    """Parameters for computing cd target with path preservation."""

    model_config = {"extra": "forbid"}

    target_name: str = Field(..., description="Target worktree name")
    current_path: str = Field(..., description="Current working directory")


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

    wtid: WorktreeID = Field(..., description="Worktree identifier")
    name: str = Field(..., description="Human-readable name")
    absolute_path: str = Field(..., description="Absolute filesystem path")
    branch_name: str = Field(..., description="Git branch name")
    has_dirty_files: bool = Field(..., description="Whether there are modified files")
    has_untracked_files: bool = Field(..., description="Whether there are untracked files")
    processing_time_ms: float = Field(..., description="Processing time in milliseconds")
    last_updated_at: datetime = Field(
        ..., description="When gitstatusd was last queried for this worktree",
    )
    is_cached: bool = Field(default=False, description="Whether this result came from cache")
    # Commit and branch info
    commit_info: CommitInfo = Field(..., description="Latest commit information")
    ahead_count: int = Field(default=0, description="Number of commits ahead of upstream branch")
    behind_count: int = Field(default=0, description="Number of commits behind upstream branch")
    is_main: bool = Field(default=False, description="Whether this is the main repository")
    upstream_branch: str = Field(..., description="Upstream branch name for ahead/behind calculations")
    # GitHub PR info
    pr_info: PRInfo | None = Field(
        default=None, description="GitHub pull request information if available",
    )


class StatusResponse(BaseModel):
    """Unified response for get_status method (always returns results for multiple worktrees)."""

    results: dict[WorktreeID, StatusResult] = Field(
        ..., description="Map of worktree ID to status results",
    )
    total_processing_time_ms: float = Field(
        ..., description="Total processing time in milliseconds",
    )
    individual_processing_times_ms: dict[WorktreeID, float] = Field(
        default_factory=dict, description="Detailed processing time per worktree",
    )
    discovery_time_ms: float = Field(default=0.0, description="Time spent on worktree discovery")
    concurrent_requests: int = Field(
        default=1, description="Number of requests processed concurrently",
    )
    daemon_health: DaemonHealth = Field(
        ..., description="Current daemon health status and error information",
    )


class PingResult(BaseModel):
    """Result for ping method."""

    message: str = "pong"
    daemon_pid: int = Field(..., description="Process ID of the daemon")
    started_at: datetime = Field(..., description="When the daemon was started")
    discovered_worktrees: list[Path] = Field(
        default_factory=list, description="List of discovered worktree paths",
    )


class WorktreeInfo(BaseModel):
    """Information about a worktree."""

    wtid: WorktreeID = Field(..., description="Worktree identifier")
    name: str = Field(..., description="Human-readable name")
    absolute_path: str = Field(..., description="Absolute filesystem path")
    branch_name: str = Field(..., description="Git branch name")
    exists: bool = Field(..., description="Whether directory exists")
    is_main: bool = Field(..., description="Whether this is main repo")


class WorktreeCreateResult(BaseModel):
    """Result for worktree creation."""

    wtid: WorktreeID = Field(..., description="Created worktree ID")
    name: str = Field(..., description="Human-readable name")
    absolute_path: str = Field(..., description="Absolute filesystem path")
    branch_name: str = Field(..., description="Git branch name")
    success: bool = Field(..., description="Operation success")


class WorktreeDeleteResult(BaseModel):
    """Result for worktree deletion."""

    wtid: WorktreeID = Field(..., description="Deleted worktree ID")
    success: bool = Field(..., description="Deletion success")
    message: str = Field(..., description="Operation message")


class WorktreeListResult(BaseModel):
    """Result for worktree listing."""

    worktrees: list[WorktreeInfo] = Field(..., description="List of worktrees")


class WorktreeIdentifyResult(BaseModel):
    """Result for worktree identification."""

    wtid: WorktreeID | None = Field(..., description="Worktree ID if identified")
    name: str | None = Field(..., description="Human-readable name if identified")
    is_worktree: bool = Field(..., description="Whether path is a managed worktree")
    relative_path: str | None = Field(..., description="Relative path within worktree if identified")


class WorktreeGetByNameResult(BaseModel):
    """Result for worktree lookup by name."""

    wtid: WorktreeID | None = Field(..., description="Worktree ID if found")
    name: str | None = Field(..., description="Human-readable name if found")
    exists: bool = Field(..., description="Whether worktree exists")
    absolute_path: str | None = Field(..., description="Absolute path if found")


class WorktreeResolvePathResult(BaseModel):
    """Result for path resolution within worktrees."""

    absolute_path: str = Field(..., description="Resolved absolute filesystem path")


class WorktreeTeleportTargetResult(BaseModel):
    """Result for teleport target computation."""

    cd_path: str = Field(..., description="Path to cd to (preserves relative position if possible)")


class ProgressUpdate(BaseModel):
    """Progress update for streaming operations."""

    operation: str = Field(..., description="Operation name")
    step: str = Field(..., description="Current step")
    progress: float = Field(..., description="Progress 0.0-1.0")
    message: str = Field(..., description="Progress message")


def create_error_response(
    code: int, message: str, request_id: uuid.UUID | None = None, data: Any = None,
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
    # Existing methods
    "get_status": (StatusParams, StatusResponse),
    "ping": (None, PingResult),  # No parameters
    "shutdown": (None, str),  # No parameters, simple string response
    
    # New worktree operations
    "worktree_create": (WorktreeCreateParams, WorktreeCreateResult),
    "worktree_delete": (WorktreeDeleteParams, WorktreeDeleteResult),
    "worktree_list": (None, WorktreeListResult),  # No parameters
    "worktree_identify": (WorktreeIdentifyParams, WorktreeIdentifyResult),
    "worktree_get_by_name": (WorktreeGetByNameParams, WorktreeGetByNameResult),
    "worktree_resolve_path": (WorktreeResolvePathParams, WorktreeResolvePathResult),
    "worktree_teleport_target": (WorktreeTeleportTargetParams, WorktreeTeleportTargetResult),
}


