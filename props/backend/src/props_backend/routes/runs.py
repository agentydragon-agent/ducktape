"""Runs API routes for triggering and monitoring agent runs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import json
import logging
import random
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from mcp.types import EmbeddedResource, ImageContent, TextContent
from props_core.agent_registry import AgentRegistry
from props_core.agent_types import AgentType, TypeConfig
from props_core.db.examples import Example
from props_core.db.models import (
    AgentRun,
    AgentRunStatus,
    Event,
    ExpectedRecallScope,
    FileSetMember,
    GradingEdge,
    Snapshot,
    TruePositive,
    TruePositiveOccurrenceORM,
)
from props_core.db.session import get_session
from props_core.ids import DefinitionId
from props_core.models.examples import ExampleKind, ExampleSpec
from props_core.splits import Split
from pydantic import BaseModel, Field, ValidationError

from agent_core.events import ApiRequest, AssistantText, EventType, Response, ToolCall, ToolCallOutput, UserText
from mcp_infra.exec.models import BaseExecResult, ExecInput
from openai_utils.client_factory import build_client
from openai_utils.model import ReasoningItem

router = APIRouter()
logger = logging.getLogger(__name__)


# --- Enums ---


class JobStatus(StrEnum):
    """Validation job status."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# --- Models ---


class ActiveRunInfo(BaseModel):
    agent_run_id: UUID
    definition_id: DefinitionId
    model: str
    status: AgentRunStatus
    created_at: datetime


class ActiveRunsResponse(BaseModel):
    runs: list[ActiveRunInfo]


class ValidationRunRequest(BaseModel):
    definition_id: DefinitionId
    example_kind: ExampleKind
    split: Split = Split.VALID
    n_samples: int = Field(ge=1, le=50, default=5)
    critic_model: str = "gpt-5.1-codex-mini"
    grader_model: str = "gpt-5.1-codex-mini"


class ValidationRunResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    n_examples_sampled: int
    message: str


class JobInfo(BaseModel):
    """Information about a validation job."""

    job_id: UUID
    definition_id: DefinitionId
    example_kind: ExampleKind
    n_samples: int
    status: JobStatus
    completed: int
    failed: int


class JobsResponse(BaseModel):
    """Response for jobs endpoint."""

    jobs: list[JobInfo]


class ChildRunInfo(BaseModel):
    """Brief info about a child agent run."""

    agent_run_id: UUID
    agent_type: AgentType
    status: AgentRunStatus


class GraderRunInfo(BaseModel):
    """Brief info about a grader run that graded this critic."""

    agent_run_id: UUID
    status: AgentRunStatus


class TpTarget(BaseModel):
    """TP match target."""

    kind: Literal["tp"] = "tp"
    tp_id: str
    occurrence_id: str
    credit: float  # Credit awarded for this match


class FpTarget(BaseModel):
    """FP match target."""

    kind: Literal["fp"] = "fp"
    fp_id: str
    occurrence_id: str


class NoMatchTarget(BaseModel):
    """No match (unknown)."""

    kind: Literal["none"] = "none"


GradingTarget = Annotated[TpTarget | FpTarget | NoMatchTarget, Field(discriminator="kind")]


class GradingEdgeInfo(BaseModel):
    """Individual grading edge for API response."""

    critique_issue_id: str
    target: GradingTarget
    rationale: str


class GradingSummary(BaseModel):
    """Summary of grading results for a critic run (aggregate stats only)."""

    tp_count: int
    fp_count: int
    unknown_count: int
    total_credit: float
    n_recall_denominator: int  # Frontend computes recall: total_credit / n_catchable


class MissedOccurrenceInfo(BaseModel):
    """A catchable TP occurrence that was not found by the critic."""

    tp_id: str
    occurrence_id: str
    tp_rationale: str  # from true_positives.rationale
    occ_note: str | None  # from true_positive_occurrences.note


