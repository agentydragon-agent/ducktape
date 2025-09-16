from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

# Removed claude_code_sdk dependency - using provider-independent types


class AgentTaskType(str, Enum):
    """Type of agent being optimized."""

    CODING = "coding"
    CODE_REVIEW = "code_review"


class FileInfo(BaseModel):
    path: str
    content: str


class SeedTask(BaseModel):
    id: str
    prompt: str
    description: str | None = None
    docker_image: str | None = None
    allowed_tools: list[str] | None = None
    pre_task_commands: str | None = None


class Criterion(BaseModel):
    name: str
    description: str


class ScoreWithRationale(BaseModel):
    score: float
    rationale: str


# CodeResult removed - use GradedRollout instead


class Grade(BaseModel):
    task: str
    task_id: str
    agent_id: str  # Changed from int to match Rollout.agent_id
    axes: dict[str, ScoreWithRationale]
    timestamp: datetime

    @property
    def overall_score(self) -> float:
        return self.axes["overall"].score

    @property
    def overall_rationale(self) -> str:
        return self.axes["overall"].rationale

    @model_validator(mode="after")
    def _ensure_overall_axis(self):
        assert "overall" in self.axes
        return self

    @field_serializer("timestamp")
    def serialize_timestamp(self, timestamp: datetime) -> str:
        return timestamp.isoformat()


class GradedRollout(BaseModel):
    """A rollout that has been graded.

    This is the core unit of work in the optimizer - an agent's attempt
    at a task along with its evaluation.
    """

    rollout: Rollout
    grade: Grade
    task: TaskDefinition

    @property
    def overall_score(self) -> float:
        """Convenience accessor for overall score."""
        return self.grade.overall_score

    @property
    def task_id(self) -> str:
        """Convenience accessor for task ID."""
        return self.task.id


# ============================================================================
# New models for generalized system
# ============================================================================


# Setup configurations
class DockerConfig(BaseModel):
    """Docker container configuration."""

    image: str
    volumes: dict[str, str] = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)
    network_enabled: bool = True  # Allow network access for git clones, package installs, etc.


class GitCloneConfig(BaseModel):
    """Git repository clone configuration."""

    repo: str
    commit: str
    subdir: str | None = None

    @field_validator("commit")
    @classmethod
    def validate_commit_hash(cls, v: str) -> str:
        """Validate that commit is a full 40-character SHA hash."""
        if len(v) != 40:
            raise ValueError(
                f"Commit must be a full 40-character SHA hash, got {len(v)} characters: {v}",
            )
        if not all(c in "0123456789abcdefABCDEF" for c in v):
            raise ValueError(f"Commit must be a valid hex SHA hash: {v}")
        return v.lower()  # Normalize to lowercase


class SandboxConfig(BaseModel):
    """Sandbox configuration for secure task execution.

    Uses a "fail closed" approach - starts with no access and only adds what's explicitly needed.
    """

    enabled: bool = True
    # Paths to mount read-only (empty by default - fail closed)
    read_only_paths: list[str] = Field(default_factory=list)
    # Paths to mount read-write (only task workspace by default)
    read_write_paths: list[str] = Field(default_factory=list)
    # Network access (disabled by default - fail closed)
    allow_network: bool = False
    # Whether to bind system directories like /usr, /lib for tools
    bind_system: bool = True


class TaskSetup(BaseModel):
    """Task setup configuration with orthogonal concerns.

    - git_clone: What code to work with (optional)
    - docker/sandbox: How to isolate execution (mutually exclusive, both optional)
    """

    git_clone: GitCloneConfig | None = None
    docker: DockerConfig | None = None
    sandbox: SandboxConfig | None = None

    @model_validator(mode="after")
    def validate_isolation(self):
        """Validate that Docker and sandbox are mutually exclusive."""
        if self.docker and self.sandbox and self.sandbox.enabled:
            raise ValueError(
                "Docker and sandbox cannot both be configured - they are mutually exclusive isolation methods",
            )
        return self


# Grading configurations
class FileBasedGrading(BaseModel):
    """Grade based on files produced."""

    strategy: Literal["file_based"] = "file_based"
    criteria_file: str | None = None
    criteria: list[Criterion] | None = None

    @model_validator(mode="after")
    def validate_criteria_source(self):
        if not self.criteria_file and not self.criteria:
            raise ValueError("Must provide either criteria_file or criteria")
        return self


