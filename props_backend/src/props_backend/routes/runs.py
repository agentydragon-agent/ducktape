"""Runs API routes for triggering and monitoring agent runs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import logging
import random
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from agent_core.events import EventType
from openai_utils.client_factory import build_client
from props.agent_registry import AgentRegistry
from props.agent_types import AgentType, TypeConfig
from props.db.examples import Example
from props.db.models import AgentRun, AgentRunStatus, Event, Snapshot
from props.db.session import get_session
from props.models.examples import ExampleKind, ExampleSpec
from props.splits import Split

router = APIRouter()
logger = logging.getLogger(__name__)


# --- Models ---


class ActiveRunInfo(BaseModel):
    agent_run_id: UUID
    definition_id: str
    model: str
    status: AgentRunStatus
    created_at: datetime


class ActiveRunsResponse(BaseModel):
    runs: list[ActiveRunInfo]


class ValidationRunRequest(BaseModel):
    definition_id: str
    example_kind: ExampleKind
    n_samples: int = Field(ge=1, le=50, default=5)
    critic_model: str = "gpt-5.1-codex-mini"
    grader_model: str = "gpt-5.1-codex-mini"


class ValidationRunResponse(BaseModel):
    job_id: UUID
    status: str
    n_examples_sampled: int
    message: str


class JobInfo(BaseModel):
    """Information about a validation job."""

    job_id: UUID
    definition_id: str
    example_kind: ExampleKind
    n_samples: int
    status: str
    completed: int
    failed: int


class JobsResponse(BaseModel):
    """Response for jobs endpoint."""

    jobs: list[JobInfo]


class AgentRunDetail(BaseModel):
    """Detailed view of an agent run."""

    agent_run_id: UUID
    definition_id: str
    parent_agent_run_id: UUID | None
    model: str
    status: AgentRunStatus
    completion_summary: str | None
    created_at: datetime
    updated_at: datetime
    type_config: TypeConfig
    event_count: int


class EventInfo(BaseModel):
    """Event information for API responses."""

    id: int
    sequence_num: int
    event_type: str
    timestamp: datetime
    payload: EventType


class EventsResponse(BaseModel):
    """Response for events endpoint."""

    agent_run_id: UUID
    events: list[EventInfo]
    total_count: int


class RunInfo(BaseModel):
    """Run information for list view."""

    agent_run_id: UUID
    definition_id: str
    agent_type: AgentType
    model: str
    status: AgentRunStatus
    created_at: datetime
    updated_at: datetime


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
    data: EventInfo


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
    definition_id: str
    example_kind: ExampleKind
    n_samples: int
    critic_model: str
    grader_model: str
    status: str = "running"
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
    definition_id: str | None = None,
    agent_type: AgentType | None = None,
    offset: int = 0,
    limit: int = 100,
) -> RunsListResponse:
    """List all agent runs with optional filters and pagination.

    Query parameters:
    - status: Filter by run status
    - definition_id: Filter by definition ID
    - agent_type: Filter by agent type (critic, grader, etc.)
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

        total_count = query.count()
        runs = query.order_by(AgentRun.created_at.desc()).offset(offset).limit(limit).all()

        return RunsListResponse(
            runs=[
                RunInfo(
                    agent_run_id=r.agent_run_id,
                    definition_id=r.agent_definition_id,
                    agent_type=r.type_config.agent_type,
                    model=r.model,
                    status=r.status,
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                )
                for r in runs
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

    # Get validation examples of the requested kind
    with get_session() as session:
        examples = (
            session.query(Example)
            .join(Snapshot, Snapshot.slug == Example.snapshot_slug)
            .filter(Snapshot.split == Split.VALID)
            .filter(Example.example_kind == body.example_kind)
            .order_by(Example.snapshot_slug)
            .all()
        )

        if not examples:
            raise HTTPException(status_code=400, detail=f"No validation examples of kind {body.example_kind}")

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

    return ValidationRunResponse(job_id=job_id, status="running", n_examples_sampled=n_to_sample, message=message)


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

        job.status = "completed"
        logger.info(f"[Job {job.job_id}] Finished: {job.completed} completed, {job.failed} failed")

    except Exception:
        logger.exception(f"[Job {job.job_id}] Batch failed")
        job.status = "failed"


# --- Run Detail Endpoints ---


@router.get("/{run_id}")
def get_run(run_id: UUID) -> AgentRunDetail:
    """Get details of a specific agent run."""
    with get_session() as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Agent run {run_id} not found")

        # Count events
        event_count = session.query(Event).filter(Event.agent_run_id == run_id).count()

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
        )


@router.get("/{run_id}/events")
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
                EventInfo(
                    id=e.id,
                    sequence_num=e.sequence_num,
                    event_type=e.event_type,
                    timestamp=e.timestamp,
                    payload=e.payload,
                )
                for e in events
            ],
            total_count=total_count,
        )


# --- WebSocket for Live Event Streaming ---

# Track active WebSocket connections per run
_ws_connections: dict[UUID, set[WebSocket]] = {}


@router.websocket("/{run_id}/stream")
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
            data=EventInfo(
                id=e.id, sequence_num=e.sequence_num, event_type=e.event_type, timestamp=e.timestamp, payload=e.payload
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
