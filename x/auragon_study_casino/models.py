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
    """Append-only server-resolved casino event audit record.

    Every row is server-stamped with the canonical balance observed when the
    event was committed. Pre-cutover rows with `source="client_reported"`
    remain readable but are no longer written.
    """

    __tablename__ = "game_events"
    __table_args__ = (UniqueConstraint("client_event_id", name="game_events_client_event_id_unique"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    server_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    game: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="server_resolved")
    wager_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    payout_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    credits_before: Mapped[int] = mapped_column(Integer, nullable=False)
    credits_after: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_before: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_after: Mapped[int] = mapped_column(Integer, nullable=False)
    server_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    server_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_json: Mapped[str] = mapped_column(Text, nullable=False)
    rules_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rng_version: Mapped[str | None] = mapped_column(String(32), nullable=True)


class LedgerEventRow(Base):
    """Append-only server-authoritative action log.

    Every server action that can affect the economy records one row here. The
    row also stores the action response result so a retried idempotency key can
    return the original committed outcome without replaying the mutation.
    """

    __tablename__ = "ledger_events"
    __table_args__ = (UniqueConstraint("client_action_id", name="ledger_events_client_action_id_unique"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_action_id: Mapped[str] = mapped_column(String(128), nullable=False)
    server_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    rules_version: Mapped[str] = mapped_column(String(32), nullable=False)
    rng_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    credits_before: Mapped[int] = mapped_column(Integer, nullable=False)
    credits_after: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_before: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_after: Mapped[int] = mapped_column(Integer, nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)


class StateSnapshotRow(Base):
    """Raw Y.Doc snapshots taken before destructive/server-authority changes."""

    __tablename__ = "state_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    doc_update_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    decoded_json: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class BlackjackHandRow(Base):
    """Server-owned blackjack hand state between deal and settlement."""

    __tablename__ = "blackjack_hands"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    wager_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    current_wager_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    credits_before: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_before: Mapped[int] = mapped_column(Integer, nullable=False)
    shoe_json: Mapped[str] = mapped_column(Text, nullable=False)
    player_json: Mapped[str] = mapped_column(Text, nullable=False)
    dealer_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