class ComparisonGrading(BaseModel):
    """Grade by comparing output to reference."""

    strategy: Literal["comparison"] = "comparison"
    reference: str
    criteria: list[dict[str, str]]


class MessageBasedGrading(BaseModel):
    """Grade based on final message output."""

    strategy: Literal["message_based"] = "message_based"
    criteria_file: str | None = None
    criteria: list[Criterion] | None = None

    @model_validator(mode="after")
    def validate_criteria_source(self):
        if not self.criteria_file and not self.criteria:
            raise ValueError("Must provide either criteria_file or criteria")
        return self


GradingConfig = FileBasedGrading | ComparisonGrading | MessageBasedGrading


# Task type definition
class TaskType(BaseModel):
    """Definition of a task type with its grading configuration."""

    name: str
    grading: GradingConfig | None  # Default grading for this task type


# Task definition (no runner!)
class TaskDefinition(BaseModel):
    """Task definition without runner specification."""

    id: str
    prompt: str
    type: str = "coding"  # Default to coding for backwards compatibility

    # Optional overrides - properly typed
    setup_overrides: TaskSetup | None = None
    grading_overrides: GradingConfig | None = None

    # Optional metadata
    description: str | None = None
    allowed_tools: list[str] | None = None
    pre_task_commands: str | None = None

    def resolve_config(
        self,
        task_types: dict[str, TaskType],
    ) -> tuple[TaskSetup | None, GradingConfig | None]:
        """Resolve final setup and grading config.

        Setup comes from task's setup_overrides only (no default).
        Grading uses task override if present, otherwise falls back to task type default.
        """
        if self.type not in task_types:
            raise ValueError(f"Unknown task type: {self.type}")

        base_type = task_types[self.type]

        # Setup is only from task (no default from type)
        setup = self.setup_overrides

        # Grading: use override if provided, otherwise use base type's default
        grading = self.grading_overrides or base_type.grading

        return setup, grading


# Common trajectory format with typed items
class AssistantMessage(BaseModel):
    """Assistant's text message."""

    type: Literal["assistant_message"] = "assistant_message"
    text: str
    # Store original provider format if needed
    original: Any | None = None


class ToolCall(BaseModel):
    """Tool invocation by the agent."""

    type: Literal["tool_call"] = "tool_call"
    tool_name: str
    arguments: dict[str, Any]
    original: Any | None = None


class ToolResult(BaseModel):
    """Result from a tool execution."""

    type: Literal["tool_result"] = "tool_result"
    tool_name: str
    result: Any
    error: str | None = None
    original: Any | None = None


class UserInput(BaseModel):
    """User input to the agent."""

    type: Literal["user_input"] = "user_input"
    text: str
    original: Any | None = None


class ErrorMessage(BaseModel):
    """Error during execution."""

    type: Literal["error"] = "error"
    message: str
    details: dict[str, Any] | None = None
    original: Any | None = None


class FinalOutput(BaseModel):
    """Final output from the agent."""

    type: Literal["final_output"] = "final_output"
    text: str
    original: Any | None = None


# Union type for all trajectory items
TrajectoryItem = AssistantMessage | ToolCall | ToolResult | UserInput | ErrorMessage | FinalOutput


@dataclass
class Rollout:
    """Common format for all agent rollouts."""

    task_id: str
    runner_id: str  # Which runner was used
    agent_id: str

    # Core content
    trajectory: list[TrajectoryItem]
    files: dict[str, str]  # filename -> content

    # Metadata
    success: bool
    error_message: str | None = None
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    metadata: dict = field(default_factory=dict)

    @property
    def final_output(self) -> str:
        """Extract final output from trajectory."""
        for item in reversed(self.trajectory):
            if isinstance(item, FinalOutput) or isinstance(item, AssistantMessage):
                return item.text
        return ""


@dataclass
class RunnerEnvironment:
    """Environment information from a runner."""

    type: str  # "docker_container", "workspace_dir", etc.
    data: dict[str, Any]  # Type-specific data

    @property
    def container_id(self) -> str | None:
        """Get Docker container ID if this is a container environment."""
        if self.type == "docker_container":
            return self.data.get("container_id")
        return None

    @property
    def workspace_path(self) -> str | None:
        """Get workspace path if this is a directory environment."""
        if self.type == "workspace_dir":
            return self.data.get("path")
        return None


@dataclass
class GradingContext:
    """Context provided to grading strategies."""

    rollout: Rollout
    task: TaskDefinition
    environment: RunnerEnvironment | None = None