class AgentRunDetail(BaseModel):
    """Detailed view of an agent run."""

    agent_run_id: UUID
    definition_id: DefinitionId
    parent_agent_run_id: UUID | None
    model: str
    status: AgentRunStatus
    completion_summary: str | None
    created_at: datetime
    updated_at: datetime
    type_config: TypeConfig
    event_count: int
    resolved_files: list[str] | None = None  # For critic runs with file_set examples
    child_runs: list[ChildRunInfo] = []  # Child runs spawned by this run
    grader_runs: list[GraderRunInfo] = []  # For critic runs: grader runs that graded this critic
    grading_summary: GradingSummary | None = None  # For critic runs: grading results
    grading_edges: list[GradingEdgeInfo] = []  # For grader runs: their output edges
    missed_occurrences: list[MissedOccurrenceInfo] = []  # For critic runs: catchable TPs not found


# --- Parsed Event Types for API ---


class DockerExecCallPayload(BaseModel):
    """Parsed docker_exec tool call."""

    type: Literal["docker_exec_call"] = "docker_exec_call"
    call_id: str
    input: ExecInput


class DockerExecOutputPayload(BaseModel):
    """Parsed docker_exec tool output."""

    type: Literal["docker_exec_output"] = "docker_exec_output"
    call_id: str
    result: BaseExecResult


class GenericToolCallPayload(BaseModel):
    """Unparsed tool call (fallback)."""

    type: Literal["tool_call"] = "tool_call"
    name: str
    call_id: str
    args_json: str | None


class GenericToolOutputPayload(BaseModel):
    """Unparsed tool output (fallback)."""

    type: Literal["tool_output"] = "tool_output"
    call_id: str
    content: list[Any]


# Union of all parsed payload types
# Uses original types where possible, custom wrappers only for docker_exec (structured result parsing)
ParsedEventPayload = Annotated[
    DockerExecCallPayload
    | DockerExecOutputPayload
    | GenericToolCallPayload
    | GenericToolOutputPayload
    | UserText
    | AssistantText
    | ApiRequest
    | Response
    | ReasoningItem,
    Field(discriminator="type"),
]


class ParsedEventInfo(BaseModel):
    """Event with parsed payload for API response."""

    id: int
    sequence_num: int
    timestamp: datetime
    payload: ParsedEventPayload


class EventsResponse(BaseModel):
    """Response for events endpoint."""

    agent_run_id: UUID
    events: list[ParsedEventInfo]
    total_count: int


class RunInfo(BaseModel):
    """Run information for list view."""

    agent_run_id: UUID
    definition_id: DefinitionId
    type_config: TypeConfig
    model: str
    status: AgentRunStatus
    created_at: datetime
    updated_at: datetime
    # Split is only present for critic runs (derived from snapshot)
    split: Split | None = None


class RunsListResponse(BaseModel):
    """Response for paginated runs list."""

    runs: list[RunInfo]
    total_count: int
    offset: int
    limit: int


# --- WebSocket Message Types (Discriminated Union) ---


class WsEventMessage(BaseModel):
    """WebSocket message containing an event."""

    type: Literal["event"] = "event"
    data: ParsedEventInfo


class WsStatusData(BaseModel):
    """Status data in WebSocket message."""

    status: AgentRunStatus
    completion_summary: str | None


class WsStatusMessage(BaseModel):
    """WebSocket message containing run status."""

    type: Literal["status"] = "status"
    data: WsStatusData


class WsCompleteMessage(BaseModel):
    """WebSocket message indicating stream is complete."""

    type: Literal["complete"] = "complete"


# Discriminated union of all WebSocket message types
WsMessage = Annotated[WsEventMessage | WsStatusMessage | WsCompleteMessage, Field(discriminator="type")]


# --- Job Tracking ---


@dataclass
class ValidationJob:
    """Tracks a validation batch job."""

    job_id: UUID
    definition_id: DefinitionId
    example_kind: ExampleKind
    n_samples: int
    critic_model: str
    grader_model: str
    status: JobStatus = JobStatus.RUNNING
    completed: int = 0
    failed: int = 0
    task: asyncio.Task | None = None
    examples: list[ExampleSpec] = field(default_factory=list)


