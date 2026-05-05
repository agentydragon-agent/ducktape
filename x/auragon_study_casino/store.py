"""Server-authoritative DocStore for the casino's Y.Doc.

The store holds one Y.Doc in memory and persists it as a single binary
update blob in SQLite. Every `POST /sync` request goes through
`apply_client_update`, which:

1. Builds a *trial* doc by cloning the canonical state and applying
   the inbound client update on top of it.
2. Runs every validator from `validators.py` against the trial.
3. On success, promotes the trial to canonical, persists, and returns
   the binary diff the client doesn't yet have.
4. On failure, the canonical doc is unchanged and the caller gets a
   `Rejected` describing which rule was violated.

The Y.Doc is not used as an unbounded casino audit log. Client-reported
game outcomes go into the separate `game_events` table, while the
SyncStatus rejection contract on the client mirrors the structure returned
here so the UI can roll back the offending transaction via `Y.UndoManager`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from x.auragon_study_casino.doc_shape import Casino
from x.auragon_study_casino.events import GameEventCreate, GameEventRead, game_event_from_row
from x.auragon_study_casino.models import DocRow, GameEventRow
from x.auragon_study_casino.validators import ValidationError, validate

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _run_alembic_migrations(engine: Engine) -> None:
    """Run pending migrations, baselining pre-Alembic DBs at the doc table."""
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        tables = set(inspect(conn).get_table_names())
        if "doc" in tables and "alembic_version" not in tables:
            alembic_command.stamp(cfg, "0001")
        alembic_command.upgrade(cfg, "head")


@dataclass(frozen=True)
class Accepted:
    """The client's update was applied and persisted."""

    server_update: bytes
    """Binary update the client should apply to catch up to the server's
    current state, computed against the state vector the client sent."""

    server_state_vector: bytes
    """Server's state vector after the merge — the client should remember
    this and pass it on the next sync as `since_state_vector`."""


@dataclass(frozen=True)
class Rejected:
    """The client's update would have violated a business rule."""

    rule: str
    message: str


class DocStore:
    """Owns the canonical Y.Doc and gates writes through the validators."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine: Engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        with self._engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.commit()
        _run_alembic_migrations(self._engine)
        self._Session = sessionmaker(bind=self._engine, expire_on_commit=False)

        # Lock around the canonical doc + persistence step. pycrdt is not
        # thread-safe and FastAPI may serve requests from multiple threads;
        # the critical section (clone → apply → validate → persist) needs
        # to be atomic.
        self._lock = RLock()

        # Seed an empty canonical doc on first boot.
        with self._Session() as s:
            row = s.scalar(select(DocRow).where(DocRow.id == 1))
            if row is None:
                seed = Casino.empty()
                s.add(DocRow(id=1, update_blob=seed.get_update()))
                s.commit()
                self._canonical = seed
            else:
                self._canonical = Casino.from_update(row.update_blob)

    @property
    def canonical(self) -> Casino:
        """Read-only access to the canonical doc; do not mutate."""
        return self._canonical

    def get_update_for_client(self, client_state_vector: bytes | None) -> bytes:
        """Binary update the client needs to catch up to the server's view."""
        with self._lock:
            return self._canonical.get_update(client_state_vector)

    def get_server_state_vector(self) -> bytes:
        with self._lock:
            return self._canonical.get_state()

    def snapshot_for_client(self, client_state_vector: bytes | None) -> tuple[bytes, bytes]:
        """Return (update_for_client, server_state_vector) atomically.

        Two callers (`/sync`'s pure-pull path and the bootstrap path) want a
        binary update and the matching server state vector. Calling
        `get_update_for_client` and `get_server_state_vector` separately is
        racy: another thread can promote a new canonical between the two
        unlocked sections, leaving the client with an update from version V
        and a state vector from version V+1. Generate the pair under a
        single lock acquisition.
        """
        with self._lock:
            return (self._canonical.get_update(client_state_vector), self._canonical.get_state())

    def apply_client_update(self, client_update: bytes, client_state_vector: bytes) -> Accepted | Rejected:
        """Apply `client_update` to a trial Casino, validate, persist on success.

        `client_state_vector` is the state vector the client had *before*
        producing this update; we use it to compute the minimal `server_update`
        the client still needs after our merge.

        Failure modes, all reported via `Rejected` so the client can surface a
        toast and roll back rather than seeing a 500:
        - `invalid_update`: pycrdt couldn't decode the client's binary blob
          (corrupt or truncated). Catching here keeps a malformed payload
          from taking the sync surface down.
        - one of the validators in `validators.py` raised.

        Persistence ordering is **persist first, then promote**: the SQLite
        write commits before `_canonical` swaps, so a disk error can't leave
        the in-memory doc ahead of what survives a process restart.
        """
        with self._lock:
            trial = Casino.from_update(self._canonical.get_update())
            try:
                trial.apply_update(client_update)
            except Exception as e:
                return Rejected(rule="invalid_update", message=f"could not decode client update: {e}")

            try:
                validate(trial)
            except ValidationError as e:
                return Rejected(rule=e.rule, message=e.message)

            # Persist first; only swap _canonical after the DB commits so a
            # disk error can't leave memory ahead of the persisted state.
            trial_update = trial.get_update()
            with self._Session() as s, s.begin():
                row = s.scalar(select(DocRow).where(DocRow.id == 1).with_for_update())
                assert row is not None
                row.update_blob = trial_update
            self._canonical = trial

            return Accepted(server_update=trial.get_update(client_state_vector), server_state_vector=trial.get_state())

    def record_game_event(self, event: GameEventCreate) -> GameEventRead:
        """Persist one client-reported casino event.

        The event is intentionally outside the Y.Doc: it is append-only,
        server-stamped, queryable, and does not inflate every client's CRDT
        payload. Until game resolution moves server-side, the row should be
        interpreted as an audit trail of what the browser reported, not as
        cryptographic proof of the draw.
        """
        with self._lock:
            server_credits = int(self._canonical.balance.get("credits", 0))
            server_tokens = int(self._canonical.balance.get("tokens", 0))

        row = GameEventRow(
            client_event_id=event.client_event_id,
            server_at_ms=int(time.time() * 1000),
            occurred_at_ms=event.occurred_at_ms,
            game=event.game,
            event_type=event.event_type,
            source="client_reported",
            wager_credits=event.wager_credits,
            payout_tokens=event.payout_tokens,
            credits_before=event.credits_before,
            credits_after=event.credits_after,
            tokens_before=event.tokens_before,
            tokens_after=event.tokens_after,
            server_credits=server_credits,
            server_tokens=server_tokens,
            outcome_json=event.outcome_json(),
        )
        with self._Session() as s:
            existing = s.scalar(select(GameEventRow).where(GameEventRow.client_event_id == event.client_event_id))
            if existing is not None:
                return game_event_from_row(existing)
            try:
                s.add(row)
                s.commit()
            except IntegrityError:
                s.rollback()
                existing = s.scalar(select(GameEventRow).where(GameEventRow.client_event_id == event.client_event_id))
                if existing is not None:
                    return game_event_from_row(existing)
                raise
            s.refresh(row)
            return game_event_from_row(row)

    def list_game_events(self, limit: int = 100) -> list[GameEventRead]:
        with self._Session() as s:
            rows = list(s.scalars(select(GameEventRow).order_by(GameEventRow.id.desc()).limit(limit)).all())
            return [game_event_from_row(row) for row in rows]


# Enable WAL on every pooled connection.
@event.listens_for(Engine, "connect")
def _sqlite_pragma_on_connect(dbapi_conn: Any, _record: Any) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()
