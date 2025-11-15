from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Protocol

from fastmcp.server import FastMCP

from adgn.inop.prompting.prompt_engineer import FeedbackProvider
from adgn.mcp.compositor.server import Compositor

# ---- Dependencies and state -------------------------------------------------


class PromptEvaluationDeps(Protocol):
    async def select_seed_tasks(self) -> list[Any]: ...
    async def run_rollouts_with_prompt(self, prompt: str, tasks: list[Any]) -> list[Any]: ...
    def persist_all(self, *, iteration: int, prompt: str, rollouts: list[Any], feedback: str) -> None: ...


@dataclass
class PromptFeedbackState:
    iteration: int = 0
    last_prompt: str | None = None
    last_feedback: str = ""


logger = logging.getLogger(__name__)


def make_prompt_feedback_server_with_state(
    deps: PromptEvaluationDeps, feedback_provider: FeedbackProvider, *, name: str = "prompt_feedback"
) -> tuple[FastMCP, PromptFeedbackState]:
    """FastMCP with closure state (tools-builder style). No lifespan/ContextVar.

    Returns (server, state). Attach via mcp.attach_inproc.
    """
    state = PromptFeedbackState()
    mcp = FastMCP(name, instructions="Prompt evaluation (rollouts+grading+persistence)")

    @mcp.tool()
    async def propose_prompt(prompt: str) -> dict[str, str]:
        logger.info("propose_prompt: start", extra={"prompt": prompt})
        state.iteration += 1
        state.last_prompt = prompt
        tasks = await deps.select_seed_tasks()
        rollouts = await deps.run_rollouts_with_prompt(prompt, tasks)
        # Let the configured provider compute feedback (may grade/aggregate internally)
        feedback = await feedback_provider.provide_feedback(rollouts)
        logger.info("propose_prompt: about to persist", extra={"iter": state.iteration})
        deps.persist_all(iteration=state.iteration, prompt=prompt, rollouts=rollouts, feedback=feedback)
        logger.info("propose_prompt: persisted", extra={"iter": state.iteration})
        state.last_feedback = feedback
        return {"feedback": feedback}

    return mcp, state


async def attach_prompt_feedback(
    comp: Compositor, deps: PromptEvaluationDeps, feedback_provider: FeedbackProvider, *, name: str = "prompt_feedback"
):
    """Attach prompt_feedback in-proc; return (server, state)."""
    server, state = make_prompt_feedback_server_with_state(deps, feedback_provider, name=name)
    await comp.mount_inproc(name, server)
    return server, state