# In-memory job tracking (jobs are transient, not persisted)
_jobs: dict[UUID, ValidationJob] = {}


# --- Helpers ---


def get_registry(request: Request) -> AgentRegistry:
    """Get registry from app state."""
    return request.app.state.registry


def _extract_text_from_mcp_content(content: list) -> str | None:
    """Extract text from MCP CallToolResult content array."""
    for item in content:
        if isinstance(item, TextContent):
            return item.text
        if isinstance(item, dict) and "text" in item:
            return item["text"]
    return None


def parse_event_payload(payload: EventType) -> ParsedEventPayload:
    """Convert internal EventType to API ParsedEventPayload."""
    try:
        if isinstance(payload, ToolCall):
            if payload.name == "docker_exec" and payload.args_json:
                try:
                    input_data = json.loads(payload.args_json)
                    return DockerExecCallPayload(call_id=payload.call_id, input=ExecInput.model_validate(input_data))
                except (json.JSONDecodeError, ValidationError):
                    pass
            return GenericToolCallPayload(name=payload.name, call_id=payload.call_id, args_json=payload.args_json)

        if isinstance(payload, ToolCallOutput):
            result_text = _extract_text_from_mcp_content(payload.result.content)
            if result_text:
                try:
                    result_data = json.loads(result_text)
                    return DockerExecOutputPayload(
                        call_id=payload.call_id, result=BaseExecResult.model_validate(result_data)
                    )
                except (json.JSONDecodeError, ValidationError):
                    pass
            return GenericToolOutputPayload(
                call_id=payload.call_id,
                content=[
                    c.model_dump() if isinstance(c, TextContent | ImageContent | EmbeddedResource) else c
                    for c in payload.result.content
                ],
            )

        # Pass through types that already have correct structure
        if isinstance(payload, UserText | AssistantText | ApiRequest | Response | ReasoningItem):
            return payload

        # Fallback - should not happen if all types covered
        raise ValueError(f"Unknown event payload type: {type(payload)}, payload={payload}")
    except Exception as e:
        logger.exception(f"Failed to parse event payload: {type(payload)}, error: {e}")
        raise


# --- Helper functions ---


def make_grading_target(d: GradingEdge) -> GradingTarget:
    """Convert a GradingEdge to a GradingTarget union type."""
    if d.tp_id is not None:
        return TpTarget(tp_id=d.tp_id, occurrence_id=d.tp_occurrence_id or "", credit=d.credit)
    if d.fp_id is not None:
        return FpTarget(fp_id=d.fp_id, occurrence_id=d.fp_occurrence_id or "")
    return NoMatchTarget()


def edges_to_info(edges: list[GradingEdge]) -> list[GradingEdgeInfo]:
    """Convert GradingEdge ORM objects to API info objects."""
    return [
        GradingEdgeInfo(critique_issue_id=d.critique_issue_id, target=make_grading_target(d), rationale=d.rationale)
        for d in edges
    ]


# --- Endpoints ---


@router.get("/active")
def list_active_runs(request: Request) -> ActiveRunsResponse:
    """List all active agent runs.

    Returns runs from both:
    - In-memory registry (currently executing)
    - Database (IN_PROGRESS status, for runs that may have started before we connected)
    """
    registry = get_registry(request)

    # Get in-memory active runs
    memory_runs = registry.list_active()
    memory_ids = {r.agent_run_id for r in memory_runs}

    # Combine: prefer memory runs (have more info), add DB runs not in memory
    result = [
        ActiveRunInfo(
            agent_run_id=r.agent_run_id,
            definition_id=r.definition_id,
            model=r.model,
            status=r.status,
            created_at=r.created_at,
        )
        for r in memory_runs
    ]

    # Also query database for IN_PROGRESS runs not in memory
    # (handles race conditions and runs started before server restart)
    with get_session() as session:
        db_runs = (
            session.query(AgentRun)
            .filter(AgentRun.status == AgentRunStatus.IN_PROGRESS)
            .order_by(AgentRun.created_at.desc())
            .all()
        )

        for db_run in db_runs:
            if db_run.agent_run_id not in memory_ids:
                result.append(
                    ActiveRunInfo(
                        agent_run_id=db_run.agent_run_id,
                        definition_id=db_run.agent_definition_id,
                        model=db_run.model,
                        status=db_run.status,
                        created_at=db_run.created_at,
                    )
                )

    return ActiveRunsResponse(runs=result)


