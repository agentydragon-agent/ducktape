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

The Y.Doc is not used as an unbounded casino audit log. Server actions write
append-only `ledger_events`, server-resolved casino rows in `game_events`, and
snapshots before destructive state replacement; the Y.Doc remains the
replicated projection clients subscribe to.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from pycrdt import Doc, Map
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from x.auragon_study_casino.doc_shape import DEFAULT_PRIZES, Casino
from x.auragon_study_casino.events import GameEventRead, LedgerEventRead, game_event_from_row, ledger_event_from_row
from x.auragon_study_casino.games import RULES_VERSION
from x.auragon_study_casino.models import DocRow, GameEventRow, LedgerEventRow, StateSnapshotRow
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


@dataclass(frozen=True)
class ActionRejectedError(Exception):
    """A server action was well-formed but cannot be committed."""

    rule: str
    message: str


@dataclass(frozen=True)
class ActionMutation:
    """Result returned by a server-action mutator before persistence."""

    result: dict[str, Any]
    details: dict[str, Any] | None = None
    replacement: Casino | None = None
    game_event: dict[str, Any] | None = None
    rng_version: str | None = None
    rules_version: str = RULES_VERSION


@dataclass(frozen=True)
class ServerActionResult:
    """Committed server action plus the Y.Doc update for the caller."""

    event: LedgerEventRead
    result: dict[str, Any]
    server_update: bytes
    server_state_vector: bytes
    game_event: GameEventRead | None = None


