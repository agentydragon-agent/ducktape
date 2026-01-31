"""Dual mock/live tests for LLM-driven Docker exec roundtrip.

Mock test scripts the LLM to call box__exec; live test uses a real OpenAI model.
Both need Docker (the exec tool runs in a real container).
"""

from __future__ import annotations

import pytest
import pytest_bazel

from agent_core.agent import Agent, AgentResult
from agent_core.handler import BaseHandler
from agent_core.loop_control import RequireAnyTool
from agent_core.mcp_provider import MCPToolProvider
from agent_core.testing.mcp.responses import MCPDecoratorMock
from agent_core.testing.responses import tool_roundtrip
from mcp_infra.exec.models import BaseExecResult, Exited, make_exec_input
from mcp_infra.prefix import MCPMountPrefix
from openai_utils.model import UserMessage

ECHO_CMD = ["/bin/echo", "-n", "hello"]
SERVER_NAME = MCPMountPrefix("box")


@pytest.mark.requires_docker
async def test_llm_exec_echo(
    mock_or_live,
    docker_exec_server_py312slim,
    compositor,
    compositor_client,
) -> None:
    """LLM calls box__exec to echo hello, agent returns stdout."""
    await compositor.mount_inproc(MCPMountPrefix("box"), docker_exec_server_py312slim)

    @mock_or_live(MCPDecoratorMock)
    def client(m: MCPDecoratorMock):
        yield
        call = m.mcp_tool_call(SERVER_NAME, "exec", make_exec_input(ECHO_CMD))
        result: BaseExecResult = yield from tool_roundtrip(call, BaseExecResult)
        assert isinstance(result.exit, Exited)
        assert result.exit.exit_code == 0
        assert (result.stdout or "") == "hello"
        yield m.assistant_text("hello")

    agent = await Agent.create(
        tool_provider=MCPToolProvider(compositor_client),
        client=client,
        handlers=[BaseHandler()],
        tool_policy=RequireAnyTool(),
    )
    agent.process_message(UserMessage.text("Call the exec tool with cmd={ECHO_CMD!r} and return exactly the stdout."))
    res: AgentResult = await agent.run()
    assert "hello" in (res.text or "")


if __name__ == "__main__":
    pytest_bazel.main()