@router.get("/jobs")
def list_jobs() -> JobsResponse:
    """List all validation jobs."""
    # JobInfo is a subset of ValidationJob fields - use model_validate for clarity
    return JobsResponse(jobs=[JobInfo.model_validate(job, from_attributes=True) for job in _jobs.values()])


@router.get("")
def list_runs(
    status: AgentRunStatus | None = None,
    definition_id: DefinitionId | None = None,
    agent_type: AgentType | None = None,
    split: Split | None = None,
    example_kind: ExampleKind | None = None,
    offset: int = 0,
    limit: int = 100,
) -> RunsListResponse:
    """List all agent runs with optional filters and pagination.

    Query parameters:
    - status: Filter by run status
    - definition_id: Filter by definition ID
    - agent_type: Filter by agent type (critic, grader, etc.)
    - split: Filter by data split (train, valid, test)
    - example_kind: Filter by example kind (whole_snapshot, file_set)
    - offset: Pagination offset (default: 0)
    - limit: Pagination limit (default: 100, max: 500)
    """
    limit = min(limit, 500)  # Cap at 500

    with get_session() as session:
        query = session.query(AgentRun)

        if status:
            query = query.filter(AgentRun.status == status)
        if definition_id:
            query = query.filter(AgentRun.agent_definition_id == definition_id)
        if agent_type:
            # agent_type is stored in JSONB type_config
            query = query.filter(AgentRun.type_config["agent_type"].astext == agent_type)
        if example_kind:
            # example_kind is at type_config->'example'->>'kind'
            query = query.filter(AgentRun.type_config["example"]["kind"].astext == example_kind)

        # Join with snapshots to get split for critic runs
        # For critic runs, snapshot_slug is at type_config->'example'->>'snapshot_slug'
        query = query.outerjoin(Snapshot, AgentRun.type_config["example"]["snapshot_slug"].astext == Snapshot.slug)

        if split:
            query = query.filter(Snapshot.split == split)

        total_count = query.count()

        runs_with_split = (
            query.add_columns(Snapshot.split).order_by(AgentRun.created_at.desc()).offset(offset).limit(limit).all()
        )

        return RunsListResponse(
            runs=[
                RunInfo(
                    agent_run_id=r.agent_run_id,
                    definition_id=r.agent_definition_id,
                    type_config=r.type_config,
                    model=r.model,
                    status=r.status,
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                    split=split,
                )
                for r, split in runs_with_split
            ],
            total_count=total_count,
            offset=offset,
            limit=limit,
        )


@router.post("/validation")
async def trigger_validation_runs(request: Request, body: ValidationRunRequest) -> ValidationRunResponse:
    """Trigger validation runs: sample N examples, run 1 critic->grader per example.

    Runs are started in the background in parallel. Poll /api/runs/jobs for status.
    Registry semaphore limits actual concurrency.
    """
    registry = get_registry(request)

    # Get examples of the requested kind and split
    with get_session() as session:
        examples = (
            session.query(Example)
            .join(Snapshot, Snapshot.slug == Example.snapshot_slug)
            .filter(Snapshot.split == body.split)
            .filter(Example.example_kind == body.example_kind)
            .order_by(Example.snapshot_slug)
            .all()
        )

        if not examples:
            raise HTTPException(status_code=404, detail=f"No {body.split} examples of kind {body.example_kind}")

        # Sample N examples
        n_to_sample = min(body.n_samples, len(examples))
        sampled = random.sample(examples, n_to_sample)
        example_specs = [e.to_example_spec() for e in sampled]

    # Create job
    job_id = uuid4()
    job = ValidationJob(
        job_id=job_id,
        definition_id=body.definition_id,
        example_kind=body.example_kind,
        n_samples=n_to_sample,
        critic_model=body.critic_model,
        grader_model=body.grader_model,
        examples=example_specs,
    )
    _jobs[job_id] = job

    # Spawn background task with parallel execution
    job.task = asyncio.create_task(_run_validation_batch(job=job, registry=registry))

    slugs = [e.snapshot_slug for e in example_specs[:3]]
    message = f"Started {n_to_sample} validation runs. Snapshots: {slugs}{'...' if n_to_sample > 3 else ''}"

    return ValidationRunResponse(
        job_id=job_id, status=JobStatus.RUNNING, n_examples_sampled=n_to_sample, message=message
    )


