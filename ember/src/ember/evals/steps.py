from __future__ import annotations

from enum import Enum
from typing import Dict, Literal

from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


class ScenarioStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class SendMatrixMessageResult(BaseModel):
    type: Literal["send_matrix_message"] = "send_matrix_message"
    status: StepStatus = StepStatus.OK
    sent: str


class WaitSecondsResult(BaseModel):
    type: Literal["wait_seconds"] = "wait_seconds"
    status: StepStatus = StepStatus.OK
    requested: float
    actual: float


class WaitForMatrixResponseResult(BaseModel):
    type: Literal["wait_for_matrix_response"] = "wait_for_matrix_response"
    status: StepStatus = StepStatus.OK
    sender: str
    body: str


class ExpectMatrixReplyResult(BaseModel):
    type: Literal["expect_matrix_reply"] = "expect_matrix_reply"
    status: StepStatus = StepStatus.OK
    expected: str
    actual: str


class ValidateRegexResult(BaseModel):
    type: Literal["validate_regex"] = "validate_regex"
    status: StepStatus = StepStatus.OK
    pattern: str
    flags: str | None = None
    matched: bool = True
    timezone_tolerance_days: int | None = None


class ProbeHttpResult(BaseModel):
    type: Literal["probe_http"] = "probe_http"
    status: StepStatus = StepStatus.OK
    port: int
    path: str
    http_status: int
    body_excerpt: str | None = None


class SnapshotWorkspaceResult(BaseModel):
    type: Literal["snapshot_workspace"] = "snapshot_workspace"
    status: StepStatus = StepStatus.OK
    artifact: str


class VerifyFileContentsResult(BaseModel):
    type: Literal["verify_file_contents"] = "verify_file_contents"
    status: StepStatus = StepStatus.OK
    path: str


class VerifyFileContainsResult(BaseModel):
    type: Literal["verify_file_contains"] = "verify_file_contains"
    status: StepStatus = StepStatus.OK
    path: str
    includes: list[str]
    min_size_bytes: int | None = None


class VerifyFileTimestampsResult(BaseModel):
    type: Literal["verify_file_timestamps"] = "verify_file_timestamps"
    status: StepStatus = StepStatus.OK
    path: str
    count: int
    order: Literal["ascending", "descending"]


class KillProcessResult(BaseModel):
    type: Literal["kill_process"] = "kill_process"
    status: StepStatus = StepStatus.OK
    container: str
    pattern: str


class EvalResult(BaseModel):
    type: Literal["eval"] = "eval"
    status: StepStatus = StepStatus.OK
    description: str | None = None
    details: Dict[str, object] = Field(default_factory=dict)


class StepSkippedResult(BaseModel):
    type: Literal["step_skipped"] = "step_skipped"
    status: StepStatus = StepStatus.SKIPPED
    step_type: str
    reason: str


class StepErrorResult(BaseModel):
    type: Literal["step_error"] = "step_error"
    status: StepStatus = StepStatus.FAILED
    step_type: str
    error: str


StepResult = (
    SendMatrixMessageResult
    | WaitSecondsResult
    | WaitForMatrixResponseResult
    | ExpectMatrixReplyResult
    | ValidateRegexResult
    | ProbeHttpResult
    | SnapshotWorkspaceResult
    | VerifyFileContentsResult
    | VerifyFileContainsResult
    | VerifyFileTimestampsResult
    | KillProcessResult
    | EvalResult
    | StepSkippedResult
    | StepErrorResult
)


class ScenarioResult(BaseModel):
    id: str
    description: str | None = None
    status: ScenarioStatus
    steps: list[StepResult]
    error: str | None = None


class ScenarioSuiteResult(BaseModel):
    scenarios: list[ScenarioResult] = Field(default_factory=list)
