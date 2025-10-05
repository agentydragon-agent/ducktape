from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
from typing import Any, Callable, cast

from adgn.agent.agent import MiniCodex
from adgn.agent.approvals import ApprovalHub, ApprovalPolicyEngine, Proposal
from adgn.agent.mcp_manager import McpManager, SamplingSnapshot
from adgn.agent.persist import ApprovalOutcome, Persistence
from adgn.agent.persist.handler import RunPersistenceHandler
from adgn.agent.runtime.specs import McpServerSpec
from adgn.agent.server.bus import ServerBus
from adgn.agent.server.history import fold_events_to_ui_state
from adgn.agent.server.runtime import AgentSession, ConnectionManager
from adgn.agent.server.system_message import get_ui_system_message
from adgn.mcp.approval_policy.server import ApprovalPolicyServer
from adgn.mcp.inproc_transport import make_inproc_slot_spec
from adgn.mcp.ui.server import make_ui_mcp
from adgn.openai_utils.client_factory import build_client
from adgn.openai_utils.model import OpenAIModelProto

from .handlers import build_handlers

logger = logging.getLogger(__name__)


@dataclass
class UiFacet:
    manager: ConnectionManager
    ui_bus: ServerBus


@dataclass
class AgentContainer:
    """Actor-owned container that manages MCP + Agent lifecycles in a single task.

    After start, the following fields are populated: mcp, session, agent, persist_handler, ui, approval_engine, approval_hub.
    """

    agent_id: str
    persistence: Persistence
    model: str
    with_ui: bool = True

    # Populated after Start
    mcp: McpManager | None = None
    approval_engine: ApprovalPolicyEngine | None = None
    approval_hub: ApprovalHub | None = None
    session: AgentSession | None = None
    agent: MiniCodex | None = None
    persist_handler: RunPersistenceHandler | None = None
    ui: UiFacet | None = None
    # Optional system prompt override (e.g., from preset)
    system_override: str | None = None
    # Optional DI: override model factory
    client_factory: Callable[[str], OpenAIModelProto] | None = None

    # Actor internals
    _mailbox: asyncio.Queue[tuple[str, dict, asyncio.Future]] = field(
        default_factory=asyncio.Queue, init=False
    )
    _actor_task: asyncio.Task | None = field(default=None, init=False)
    _ready: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _closed: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    # Internal helpers/state
    _cm: ConnectionManager | None = field(default=None, init=False)
    _ui_bus: ServerBus | None = field(default=None, init=False)

    def _ensure_actor(self) -> None:
        if self._actor_task is None:
            self._actor_task = asyncio.create_task(self._actor_loop())

    async def _post(self, op: str, **kwargs: Any) -> Any:
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        await self._mailbox.put((op, kwargs, fut))
        return await fut

    async def start(self, *, specs: dict[str, McpServerSpec]) -> None:
        self._ensure_actor()
        await self._post("start", specs=specs)
        await self._ready.wait()

    async def close(self) -> dict[str, Any]:
        if self._actor_task is None:
            return {"drained": True}
        result = await self._post("close")
        await self._closed.wait()
        try:
            return result if isinstance(result, dict) else {"drained": True}
        except Exception:
            return {"drained": True}

    async def reconfigure_mcp(
        self,
        *,
        specs: dict[str, McpServerSpec] | None = None,
        attach: dict[str, McpServerSpec] | None = None,
        detach: list[str] | None = None,
    ) -> None:
        await self._post("reconfigure", specs=specs, attach=attach, detach=detach)

    async def sampling_snapshot(self) -> SamplingSnapshot | None:
        """Return a structured snapshot of servers/tools via the actor."""
        return cast(SamplingSnapshot | None, await self._post("sampling_snapshot"))

    async def sampling_snapshot_incremental(self) -> None:
        """Start streaming sampling snapshots as MCP servers initialize."""
        await self._post("sampling_snapshot_incremental")

    async def record_policy_outcome(
        self, call_id: str, tool_key: str, outcome: ApprovalOutcome
    ) -> None:
        if self.session is None:
            return
        run_id = self.session.active_run.run_id if self.session.active_run else None
        if not run_id:
            return
        await self.persistence.record_approval(
            run_id=run_id,
            agent_id=None,
            call_id=call_id,
            tool_key=tool_key,
            outcome=outcome,
            decided_at=datetime.now(UTC),
        )

    async def _attach_inproc_servers(self, mcp: McpManager, ui_bus: ServerBus | None) -> None:
        if self.with_ui and ui_bus is not None:
            await mcp.attach_server("ui", make_inproc_slot_spec(make_ui_mcp("ui", ui_bus)))
        engine = self.approval_engine
        assert engine is not None

        async def _push_snapshot() -> None:
            if self.session is not None and self._cm is not None:
                await self._cm.send_payload(self.session.build_snapshot())

        await mcp.attach_server(
            "approval_policy",
            make_inproc_slot_spec(
                ApprovalPolicyServer(
                    engine,
                    agent_id=self.agent_id,
                    persistence=self.persistence,
                    on_change=_push_snapshot,
                )
            ),
        )

    async def _op_start(self, *, specs: dict[str, McpServerSpec]) -> None:
        # Initialize approvals and UI bus
        if self.with_ui and self._ui_bus is None:
            self._ui_bus = ServerBus()
        self.approval_engine = ApprovalPolicyEngine()
        self.approval_hub = ApprovalHub()
        # Load latest persisted approval policy (if any)
        latest = await self.persistence.get_latest_policy(self.agent_id)  # type: ignore[attr-defined]
        if latest is not None:
            content, ver = latest
            self.approval_engine.load_policy(content, version=ver)

        # Session & manager
        self._cm = ConnectionManager()
        sess = AgentSession(
            self._cm,
            approval_hub=self.approval_hub,
            persistence=self.persistence,
        )
        sess.agent_id = self.agent_id
        if self.with_ui and self._ui_bus is not None:
            sess.ui_bus = self._ui_bus
        sess.approval_engine = self.approval_engine

        # MCP manager and servers
        client = (
            self.client_factory(self.model)
            if self.client_factory is not None
            else build_client(self.model, enable_debug_logging=True)
        )
        mcp = McpManager(specs)
        await mcp.__aenter__()
        await self._attach_inproc_servers(mcp, self._ui_bus)

        def _get_run_id() -> str | None:
            return sess.active_run.run_id if sess.active_run else None

        handlers, persist_handler, _policy_handler = build_handlers(
            mcp=mcp,
            manager=self._cm,
            persistence=self.persistence,
            approval_engine=self.approval_engine,
            approval_hub=self.approval_hub,
            get_run_id=_get_run_id,
            ui_bus=self._ui_bus if self.with_ui else None,
        )
        # Provide persistence handler to the session deterministically
        sess.set_persist_handler(persist_handler)

        # Compose system prompt: preset/system_override + MCP server headers
        base_system = self.system_override or str(get_ui_system_message())
        # Include a simple header of attached MCP servers from desired specs
        server_list = sorted(specs.keys())
        server_header = "\n\n" + (
            "MCP servers:\n" + "\n".join(f"- {name}" for name in server_list) if server_list else ""
        )
        system_text = (base_system + server_header).strip()
        agent = await MiniCodex.create(
            model=self.model,
            mcp=mcp,
            system=system_text,
            client=client,
            handlers=handlers,
        )
        sess.attach_agent(agent, model=self.model, system=system_text)
        if self.with_ui and self._ui_bus is not None:
            self.ui = UiFacet(manager=self._cm, ui_bus=self._ui_bus)

        # Publish to container
        self.mcp = mcp
        self.session = sess
        self.agent = agent
        self.persist_handler = persist_handler
        # Hydrate approval policy + proposals from persistence (per agent)
        if self.session and self.session.agent_id:
            latest = await self.persistence.get_latest_policy(self.session.agent_id)
            if latest is not None and self.approval_engine is not None:
                content, version = latest
                self.approval_engine.load_policy(content, version=version)
            # Load proposals
            rows = await self.persistence.list_proposals(self.session.agent_id)
            if rows:
                proposals: list[Proposal] = []
                for row in rows:
                    created_at = (
                        datetime.fromisoformat(row["created_at"])
                        if row["created_at"]
                        else datetime.now(UTC)
                    )
                    decided_at = (
                        datetime.fromisoformat(row["decided_at"]) if row["decided_at"] else None
                    )
                    proposals.append(
                        Proposal(
                            id=row["id"],
                            source=row["source"],
                            status=row["status"],
                            created_at=created_at,
                            decided_at=decided_at,
                            rationale=row["rationale"],
                        )
                    )
                self.approval_engine.load_proposals(proposals)
        # Hydrate UI state from the most recent persisted run (do not swallow errors)
        if self.with_ui and self.session and self.session.agent_id:
            # Load all runs for this agent (oldest → newest) and fold all events
            runs = await self.persistence.list_runs(agent_id=self.session.agent_id, limit=1000000)
            if runs:
                # list_runs returns DESC by started_at; fold oldest to newest
                runs_sorted = list(reversed(runs))
                all_events = []
                for run_row in runs_sorted:
                    evts = await self.persistence.load_events(run_row.id)
                    all_events.extend(evts)
                if all_events:
                    self.session.ui_state = fold_events_to_ui_state(all_events)
        self._ready.set()

    async def _op_reconfigure(
        self,
        *,
        specs: dict[str, McpServerSpec] | None,
        attach: dict[str, McpServerSpec],
        detach: list[str],
    ) -> None:
        if self.mcp is None:
            raise RuntimeError("container not started")
        if specs is not None:
            desired = self.mcp.slots_from_specs(specs)
            await self.mcp.reconfigure(desired)
        else:
            for name in detach:
                if name != "resources":
                    await self.mcp.detach_server(name)
            if attach:
                new_specs = self.mcp.slots_from_specs(attach)
                for name, spec in new_specs.items():
                    await self.mcp.attach_server(name, spec)

    async def _op_sampling_snapshot(self) -> SamplingSnapshot | None:
        if self.mcp is None:
            return None
        # UI consumers need full server status (running+failed). The model‑facing
        # sampling_snapshot on the manager includes only RUNNING servers.
        return await self.mcp.servers_status()

    async def _op_sampling_snapshot_incremental(self) -> None:
        """Iterate MCP servers and emit a snapshot after each initialization attempt."""
        if self.mcp is None or self._cm is None or self.session is None:
            return
        from adgn.agent.mcp_manager import InitializeView, SamplingSnapshot, ServerEntry

        # Use the public API to get configured server names
        # Snapshot current configured servers from specs for deterministic iteration
        servers = list(self.mcp.server_names)
        partial: list[ServerEntry] = []
        for name in servers:
            try:
                init_res = await self.mcp.get_server_initialize(name)
                entry = ServerEntry(
                    name=name,
                    state="running",
                    initialize=InitializeView(
                        instructions=init_res.instructions,
                        server_info=init_res.serverInfo,
                    ),
                    supports_resources=self.mcp._supports_resources_from_init(init_res),
                )
                try:
                    tools_entries = await self.mcp.list_tools(only=[name])
                    entry.tools = [te.tool for te in tools_entries if te.server == name]
                except Exception:
                    entry.tools = []
                partial.append(entry)
            except Exception as e:
                partial.append(
                    ServerEntry(
                        name=name,
                        state="failed",
                        error=str(e),
                        supports_resources=None,
                    )
                )
            snap = SamplingSnapshot(ts=datetime.now(UTC).isoformat(), servers=list(partial))
            await self._cm.send_payload(self.session.build_snapshot(sampling=snap))

    async def _op_close(self) -> dict[str, Any]:
        drained_ok = True
        drain_error: Exception | None = None
        try:
            if self.ui:
                await self.ui.manager.flush()
            if self.session is not None:
                await self.session.cancel_active_run()
            if self.mcp is not None:
                await self.mcp.wait_idle(timeout=None)
            if self.persist_handler is not None:
                await self.persist_handler.drain()
        except Exception as e:
            drained_ok = False
            drain_error = e
        finally:
            try:
                if self.agent is not None:
                    await self.agent.__aexit__(None, None, None)
            finally:
                if self.mcp is not None:
                    await self.mcp.__aexit__(None, None, None)
            self._closed.set()
        result: dict[str, Any] = {"drained": drained_ok}
        if not drained_ok and drain_error is not None:
            result["error"] = type(drain_error).__name__
        return result

    async def _actor_loop(self) -> None:
        try:
            while True:
                op, kwargs, fut = await self._mailbox.get()
                try:
                    if op == "start":
                        await self._op_start(specs=kwargs.get("specs") or {})
                        fut.set_result(None)
                        continue

                    if op == "reconfigure":
                        await self._op_reconfigure(
                            specs=kwargs.get("specs"),
                            attach=kwargs.get("attach") or {},
                            detach=kwargs.get("detach") or [],
                        )
                        fut.set_result(None)
                        continue

                    if op == "sampling_snapshot":
                        snap = await self._op_sampling_snapshot()
                        fut.set_result(snap)
                        continue

                    if op == "sampling_snapshot_incremental":

                        async def _run_stream() -> None:
                            await self._op_sampling_snapshot_incremental()

                        asyncio.create_task(_run_stream())
                        fut.set_result(None)
                        continue

                    if op == "close":
                        result = await self._op_close()
                        fut.set_result(result)
                        break
                except Exception as e:  # deliver failure back to caller
                    if not fut.done():
                        fut.set_exception(e)
        except Exception as e:
            # Unhandled actor failure; log and signal closed so registry can clean up
            logger.exception("container actor crashed", exc_info=e)
            self._closed.set()


async def build_container(
    *,
    agent_id: str,
    specs: dict[str, McpServerSpec],
    persistence: Persistence,
    model: str,
    with_ui: bool = True,
    system: str | None = None,
    client_factory: Callable[[str], OpenAIModelProto] | None = None,
) -> AgentContainer:
    c = AgentContainer(
        agent_id=agent_id,
        persistence=persistence,
        model=model,
        with_ui=with_ui,
        system_override=system,
        client_factory=client_factory,
    )
    await c.start(specs=specs)
    return c
