from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from fastmcp.client import Client
from fastmcp.client.client import CallToolResult
from fastmcp.mcp_config import MCPServerTypes
from fastmcp.server import FastMCP
import mcp.types
from pydantic import BaseModel
import pytest

from adgn.agent.agent import MiniCodex
from adgn.agent.events import EventType, ToolCall, ToolCallOutput, UserText
from adgn.agent.handler import BaseHandler
from adgn.agent.loop_control import RequireAnyTool
from adgn.agent.persist.events import EventRecord
from adgn.agent.policies.loader import approve_all_policy_text
from adgn.agent.policy_eval.container import ContainerPolicyEvaluator
from adgn.agent.recording_handler import RecordingHandler
from adgn.agent.server.app import create_app
from adgn.agent.server.protocol import FunctionCallOutput
from adgn.agent.server.state import new_state
from adgn.mcp._shared.calltool import fastmcp_to_mcp_result
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp.approval_policy.engine import PolicyEngine
from adgn.mcp.editor_server import make_editor_server
from adgn.mcp.testing.editor_stubs import EditorServerStub
from adgn.mcp.testing.simple_servers import SendMessageInput
from adgn.openai_utils.model import OpenAIModelProto, ResponsesResult
from tests.agent.testdata.approval_policy import fetch_policy, make_policy
from tests.llm.support.openai_mock import FakeOpenAIModel
from tests.support.types import McpServerSpecs

# --- Pytest fixtures (prefer fixtures over cross-importing test modules) ---

# Note: docker_client and approval_policy_server fixtures are provided globally in tests/conftest.py


@pytest.fixture
async def compositor_client(compositor):
    """Client connected to the compositor fixture."""
    async with Client(compositor) as client:
        yield client


@pytest.fixture
def policy_evaluator(docker_client, approval_policy_server: PolicyEngine) -> ContainerPolicyEvaluator:
    """Container-backed policy evaluator using the default policy engine.

    Deduplicates setup across tests that need to call policy.decide(...).
    Requires Docker (tests should mark with @pytest.mark.requires_docker).
    """
    return ContainerPolicyEvaluator(agent_id="tests", docker_client=docker_client, engine=approval_policy_server)


@pytest.fixture
def make_policy_evaluator(docker_client, make_approval_policy_server):
    """Factory that builds a ContainerPolicyEvaluator for a given policy source."""

    def _make(policy_source: str, *, agent_id: str = "tests") -> ContainerPolicyEvaluator:
        engine = make_approval_policy_server(policy_source, agent_id=agent_id)
        return ContainerPolicyEvaluator(agent_id=agent_id, docker_client=docker_client, engine=engine)

    return _make


# ---- Standard policy text fixtures (string sources) ----


@pytest.fixture
def policy_allow_all() -> str:
    """Return the text of the approve-all policy from packaged resources."""
    return approve_all_policy_text()


@pytest.fixture
def policy_ui_send_message_allow() -> str:
    result: str = make_policy(
        decision_expr="PolicyDecision.ALLOW",
        server="ui",
        tool="send_message",
        default="ask",
        doc="Allow UI send_message; ask otherwise.",
    )
    return result


@pytest.fixture
def policy_failing_tests() -> str:
    return str(fetch_policy("failing_tests"))


# --- Missing fixtures for default policy tests ---


@pytest.fixture
def policy_version_test() -> str:
    result: str = make_policy(
        decision_expr="PolicyDecision.ALLOW",
        server="ui",
        tool="send_message",
        default="ask",
        doc="Version bump check policy used in tests.",
    )
    return result


@pytest.fixture
def policy_invalid_syntax() -> str:
    # Intentionally invalid Python
    return "class ApprovalPolicy:\n    '''invalid'''\n    def decide(self, ctx):\n        return (PolicyDecision.ALLOW, 'ok'\n"


@pytest.fixture
def policy_context_checking() -> str:
    return str(fetch_policy("context_checking"))


@pytest.fixture
def policy_const() -> str:
    return str(fetch_policy("const"))


# reasoning_model fixture is provided globally in tests/support/responses.py
# (registered via pytest_plugins in tests/conftest.py)

# assistant_response_factory, tool_call_response_factory, responses_factory
# come from tests.support.responses (registered globally in tests/conftest.py).


# Local factory: construct our Pydantic-only fake client from a sequence of ResponsesResult
@pytest.fixture
def make_fake_openai() -> Callable[[Iterable[ResponsesResult]], FakeOpenAIModel]:
    """Factory to create FakeOpenAIModel instances from response sequences.

    Usage:
        client = make_fake_openai([responses_factory.make_assistant_message("ok")])
    """

    def _make(outputs: Iterable[ResponsesResult]) -> FakeOpenAIModel:
        return FakeOpenAIModel(list(outputs))

    return _make