ServerActionMutator = Callable[[Casino, Any, int], ActionMutation]


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
        self._ensure_initial_snapshot()

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

    def run_server_action(
        self,
        *,
        client_action_id: str,
        action_type: str,
        client_state_vector: bytes | None,
        mutator: ServerActionMutator,
        snapshot_reason: str | None = None,
        snapshot_note: str | None = None,
    ) -> ServerActionResult:
        """Run one idempotent, server-authoritative mutation.

        The mutation, validation, Y.Doc persistence, and event inserts commit in
        one SQLite transaction. `_canonical` is promoted only after the DB
        commit succeeds, matching `apply_client_update`'s durability contract.
        """
        with self._lock:
            existing_game_event: GameEventRead | None = None
            with self._Session() as s:
                existing = s.scalar(select(LedgerEventRow).where(LedgerEventRow.client_action_id == client_action_id))
                if existing is not None:
                    if existing.action_type.startswith("casino.") or existing.action_type.startswith("blackjack."):
                        game_row = s.scalar(
                            select(GameEventRow).where(GameEventRow.client_event_id == client_action_id)
                        )
                        if game_row is not None:
                            existing_game_event = game_event_from_row(game_row)
                    return ServerActionResult(
                        event=ledger_event_from_row(existing),
                        result=json.loads(existing.result_json),
                        server_update=self._canonical.get_update(client_state_vector),
                        server_state_vector=self._canonical.get_state(),
                        game_event=existing_game_event,
                    )

            now_ms = int(time.time() * 1000)
            before_credits = self._credits(self._canonical)
            before_tokens = self._tokens(self._canonical)
            trial = Casino.from_update(self._canonical.get_update())

            with self._Session() as s, s.begin():
                if snapshot_reason is not None:
                    s.add(self._snapshot_row(snapshot_reason, now_ms, snapshot_note))

                mutation = mutator(trial, s, now_ms)
                next_casino = mutation.replacement or trial
                try:
                    validate(next_casino)
                except ValidationError as e:
                    raise ActionRejectedError(rule=e.rule, message=e.message) from e

                after_credits = self._credits(next_casino)
                after_tokens = self._tokens(next_casino)
                result_json = self._json(mutation.result)
                details_json = self._json(mutation.details or {})
                event_row = LedgerEventRow(
                    client_action_id=client_action_id,
                    server_at_ms=now_ms,
                    action_type=action_type,
                    source="server_action",
                    rules_version=mutation.rules_version,
                    rng_version=mutation.rng_version,
                    credits_before=before_credits,
                    credits_after=after_credits,
                    tokens_before=before_tokens,
                    tokens_after=after_tokens,
                    details_json=details_json,
                    result_json=result_json,
                )
                s.add(event_row)

                game_event_row: GameEventRow | None = None
                if mutation.game_event is not None:
                    game_event_row = self._game_event_row(
                        client_event_id=client_action_id,
                        server_at_ms=now_ms,
                        event=mutation.game_event,
                        credits_before=before_credits,
                        credits_after=after_credits,
                        tokens_before=before_tokens,
                        tokens_after=after_tokens,
                        server_credits=after_credits,
                        server_tokens=after_tokens,
                        rules_version=mutation.rules_version,
                        rng_version=mutation.rng_version,
                    )
                    s.add(game_event_row)

                trial_update = next_casino.get_update()
                row = s.scalar(select(DocRow).where(DocRow.id == 1).with_for_update())
                assert row is not None
                row.update_blob = trial_update
                s.flush()
                s.refresh(event_row)
                if game_event_row is not None:
                    s.refresh(game_event_row)
                    game_event = game_event_from_row(game_event_row)
                else:
                    game_event = None

            self._canonical = next_casino
            return ServerActionResult(
                event=ledger_event_from_row(event_row),
                result=json.loads(result_json),
                server_update=next_casino.get_update(client_state_vector),
                server_state_vector=next_casino.get_state(),
                game_event=game_event,
            )

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
            before_economy = self._economy_fingerprint(self._canonical)
            trial = Casino.from_update(self._canonical.get_update())
            try:
                trial.apply_update(client_update)
            except Exception as e:
                return Rejected(rule="invalid_update", message=f"could not decode client update: {e}")

            try:
                validate(trial)
            except ValidationError as e:
                return Rejected(rule=e.rule, message=e.message)

            if self._economy_fingerprint(trial) != before_economy:
                return Rejected(
                    rule="server_authority",
                    message="balance and prize log changes must go through server action endpoints",
                )

            # Persist first; only swap _canonical after the DB commits so a
            # disk error can't leave memory ahead of the persisted state.
            with self._Session() as s, s.begin():
                row = s.scalar(select(DocRow).where(DocRow.id == 1).with_for_update())
                assert row is not None
                row.update_blob = trial.get_update()
            self._canonical = trial

            return Accepted(server_update=trial.get_update(client_state_vector), server_state_vector=trial.get_state())

    def list_game_events(self, limit: int = 100) -> list[GameEventRead]:
        with self._Session() as s:
            rows = list(s.scalars(select(GameEventRow).order_by(GameEventRow.id.desc()).limit(limit)).all())
            return [game_event_from_row(row) for row in rows]

    def list_ledger_events(self, limit: int = 100) -> list[LedgerEventRead]:
        with self._Session() as s:
            rows = list(s.scalars(select(LedgerEventRow).order_by(LedgerEventRow.id.desc()).limit(limit)).all())
            return [ledger_event_from_row(row) for row in rows]

    def build_import_casino(self, data: dict[str, Any]) -> Casino:
        casino = Casino(Doc())
        casino.balance["credits"] = int(data.get("credits", 0))
        casino.balance["tokens"] = int(data.get("tokens", 0))
        for session in data.get("sessions", []) or []:
            session_id = str(session.get("id") or f"imported-{uuid.uuid4()}")
            sm: Map = Map()
            casino.sessions[session_id] = sm
            sm["subject"] = str(session.get("subject") or "Imported")
            sm["seconds"] = int(session.get("seconds", 0))
            sm["ended_at_ms"] = int(session.get("endedAt") or session.get("ended_at_ms") or 0)
        for prize_id, name, cost in self._prizes_from_import(data):
            pm: Map = Map()
            casino.prizes[prize_id] = pm
            pm["name"] = name
            pm["cost"] = int(cost)
        for prize in data.get("prizeLog", []) or []:
            entry: Map = Map()
            casino.prize_log.append(entry)
            entry["id"] = str(prize.get("id") or f"imported-redemption-{uuid.uuid4()}")
            entry["name"] = str(prize.get("name") or "Imported prize")
            entry["cost"] = int(prize.get("cost", 0))
            entry["at_ms"] = int(prize.get("at") or prize.get("at_ms") or 0)
        if data.get("activeSession"):
            active = data["activeSession"]
            active_sm: Map = Map()
            session_id = f"active-{uuid.uuid4()}"
            casino.sessions[session_id] = active_sm
            active_sm["subject"] = str(active.get("subject") or "Imported")
            active_sm["start_time_ms"] = int(
                active.get("startTime") or active.get("start_time_ms") or int(time.time() * 1000)
            )
            active_sm["paused"] = bool(active.get("paused", False))
            active_sm["paused_duration_ms"] = int(active.get("pausedDuration") or active.get("paused_duration_ms") or 0)
            active_sm["pause_started_at_ms"] = active.get("pauseStartedAt") or active.get("pause_started_at_ms")
        return casino

    def build_reset_casino(self) -> Casino:
        casino = Casino(Doc())
        casino.balance["credits"] = 0
        casino.balance["tokens"] = 0
        for prize_id, prize in self._canonical.prizes.items():
            pm: Map = Map()
            casino.prizes[str(prize_id)] = pm
            pm["name"] = prize.get("name")
            pm["cost"] = int(prize.get("cost", 0))
        return casino

    def _ensure_initial_snapshot(self) -> None:
        with self._Session() as s, s.begin():
            existing = s.scalar(select(StateSnapshotRow).limit(1))
            if existing is None:
                s.add(self._snapshot_row("initial_authority_adoption", int(time.time() * 1000), None))

    def _snapshot_row(self, reason: str, now_ms: int, note: str | None) -> StateSnapshotRow:
        return StateSnapshotRow(
            server_at_ms=now_ms,
            reason=reason,
            doc_update_blob=self._canonical.get_update(),
            decoded_json=self._json(self._casino_json(self._canonical)),
            note=note,
        )

    def _game_event_row(
        self,
        *,
        client_event_id: str,
        server_at_ms: int,
        event: dict[str, Any],
        credits_before: int,
        credits_after: int,
        tokens_before: int,
        tokens_after: int,
        server_credits: int,
        server_tokens: int,
        rules_version: str,
        rng_version: str | None,
    ) -> GameEventRow:
        return GameEventRow(
            client_event_id=client_event_id,
            server_at_ms=server_at_ms,
            occurred_at_ms=server_at_ms,
            game=str(event["game"]),
            event_type="settle",
            source="server_resolved",
            wager_credits=int(event["wager_credits"]),
            payout_tokens=int(event["payout_tokens"]),
            credits_before=credits_before,
            credits_after=credits_after,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            server_credits=server_credits,
            server_tokens=server_tokens,
            outcome_json=self._json(event["outcome"]),
            rules_version=rules_version,
            rng_version=rng_version,
        )

    def _economy_fingerprint(self, casino: Casino) -> dict[str, Any]:
        return {
            "credits": self._credits(casino),
            "tokens": self._tokens(casino),
            "prize_log": [
                {
                    "id": entry.get("id"),
                    "name": entry.get("name"),
                    "cost": int(entry.get("cost", 0)),
                    "at_ms": int(entry.get("at_ms", 0)),
                }
                for entry in casino.prize_log
            ],
        }

    def _casino_json(self, casino: Casino) -> dict[str, Any]:
        return {
            "balance": {"credits": self._credits(casino), "tokens": self._tokens(casino)},
            "sessions": [dict(session.items()) | {"id": session_id} for session_id, session in casino.sessions.items()],
            "prizes": [
                {"id": prize_id, "name": prize.get("name"), "cost": int(prize.get("cost", 0))}
                for prize_id, prize in casino.prizes.items()
            ],
            "prize_log": [
                {
                    "id": entry.get("id"),
                    "name": entry.get("name"),
                    "cost": int(entry.get("cost", 0)),
                    "at_ms": int(entry.get("at_ms", 0)),
                }
                for entry in casino.prize_log
            ],
        }

    @staticmethod
    def _credits(casino: Casino) -> int:
        return int(casino.balance.get("credits", 0))

    @staticmethod
    def _tokens(casino: Casino) -> int:
        return int(casino.balance.get("tokens", 0))

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _prizes_from_import(data: dict[str, Any]) -> list[tuple[str, str, int]]:
        prizes = data.get("prizes")
        if prizes:
            return [
                (str(p.get("id") or f"p-{uuid.uuid4()}"), str(p.get("name") or "Imported prize"), int(p.get("cost", 1)))
                for p in prizes
            ]
        return DEFAULT_PRIZES


# Enable WAL on every pooled connection.
@event.listens_for(Engine, "connect")
def _sqlite_pragma_on_connect(dbapi_conn: Any, _record: Any) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()
