from __future__ import annotations

import asyncio

from fastmcp.mcp_config import MCPConfig
import pytest

from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.agent.runtime.container import build_container
from adgn.openai_utils.model import (
    InputTextPart,
    ResponsesRequest,
    ResponsesResult,
)
import docker
from tests.llm.support.openai_mock import make_mock


def _policy_source_allow() -> str:
    """Minimal allow-all policy program for container evaluator (no imports)."""
    return (
        "import sys, json\n"
        "_ = json.load(sys.stdin)\n"
        "print(json.dumps({'decision': 'allow', 'rationale': 'ok'}))\n"
    )


def _docker_available() -> bool:
    try:
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


@pytest.mark.asyncio
@pytest.mark.requires_docker
@pytest.mark.skipif(not _docker_available(), reason="docker not available")
async def test_notifications_handler_in_container_inserts_system_message(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Persistence and container
    db = tmp_path / "agent.sqlite"
    p = SQLitePersistence(str(db))
    await p.ensure_schema()

    # Capture OpenAI requests
    captured: list[ResponsesRequest] = []

    async def _create(req: ResponsesRequest) -> ResponsesResult:
        captured.append(req)
        # Always return a simple assistant message; notifications come from admin set_policy
        from tests.fixtures.responses import ResponsesFactory

        return ResponsesFactory("test-model").make_assistant_message("done")

    client = make_mock(_create)
    # Patch container model factory to our mock client
    monkeypatch.setattr("adgn.agent.runtime.container.build_client", lambda *a, **k: client)

    # Build container headless (no UI) with allow-all policy
    container = await build_container(
        agent_id="notif-e2e",
        mcp_config=MCPConfig(),
        persistence=p,
        model="test-model",
        with_ui=False,
        docker_client=docker.from_env(),
        initial_policy=_policy_source_allow(),
    )

    try:
        # Trigger a policy update via admin MCP client (out-of-band notification)
        await container.policy_approver.set_policy_text(_policy_source_allow())

        # Run one turn; first sampling triggers notifier tool; second should include notification insert
        assert container.session is not None
        await asyncio.wait_for(container.session.run("go"), timeout=30)

        # Look for the system notification in the request input
        found = False
        for req in captured:
            inp = req.input or []
            for msg in inp:
                # UserMessage with inserted system notification block
                for c in getattr(msg, "content", []) or []:
                    if isinstance(c, InputTextPart) and "<system notification>" in c.text:
                        if "approval-policy" in c.text or "policy.py" in c.text:
                            found = True
                            break
                if found:
                    break
            if found:
                break
        assert found, "expected system notification inserted by NotificationsHandler"
    finally:
        await container.close()