@pytest.fixture
def make_test_agent(responses_factory):
    """Factory to create MiniCodex backed by FakeOpenAIModel with canned responses.

    Returns (agent, fake_client) tuple so tests can inspect the client after run.

    Usage:
        agent, client = await make_test_agent(
            mcp_client,
            [responses_factory.make_assistant_message("done")],
        )
        result = await agent.run("hi")
        assert client.calls == 1
    """

    async def _make(mcp_client, responses, *, handlers=(), system="test", tool_policy=None, **kwargs):
        client = FakeOpenAIModel(responses)
        if not handlers:
            handlers = [BaseHandler()]
        if tool_policy is None:
            tool_policy = RequireAnyTool()
        agent = await MiniCodex.create(
            mcp_client=mcp_client, system=system, client=client, handlers=handlers, tool_policy=tool_policy, **kwargs
        )
        return agent, client

    return _make


# No extra param fixtures here; reuse existing LIVE sentinel infra from tests/llm.


# ---- Shared ContainerOptions fixtures and in-proc docker exec specs ----
# Kept here so all tests can reuse the same settings consistently.


@pytest.fixture
def typed_editor_factory(tmp_path: Path):
    """Factory that yields (EditorServerStub, target_path) for an in-proc editor server."""

    @asynccontextmanager
    async def _open(initial_text: str = "x = 1\n") -> AsyncIterator[tuple[EditorServerStub, Path]]:
        target = tmp_path / "sample.py"
        target.write_text(initial_text, encoding="utf-8")

        srv = make_editor_server(target)
        async with Client(srv) as session:
            stub = EditorServerStub.from_server(srv, session)
            yield stub, target

    return _open


# Provide a shared typed MCP session helper for tests that need a TypedClient
# make_typed_mcp now provided globally in tests/conftest.py


# echo_spec fixture is provided at tests/conftest.py for all suites.


# Helper: create a live agent via HTTP on a TestClient and return its id
@pytest.fixture
def create_live_agent():
    def _create(client, *, specs: McpServerSpecs | None = None) -> str:
        specs = specs or {}
        # Split into typed JSON specs vs runtime slot specs
        typed: dict[str, MCPServerTypes] = {}
        inproc: dict[str, FastMCP] = {}
        for k, v in list(specs.items()):
            if isinstance(v, FastMCP):
                inproc[k] = v
                continue
            # Must be MCPServerTypes at this point
            assert isinstance(v, BaseModel), f"Expected MCPServerTypes or FastMCP, got {type(v)}"
            typed[k] = v
        # Create agent via API using a preset
        resp = client.post("/api/agents", json={"preset": "default"})
        assert resp.status_code == 200, resp.text
        agent_id = str(resp.json()["id"])
        # Attach typed specs via HTTP reconfigure, then runtime slots in-process
        if typed:
            # Enforce one format: ALL typed specs must be Pydantic models (MCPServerTypes).
            if not all(isinstance(v, BaseModel) for v in typed.values()):
                raise AssertionError("Typed MCP specs must be provided as Pydantic models only")
            # Send over HTTP; server rehydrates to typed MCPServerTypes (TestClient handles Pydantic serialization)
            r = client.patch(f"/api/agents/{agent_id}/mcp", json={"attach": typed})
            assert r.status_code == 200, r.text
        if inproc:

            async def _attach_async() -> None:
                reg = client.app.state.registry
                c = await reg.ensure_live(agent_id, with_ui=True)
                comp = c._compositor
                if comp is None:
                    raise AssertionError("compositor not initialized on container")
                for name, server in inproc.items():
                    await comp.mount_inproc(name, server)
                await c._push_snapshot_and_status()

            client.portal.call(_attach_async)
        return agent_id

    return _create


@pytest.fixture
def patch_agent_build_client(monkeypatch: pytest.MonkeyPatch) -> Callable[[OpenAIModelProto], None]:
    """Return a function to patch container.build_client to a provided fake client.

    Keeps model patching independent from agent creation, so tests can opt-in.
    """

    def _patch(fake_model: OpenAIModelProto) -> None:
        monkeypatch.setattr("adgn.agent.runtime.container.build_client", lambda *a, **k: fake_model)

    return _patch


@pytest.fixture
def agent_app_client():
    """Yield a (app, client) pair for the UI server with static assets not required.

    Ensures a consistent pattern across tests, avoiding repeated create_app/TestClient boilerplate.
    """
    app = create_app(require_static_assets=False)
    with TestClient(app) as client:
        yield app, client


@pytest.fixture
def agent_test_client(agent_app_client):
    """Return just the TestClient for agent server tests.

    Use this when you only need the client and not the app.
    """
    _app, client = agent_app_client
    return client


# ---- Recording handler fixture -----------------------------------------------


@pytest.fixture
def recording_handler() -> RecordingHandler:
    """Fresh RecordingHandler for capturing agent events during tests."""
    return RecordingHandler()


# ---- Server fixtures for tool error and parallel tests ------------------------


@pytest.fixture
def validation_server() -> FastMCP:
    """FastMCP server with a tool that validates input strictly."""
    mcp = FastMCP("validator")

    @mcp.tool()
    def send_message(input: SendMessageInput) -> dict[str, Any]:
        return {"ok": True, "message": input.content}

    return mcp


@pytest.fixture
def failing_server() -> FastMCP:
    """FastMCP server with a tool that returns an error."""
    mcp = FastMCP("editor")

    @mcp.tool()
    def fail(x: int) -> dict[str, Any]:
        return {"ok": False, "error": "boom"}

    return mcp


