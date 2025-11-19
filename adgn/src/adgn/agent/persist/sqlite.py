from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, cast
import uuid
from uuid import UUID

import aiosqlite
from fastmcp.mcp_config import MCPConfig
from pydantic import JsonValue, TypeAdapter

from adgn.agent.persist import Policy, PolicyProposal
from adgn.agent.runtime.auto_attach import filter_persistable_servers
from adgn.agent.types import AgentID

from . import (
    AgentMetadata,
    AgentRow,
    Decision,
    EventType,
    Persistence,
    RunRow,
    RunStatus,
    ToolCall,
    ToolCallExecution,
    ToolCallRecord,
)
from .events import EventRecord, parse_event

MAX_EVENT_PAYLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB hard limit per event payload


def _now() -> datetime:
    return datetime.now(UTC)


class SQLitePersistence(Persistence):
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    # Centralized connection helpers to keep row_factory consistent
    @asynccontextmanager
    async def _open(self):
        async with aiosqlite.connect(self.db_path) as db:
            # Enforce FK cascades on every connection
            await db.execute("PRAGMA foreign_keys = ON;")
            db.row_factory = aiosqlite.Row
            yield db

    @asynccontextmanager
    async def _db_connection(self):
        async with aiosqlite.connect(self.db_path) as db:
            # Enforce FK cascades on every connection
            await db.execute("PRAGMA foreign_keys = ON;")
            db.row_factory = aiosqlite.Row
            yield db

    async def ensure_schema(self) -> None:
        """Create base tables using the current schema.

        Drops old schema_version and approvals tables without versioning.
        Creates new tool_calls table for ToolCallRecord persistence.
        Maintains approval_policies for backward compatibility but adds new
        policies and policy_history tables for enhanced state management.
        """
        async with self._open() as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            # executescript allows multiple statements in one call
            await db.executescript(
                """
-- Drop old tables (no versioning, no backward compatibility)
DROP TABLE IF EXISTS schema_version;
DROP TABLE IF EXISTS approvals;

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
CREATE TABLE IF NOT EXISTS tool_calls (
  call_id TEXT PRIMARY KEY,
  run_id TEXT NULL REFERENCES runs(id) ON DELETE CASCADE,
  agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  tool_call_json TEXT NOT NULL,
  decision_json TEXT NULL,
  execution_json TEXT NULL,
  created_at TEXT NOT NULL,
  decided_at TEXT NULL,
  completed_at TEXT NULL
);
CREATE INDEX IF NOT EXISTS idx_tool_calls_run ON tool_calls(run_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_agent ON tool_calls(agent_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_decided ON tool_calls(decided_at);
CREATE TABLE IF NOT EXISTS approval_policies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policies (
  id TEXT PRIMARY KEY,
  text TEXT NOT NULL,
  description TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policy_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  policy_id TEXT NOT NULL,
  text TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by TEXT,
  FOREIGN KEY (policy_id) REFERENCES policies(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_policy_history_policy ON policy_history(policy_id);
CREATE INDEX IF NOT EXISTS idx_policy_history_updated ON policy_history(updated_at);
CREATE TABLE IF NOT EXISTS policy_proposals (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  decided_at TEXT NULL
);
-- Chat: messages and per-server last-read (HWM)
CREATE TABLE IF NOT EXISTS chat_messages (
  agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  author TEXT NOT NULL,
  mime TEXT NOT NULL,
  content TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_agent ON chat_messages(agent_id);
CREATE TABLE IF NOT EXISTS chat_last_read (
  agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  server_name TEXT NOT NULL,
  last_id INTEGER NULL,
  PRIMARY KEY (agent_id, server_name)
);
                    """
            )
            await db.commit()

    # Agents -----------------------------------------------------------------
    async def create_agent(self, *, mcp_config: MCPConfig, metadata: AgentMetadata) -> AgentID:
        agent_id = AgentID(uuid.uuid4().hex)
        async with self._open() as db:
            # Persist only user-configured servers (exclude default auto-attached)
            spec_json = filter_persistable_servers(mcp_config).model_dump(mode="json")
            await db.execute(
                "INSERT INTO agents (id, created_at, specs, metadata) VALUES (?, ?, ?, ?)",
                (agent_id, _now().isoformat(), json.dumps(spec_json), json.dumps(metadata.model_dump())),
            )
            await db.commit()
        return agent_id

    async def update_agent_specs(self, agent_id: AgentID, *, mcp_config: MCPConfig) -> None:
        async with self._open() as db:
            spec_json = filter_persistable_servers(mcp_config).model_dump(mode="json")
            await db.execute("UPDATE agents SET specs = ? WHERE id = ?", (json.dumps(spec_json), agent_id))
            await db.commit()

    async def patch_agent_specs(
        self, agent_id: AgentID, *, attach: dict[str, MCPConfig] | None = None, detach: list[str] | None = None
    ) -> MCPConfig:
        attach = attach or {}
        detach = detach if detach is not None else []
        async with self._db_connection() as db:
            async with db.execute("SELECT specs FROM agents WHERE id = ?", (agent_id,)) as cur:
                r = await cur.fetchone()
            if not r:
                raise KeyError(f"agent not found: {agent_id}")
            # Load persisted JSON and rehydrate to MCPConfig
            cfg = MCPConfig.model_validate(json.loads(r["specs"])) if r["specs"] else MCPConfig()
            # Apply detach
            for name in detach:
                cfg.mcpServers.pop(name, None)
            # Apply attach: when given a whole config per name, merge servers
            for _name, subcfg in attach.items():
                # Runtime assertion: values must be MCPConfig per typed API
                assert isinstance(subcfg, MCPConfig), "attach values must be MCPConfig instances"
                # Merge all entries from the provided config
                for k, v in subcfg.mcpServers.items():
                    cfg.mcpServers[k] = v
            await self.update_agent_specs(agent_id, mcp_config=cfg)
        return cfg

    async def list_agents(self) -> list[AgentRow]:
        out: list[AgentRow] = []
        async with (
            self._db_connection() as db,
            db.execute("SELECT id, created_at, specs, metadata FROM agents ORDER BY created_at DESC") as cur,
        ):
            async for r in cur:
                meta_val = AgentMetadata.model_validate_json(cast(str, r["metadata"]))
                out.append(
                    AgentRow(
                        id=AgentID(r["id"]),
                        created_at=datetime.fromisoformat(r["created_at"]),
                        mcp_config=MCPConfig.model_validate(json.loads(r["specs"])) if r["specs"] else MCPConfig(),
                        metadata=meta_val,
                    )
                )
        return out

    async def get_agent(self, agent_id: AgentID) -> AgentRow | None:
        async with self._db_connection() as db:
            cur = await db.execute("SELECT id, created_at, specs, metadata FROM agents WHERE id = ?", (agent_id,))
            r = await cur.fetchone()
            if not r:
                return None
            meta_val = AgentMetadata.model_validate_json(cast(str, r["metadata"]))
            return AgentRow(
                id=AgentID(r["id"]),
                created_at=datetime.fromisoformat(r["created_at"]),
                mcp_config=MCPConfig.model_validate(json.loads(r["specs"])) if r["specs"] else MCPConfig(),
                metadata=meta_val,
            )

    async def list_agents_last_activity(self) -> dict[AgentID, datetime | None]:
        """Return a mapping of agent_id -> last activity timestamp (UTC) or None.

        Activity considers any of: event ts, run finished_at, run started_at, or
        agent created_at as a fallback, taking the maximum.
        """
        out: dict[AgentID, datetime | None] = {}
        async with (
            self._db_connection() as db,
            db.execute(
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
            ) as cur,
        ):
            async for r in cur:
                ts = r["last_ts"]
                out[AgentID(r["agent_id"])] = datetime.fromisoformat(ts) if ts is not None else None
        return out

    async def delete_agent(self, agent_id: AgentID) -> None:
        """Delete an agent and all associated records.

        Always purges related runs (and cascaded events/approvals) and deletes
        the agent row (cascading to approval_policies).
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
    async def get_latest_policy(self, agent_id: AgentID) -> tuple[str, int] | None:
        """Return (content, id) of the latest approval policy for the agent, or None."""
        async with (
            self._db_connection() as db,
            db.execute(
                """
