from __future__ import annotations

import asyncio
import json
from typing import Any, List, cast

import uvicorn
from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.approvals import ApprovalHub
from adgn_llm.mini_codex.handler import AbortTurnDecision
from adgn_llm.mini_codex.handler import BaseHandler as _BaseHandler
from adgn_llm.mini_codex.handler import (
    BeforeToolCallDecision,
    BypassToolInjectOutput,
    ContinueDecision,
)
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Minimal local-only FastAPI UI for MiniCodex (v0)
# - Single-session, in-process
# - WebSocket /ws: duplex channel for events and control
# - GET /transcript -> current run transcript
# - GET / -> serves static/index.html from same dir (developer should add static file)

app = FastAPI()
app.mount("/static", StaticFiles(directory="./static"), name="static")


# Simple connection manager for one UI client (v0 single-session)
class ConnectionManager:
    def __init__(self) -> None:
        self.websocket: WebSocket | None = None
        self.lock = asyncio.Lock()
        self._session: "AgentSession" | None = None

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self.lock:
            self.websocket = ws

    async def disconnect(self, ws: WebSocket) -> None:
        async with self.lock:
            if self.websocket is ws:
                self.websocket = None

    async def send_json(self, payload: dict[str, Any]) -> None:
        async with self.lock:
            if self.websocket is not None:
                try:
                    await self.websocket.send_json(payload)
                except Exception:
                    # best-effort; ignore for now
                    pass

    # ---- Handler adapter methods (so manager can be used as a BaseHandler) ----
    def set_session(self, session: "AgentSession") -> None:
        self._session = session

    def on_response(self, evt: Any) -> None:
        return None

    def on_user_text_event(self, evt: Any) -> None:
        asyncio.create_task(self.send_json({"kind": "user_text", "text": evt.text}))

    def on_assistant_text_event(self, evt: Any) -> None:
        asyncio.create_task(self.send_json({"kind": "assistant_text", "text": evt.text}))

    def on_tool_call_event(self, evt: Any) -> None:
        asyncio.create_task(
            self.send_json(
                {
                    "kind": "tool_call",
                    "name": evt.name,
                    "args": evt.args,
                    "call_id": evt.call_id,
                }
            )
        )

    async def before_tool_call(self, evt: Any) -> BeforeToolCallDecision | None:
        payload = {
            "kind": "approval_pending",
            "call_id": evt.call_id,
            "tool_key": evt.name,
            "args": evt.args,
        }
        await self.send_json(payload)
        if self._session is None:
            return ContinueDecision()
        decision = await self._session.approval_hub.await_decision(evt.call_id, payload)
        # Send a UI-friendly label derived from the concrete decision type
        if isinstance(decision, ContinueDecision):
            label = "continue"
        elif isinstance(decision, BypassToolInjectOutput):
            label = "inject_result"
        elif isinstance(decision, AbortTurnDecision):
            label = "abort"
        else:
            label = "unknown"
        await self.send_json({"kind": "approval_decision", "call_id": evt.call_id, "decision": label})
        return decision

    def on_function_call_output_event(self, evt: Any) -> None:
        asyncio.create_task(
            self.send_json(
                {
                    "kind": "function_call_output",
                    "call_id": evt.call_id,
                    "output": evt.output,
                }
            )
        )


manager = ConnectionManager()