@pytest.fixture
def slow_server() -> FastMCP:
    """FastMCP server with two slow async tools for parallel call testing."""
    mcp = FastMCP("dummy")

    @mcp.tool()
    async def slow() -> dict[str, Any]:
        await asyncio.sleep(0.30)
        return {"ok": True, "tool": "slow", "args": {}}

    @mcp.tool()
    async def slow2() -> dict[str, Any]:
        await asyncio.sleep(0.30)
        return {"ok": True, "tool": "slow2", "args": {}}

    return mcp


# ---- UI reducer/history test fixtures ----------------------------------------


@pytest.fixture
def fresh_ui_state():
    """Fresh UI state for reducer tests."""
    return new_state()


@pytest.fixture
def call_id_gen() -> Callable[[], str]:
    """Lightweight call_id generator for tests."""
    counter = {"count": 0}

    def _gen() -> str:
        counter["count"] += 1
        return f"test_call:{counter['count']}"

    return _gen


@pytest.fixture
def make_tool_call(call_id_gen: Callable[[], str]) -> Callable[..., ToolCall]:
    """Factory for ToolCall events with auto call_id generation."""

    def _make(server: str, tool: str, args: dict[str, Any] | None = None, args_json: str | None = None) -> ToolCall:
        # Support both args (dict) and args_json (string) for backwards compatibility
        if args_json is None and args is not None:
            args_json = json.dumps(args)
        return ToolCall(name=build_mcp_function(server, tool), args_json=args_json, call_id=call_id_gen())

    return _make


@pytest.fixture
def make_call_result() -> Callable[[dict[str, Any] | None, bool], mcp.types.CallToolResult]:
    """Factory for MCP CallToolResult."""

    def _make(structured_content: dict[str, Any] | None = None, is_error: bool = False) -> mcp.types.CallToolResult:
        return fastmcp_to_mcp_result(
            CallToolResult(content=[], structured_content=structured_content or {}, is_error=is_error, meta=None)
        )

    return _make


@pytest.fixture
def make_tool_call_output(
    make_call_result: Callable[[dict[str, Any] | None, bool], mcp.types.CallToolResult],
) -> Callable[[str, dict[str, Any] | None, bool], ToolCallOutput]:
    """Factory for ToolCallOutput events."""

    def _make(call_id: str, structured_content: dict[str, Any] | None = None, is_error: bool = False) -> ToolCallOutput:
        return ToolCallOutput(call_id=call_id, result=make_call_result(structured_content, is_error))

    return _make


@pytest.fixture
def make_function_output(
    make_call_result: Callable[[dict[str, Any] | None, bool], mcp.types.CallToolResult],
) -> Callable[[str, dict[str, Any] | None, bool], FunctionCallOutput]:
    """Factory for protocol FunctionCallOutput (not EventRecord)."""

    def _make(
        call_id: str, structured_content: dict[str, Any] | None = None, is_error: bool = False
    ) -> FunctionCallOutput:
        return FunctionCallOutput(call_id=call_id, result=make_call_result(structured_content, is_error))

    return _make


# --- EventRecord factories for history tests ---


@pytest.fixture
def event_ts() -> datetime:
    """Shared timestamp for EventRecord tests."""
    return datetime.now(UTC)


@pytest.fixture
def make_event_record(event_ts: datetime) -> Callable[[EventType, int | None], EventRecord]:
    """Wrap any EventType in an EventRecord with auto-sequencing."""
    seq_counter = {"count": 0}

    def _wrap(payload: EventType, seq: int | None = None) -> EventRecord:
        if seq is None:
            seq_counter["count"] += 1
            seq = seq_counter["count"]
        return EventRecord(seq=seq, ts=event_ts, payload=payload)

    return _wrap


@pytest.fixture
def make_user_text_event(
    make_event_record: Callable[[EventType, int | None], EventRecord],
) -> Callable[[int, str], EventRecord]:
    """Factory for UserText EventRecord."""

    def _make(seq: int, text: str) -> EventRecord:
        return make_event_record(UserText(text=text), seq)

    return _make


@pytest.fixture
def make_tool_call_event(
    make_event_record: Callable[[EventType, int | None], EventRecord], make_tool_call: Callable[..., ToolCall]
) -> Callable[..., EventRecord]:
    """Factory for ToolCall EventRecord."""

    def _make(seq: int, server: str, tool: str, args_json: str | None = None) -> EventRecord:
        return make_event_record(make_tool_call(server, tool, args_json=args_json), seq)

    return _make


@pytest.fixture
def make_function_output_event(
    make_event_record: Callable[[EventType, int | None], EventRecord],
    make_tool_call_output: Callable[[str, dict[str, Any] | None, bool], ToolCallOutput],
) -> Callable[[int, str, dict[str, Any] | None], EventRecord]:
    """Factory for ToolCallOutput EventRecord."""

    def _make(seq: int, call_id: str, structured_content: dict[str, Any] | None = None) -> EventRecord:
        return make_event_record(make_tool_call_output(call_id, structured_content, False), seq)

    return _make
