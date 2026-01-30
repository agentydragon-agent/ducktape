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
from mcp_infra.exec.docker.server import ContainerExecServer
from mcp_infra.exec.models import BaseExecResult, Exited, make_exec_input
from mcp_infra.naming import build_mcp_function
from mcp_infra.prefix import MCPMountPrefix
from mcp_infra.testing.fixtures import make_container_opts
from openai_utils.client_factory import build_client
from openai_utils.model import OpenAIModelProto, UserMessage
from openai_utils.testing.fixtures import ClientMode, mock_and_live

ECHO_CMD = ["/bin/echo", "-n", "hello"]
SERVER_NAME = MCPMountPrefix("box")


@pytest.fixture
async def docker_exec_server_py312slim(async_docker_client, python_slim_image):
    """Canonical Docker exec server using python-slim image."""
    opts = make_container_opts(python_slim_image)
    return ContainerExecServer(async_docker_client, opts)


@pytest.fixture
async def mcp_client_box(docker_exec_server_py312slim, compositor, compositor_client):
    """MCP client with box Docker exec server (no policy gateway)."""
    await compositor.mount_inproc(MCPMountPrefix("box"), docker_exec_server_py312slim)
    return compositor_client


@mock_and_live
@pytest.mark.requires_docker
async def test_llm_exec_echo(mode: ClientMode, mcp_client_box, live_openai_model) -> None:
    """LLM calls box__exec to echo hello, agent returns stdout."""
    if mode is ClientMode.MOCK:

        @MCPDecoratorMock.mock()
        def mock(m: MCPDecoratorMock):
            yield
            call = m.mcp_tool_call(SERVER_NAME, "exec", make_exec_input(ECHO_CMD))
            result: BaseExecResult = yield from tool_roundtrip(call, BaseExecResult)
            assert isinstance(result.exit, Exited)
            assert result.exit.exit_code == 0
            assert (result.stdout or "") == "hello"
            yield m.assistant_text("hello")

        client: OpenAIModelProto = mock
    else:
        client = build_client(live_openai_model)

    agent = await Agent.create(
        tool_provider=MCPToolProvider(mcp_client_box),
        client=client,
        handlers=[BaseHandler()],
        tool_policy=RequireAnyTool(),
    )
    agent.process_message(
        UserMessage.text(
            "Call the tool "
            f"{build_mcp_function(SERVER_NAME, 'exec')} "
            f"with cmd={ECHO_CMD!r} and return exactly the stdout."
        )
    )
    res: AgentResult = await agent.run()
    assert (res.text or "").strip() == "hello"


if __name__ == "__main__":
    pytest_bazel.main()
