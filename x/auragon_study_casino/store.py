"""Event store — wraps the SQLAlchemy session and exposes an append/load API.

The invariant this maintains: the `snapshot` row is always the reduction of
all events up to `last_event_id`. Every successful `append` re-reduces the
new events into the snapshot and bumps the ETag (sha256 of the serialized
snapshot blob, truncated to 16 hex chars).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from x.auragon_study_casino.models import Base, EventRow, SnapshotRow
from x.auragon_study_casino.reducer import initial_state, reduce_event


@dataclass(frozen=True)
class LoadedState:
    state: dict[str, Any]
    last_event_id: int
    etag: str


@dataclass(frozen=True)
class IncomingEvent:
    type: str
    ts_ms: int
    payload: dict[str, Any]


def _compute_etag(state: dict[str, Any], last_event_id: int) -> str:
    # Fold last_event_id into the hash so two identical snapshots at different
    # log positions get different ETags — prevents an If-Match from a stale
    # client from passing just because their content happens to match.
    blob = json.dumps({"state": state, "last": last_event_id}, sort_keys=True, separators=(",", ":"))
    return f'"{hashlib.sha256(blob.encode()).hexdigest()[:16]}"'


class EventStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine: Engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        # WAL mode gives us readers+one-writer concurrency, which is what we
        # want for a FastAPI pod serving many GET /state alongside occasional
        # POST /events.
        with self._engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.commit()
        Base.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine, expire_on_commit=False)

        # Seed the snapshot row on first boot so later code can always assume
        # it exists.
        with self._Session() as s:
            if s.scalar(select(SnapshotRow).where(SnapshotRow.id == 1)) is None:
                empty = initial_state()
                s.add(SnapshotRow(id=1, state=empty, last_event_id=0, etag=_compute_etag(empty, 0)))
                s.commit()

    def load(self) -> LoadedState:
        with self._Session() as s:
            row = s.scalar(select(SnapshotRow).where(SnapshotRow.id == 1))
            assert row is not None  # seeded in __init__
            return LoadedState(state=row.state, last_event_id=row.last_event_id, etag=row.etag)

    def append(self, events: list[IncomingEvent], *, if_match: str | None = None) -> LoadedState:
        """Append events, re-reduce into snapshot, return new LoadedState.

        Raises `StaleETagError` if `if_match` doesn't match the current snapshot
        ETag. Raises `ValueError` (from the reducer) if any event is malformed.
        """
        if not events:
            raise ValueError("no events to append")
        with self._Session() as s, s.begin():
            row = s.scalar(select(SnapshotRow).where(SnapshotRow.id == 1).with_for_update())
            assert row is not None
            if if_match is not None and if_match != row.etag:
                raise StaleETagError(expected=row.etag, got=if_match)

            state = row.state
            last_id = row.last_event_id
            for inc in events:
                # Reduce first so malformed events abort before any insert.
                state = reduce_event(state, inc.type, inc.payload)
                ev = EventRow(ts_ms=inc.ts_ms, type=inc.type, payload=inc.payload)
                s.add(ev)
                s.flush()  # get ev.id
                last_id = ev.id

            row.state = state
            row.last_event_id = last_id
            row.etag = _compute_etag(state, last_id)
            return LoadedState(state=state, last_event_id=last_id, etag=row.etag)

    def list_events(self, *, since_id: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        with self._Session() as s:
            rows = s.scalars(select(EventRow).where(EventRow.id > since_id).order_by(EventRow.id).limit(limit)).all()
            return [{"id": r.id, "ts_ms": r.ts_ms, "type": r.type, "payload": r.payload} for r in rows]


class StaleETagError(Exception):
    def __init__(self, *, expected: str, got: str) -> None:
        super().__init__(f"etag mismatch: expected {expected}, got {got}")
        self.expected = expected
        self.got = got


# Enable WAL mode on every new connection (not just the first one). Needed
# because create_engine's connection pool recycles, and PRAGMA journal_mode
# only sticks per-connection via WAL's file-backed mode flag.
@event.listens_for(Engine, "connect")
def _sqlite_pragma_on_connect(dbapi_conn: Any, _record: Any) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()