SELECT content, id
FROM approval_policies
WHERE agent_id = ?
ORDER BY id DESC
LIMIT 1
                """,
                (agent_id,),
            ) as cur,
        ):
            row = await cur.fetchone()
            if not row:
                return None
            return (cast(str, row["content"]), int(row["id"]))

    async def set_policy(self, agent_id: AgentID, *, content: str) -> int:
        """Persist a new policy for agent; returns assigned id."""
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

    # ---- Policy proposals (single-store: SQLite) ----------------------------
    async def create_policy_proposal(self, agent_id: AgentID, *, proposal_id: str, content: str) -> None:
        async with self._open() as db:
            await db.execute(
                """
INSERT INTO policy_proposals (id, agent_id, content, status, created_at, decided_at)
VALUES (?, ?, ?, 'pending', ?, NULL)
                """,
                (proposal_id, agent_id, content, _now().isoformat()),
            )
            await db.commit()

    async def list_policy_proposals(self, agent_id: AgentID) -> list[PolicyProposal]:
        async with self._db_connection() as db:
            out: list[PolicyProposal] = []
            async with db.execute(
                """
SELECT id, status, created_at, decided_at
FROM policy_proposals
WHERE agent_id = ?
ORDER BY created_at DESC
                """,
                (agent_id,),
            ) as cur:
                async for row in cur:
                    out.append(
                        PolicyProposal(
                            id=str(row["id"]),
                            status=str(row["status"]),
                            created_at=datetime.fromisoformat(cast(str, row["created_at"])),
                            decided_at=(
                                datetime.fromisoformat(cast(str, row["decided_at"])) if row["decided_at"] else None
                            ),
                            content="",  # content not selected in list; leave empty
                        )
                    )
        return out

    async def get_policy_proposal(self, agent_id: AgentID, proposal_id: str) -> PolicyProposal | None:
        async with (
            self._db_connection() as db,
            db.execute(
                """
