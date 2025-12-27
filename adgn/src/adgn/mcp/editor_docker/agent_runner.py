from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import aiodocker
from fastmcp.client import Client

from adgn.agent.bootstrap import run_init_script
from adgn.mcp.editor_docker.handlers import TerminateOnEditorSubmit
from adgn.mcp.editor_docker.runner import EditorDockerSession, editor_docker_session, writeback_success
from adgn.mcp.editor_docker.submit_server import SubmitState, SubmitStatePending, SubmitStateSuccess
from agent_core.agent import Agent
from agent_core.handler import AbortIf, BaseHandler
from agent_core.loop_control import AllowAnyToolOrTextMessage
from agent_core.turn_limit import MaxTurnsHandler
from openai_utils.model import OpenAIModelProto, SystemMessage


async def _run_agent_in_session(sess: EditorDockerSession, model_client: OpenAIModelProto, max_turns: int) -> None:
    """Run the agent loop within an established editor session."""
    async with Client(sess.compositor) as mcp_client:
        # Run init script and use output as system prompt
        system_prompt = await run_init_script(mcp_client, sess.runtime)

        # Give a small buffer for submit turns on top of caller-specified limit
        effective_max_turns = max_turns + 2

        handlers: Iterable[BaseHandler] = (
            TerminateOnEditorSubmit(),
            AbortIf(lambda: not isinstance(sess.submit_server.state, SubmitStatePending)),
            MaxTurnsHandler(max_turns=effective_max_turns),
        )

        agent = Agent(
            mcp_client=mcp_client,
            client=model_client,
            parallel_tool_calls=False,
            handlers=handlers,
            tool_policy=AllowAnyToolOrTextMessage(),
            reasoning_effort=None,
            reasoning_summary=None,
        )

        # Insert system message from init output
        agent.process_message(SystemMessage.text(system_prompt))

        await agent.run()


async def run_editor_docker_agent(
    *,
    file_path: Path,
    docker_client: aiodocker.Docker,
    model_client: OpenAIModelProto,
    max_turns: int = 40,
    image_id: str,
    network: str = "bridge",
) -> SubmitState:
    """Run the docker-editor agent with step-runner or real model.

    - Starts a docker exec runtime + submit server via editor_docker_session
    - Runs /init to get system prompt (includes file content)
    - Runs Agent with AllowAnyToolOrTextMessage and termination on submit-success/failure
    - Writes submitted content back to host file on success

    Returns:
        SubmitState: the final submission state (pending/success/failure).
    """
    async with editor_docker_session(
        file_path=file_path, docker_client=docker_client, image_id=image_id, network_name=network
    ) as sess:
        await _run_agent_in_session(sess, model_client, max_turns)

        state: SubmitState = sess.submit_server.state
        if isinstance(state, SubmitStateSuccess):
            writeback_success(file_path, state.content)

        return state
