from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Protocol, cast

from mcp.server.fastmcp import FastMCP

from adgn.llm.inop.prompting.prompt_engineer import FeedbackProvider

# ---- Dependencies and state -------------------------------------------------


class PromptEvaluationDeps(Protocol):
    async def select_seed_tasks(self) -> list[Any]: ...
    async def run_rollouts_with_prompt(
        self,
        prompt: str,
        tasks: list[Any],
    ) -> list[Any]: ...
    def persist_all(
        self,
        *,
        iteration: int,
        prompt: str,
        rollouts: list[Any],
        feedback: str,
    ) -> None: ...


@dataclass
class PromptFeedbackState:
    iteration: int = 0
    last_prompt: str | None = None
    last_feedback: str = ""


@dataclass
class SessionStateHandle:
    ready: asyncio.Event
    state: PromptFeedbackState | None = None


_state_var: ContextVar[PromptFeedbackState] = ContextVar("_prompt_feedback_state")
logger = logging.getLogger(__name__)


# ---- Server factory ---------------------------------------------------------


def make_prompt_feedback_server_with_handle(
    deps: PromptEvaluationDeps,
    feedback_provider: FeedbackProvider,
    *,
    name: str = "prompt_feedback",
) -> tuple[FastMCP, SessionStateHandle]:
    """FastMCP server with per-session state and an external handle.

    Usage (in-proc only):
      server, handle = make_prompt_feedback_server_with_handle(deps, feedback_provider)
      # Wire server into fastmcp_inproc_client session; after initialize:
      await handle.ready.wait(); state = handle.state
    """
    handle = SessionStateHandle(ready=asyncio.Event())

    @asynccontextmanager
    async def lifespan(_server: FastMCP):  # yields PromptFeedbackState per session
        state = PromptFeedbackState()
        handle.state = state
        handle.ready.set()
        token: Token = _state_var.set(state)
        try:
            yield state
        finally:
            _state_var.reset(token)

    mcp = FastMCP(
        name,
        instructions="Prompt evaluation (rollouts+grading+persistence)",
        lifespan=lifespan,
    )

    @mcp.tool()
    async def propose_prompt(prompt: str) -> dict[str, str]:
        logger.info("propose_prompt: start", extra={"prompt": prompt})
        # Use request context lifespan to get per-session state; avoids cross-task ContextVar issues
        ctx = mcp.get_context()
        state = cast(PromptFeedbackState, ctx.request_context.lifespan_context)
        state.iteration += 1
        state.last_prompt = prompt
        tasks = await deps.select_seed_tasks()
        rollouts = await deps.run_rollouts_with_prompt(prompt, tasks)
        # Let the configured provider compute feedback (may grade/aggregate internally)
        feedback = await feedback_provider.provide_feedback(rollouts)
        logger.info("propose_prompt: about to persist", extra={"iter": state.iteration})
        deps.persist_all(
            iteration=state.iteration,
            prompt=prompt,
            rollouts=rollouts,
            feedback=feedback,
        )
        logger.info("propose_prompt: persisted", extra={"iter": state.iteration})
        state.last_feedback = feedback
        return {"feedback": feedback}

    return mcp, handle