SELECT id, status, created_at, decided_at, content
FROM policy_proposals
WHERE agent_id = ? AND id = ?
                """,
                (agent_id, proposal_id),
            ) as cur,
        ):
            row = await cur.fetchone()
            if not row:
                return None
            return PolicyProposal(
                id=str(row["id"]),
                status=str(row["status"]),
                created_at=datetime.fromisoformat(cast(str, row["created_at"])),
                decided_at=(datetime.fromisoformat(cast(str, row["decided_at"])) if row["decided_at"] else None),
                content=cast(str, row["content"]),
            )

    async def approve_policy_proposal(self, agent_id: AgentID, proposal_id: str) -> int:
        """Mark proposal approved and persist content as new active policy.

        Returns the new active policy id.
        """
        # Read proposal content
        async with (
            self._db_connection() as db,
            db.execute(
                "SELECT content FROM policy_proposals WHERE agent_id = ? AND id = ?", (agent_id, proposal_id)
            ) as cur,
        ):
            row = await cur.fetchone()
            if not row:
                raise KeyError("proposal_not_found")
            content = cast(str, row["content"])
        # Persist as active policy and mark proposal approved in one transaction
        async with self._open() as db:
            await db.execute(
                "INSERT INTO approval_policies (agent_id, content, created_at) VALUES (?, ?, ?)",
                (agent_id, content, _now().isoformat()),
            )
            await db.execute(
                "UPDATE policy_proposals SET status = 'approved', decided_at = ? WHERE agent_id = ? AND id = ?",
                (_now().isoformat(), agent_id, proposal_id),
            )
            cur = await db.execute("SELECT last_insert_rowid();")
            row = await cur.fetchone()
            await db.commit()
            return int(row[0]) if row and row[0] is not None else 0

    async def reject_policy_proposal(self, agent_id: AgentID, proposal_id: str) -> None:
        async with self._open() as db:
            await db.execute(
                "UPDATE policy_proposals SET status = 'rejected', decided_at = ? WHERE agent_id = ? AND id = ?",
                (_now().isoformat(), agent_id, proposal_id),
            )
            await db.commit()

    # Seatbelt templates are volume-backed via Docker; no DB APIs in final shape

    # Runs --------------------------------------------------------------------
    async def start_run(
        self,
        *,
        run_id: UUID,
        agent_id: AgentID,
        system_message: str | None,
        model: str | None,
        model_params: dict[str, JsonValue] | None,
        started_at: datetime,
    ) -> None:
        async with self._open() as db:
            await db.execute(
                """