async def _run_validation_batch(job: ValidationJob, registry: AgentRegistry) -> None:
    """Run critic->grader for each example in the job, in parallel.

    Registry semaphore limits actual concurrency.
    """
    try:
        critic_client = build_client(job.critic_model)
        grader_client = build_client(job.grader_model)

        async def run_one(example: ExampleSpec) -> bool:
            """Run critic + grader for one example. Returns True on success."""
            try:
                logger.info(f"[Job {job.job_id}] Running critic on {example.snapshot_slug}")
                critic_run_id = await registry.run_critic(
                    definition_id=job.definition_id, example=example, client=critic_client, max_turns=100
                )

                # Check critic status
                with get_session() as session:
                    critic_run = session.get(AgentRun, critic_run_id)
                    if critic_run is None or critic_run.status != AgentRunStatus.COMPLETED:
                        status = critic_run.status if critic_run else "not found"
                        logger.warning(f"[Job {job.job_id}] Critic failed with status {status}")
                        return False

                # Run grader
                logger.info(f"[Job {job.job_id}] Running grader on critic {critic_run_id}")
                await registry.run_grader(critic_run_id=critic_run_id, client=grader_client, max_turns=200)
                return True

            except Exception:
                logger.exception(f"[Job {job.job_id}] Error processing {example.snapshot_slug}")
                return False

        # Run all examples in parallel; registry semaphore limits concurrency
        results = await asyncio.gather(*[run_one(e) for e in job.examples], return_exceptions=True)

        # Count successes and failures
        for result in results:
            if result is True:
                job.completed += 1
            else:
                job.failed += 1

        job.status = JobStatus.COMPLETED
        logger.info(f"[Job {job.job_id}] Finished: {job.completed} completed, {job.failed} failed")

    except Exception:
        logger.exception(f"[Job {job.job_id}] Batch failed")
        job.status = JobStatus.FAILED


# --- Run Detail Endpoints ---


