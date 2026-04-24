"""SQLAlchemy models for the event-sourced state store.

Two tables:

- `events` is an append-only log keyed by auto-incrementing id. Each row carries
  a client-supplied event timestamp (ms since epoch) so the UI can render
  accurate "when did this session end" metadata even if the server clock
  drifted from the client.
- `snapshot` caches the reduced state at a given `last_event_id`. One row, id=1.
  The snapshot isn't a source of truth — it's derivable from the event log —
  but having it means `GET /state` is an O(1) table scan instead of an O(N)
  fold over all events.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, CheckConstraint, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EventRow(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Client-supplied wall-clock timestamp (ms since Unix epoch). Not reliable
    # across devices; only used for display. Server insertion order is `id`.
    ts_ms: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class SnapshotRow(Base):
    __tablename__ = "snapshot"
    __table_args__ = (CheckConstraint("id = 1", name="snapshot_single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSON)
    last_event_id: Mapped[int] = mapped_column(Integer)
    etag: Mapped[str] = mapped_column(String(64))
