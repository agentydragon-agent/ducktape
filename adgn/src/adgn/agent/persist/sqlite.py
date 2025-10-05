from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
import json
from typing import Any, cast
import uuid

import aiosqlite

from . import AgentRow, ApprovalOutcome, EventType, Persistence, RunRow, RunStatus
from .events import EventRecord, parse_event

MAX_EVENT_PAYLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB hard limit per event payload


def _now() -> datetime:
    return datetime.now(UTC)


class SQLitePersistence(Persistence):
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    # Centralized connection helpers to keep row_factory consistent
    @asynccontextmanager
    async def _open(self):
        async with aiosqlite.connect(self.db_path) as db:
            # Enforce FK cascades on every connection
            await db.execute("PRAGMA foreign_keys = ON;")
            yield db

    @asynccontextmanager
    async def _open_row(self):
        async with aiosqlite.connect(self.db_path) as db:
            # Enforce FK cascades on every connection
            await db.execute("PRAGMA foreign_keys = ON;")
            db.row_factory = aiosqlite.Row
            yield db

    async def ensure_schema(self) -> None:
        """Create base tables if missing using the current schema.

        Note: This function does not implement versioned migrations. To apply
        schema changes, recreate the database or manage data migration outside
        this helper.
        """
        async with self._open() as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            # executescript allows multiple statements in one call
            await db.executescript(
                """
CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  specs TEXT NOT NULL,
  metadata TEXT
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  agent_id TEXT NULL REFERENCES agents(id) ON DELETE SET NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT NULL,
  status TEXT NOT NULL,
  system_message TEXT NULL,
  model TEXT NULL,
  model_params TEXT NULL,
  event_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_runs_agent_started ON runs(agent_id, started_at);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  ts TEXT NOT NULL,
  type TEXT NOT NULL,
  payload TEXT NOT NULL,
  call_id TEXT NULL,
  tool_key TEXT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_call ON events(call_id);
CREATE TABLE IF NOT EXISTS approvals (
  call_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  agent_id TEXT NULL REFERENCES agents(id) ON DELETE SET NULL,
  tool_key TEXT NOT NULL,
  outcome TEXT NOT NULL,
  decided_at TEXT NOT NULL,
  details TEXT NULL
);
CREATE INDEX IF NOT EXISTS idx_approvals_run_decided ON approvals(run_id, decided_at);
CREATE TABLE IF NOT EXISTS approval_policies (
  version INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policy_proposals (
  id TEXT NOT NULL,
  agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  rationale TEXT NULL,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL,
  decided_at TEXT NULL,
  PRIMARY KEY (agent_id, id)
);
                    """
            )
            await db.commit()

    # Agents -----------------------------------------------------------------
    async def create_agent(
        self, *, specs: dict[str, Any], metadata: dict[str, Any] | None = None
    ) -> str:
        agent_id = uuid.uuid4().hex
        async with self._open() as db:
            await db.execute(
                "INSERT INTO agents (id, created_at, specs, metadata) VALUES (?, ?, ?, ?)",
                (
                    agent_id,
                    _now().isoformat(),
                    json.dumps(specs),
                    json.dumps(metadata) if metadata else None,
                ),
            )
            await db.commit()
        return agent_id

    async def update_agent_specs(self, agent_id: str, *, specs: dict[str, Any]) -> None:
        async with self._open() as db:
            await db.execute(
                "UPDATE agents SET specs = ? WHERE id = ?",
                (json.dumps(specs), agent_id),
            )
            await db.commit()

    async def patch_agent_specs(
        self,
        agent_id: str,
        *,
        attach: dict[str, Any] | None = None,
        detach: list[str] | None = None,
    ) -> dict[str, Any]:
        attach = attach or {}
        detach = detach or []
        async with self._open_row() as db:
            async with db.execute("SELECT specs FROM agents WHERE id = ?", (agent_id,)) as cur:
                r = await cur.fetchone()
            if not r:
                raise KeyError(f"agent not found: {agent_id}")
            specs = cast(dict[str, Any], json.loads(r["specs"])) if r["specs"] else {}
            # apply detach first
            for name in detach:
                specs.pop(name, None)
            # then attach/replace entries
            for name, spec in attach.items():
                specs[name] = spec
            await db.execute(
                "UPDATE agents SET specs = ? WHERE id = ?",
                (json.dumps(specs), agent_id),
            )
            await db.commit()
        return cast(dict[str, Any], specs)

    async def list_agents(self) -> list[AgentRow]:
        out: list[AgentRow] = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, created_at, specs, metadata FROM agents ORDER BY created_at DESC"
            ) as cur:
                async for r in cur:
                    out.append(
                        AgentRow(
                            id=r["id"],
                            created_at=datetime.fromisoformat(r["created_at"]),
                            specs=json.loads(r["specs"]) if r["specs"] else {},
                            metadata=json.loads(r["metadata"]) if r["metadata"] else None,
                        )
                    )
        return out

    async def get_agent(self, agent_id: str) -> AgentRow | None:
        async with self._open_row() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id, created_at, specs, metadata FROM agents WHERE id = ?",
                (agent_id,),
            )
            r = await cur.fetchone()
            if not r:
                return None
            return AgentRow(
                id=r["id"],
                created_at=datetime.fromisoformat(r["created_at"]),
                specs=json.loads(r["specs"]) if r["specs"] else {},
                metadata=json.loads(r["metadata"]) if r["metadata"] else None,
            )

    async def list_agents_last_activity(self) -> dict[str, datetime | None]:
        """Return a mapping of agent_id -> last activity timestamp (UTC) or None.

        Activity considers any of: event ts, run finished_at, run started_at, or
        agent created_at as a fallback, taking the maximum.
        """
        out: dict[str, datetime | None] = {}
        async with self._open_row() as db:
            async with db.execute(
                (
                    """
SELECT a.id as agent_id,
       MAX(
         COALESCE(e.ts, r.finished_at, r.started_at, a.created_at)
       ) as last_ts
FROM agents a
LEFT JOIN runs r ON r.agent_id = a.id
LEFT JOIN events e ON e.run_id = r.id
GROUP BY a.id
                    """
                )
            ) as cur:
                async for r in cur:
                    ts = r["last_ts"]
                    out[r["agent_id"]] = datetime.fromisoformat(ts) if ts is not None else None
        return out

    async def delete_agent(self, agent_id: str) -> None:
        """Delete an agent and all associated records.

        Always purges related runs (and cascaded events/approvals) and deletes
        the agent row (cascading to approval_policies/policy_proposals).
        """
        async with self._open() as db:
            # Single transaction for atomicity
            await db.execute("BEGIN;")
            # Purge runs first; events/approvals cascade from runs
            await db.execute("DELETE FROM runs WHERE agent_id = ?", (agent_id,))
            # Delete agent; policies/proposals cascade from agents
            await db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
            await db.commit()

    # ---- Approval policy (per-agent) ---------------------------------------
    async def get_latest_policy(self, agent_id: str) -> tuple[str, int] | None:
        """Return (content, version) of the latest approval policy for the agent, or None."""
        async with self._open_row() as db:
            async with db.execute(
                """
SELECT content, version
FROM approval_policies
WHERE agent_id = ?
ORDER BY version DESC
LIMIT 1
                """,
                (agent_id,),
            ) as cur:
                row = await cur.fetchone()
                if not row:
                    return None
                return (cast(str, row["content"]), int(row["version"]))

    async def set_policy(self, agent_id: str, *, content: str) -> int:
        """Persist a new policy version for agent; returns assigned version."""
        async with self._open() as db:
            await db.execute(
                "INSERT INTO approval_policies (agent_id, content, created_at) VALUES (?, ?, ?)",
                (agent_id, content, _now().isoformat()),
            )
            # In SQLite, last_insert_rowid() returns the INTEGER PRIMARY KEY value for this connection
            cur = await db.execute("SELECT last_insert_rowid();")
            row = await cur.fetchone()
            await db.commit()
            return int(row[0]) if row and row[0] is not None else 0

    async def create_proposal(
        self,
        agent_id: str,
        *,
        proposal_id: str,
        source: str,
        rationale: str | None,
        created_at: datetime,
    ) -> None:
        async with self._open() as db:
            await db.execute(
                """
INSERT INTO policy_proposals (id, agent_id, status, rationale, source, created_at, decided_at)
VALUES (?, ?, 'open', ?, ?, ?, NULL)
                """,
                (
                    proposal_id,
                    agent_id,
                    rationale,
                    source,
                    created_at.isoformat(),
                ),
            )
            await db.commit()

    async def set_proposal_status(
        self,
        agent_id: str,
        *,
        proposal_id: str,
        status: str,
        decided_at: datetime | None,
    ) -> None:
        async with self._open() as db:
            await db.execute(
                """
UPDATE policy_proposals
SET status = ?, decided_at = ?
WHERE id = ? AND agent_id = ?
                """,
                (
                    status,
                    decided_at.isoformat() if decided_at else None,
                    proposal_id,
                    agent_id,
                ),
            )
            await db.commit()

    async def list_proposals(self, agent_id: str) -> list[dict[str, Any]]:
        async with self._open_row() as db:
            async with db.execute(
                """
SELECT id, status, rationale, source, created_at, decided_at
FROM policy_proposals
WHERE agent_id = ?
ORDER BY created_at ASC
                """,
                (agent_id,),
            ) as cur:
                rows = await cur.fetchall()
                out: list[dict[str, Any]] = []
                for r in rows:
                    out.append(
                        {
                            "id": r["id"],
                            "status": r["status"],
                            "rationale": r["rationale"],
                            "source": r["source"],
                            "created_at": r["created_at"],
                            "decided_at": r["decided_at"],
                        }
                    )
                return out

    # Runs --------------------------------------------------------------------
    async def start_run(
        self,
        *,
        run_id: str,
        agent_id: str | None,
        system_message: str | None,
        model: str | None,
        model_params: dict[str, Any] | None,
        started_at: datetime,
    ) -> None:
        async with self._open() as db:
            await db.execute(
                """
INSERT INTO runs (id, agent_id, started_at, finished_at, status, system_message, model, model_params, event_count)
VALUES (?, ?, ?, NULL, 'running', ?, ?, ?, 0)
                """,
                (
                    run_id,
                    agent_id,
                    started_at.isoformat(),
                    system_message,
                    model,
                    json.dumps(model_params) if model_params else None,
                ),
            )
            await db.commit()

    async def finish_run(self, run_id: str, *, status: RunStatus, finished_at: datetime) -> None:
        async with self._open() as db:
            await db.execute(
                "UPDATE runs SET status = ?, finished_at = ? WHERE id = ?",
                (status.value, finished_at.isoformat(), run_id),
            )
            await db.commit()

    async def append_event(
        self,
        *,
        run_id: str,
        seq: int,
        ts: datetime,
        type: EventType,
        payload: dict[str, Any],
        call_id: str | None = None,
        tool_key: str | None = None,
    ) -> None:
        # Apply hard limit per event payload (serialized JSON)
        s = json.dumps(payload, ensure_ascii=False)
        if len(s.encode("utf-8")) > MAX_EVENT_PAYLOAD_BYTES:
            raise ValueError(f"event payload exceeds {MAX_EVENT_PAYLOAD_BYTES} bytes")
        async with self._open() as db:
            await db.execute(
                "INSERT INTO events (run_id, seq, ts, type, payload, call_id, tool_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, seq, ts.isoformat(), type.value, s, call_id, tool_key),
            )
            await db.execute(
                "UPDATE runs SET event_count = event_count + 1 WHERE id = ?",
                (run_id,),
            )
            await db.commit()

    async def record_approval(
        self,
        *,
        run_id: str,
        agent_id: str | None,
        call_id: str,
        tool_key: str,
        outcome: ApprovalOutcome,
        decided_at: datetime,
        details: dict[str, Any] | None = None,
    ) -> None:
        async with self._open() as db:
            await db.execute(
                """
INSERT OR REPLACE INTO approvals (call_id, run_id, agent_id, tool_key, outcome, decided_at, details)
VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    call_id,
                    run_id,
                    agent_id,
                    tool_key,
                    outcome.value,
                    decided_at.isoformat(),
                    json.dumps(details) if details else None,
                ),
            )
            await db.commit()

    async def list_runs(self, *, agent_id: str | None = None, limit: int = 50) -> list[RunRow]:
        params: list[Any] = []
        where = ""
        if agent_id:
            where = "WHERE agent_id = ?"
            params.append(agent_id)
        sql = f"SELECT id, agent_id, started_at, finished_at, status, system_message, model, model_params, event_count FROM runs {where} ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        out: list[RunRow] = []
        async with self._open_row() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params) as cur:
                async for r in cur:
                    out.append(
                        RunRow(
                            id=r["id"],
                            agent_id=r["agent_id"],
                            started_at=datetime.fromisoformat(r["started_at"]),
                            finished_at=datetime.fromisoformat(r["finished_at"])
                            if r["finished_at"]
                            else None,
                            status=RunStatus(r["status"]),
                            system_message=r["system_message"],
                            model=r["model"],
                            model_params=json.loads(r["model_params"])
                            if r["model_params"]
                            else None,
                            event_count=int(r["event_count"] or 0),
                        )
                    )
        return out

    async def get_run(self, run_id: str) -> RunRow | None:
        async with self._open_row() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id, agent_id, started_at, finished_at, status, system_message, model, model_params, event_count FROM runs WHERE id = ?",
                (run_id,),
            )
            r = await cur.fetchone()
            if not r:
                return None
            return RunRow(
                id=r["id"],
                agent_id=r["agent_id"],
                started_at=datetime.fromisoformat(r["started_at"]),
                finished_at=datetime.fromisoformat(r["finished_at"]) if r["finished_at"] else None,
                status=RunStatus(r["status"]),
                system_message=r["system_message"],
                model=r["model"],
                model_params=json.loads(r["model_params"]) if r["model_params"] else None,
                event_count=int(r["event_count"] or 0),
            )

    async def load_events(self, run_id: str) -> list[EventRecord]:
        out: list[EventRecord] = []
        async with self._open_row() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT seq, ts, type, payload, call_id, tool_key FROM events WHERE run_id = ? ORDER BY seq ASC",
                (run_id,),
            ) as cur:
                async for r in cur:
                    out.append(
                        parse_event(
                            {
                                "seq": int(r["seq"]),
                                "ts": r["ts"],
                                "type": r["type"],
                                "payload": json.loads(r["payload"]) if r["payload"] else {},
                                "call_id": r["call_id"],
                                "tool_key": r["tool_key"],
                            }
                        )
                    )
        return out
