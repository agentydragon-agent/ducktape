"""Internal durable input acceptance; transport authorization remains the caller's responsibility.

Not exposed by an RPC yet. In particular, do not use a caller-supplied identity here: the
future boundary must authenticate it and authorize the immutable Session destination first.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from agentplane.protocol import command_pb2, event_log_pb2
from agentplane.sandbox_service.session_history.db import InputSubmission, SessionHistory
from agentplane.subjects import ServiceAccountRef

# gazelle:include_dep @pypi//protobuf


class NotificationNotice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    inbox_id: UUID
    through_cursor: int = Field(ge=0, le=2**63 - 1)


class InputMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    notification_notice: NotificationNotice | None = None


class SubmitInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    command_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=1_048_576)
    metadata: InputMetadata = Field(default_factory=InputMetadata)

    def runner_command(self) -> command_pb2.Command:
        """Allowlisted conversion: service metadata/provenance never enters runner Commands."""
        return command_pb2.Command(command_id=self.command_id, submit_input=command_pb2.SubmitInput(text=self.text))


class SubmissionConflictError(ValueError):
    pass


class SubmissionNotFoundError(LookupError):
    pass


class SubmissionRefusedError(ValueError):
    """Only a definitive non-admission refusal, never a timeout or transport failure."""


class SubmissionState(StrEnum):
    PENDING_ADMISSION = "pending_admission"
    ADMITTED = "admitted"
    REJECTED = "rejected"


@dataclass(frozen=True)
class Submission:
    state: SubmissionState
    admission: bytes | None
    rejection: str | None

    @classmethod
    def from_row(cls, row: InputSubmission) -> Submission:
        return cls(SubmissionState(row.state), row.admission, row.rejection)

    def receipt(self) -> event_log_pb2.EventEntry:
        if self.admission is None:
            raise ValueError("submission has no admission receipt")
        return event_log_pb2.EventEntry.FromString(self.admission)


async def reconcile_admission(session: AsyncSession, session_id: UUID, entry: event_log_pb2.EventEntry) -> None:
    """Called under the SessionHistory lock, in the same transaction as spool checkpointing.

    Other command producers have no submission row and remain valid archive entries. Replay
    invokes this for duplicates too, allowing reconciliation to be repeated idempotently.
    """
    if not entry.event.HasField("command_admitted"):
        return
    command = entry.event.command_admitted.command
    row = await session.get(InputSubmission, (session_id, command.command_id))
    if row is None:
        return
    if not entry.cursor or not entry.origin.source_id or entry.origin.sequence != entry.cursor:
        raise SubmissionConflictError("invalid admission origin")
    if command_pb2.Command.FromString(row.runner_command) != command:
        raise SubmissionConflictError("admission differs from retained input")
    payload = entry.SerializeToString(deterministic=True)
    if row.admission is not None and row.admission != payload:
        raise SubmissionConflictError("conflicting admission receipt")
    # Positive durable evidence wins over a racing refusal; never regress an admission.
    row.state = SubmissionState.ADMITTED
    row.admission = payload
    row.rejection = None


class SubmissionStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def _lock(self, session: AsyncSession, session_id: UUID) -> SessionHistory:
        history = await session.scalar(select(SessionHistory).where(SessionHistory.id == session_id).with_for_update())
        if history is None:
            raise SubmissionNotFoundError(session_id)
        return history

    async def accept(
        self,
        session_id: UUID,
        request: SubmitInput,
        *,
        caller: ServiceAccountRef,
        notification_producers: frozenset[ServiceAccountRef],
    ) -> Submission:
        """Persist before runner contact. Destination authorization must precede this call.

        Caller provenance is server supplied, retained immutably, and checked on retries.
        This internal read/write API must not be exposed without the transport scope checks.
        """
        if request.metadata.notification_notice is not None and caller not in notification_producers:
            raise PermissionError("caller cannot attach notification provenance")
        command = request.runner_command().SerializeToString(deterministic=True)
        metadata = request.metadata.model_dump_json()
        async with self._sessions.begin() as session:
            await self._lock(session, session_id)
            row = await session.get(InputSubmission, (session_id, request.command_id))
            if row is None:
                row = InputSubmission(
                    session_id=session_id,
                    command_id=request.command_id,
                    runner_command=command,
                    metadata_json=metadata,
                    caller_namespace=caller.namespace,
                    caller_name=caller.name,
                    state=SubmissionState.PENDING_ADMISSION,
                )
                session.add(row)
            elif (
                command_pb2.Command.FromString(row.runner_command) != request.runner_command()
                or row.metadata_json != metadata
                or (row.caller_namespace, row.caller_name) != (caller.namespace, caller.name)
            ):
                raise SubmissionConflictError("command ID already belongs to a different submission")
            return Submission.from_row(row)

    async def read(self, session_id: UUID, command_id: str) -> Submission:
        """Internal lookup only; the future status RPC must authorize Session access."""
        async with self._sessions() as session:
            row = await session.get(InputSubmission, (session_id, command_id))
            if row is None:
                raise SubmissionNotFoundError(command_id)
            return Submission.from_row(row)

    async def admitted(self, session_id: UUID, entry: event_log_pb2.EventEntry) -> Submission:
        if not entry.event.HasField("command_admitted"):
            raise SubmissionConflictError("expected a command admission receipt")
        async with self._sessions.begin() as session:
            history = await self._lock(session, session_id)
            if history.source_id is not None and history.source_id != entry.origin.source_id:
                raise SubmissionConflictError("admission source differs from Session history")
            row = await session.get(InputSubmission, (session_id, entry.event.command_admitted.command.command_id))
            if row is None:
                raise SubmissionNotFoundError(entry.event.command_admitted.command.command_id)
            await reconcile_admission(session, session_id, entry)
            # A direct receipt is not a contiguous archive prefix: do not advance last_cursor.
            return Submission.from_row(row)

    async def rejected(self, session_id: UUID, command_id: str, reason: str) -> Submission:
        if not reason or len(reason) > 512:
            raise ValueError("a bounded, sanitized rejection reason is required")
        async with self._sessions.begin() as session:
            await self._lock(session, session_id)
            row = await session.get(InputSubmission, (session_id, command_id))
            if row is None:
                raise SubmissionNotFoundError(command_id)
            if row.state == SubmissionState.PENDING_ADMISSION:
                row.state = SubmissionState.REJECTED
                row.rejection = reason
            return Submission.from_row(row)


async def submit_input(
    store: SubmissionStore,
    session_id: UUID,
    request: SubmitInput,
    *,
    caller: ServiceAccountRef,
    notification_producers: frozenset[ServiceAccountRef],
    dispatch: Callable[[command_pb2.Command], Awaitable[event_log_pb2.EventEntry]],
) -> event_log_pb2.EventEntry:
    """One caller-driven attempt, not a background queue or harness startup mechanism.

    The future RPC must authorize first and provide a destination-bound dispatcher. Only
    proven non-admission can raise SubmissionRefusedError. All other exceptions (including
    cancellation) leave the durable state untouched for spool reconciliation or exact retry.
    """
    current = await store.accept(session_id, request, caller=caller, notification_producers=notification_producers)
    if current.state == SubmissionState.ADMITTED:
        return current.receipt()
    if current.state == SubmissionState.REJECTED:
        raise SubmissionRefusedError(current.rejection)
    try:
        receipt = await dispatch(request.runner_command())
    except SubmissionRefusedError as error:
        current = await store.rejected(session_id, request.command_id, str(error))
        if current.state == SubmissionState.ADMITTED:
            return current.receipt()
        raise
    if receipt.event.command_admitted.command != request.runner_command():
        raise SubmissionConflictError("dispatcher returned a receipt for different work")
    return (await store.admitted(session_id, receipt)).receipt()
