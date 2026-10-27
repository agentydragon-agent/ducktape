"""Experimental conversation authority, isolated from every production schema."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "spike_conversation"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    owner: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    pending: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    stopped: Mapped[bool] = mapped_column(default=False)
    executor_session: Mapped[str | None]


class Intent(Base):
    __tablename__ = "spike_intent"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey(Conversation.id))
    generation: Mapped[int]
    request: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class RemoteProcess(Base):
    __tablename__ = "spike_process"

    id: Mapped[str] = mapped_column(primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey(Conversation.id))
    generation: Mapped[int]
    after_seq: Mapped[int | None]
    status: Mapped[str]
    tty: Mapped[bool]
    exit_code: Mapped[int | None]


class LiveCell(Base):
    __tablename__ = "spike_cell"

    id: Mapped[str] = mapped_column(primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey(Conversation.id), primary_key=True)
    generation: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str]


class InterruptRequest(Base):
    __tablename__ = "spike_interrupt"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey(Conversation.id))
    generation: Mapped[int]
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class LostOwnershipError(RuntimeError):
    pass


class UnknownEffectError(RuntimeError):
    pass


class InterruptPendingError(RuntimeError):
    pass


@dataclass(frozen=True)
class Owner:
    conversation_id: UUID
    id: UUID
    generation: int


class Store:
    def __init__(self, engine: AsyncEngine):
        self.sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def create(self, prompt: str) -> UUID:
        conversation_id = uuid4()
        async with self.sessions.begin() as db:
            db.add(Conversation(id=conversation_id, items=[{"type": "message", "role": "user", "content": prompt}]))
        return conversation_id

    async def claim(self, conversation_id: UUID, *, lease: timedelta) -> Owner:
        async with self.sessions.begin() as db:
            row = (
                await db.scalars(select(Conversation).where(Conversation.id == conversation_id).with_for_update())
            ).one()
            now = (await db.scalars(select(func.clock_timestamp()))).one()
            if row.owner is not None and row.lease_until is not None and row.lease_until > now:
                raise LostOwnershipError("conversation already has a live sampler")
            row.generation += 1
            row.owner = uuid4()
            row.lease_until = now + lease
            return Owner(conversation_id, row.owner, row.generation)

    async def read(self, owner: Owner) -> Conversation:
        async with self.sessions.begin() as db:
            return await self._lock(db, owner)

    async def release(self, owner: Owner) -> None:
        async with self.sessions.begin() as db:
            row = await self._lock(db, owner)
            row.owner = None
            row.lease_until = None
            for request in (
                await db.scalars(
                    select(InterruptRequest).where(
                        InterruptRequest.conversation_id == owner.conversation_id,
                        InterruptRequest.generation == owner.generation,
                        InterruptRequest.result.is_(None),
                    )
                )
            ).all():
                request.result = {"status": "not_applied", "reason": "owner completed before observing request"}

    async def status(self, conversation_id: UUID) -> dict[str, Any]:
        async with self.sessions() as db:
            row = (await db.scalars(select(Conversation).where(Conversation.id == conversation_id))).one()
            return {
                "generation": row.generation,
                "owner": str(row.owner) if row.owner else None,
                "pending": row.pending,
                "stopped": row.stopped,
                "interrupts": [
                    {"id": str(request.id), "generation": request.generation, "result": request.result}
                    for request in (
                        await db.scalars(
                            select(InterruptRequest).where(InterruptRequest.conversation_id == conversation_id)
                        )
                    ).all()
                ],
            }

    async def begin(self, owner: Owner, request: dict[str, Any]) -> UUID:
        """Commit intent before any provider or executor request leaves this process."""
        async with self.sessions.begin() as db:
            row = await self._lock(db, owner)
            await self._check_interrupt(db, owner)
            if row.pending is not None:
                raise UnknownEffectError(
                    f"unresolved {row.pending['kind']} intent {row.pending['id']}; no automatic replay"
                )
            intent_id = uuid4()
            db.add(Intent(id=intent_id, conversation_id=row.id, generation=owner.generation, request=request))
            row.pending = {"id": str(intent_id), "kind": request["kind"]}
            return intent_id

    async def finish(self, owner: Owner, intent_id: UUID, result: dict[str, Any], items: list[dict[str, Any]]) -> None:
        async with self.sessions.begin() as db:
            row = await self._lock(db, owner)
            if row.pending is None or row.pending["id"] != str(intent_id):
                raise ValueError("result does not match the pending intent")
            intent = (await db.scalars(select(Intent).where(Intent.id == intent_id))).one()
            intent.result = result
            row.items = [*row.items, *items]
            row.pending = None

    async def record_nested(self, owner: Owner, request: dict[str, Any]) -> UUID:
        async with self.sessions.begin() as db:
            await self._lock(db, owner)
            if request["kind"] == "tool":
                await self._check_interrupt(db, owner)
            intent_id = uuid4()
            db.add(
                Intent(
                    id=intent_id, conversation_id=owner.conversation_id, generation=owner.generation, request=request
                )
            )
            return intent_id

    async def finish_nested(self, owner: Owner, intent_id: UUID, result: dict[str, Any]) -> None:
        async with self.sessions.begin() as db:
            await self._lock(db, owner)
            intent = (await db.scalars(select(Intent).where(Intent.id == intent_id))).one()
            if intent.generation != owner.generation or intent.conversation_id != owner.conversation_id:
                raise LostOwnershipError("nested intent belongs to another owner")
            intent.result = result

    async def register_process(self, owner: Owner, process_id: str, *, tty: bool) -> None:
        async with self.sessions.begin() as db:
            await self._lock(db, owner)
            db.add(
                RemoteProcess(
                    id=process_id,
                    conversation_id=owner.conversation_id,
                    generation=owner.generation,
                    status="starting",
                    tty=tty,
                )
            )

    async def set_executor_session(self, owner: Owner, session_id: str) -> None:
        async with self.sessions.begin() as db:
            row = await self._lock(db, owner)
            if row.executor_session is not None and row.executor_session != session_id:
                process = await db.scalar(
                    select(RemoteProcess.id)
                    .where(RemoteProcess.conversation_id == owner.conversation_id, RemoteProcess.status != "exited")
                    .limit(1)
                )
                cell = await db.scalar(
                    select(LiveCell.id)
                    .where(LiveCell.conversation_id == owner.conversation_id, LiveCell.status == "live")
                    .limit(1)
                )
                if process is not None or cell is not None:
                    raise UnknownEffectError("executor returned another session; existing handles cannot be replaced")
            row.executor_session = session_id

    async def process(self, owner: Owner, process_id: str) -> RemoteProcess:
        async with self.sessions.begin() as db:
            await self._lock(db, owner)
            return (
                await db.scalars(
                    select(RemoteProcess).where(
                        RemoteProcess.id == process_id, RemoteProcess.conversation_id == owner.conversation_id
                    )
                )
            ).one()

    async def process_result(
        self, owner: Owner, process_id: str, after_seq: int | None, status: str, exit_code: int | None = None
    ) -> None:
        async with self.sessions.begin() as db:
            await self._lock(db, owner)
            row = (
                await db.scalars(
                    select(RemoteProcess).where(
                        RemoteProcess.id == process_id, RemoteProcess.conversation_id == owner.conversation_id
                    )
                )
            ).one()
            row.after_seq, row.status, row.exit_code = after_seq, status, exit_code

    async def cell_result(self, owner: Owner, cell_id: str, status: str) -> None:
        async with self.sessions.begin() as db:
            await self._lock(db, owner)
            row = (
                await db.scalars(
                    select(LiveCell).where(
                        LiveCell.id == cell_id,
                        LiveCell.conversation_id == owner.conversation_id,
                        LiveCell.generation == owner.generation,
                    )
                )
            ).one_or_none()
            if row is None:
                db.add(
                    LiveCell(
                        id=cell_id, conversation_id=owner.conversation_id, generation=owner.generation, status=status
                    )
                )
            elif row.conversation_id != owner.conversation_id or row.generation != owner.generation:
                raise LostOwnershipError("cell belongs to another owner")
            else:
                row.status = status

    async def execution_state(self, owner: Owner) -> dict[str, Any]:
        async with self.sessions.begin() as db:
            await self._lock(db, owner)
            processes = (
                await db.scalars(
                    select(RemoteProcess).where(
                        RemoteProcess.conversation_id == owner.conversation_id, RemoteProcess.status != "exited"
                    )
                )
            ).all()
            cells = (
                await db.scalars(
                    select(LiveCell).where(LiveCell.conversation_id == owner.conversation_id, LiveCell.status == "live")
                )
            ).all()
            return {
                "processes": [{"session_id": p.id, "status": p.status, "tty": p.tty} for p in processes],
                "cells": [{"cell_id": c.id, "status": c.status, "generation": c.generation} for c in cells],
            }

    async def check_live_cells(self, owner: Owner, *, runtime_available: bool) -> None:
        state = await self.execution_state(owner)
        if state["cells"] and (
            not runtime_available or any(c["generation"] != owner.generation for c in state["cells"])
        ):
            raise UnknownEffectError("live JavaScript cell lost its host; no automatic replay or V8 recovery")

    async def request_interrupt(self, conversation_id: UUID, generation: int) -> UUID:
        """External API targets an observed generation; a stale request cannot cancel a later run."""
        async with self.sessions.begin() as db:
            row = (
                await db.scalars(select(Conversation).where(Conversation.id == conversation_id).with_for_update())
            ).one()
            now = (await db.scalars(select(func.clock_timestamp()))).one()
            if row.owner is None or row.generation != generation or row.lease_until is None or row.lease_until <= now:
                raise LostOwnershipError("interrupt target is not the active owner generation")
            request_id = uuid4()
            db.add(InterruptRequest(id=request_id, conversation_id=conversation_id, generation=generation))
            return request_id

    async def pending_interrupts(self, owner: Owner) -> list[UUID]:
        async with self.sessions.begin() as db:
            await self._lock(db, owner)
            return list(
                await db.scalars(
                    select(InterruptRequest.id).where(
                        InterruptRequest.conversation_id == owner.conversation_id,
                        InterruptRequest.generation == owner.generation,
                        InterruptRequest.result.is_(None),
                    )
                )
            )

    async def acknowledge_interrupt(self, owner: Owner, request_ids: list[UUID], result: dict[str, Any]) -> None:
        async with self.sessions.begin() as db:
            row = await self._lock(db, owner)
            active_call = None
            for request_id in request_ids:
                request = (
                    await db.scalars(
                        select(InterruptRequest).where(
                            InterruptRequest.id == request_id,
                            InterruptRequest.conversation_id == owner.conversation_id,
                            InterruptRequest.generation == owner.generation,
                        )
                    )
                ).one()
                request.result = result
            if row.pending is not None:
                intent = await db.get(Intent, UUID(row.pending["id"]))
                assert intent is not None
                active_call = intent.request.get("call", {}).get("call_id")
                intent.result = {"status": "interrupted", **result}
                if result["cleanup_complete"]:
                    row.pending = None
            if result["cleanup_complete"]:
                completed = {item["call_id"] for item in row.items if item["type"] == "custom_tool_call_output"}
                row.items = [
                    *row.items,
                    *[
                        {
                            "type": "custom_tool_call_output",
                            "call_id": item["call_id"],
                            "output": [
                                {
                                    "type": "input_text",
                                    "text": (
                                        "Interrupted by user. Partial effects may have occurred."
                                        if item["call_id"] == active_call
                                        else "Not started because user interrupted the turn."
                                    ),
                                }
                            ],
                        }
                        for item in row.items
                        if item["type"] == "custom_tool_call" and item["call_id"] not in completed
                    ],
                ]
                for nested in (
                    await db.scalars(
                        select(Intent).where(
                            Intent.conversation_id == owner.conversation_id,
                            Intent.generation == owner.generation,
                            Intent.result.is_(None),
                        )
                    )
                ).all():
                    nested.result = {"status": "interrupted", "partial_effects_possible": True}
            elif row.pending is None:
                # A yielded cell/process may be interrupted between outer transitions.
                # Uncertain cleanup still needs a durable blocking boundary.
                intent_id = uuid4()
                db.add(
                    Intent(
                        id=intent_id,
                        conversation_id=owner.conversation_id,
                        generation=owner.generation,
                        request={"kind": "interrupt", "requests": [str(i) for i in request_ids]},
                        result=result,
                    )
                )
                row.pending = {"id": str(intent_id), "kind": "interrupt"}
            row.stopped = True

    async def append_input(self, owner: Owner, prompt: str) -> None:
        async with self.sessions.begin() as db:
            row = await self._lock(db, owner)
            if row.pending is not None:
                raise UnknownEffectError("unresolved intent blocks new input; no automatic replay")
            row.items = [*row.items, {"type": "message", "role": "user", "content": prompt}]
            row.stopped = False

    @staticmethod
    async def _check_interrupt(db: AsyncSession, owner: Owner) -> None:
        request = await db.scalar(
            select(InterruptRequest.id)
            .where(
                InterruptRequest.conversation_id == owner.conversation_id,
                InterruptRequest.generation == owner.generation,
                InterruptRequest.result.is_(None),
            )
            .limit(1)
        )
        if request is not None:
            raise InterruptPendingError("interrupt already requested; next dispatch is blocked")

    @staticmethod
    async def _lock(db: AsyncSession, owner: Owner) -> Conversation:
        row = (
            await db.scalars(select(Conversation).where(Conversation.id == owner.conversation_id).with_for_update())
        ).one()
        now = (await db.scalars(select(func.clock_timestamp()))).one()
        if (
            row.owner != owner.id
            or row.generation != owner.generation
            or row.lease_until is None
            or row.lease_until <= now
        ):
            raise LostOwnershipError("sampler generation is stale or expired")
        return row
