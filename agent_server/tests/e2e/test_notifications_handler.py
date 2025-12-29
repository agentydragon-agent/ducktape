from __future__ import annotations

import asyncio

import pytest
from agent_core.testing import AssistantMessage, CapturingOpenAIModel
from fastmcp.mcp_config import MCPConfig
from openai_utils.model import InputTextPart

from agent_server.runtime.container import build_container
from agent_server.testing.steps import ApprovalPolicyAdminSetPolicyCall


@pytest.mark.requires_docker
@pytest.mark.timeout(35)
async def test_notifications_handler_in_container_inserts_system_message(
    docker_client,
    async_docker_client,
    sqlite_persistence,
    monkeypatch: pytest.MonkeyPatch,
    policy_allow_all: str,
    make_step_runner,
) -> None:
    # Capture OpenAI requests and mock agent responses
    runner = make_step_runner(
        steps=[
            # First turn: agent calls admin_set_policy to trigger notification
            ApprovalPolicyAdminSetPolicyCall(source=policy_allow_all),
            # Subsequent turns: just return done
            AssistantMessage("done"),
        ]
    )
    client = CapturingOpenAIModel(runner)
    # Build container headless (no UI) with allow-all policy
    container = await build_container(
        agent_id="notif-e2e",
        mcp_config=MCPConfig(),
        persistence=sqlite_persistence,
        model="test-model",
        client_factory=lambda _model: client,
        with_ui=False,
        async_docker_client=async_docker_client,
        initial_policy=policy_allow_all,
    )

    try:
        # First turn: agent sets policy via MCP tool, triggering notification
        assert container.session is not None
        await asyncio.wait_for(container.session.run("set policy"), timeout=30)

        # Second turn: notification should be inserted
        await asyncio.wait_for(container.session.run("check"), timeout=30)

        # Look for the system notification in the request input
        found = False
        for req in client.captured:
            inp = req.input or []
            for msg in inp:
                # UserMessage with inserted system notification block
                for c in getattr(msg, "content", []) or []:
                    if (
                        isinstance(c, InputTextPart)
                        and "<system notification>" in c.text
                        and ("approval-policy" in c.text or "policy.py" in c.text)
                    ):
                        found = True
                        break
                if found:
                    break
            if found:
                break
        assert found, "expected system notification inserted by NotificationsHandler"
    finally:
        await container.close()