@router.get("/run/{run_id}")
def get_run(run_id: UUID) -> AgentRunDetail:
    """Get details of a specific agent run."""
    with get_session() as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Agent run {run_id} not found")

        # Count events
        event_count = session.query(Event).filter(Event.agent_run_id == run_id).count()

        # Get child runs
        child_run_rows = (
            session.query(AgentRun).filter(AgentRun.parent_agent_run_id == run_id).order_by(AgentRun.created_at).all()
        )
        child_runs = [
            ChildRunInfo(agent_run_id=child.agent_run_id, agent_type=child.type_config.agent_type, status=child.status)
            for child in child_run_rows
        ]

        # Resolve files for critic runs with file_set examples
        resolved_files: list[str] | None = None
        grading_summary: GradingSummary | None = None
        grader_runs: list[GraderRunInfo] = []
        grading_edges: list[GradingEdgeInfo] = []
        missed_occurrences: list[MissedOccurrenceInfo] = []

        if run.type_config.agent_type == AgentType.CRITIC:
            example = run.type_config.example
            if example.kind == ExampleKind.FILE_SET:
                members = (
                    session.query(FileSetMember.file_path)
                    .filter(
                        FileSetMember.snapshot_slug == example.snapshot_slug,
                        FileSetMember.files_hash == example.files_hash,
                    )
                    .order_by(FileSetMember.file_path)
                    .all()
                )
                resolved_files = [m.file_path for m in members]

            # Find grader runs that graded this critic (linked via type_config.graded_agent_run_id)
            # Use JSONB query since type_config is polymorphic
            grader_rows = (
                session.query(AgentRun)
                .filter(AgentRun.type_config["graded_agent_run_id"].astext == str(run_id))
                .order_by(AgentRun.created_at)
                .all()
            )
            grader_runs = [
                GraderRunInfo(agent_run_id=grader.agent_run_id, status=grader.status) for grader in grader_rows
            ]
            grader_run_ids = [g.agent_run_id for g in grader_rows]
            if grader_run_ids:
                # Aggregate grading edges from all grader runs for this critic
                edges = session.query(GradingEdge).filter(GradingEdge.grader_run_id.in_(grader_run_ids)).all()
                tp_count = sum(1 for d in edges if d.tp_id is not None)
                fp_count = sum(1 for d in edges if d.fp_id is not None)
                unknown_count = 0  # No "unknown" type in edges model - all edges are TP or FP
                total_credit = sum(d.credit for d in edges if d.tp_id is not None)

                # Get n_recall_denominator from example for recall calculation
                example_row = (
                    session.query(Example)
                    .filter(
                        Example.snapshot_slug == example.snapshot_slug,
                        Example.example_kind == example.kind,
                        Example.files_hash == (example.files_hash if example.kind == ExampleKind.FILE_SET else None),
                    )
                    .first()
                )
                n_catchable = example_row.n_recall_denominator if example_row else None

                grading_summary = GradingSummary(
                    tp_count=tp_count,
                    fp_count=fp_count,
                    unknown_count=unknown_count,
                    total_credit=total_credit,
                    n_recall_denominator=n_catchable or 0,
                )
                grading_edges = edges_to_info(edges)

                # Find missed occurrences: catchable TPs not matched in grading_edges
                matched_occ_keys = {(d.tp_id, d.tp_occurrence_id) for d in edges if d.tp_id is not None}

                # Query catchable occurrences based on example type
                if example.kind == ExampleKind.FILE_SET:
                    # For file_set: join through expected_recall_scopes
                    catchable_occs = (
                        session.query(TruePositiveOccurrenceORM, TruePositive.rationale)
                        .join(
                            ExpectedRecallScope,
                            (TruePositiveOccurrenceORM.snapshot_slug == ExpectedRecallScope.snapshot_slug)
                            & (TruePositiveOccurrenceORM.tp_id == ExpectedRecallScope.tp_id)
                            & (TruePositiveOccurrenceORM.occurrence_id == ExpectedRecallScope.occurrence_id),
                        )
                        .join(
                            TruePositive,
                            (TruePositiveOccurrenceORM.snapshot_slug == TruePositive.snapshot_slug)
                            & (TruePositiveOccurrenceORM.tp_id == TruePositive.tp_id),
                        )
                        .filter(
                            ExpectedRecallScope.snapshot_slug == example.snapshot_slug,
                            ExpectedRecallScope.files_hash == example.files_hash,
                        )
                        .all()
                    )
                else:
                    # For whole_snapshot: all occurrences in snapshot are catchable
                    catchable_occs = (
                        session.query(TruePositiveOccurrenceORM, TruePositive.rationale)
                        .join(
                            TruePositive,
                            (TruePositiveOccurrenceORM.snapshot_slug == TruePositive.snapshot_slug)
                            & (TruePositiveOccurrenceORM.tp_id == TruePositive.tp_id),
                        )
                        .filter(TruePositiveOccurrenceORM.snapshot_slug == example.snapshot_slug)
                        .all()
                    )

                for occ, tp_rationale in catchable_occs:
                    if (occ.tp_id, occ.occurrence_id) not in matched_occ_keys:
                        missed_occurrences.append(
                            MissedOccurrenceInfo(
                                tp_id=occ.tp_id,
                                occurrence_id=occ.occurrence_id,
                                tp_rationale=tp_rationale,
                                occ_note=occ.note,
                            )
                        )

        elif run.type_config.agent_type == AgentType.GRADER:
            # For grader runs, get their own edges
            edges = session.query(GradingEdge).filter(GradingEdge.grader_run_id == run_id).all()
            grading_edges = edges_to_info(edges)

        return AgentRunDetail(
            agent_run_id=run.agent_run_id,
            definition_id=run.agent_definition_id,
            parent_agent_run_id=run.parent_agent_run_id,
            model=run.model,
            status=run.status,
            completion_summary=run.completion_summary,
            created_at=run.created_at,
            updated_at=run.updated_at,
            type_config=run.type_config,
            event_count=event_count,
            resolved_files=resolved_files,
            child_runs=child_runs,
            grader_runs=grader_runs,
            grading_summary=grading_summary,
            grading_edges=grading_edges,
            missed_occurrences=missed_occurrences,
        )


