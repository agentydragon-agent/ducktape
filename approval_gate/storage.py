"""SQLite-backed storage for action records.

Uses SQLAlchemy async ORM with the aiosqlite driver.

Schema:
  actions(id TEXT PK, created_at TEXT, updated_at TEXT,
          call_json TEXT, justification TEXT, session_key TEXT,
          state_json TEXT, status TEXT INDEX)

status is stored as a denormalised indexed column for fast pending queries;
it always matches action.state.status.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter
from sqlalchemy import Index, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from approval_gate.models import Action, ActionState, ActionStatus, PendingState, ToolCall

logger = logging.getLogger(__name__)

_ACTION_STATE_TA: TypeAdapter[ActionState] = TypeAdapter(ActionState)


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


class _Base(DeclarativeBase):
    pass


class _ActionRow(_Base):
    __tablename__ = "actions"
    __table_args__ = (Index("idx_actions_status", "status"), Index("idx_actions_created", "created_at"))

    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=_now)
    updated_at: Mapped[str] = mapped_column(String, nullable=False, default=_now, onupdate=_now)
    call_json: Mapped[str] = mapped_column(Text, nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    session_key: Mapped[str | None] = mapped_column(String, nullable=True)
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)


def _row_to_action(row: _ActionRow) -> Action:
    return Action(
        id=row.id,
        created_at=datetime.fromisoformat(row.created_at),
        updated_at=datetime.fromisoformat(row.updated_at),
        call=ToolCall.model_validate_json(row.call_json),
        justification=row.justification,
        session_key=row.session_key,
        state=_ACTION_STATE_TA.validate_json(row.state_json),
    )


class ActionStorage:
    """Async SQLite storage for action records."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @classmethod
    async def initialize(cls, db_path: Path) -> ActionStorage:
        """Open the database, create schema if needed, and return a ready storage."""
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        async with engine.begin() as conn:
            await conn.run_sync(_Base.metadata.create_all)
        return cls(async_sessionmaker(engine, expire_on_commit=False))

    async def create(self, *, action_id: str, call: ToolCall, justification: str, session_key: str | None) -> Action:
        """Insert a new pending action."""
        state = PendingState()
        row = _ActionRow(
            id=action_id,
            call_json=call.model_dump_json(),
            justification=justification,
            session_key=session_key,
            state_json=state.model_dump_json(),
            status=state.status,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
        logger.debug("created action id=%s tool=%s", action_id, call.tool_name)
        return _row_to_action(row)

    async def get(self, action_id: str) -> Action | None:
        """Fetch a single action by ID."""
        async with self._session_factory() as session:
            row = await session.get(_ActionRow, action_id)
        if row is None:
            return None
        return _row_to_action(row)

    async def update_state(self, action_id: str, new_state: ActionState) -> Action | None:
        """Replace the state of an existing action; returns updated action or None."""
        async with self._session_factory() as session:
            row = await session.get(_ActionRow, action_id)
            if row is None:
                return None
            row.state_json = _ACTION_STATE_TA.dump_json(new_state).decode()
            row.status = new_state.status
            await session.commit()
            await session.refresh(row)
        return _row_to_action(row)

    async def list_by_status(self, status: ActionStatus | None = None, *, limit: int = 100) -> list[Action]:
        """List actions, optionally filtered by status, newest first."""
        async with self._session_factory() as session:
            stmt = select(_ActionRow).order_by(_ActionRow.created_at.desc()).limit(limit)
            if status is not None:
                stmt = stmt.where(_ActionRow.status == status)
            result = await session.execute(stmt)
            rows = result.scalars().all()
        return [_row_to_action(r) for r in rows]
