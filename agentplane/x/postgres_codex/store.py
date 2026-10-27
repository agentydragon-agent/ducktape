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


class Intent(Base):
    __tablename__ = "spike_intent"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey(Conversation.id))
    generation: Mapped[int]
    request: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class LostOwnershipError(RuntimeError):
    pass


class UnknownEffectError(RuntimeError):
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

    async def begin(self, owner: Owner, request: dict[str, Any]) -> UUID:
        """Commit intent before any provider or executor request leaves this process."""
        async with self.sessions.begin() as db:
            row = await self._lock(db, owner)
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
