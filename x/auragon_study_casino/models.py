"""SQLAlchemy models for the Y.Doc-backed state store.

The canonical app state is one row containing the latest binary Y-CRDT
update. Client-reported casino outcomes are stored separately as an
append-only audit log so the Y.Doc does not grow with every spin or hand.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DocRow(Base):
    """The single canonical Y.Doc, serialized as a binary update blob."""

    __tablename__ = "doc"
    __table_args__ = (CheckConstraint("id = 1", name="doc_single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    update_blob: Mapped[bytes] = mapped_column(LargeBinary)


class GameEventRow(Base):
    """Append-only, client-reported casino event audit record.

    The current implementation still resolves games in the browser, so rows
    here are not proof of fair randomness. They are a server-stamped audit trail
    of what the client reported, plus the server's canonical balance observed
    when the event was recorded.
    """

    __tablename__ = "game_events"
    __table_args__ = (UniqueConstraint("client_event_id", name="game_events_client_event_id_unique"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    server_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    game: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="client_reported")
    wager_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    payout_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    credits_before: Mapped[int] = mapped_column(Integer, nullable=False)
    credits_after: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_before: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_after: Mapped[int] = mapped_column(Integer, nullable=False)
    server_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    server_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_json: Mapped[str] = mapped_column(Text, nullable=False)