INSERT INTO runs (id, agent_id, started_at, finished_at, status, system_message, model, model_params, event_count)
VALUES (?, ?, ?, NULL, 'running', ?, ?, ?, 0)
                """,
                (
                    str(run_id),
                    agent_id,
                    started_at.isoformat(),
                    system_message,
                    model,
                    json.dumps(model_params) if model_params else None,
                ),
            )
            await db.commit()

    async def finish_run(self, run_id: UUID, *, status: RunStatus, finished_at: datetime) -> None:
        async with self._open() as db:
            await db.execute(
                "UPDATE runs SET status = ?, finished_at = ? WHERE id = ?",
                (status.value, finished_at.isoformat(), str(run_id)),
            )
            await db.commit()

    async def append_event(
        self,
        *,
        run_id: UUID,
        seq: int,
        ts: datetime,
        type: EventType,
        payload: dict[str, JsonValue],
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
                (str(run_id), seq, ts.isoformat(), type.value, s, call_id, tool_key),
            )
            await db.execute("UPDATE runs SET event_count = event_count + 1 WHERE id = ?", (str(run_id),))
            await db.commit()

    async def list_runs(self, *, agent_id: AgentID | None = None, limit: int = 50) -> list[RunRow]:
        params: list[object] = []
        where = ""
        if agent_id:
            where = "WHERE agent_id = ?"
            params.append(agent_id)
        sql = f"SELECT id, agent_id, started_at, finished_at, status, system_message, model, model_params, event_count FROM runs {where} ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        out: list[RunRow] = []
        async with self._db_connection() as db, db.execute(sql, params) as cur:
            async for r in cur:
                out.append(
                    RunRow(
                        id=UUID(r["id"]),
                        agent_id=AgentID(r["agent_id"]),
                        started_at=datetime.fromisoformat(r["started_at"]),
                        finished_at=datetime.fromisoformat(r["finished_at"]) if r["finished_at"] else None,
                        status=RunStatus(r["status"]),
                        system_message=r["system_message"],
                        model=r["model"],
                        model_params=json.loads(r["model_params"]) if r["model_params"] else None,
                        event_count=int(r["event_count"] or 0),
                    )
                )
        return out

    async def get_run(self, run_id: UUID) -> RunRow | None:
        async with self._db_connection() as db:
            cur = await db.execute(
                "SELECT id, agent_id, started_at, finished_at, status, system_message, model, model_params, event_count FROM runs WHERE id = ?",
                (str(run_id),),
            )
            r = await cur.fetchone()
            if not r:
                return None
            return RunRow(
                id=UUID(r["id"]),
                agent_id=AgentID(r["agent_id"]),
                started_at=datetime.fromisoformat(r["started_at"]),
                finished_at=datetime.fromisoformat(r["finished_at"]) if r["finished_at"] else None,
                status=RunStatus(r["status"]),
                system_message=r["system_message"],
                model=r["model"],
                model_params=json.loads(r["model_params"]) if r["model_params"] else None,
                event_count=int(r["event_count"] or 0),
            )

    async def load_events(self, run_id: UUID) -> list[EventRecord]:
        out: list[EventRecord] = []
        async with (
            self._db_connection() as db,
            db.execute(
                "SELECT seq, ts, type, payload, call_id, tool_key FROM events WHERE run_id = ? ORDER BY seq ASC",
                (str(run_id),),
            ) as cur,
        ):
            async for r in cur:
                # Parse event using raw row data; use Pydantic for JSON payload parsing
                row_dict = dict(r)
                if r["payload"]:
                    row_dict["payload"] = TypeAdapter(dict[str, Any]).validate_json(r["payload"])
                else:
                    row_dict["payload"] = {}
                out.append(parse_event(row_dict))
        return out

    # Tool Calls (new ToolCallRecord persistence) --------------------------------
    async def save_tool_call(self, record: ToolCallRecord) -> None:
        """Save or update a tool call record."""
        async with self._open() as db:
            # Serialize nested Pydantic models to JSON
            tool_call_json = record.tool_call.model_dump_json()
            decision_json = record.decision.model_dump_json() if record.decision else None
            execution_json = record.execution.model_dump_json() if record.execution else None

            # Extract timestamps
            created_at = _now().isoformat()
            decided_at = record.decision.decided_at.isoformat() if record.decision else None
            completed_at = record.execution.completed_at.isoformat() if record.execution else None

            await db.execute(
                """
                INSERT OR REPLACE INTO tool_calls (
                    call_id, run_id, agent_id,
                    tool_call_json, decision_json, execution_json,
                    created_at, decided_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.call_id,
                    record.run_id,
                    record.agent_id,
                    tool_call_json,
                    decision_json,
                    execution_json,
                    created_at,
                    decided_at,
                    completed_at,
                ),
            )
            await db.commit()

    async def get_tool_call(self, call_id: str) -> ToolCallRecord | None:
        """Get a tool call record by call_id."""
        async with self._db_connection() as db:
            cur = await db.execute(
                """
                SELECT call_id, run_id, agent_id,
                       tool_call_json, decision_json, execution_json
                FROM tool_calls WHERE call_id = ?
                """,
                (call_id,),
            )
            r = await cur.fetchone()
            if not r:
                return None

            # Deserialize JSON to Pydantic models
            tool_call = ToolCall.model_validate_json(r["tool_call_json"])
            decision = Decision.model_validate_json(r["decision_json"]) if r["decision_json"] else None
            execution = ToolCallExecution.model_validate_json(r["execution_json"]) if r["execution_json"] else None

            return ToolCallRecord(
                call_id=r["call_id"],
                run_id=r["run_id"],
                agent_id=AgentID(r["agent_id"]),
                tool_call=tool_call,
                decision=decision,
                execution=execution,
            )

    async def list_tool_calls(self, run_id: str | None = None) -> list[ToolCallRecord]:
        """List tool call records, optionally filtered by run_id."""
        out: list[ToolCallRecord] = []
        async with self._db_connection() as db:
            if run_id:
                sql = """
                    SELECT call_id, run_id, agent_id,
                           tool_call_json, decision_json, execution_json
                    FROM tool_calls WHERE run_id = ?
                    ORDER BY created_at ASC
                """
                params: tuple[str, ...] = (run_id,)
            else:
                sql = """
                    SELECT call_id, run_id, agent_id,
                           tool_call_json, decision_json, execution_json
                    FROM tool_calls
                    ORDER BY created_at ASC
                """
                params = ()

            async with db.execute(sql, params) as cur:
                async for r in cur:
                    # Deserialize JSON to Pydantic models
                    tool_call = ToolCall.model_validate_json(r["tool_call_json"])
                    decision = Decision.model_validate_json(r["decision_json"]) if r["decision_json"] else None
                    execution = (
                        ToolCallExecution.model_validate_json(r["execution_json"]) if r["execution_json"] else None
                    )

                    out.append(
                        ToolCallRecord(
                            call_id=r["call_id"],
                            run_id=r["run_id"],
                            agent_id=AgentID(r["agent_id"]),
                            tool_call=tool_call,
                            decision=decision,
                            execution=execution,
                        )
                    )
        return out

    # Policy state management (new enhanced API) ---------------------------------
    async def create_policy(
        self, *, policy_id: str, text: str, description: str | None = None, enabled: bool = True
    ) -> Policy:
        """Create a new policy and save initial version to history."""
        now = _now()
        async with self._open() as db:
            await db.execute(
                """
                INSERT INTO policies (id, text, description, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (policy_id, text, description, 1 if enabled else 0, now.isoformat(), now.isoformat()),
            )
            # Record initial version in history
            await db.execute(
                """
                INSERT INTO policy_history (policy_id, text, updated_at, updated_by)
                VALUES (?, ?, ?, ?)
                """,
                (policy_id, text, now.isoformat(), None),
            )
            await db.commit()
        return Policy(id=policy_id, text=text, description=description, enabled=enabled, created_at=now, updated_at=now)

    async def get_policy(self, policy_id: str) -> Policy | None:
        """Get a policy by ID."""
        async with (
            self._db_connection() as db,
            db.execute(
                """
                SELECT id, text, description, enabled, created_at, updated_at
                FROM policies
                WHERE id = ?
                """,
                (policy_id,),
            ) as cur,
        ):
            row = await cur.fetchone()
            if not row:
                return None
            return Policy(
                id=str(row["id"]),
                text=str(row["text"]),
                description=str(row["description"]) if row["description"] else None,
                enabled=bool(row["enabled"]),
                created_at=datetime.fromisoformat(cast(str, row["created_at"])),
                updated_at=datetime.fromisoformat(cast(str, row["updated_at"])),
            )

    async def update_policy(self, policy_id: str, *, text: str, description: str | None = None) -> Policy:
        """Update policy text and description, saving old version to history."""
        now = _now()
        async with self._open() as db:
            # Get current policy to save to history
            cur = await db.execute("SELECT text FROM policies WHERE id = ?", (policy_id,))
            row = await cur.fetchone()
            if not row:
                raise KeyError(f"Policy not found: {policy_id}")
            old_text = row[0]

            # Save old version to history
            await db.execute(
                """
                INSERT INTO policy_history (policy_id, text, updated_at, updated_by)
                VALUES (?, ?, ?, ?)
                """,
                (policy_id, old_text, now.isoformat(), None),
            )

            # Update current policy
            await db.execute(
                """
                UPDATE policies
                SET text = ?, description = ?, updated_at = ?
                WHERE id = ?
                """,
                (text, description, now.isoformat(), policy_id),
            )
            await db.commit()

        # Fetch and return updated policy
        result = await self.get_policy(policy_id)
        if result is None:
            raise RuntimeError(f"Policy disappeared after update: {policy_id}")
        return result

    async def list_policies(self, *, offset: int = 0, limit: int = 100) -> list[Policy]:
        """List policies with pagination."""
        out: list[Policy] = []
        async with (
            self._db_connection() as db,
            db.execute(
                """
                SELECT id, text, description, enabled, created_at, updated_at
                FROM policies
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ) as cur,
        ):
            async for row in cur:
                out.append(
                    Policy(
                        id=str(row["id"]),
                        text=str(row["text"]),
                        description=str(row["description"]) if row["description"] else None,
                        enabled=bool(row["enabled"]),
                        created_at=datetime.fromisoformat(cast(str, row["created_at"])),
                        updated_at=datetime.fromisoformat(cast(str, row["updated_at"])),
                    )
                )
        return out

    async def delete_policy(self, policy_id: str) -> None:
        """Delete a policy and its history."""
        async with self._open() as db:
            await db.execute("DELETE FROM policies WHERE id = ?", (policy_id,))
            await db.commit()