@router.get("/run/{run_id}/events")
def get_run_events(run_id: UUID, offset: int = 0, limit: int = 100) -> EventsResponse:
    """Get events for a specific agent run.

    Supports pagination via offset/limit. Events are ordered by sequence_num.
    """
    with get_session() as session:
        # Verify run exists
        run = session.get(AgentRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Agent run {run_id} not found")

        # Get total count
        total_count = session.query(Event).filter(Event.agent_run_id == run_id).count()

        # Get paginated events
        events = (
            session.query(Event)
            .filter(Event.agent_run_id == run_id)
            .order_by(Event.sequence_num)
            .offset(offset)
            .limit(limit)
            .all()
        )

        return EventsResponse(
            agent_run_id=run_id,
            events=[
                ParsedEventInfo(
                    id=e.id, sequence_num=e.sequence_num, timestamp=e.timestamp, payload=parse_event_payload(e.payload)
                )
                for e in events
            ],
            total_count=total_count,
        )


# --- WebSocket for Live Event Streaming ---

# Track active WebSocket connections per run
_ws_connections: dict[UUID, set[WebSocket]] = {}


@router.websocket("/run/{run_id}/stream")
async def stream_run_events(websocket: WebSocket, run_id: UUID) -> None:
    """WebSocket endpoint for live event streaming.

    Clients connect to receive real-time events as they are written to the database.
    Initial connection sends all existing events, then streams new ones.
    """
    await websocket.accept()

    # Verify run exists
    with get_session() as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            await websocket.close(code=4004, reason=f"Agent run {run_id} not found")
            return

    # Track connection
    if run_id not in _ws_connections:
        _ws_connections[run_id] = set()
    _ws_connections[run_id].add(websocket)

    def _make_event_msg(e: Event) -> WsEventMessage:
        return WsEventMessage(
            data=ParsedEventInfo(
                id=e.id, sequence_num=e.sequence_num, timestamp=e.timestamp, payload=parse_event_payload(e.payload)
            )
        )

    def _make_status_msg(run: AgentRun) -> WsStatusMessage:
        return WsStatusMessage(data=WsStatusData(status=run.status, completion_summary=run.completion_summary))

    try:
        # Send initial state: all existing events
        last_seq = -1
        with get_session() as session:
            events = session.query(Event).filter(Event.agent_run_id == run_id).order_by(Event.sequence_num).all()
            for e in events:
                await websocket.send_json(_make_event_msg(e).model_dump(mode="json"))
                last_seq = e.sequence_num

            # Send current run status
            run = session.get(AgentRun, run_id)
            if run:
                await websocket.send_json(_make_status_msg(run).model_dump(mode="json"))

        # Poll for new events (until run completes or client disconnects)
        while True:
            await asyncio.sleep(0.5)  # Poll every 500ms

            with get_session() as session:
                # Check for new events
                new_events = (
                    session.query(Event)
                    .filter(Event.agent_run_id == run_id, Event.sequence_num > last_seq)
                    .order_by(Event.sequence_num)
                    .all()
                )

                for e in new_events:
                    await websocket.send_json(_make_event_msg(e).model_dump(mode="json"))
                    last_seq = e.sequence_num

                # Check run status
                run = session.get(AgentRun, run_id)
                if run and run.status != AgentRunStatus.IN_PROGRESS:
                    # Send final status and close
                    await websocket.send_json(_make_status_msg(run).model_dump(mode="json"))
                    await websocket.send_json(WsCompleteMessage().model_dump(mode="json"))
                    break

    except WebSocketDisconnect:
        logger.debug(f"WebSocket disconnected for run {run_id}")
    finally:
        # Clean up connection tracking
        if run_id in _ws_connections:
            _ws_connections[run_id].discard(websocket)
            if not _ws_connections[run_id]:
                del _ws_connections[run_id]


# --- WebSocket for Runs Feed (list updates) ---


class WsFeedRunsMessage(BaseModel):
    """WebSocket message containing recent runs."""

    type: Literal["runs"] = "runs"
    runs: list[RunInfo]


class WsFeedJobsMessage(BaseModel):
    """WebSocket message containing active jobs."""

    type: Literal["jobs"] = "jobs"
    jobs: list[JobInfo]


# Track active feed connections
_feed_connections: set[WebSocket] = set()


def _build_run_info(run: AgentRun, split: Split | None) -> RunInfo:
    """Convert AgentRun ORM to RunInfo."""
    return RunInfo(
        agent_run_id=run.agent_run_id,
        definition_id=run.definition_id,
        type_config=run.type_config,
        model=run.model,
        status=run.status,
        created_at=run.created_at,
        updated_at=run.updated_at,
        split=split,
    )


def _get_recent_runs(session, limit: int = 20) -> list[RunInfo]:
    """Get recent runs with split info."""
    runs = session.query(AgentRun).order_by(AgentRun.updated_at.desc()).limit(limit).all()
    result = []
    for run in runs:
        split = None
        if run.type_config.get("agent_type") == "critic":
            snapshot_slug = run.type_config.get("snapshot_slug")
            if snapshot_slug:
                snapshot = session.query(Snapshot).filter_by(slug=snapshot_slug).first()
                if snapshot:
                    split = snapshot.split
        result.append(_build_run_info(run, split))
    return result


def _get_active_jobs() -> list[JobInfo]:
    """Get active validation jobs from in-memory store."""
    return [JobInfo.model_validate(job, from_attributes=True) for job in _jobs.values()]


@router.websocket("/feed")
async def runs_feed(websocket: WebSocket) -> None:
    """WebSocket endpoint for live runs/jobs feed.

    Sends initial state then streams updates when runs or jobs change.
    """
    await websocket.accept()
    _feed_connections.add(websocket)

    try:
        # Send initial state
        with get_session() as session:
            runs = _get_recent_runs(session)
            jobs = _get_active_jobs()
            await websocket.send_json(WsFeedRunsMessage(runs=runs).model_dump(mode="json"))
            await websocket.send_json(WsFeedJobsMessage(jobs=jobs).model_dump(mode="json"))
            last_updated = max((r.updated_at for r in runs), default=datetime.min)
            last_job_state = [(j.job_id, j.completed, j.failed) for j in jobs]

        # Poll for changes
        while True:
            await asyncio.sleep(1.0)

            with get_session() as session:
                # Check for new/updated runs
                current_runs = _get_recent_runs(session)
                current_updated = max((r.updated_at for r in current_runs), default=datetime.min)

                if current_updated > last_updated:
                    await websocket.send_json(WsFeedRunsMessage(runs=current_runs).model_dump(mode="json"))
                    last_updated = current_updated

                # Check for job changes
                current_jobs = _get_active_jobs()
                current_job_state = [(j.job_id, j.completed, j.failed) for j in current_jobs]

                if current_job_state != last_job_state:
                    await websocket.send_json(WsFeedJobsMessage(jobs=current_jobs).model_dump(mode="json"))
                    last_job_state = current_job_state

    except WebSocketDisconnect:
        logger.debug("Feed WebSocket disconnected")
    finally:
        _feed_connections.discard(websocket)