class AgentSession:
    """Single-session orchestrator that simulates integration points for MiniCodex.

    This MVP implements the approval rendezvous and transcript wiring. The real
    MiniCodex.run wiring should be plugged in where noted (create MiniCodex and
    register event handlers to append to `transcript` and forward events to clients).
    """

    def __init__(self) -> None:
        self.transcript: List[dict[str, Any]] = []
        self._task: asyncio.Task | None = None
        self.approval_hub = ApprovalHub()
        self._lock = asyncio.Lock()
        # TODO: None does not make sense. consider direct bind in __init__
        self._agent: MiniCodex | None = None

    def attach_agent(self, agent: "MiniCodex") -> None:
        """Attach a MiniCodex instance and register the UI manager as a handler.

        The ConnectionManager implements the handler hooks (on_* and before_tool_call)
        so we register it directly on the agent's controller. We also set the
        manager's session to enable approval hub awaits.
        """
        self._agent = agent
        # Tell manager about this session
        manager.set_session(self)
        # Best-effort: append manager as a handler to the agent so it receives events
        try:
            agent._controller._handlers.append(cast(_BaseHandler, manager))
        except Exception:
            # If agent shape differs, keep reference only; caller may register manually
            pass

    async def run(self, prompt: str) -> None:
        """Run a single simulated agent turn. Replace with real MiniCodex.run wiring.

        Behavior:
        - Append user_text to transcript and forward
        - Simulate encountering a single tool call that needs approval
        - Emit approval_pending over WS and await decision via ApprovalHub
        - If allow -> emit a fake function_call_output with real result
        - If inject_result -> emit injected result
        - If abort -> emit denial + aborted synthetic outputs
        """
        # Guard so only one run at a time
        async with self._lock:
            if self._task is not None and not self._task.done():
                await manager.send_json({"kind": "status", "msg": "agent_busy"})
                return
            self._task = asyncio.create_task(self._run_impl(prompt))

    async def _run_impl(self, prompt: str) -> None:
        # Append user_text
        user_evt = {"kind": "user_text", "text": prompt}
        self.transcript.append(user_evt)
        await manager.send_json({"kind": "user_text", "text": prompt})

        # Simulate the agent producing a tool_call that needs approval
        # In real wiring, this will be captured from MiniCodex resp. For v0 we synthesize
        call_id = "sim-call-1"
        server = "local"
        tool_name = "echo"
        tool_key = f"mcp__{server}__{tool_name}"
        tc_event = {
            "kind": "tool_call",
            "name": tool_key,
            "args": {"text": prompt},
            "call_id": call_id,
        }
        self.transcript.append(tc_event)
        await manager.send_json(
            {
                "kind": "tool_call",
                "name": tool_key,
                "args": {"text": prompt},
                "call_id": call_id,
            }
        )

        # Emit approval_pending and wait
        pending_payload = {
            "kind": "approval_pending",
            "call_id": call_id,
            "tool_key": tool_key,
            "args": {"text": prompt},
        }
        self.transcript.append(pending_payload)
        await manager.send_json(pending_payload)

        # Wait for a decision from the UI via ApprovalHub.resolve(call_id, decision)
        try:
            decision = await asyncio.wait_for(self.approval_hub.await_decision(call_id, pending_payload), timeout=60.0)
        except asyncio.TimeoutError:
            # timed out -> treat as abort
            deny = {"ok": False, "error": "approval_timeout"}
            fco = {
                "kind": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(deny),
            }
            self.transcript.append(fco)
            await manager.send_json({"kind": "approval_decision", "call_id": call_id, "allowed": False})
            await manager.send_json(fco)
            # also emit aborted marker
            await manager.send_json({"kind": "aborted"})
            return

        # Publish resolution event
        await manager.send_json(
            {
                "kind": "approval_decision",
                "call_id": call_id,
                "decision": decision.action,
            }
        )

        # Act according to decision type
        if isinstance(decision, ContinueDecision):
            # execute and emit fake result
            result = {"ok": True, "echo": prompt}
            fco = {
                "kind": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(result),
            }
            self.transcript.append(fco)
            await manager.send_json(fco)
            return

        if isinstance(decision, BypassToolInjectOutput):
            res = decision.result
            if res is None:
                payload = {"ok": False, "error": "injected_no_result"}
            else:
                payload = (
                    res.structuredContent
                    if res.structuredContent is not None
                    else {"content": [c.model_dump() for c in (res.content or [])]}
                )
            fco = {
                "kind": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(payload),
            }
            self.transcript.append(fco)
            await manager.send_json(fco)
            return

        if isinstance(decision, AbortTurnDecision):
            deny_payload = {"ok": False, "error": f"User denied: {tool_key}"}
            fco = {
                "kind": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(deny_payload),
            }
            self.transcript.append(fco)
            await manager.send_json(fco)
            # synthesize aborted marker
            await manager.send_json({"kind": "aborted"})
            return

        # Unknown decision -> crash (fail-fast)
        raise RuntimeError(f"Unknown before-tool-call decision: {decision!r}")


# Single global session for v0
session = AgentSession()


@app.get("/")
async def index() -> HTMLResponse:
    try:
        with open("src/adgn_llm/mini_codex/ui/static/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except FileNotFoundError:
        return HTMLResponse(
            "<html><body><h1>MiniCodex UI</h1><p>Place static/index.html in src/adgn_llm/mini_codex/ui/static/</p></body></html>"
        )


@app.get("/transcript")
async def get_transcript() -> JSONResponse:
    return JSONResponse(session.transcript)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
            except Exception:
                await manager.send_json({"kind": "error", "msg": "invalid_json"})
                continue

            typ = msg.get("type")
            if typ == "send":
                text = msg.get("text", "")
                # Only start run if no run is active
                await session.run(text)
                continue

            if typ == "approve" or typ == "deny":
                call_id = msg.get("call_id")
                if not call_id:
                    await manager.send_json({"kind": "error", "msg": "missing_call_id"})
                    continue
                if typ == "approve":
                    decision: BeforeToolCallDecision = ContinueDecision()
                else:
                    decision = AbortTurnDecision(reason="ui_deny")
                # resolve via hub
                session.approval_hub.resolve(call_id, decision)
                # Use isinstance-based labeling for UI (no stringly-typed access)
                if isinstance(decision, ContinueDecision):
                    label = "continue"
                elif isinstance(decision, BypassToolInjectOutput):
                    label = "inject_result"
                elif isinstance(decision, AbortTurnDecision):
                    label = "abort"
                else:
                    label = "unknown"
                await manager.send_json(
                    {
                        "kind": "status",
                        "msg": "resolved",
                        "call_id": call_id,
                        "decision": label,
                    }
                )
                continue

            if typ == "abort":
                # v0: cancel running task if any
                if session._task is not None and not session._task.done():
                    session._task.cancel()
                    await manager.send_json({"kind": "aborted"})
                else:
                    await manager.send_json({"kind": "status", "msg": "no_active_run"})
                continue

            await manager.send_json({"kind": "error", "msg": "unknown_command"})

    except WebSocketDisconnect:
        await manager.disconnect(ws)


# CLI-style entrypoint helper (optional)
def run_uvicorn():
    uvicorn.run(
        "adgn_llm.mini_codex.ui.server:app",
        host="127.0.0.1",
        port=8765,
        log_level="info",
    )
