"""Prompt Evaluation MCP server.

- Server name: prompt_eval
 - Tool: test_prompt(PromptEvalArgs) -> PromptEvalOutput (typed metrics list)

Behavior:
- On each call, iterates all known specimens (SpecimenRegistry), runs the critic and grader, and returns typed metrics.
- Persists artifacts under props/runs/prompt_optimize/<ts>/<round>/<specimen>/ including critic.json, grade.json, and transcripts.
- Failure semantics: if any specimen run fails, this tool raises an Exception. FastMCP translates
  this into an isError tool payload. Callers should treat such results as tool errors.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import json
import logging
from pathlib import Path
import traceback
from typing import Any

from fastmcp.client import Client
from pydantic import BaseModel, ConfigDict

from adgn.agent.agent import MiniCodex
from adgn.agent.handler import BaseHandler
from adgn.agent.loop_control import Continue, NoLoopDecision, RequireAny
from adgn.agent.reducer import GateUntil
from adgn.agent.transcript_handler import TranscriptHandler
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.openai_utils.model import OpenAIModelProto
from adgn.props.critic import CriticSubmitPayload, CriticSubmitState, attach_critic_submit
from adgn.props.docker_env import properties_docker_spec
from adgn.props.grade_runner import _metrics_row, grade_critic_output
from adgn.props.lint_issue import make_container_info_call, make_ls_workspace_call
from adgn.props.prompts.util import build_scope_text, render_prompt_template
from adgn.props.prop_utils import pkg_dir
from adgn.props.specimens.registry import SpecimenRegistry, find_specimens_base, list_specimen_names

logger = logging.getLogger(__name__)


class PromptEvalArgs(BaseModel):
    """Input model for test_prompt (flat helper for tests)."""

    prompt: str
    model_config = ConfigDict(extra="forbid")


class MetricsRow(BaseModel):
    """Typed per-specimen metrics row returned by prompt_eval.test_prompt."""

    specimen: str
    expected: int
    reported: int
    true_positives: int
    false_positive: int
    unknown: int
    false_negatives: int
    precision: float
    recall: float
    fuzzy_precision: float
    fuzzy_recall: float

    model_config = ConfigDict(extra="forbid")


class PromptEvalOutput(BaseModel):
    metrics: list[MetricsRow]

    model_config = ConfigDict(extra="forbid")


async def _run_critic_for_specimen(
    specimen: str, system_prompt: str, client: OpenAIModelProto, run_dir: Path, *, agent_model: str = "gpt-5"
) -> CriticSubmitPayload:
    """Run critic with a custom system prompt (no properties mount); return CriticSubmitPayload model and persist."""
    rec = SpecimenRegistry.load_strict(specimen)
    critic_state = CriticSubmitState()

    # Render user prompt with explicit scope (no property definitions mounted)
    scope_text = build_scope_text(rec.manifest.scope.include, rec.manifest.scope.exclude)
    user_prompt = render_prompt_template("critic_user_prompt.j2.md", scope_text=scope_text)

    async with rec.hydrated_copy(gitconfig=None) as content_root:
        wiring = properties_docker_spec(content_root, mount_properties=False)
        comp = Compositor("compositor")
        await wiring.attach(comp)
        await attach_critic_submit(comp, critic_state)

        # Bootstrap handler: emit synthetic function_calls without sampling to inspect mounts
        class BootstrapInspectHandler(BaseHandler):
            def __init__(self) -> None:
                self._done: bool = False
                self._emitted: bool = False

            def on_before_sample(self):
                if self._done:
                    return NoLoopDecision()
                # First cycle: emit synthetic calls, but do NOT mark done yet
                if not self._emitted:
                    self._emitted = True
                    calls = [make_container_info_call(wiring)]
                    calls.append(make_ls_workspace_call(wiring))
                    return Continue(RequireAny(), inserts_input=tuple(calls), skip_sampling=True)
                # Second cycle: mark done and defer; subsequent cycles will continue normally
                self._done = True
                return NoLoopDecision()

        bootstrap = BootstrapInspectHandler()

        def _ready_state() -> bool:
            return (critic_state.result is not None) or (critic_state.error is not None)

        def _defer_bootstrap() -> bool:
            return not bootstrap._done

        handlers = [
            bootstrap,
            # Canonical per-run transcript JSONL (events.jsonl + metadata.json)
            TranscriptHandler(dest_dir=run_dir / specimen / "critic"),
            # Defer gating during first bootstrap phase to avoid Continue conflicts
            GateUntil(_ready_state, defer_when=_defer_bootstrap),
        ]
        # Use the caller-provided typed client; logging is configured at the entrypoint
        model_client: OpenAIModelProto = client
        async with Client(comp) as mcp_client:
            agent = await MiniCodex.create(
                model=agent_model,
                mcp_client=mcp_client,
                system=system_prompt,
                client=model_client,
                handlers=handlers,
                parallel_tool_calls=True,
            )
            await agent.run(user_prompt)
    assert (critic_state.result is not None) or (critic_state.error is not None), (
        "critic_submit.submit_result or submit_error was not called"
    )
    # Persist
    out_dir = run_dir / specimen
    out_dir.mkdir(parents=True, exist_ok=True)
    if critic_state.error is not None:
        (out_dir / "critic_error.json").write_text(critic_state.error.model_dump_json(indent=2), encoding="utf-8")
        raise RuntimeError(
            f"critic error: {critic_state.error.message}"
        )  # surfaced to caller; per-round errors.json aggregates
    assert critic_state.result is not None
    (out_dir / "critic.json").write_text(critic_state.result.model_dump_json(indent=2), encoding="utf-8")
    return critic_state.result


@dataclass
class PromptEvalState:
    successful_calls: int = 0


def build_server(
    *, client: OpenAIModelProto, name: str = "prompt_eval", agent_model: str = "gpt-5", run_dir_base: Path | None = None
) -> tuple[NotifyingFastMCP, PromptEvalState]:
    """Build a prompt_eval server that tracks rounds and writes under a fixed run dir.

    Layout (per server instance):
    adgn_llm/properties/runs/prompt_optimize/<ts>/<round>/<specimen>/{critic,grader}/...
    """
    # Freeze base run dir at server construction (tests may inject a tmp dir)
    if run_dir_base is not None:
        base_run_dir = run_dir_base
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_run_dir = pkg_dir() / "runs" / "prompt_optimize" / ts
    base_run_dir.mkdir(parents=True, exist_ok=True)
    round_idx = {"n": -1}  # mutable cell for closure

    state = PromptEvalState()

    mcp = NotifyingFastMCP(name, instructions="Prompt Evaluation server — evaluate candidate critic prompts")
    # TODO(mpokorny): FastMCP wraps tool Exceptions into ToolError, so this tool cannot crash the server;
    # failures propagate as tool errors. We log at ERROR and surface per-specimen/round summaries.

    @mcp.tool(flat=True)
    async def test_prompt(payload: PromptEvalArgs) -> PromptEvalOutput:
        """Evaluate a critic system prompt across all specimens and return metrics.

        Success: returns PromptEvalOutput(metrics=[...]).
        Failure: raises an Exception; FastMCP will surface an isError tool payload.
        """
        # Next round
        round_idx["n"] += 1
        this_round = round_idx["n"]
        round_dir = base_run_dir / str(this_round)
        round_dir.mkdir(parents=True, exist_ok=True)
        (round_dir / "prompt.txt").write_text(payload.prompt, encoding="utf-8")
        logger.info("prompt_eval round root: %s", round_dir)

        base = find_specimens_base()
        specimens = list_specimen_names(base)
        # client is required and injected by the caller to avoid implicit network clients
        if client is None:
            raise ValueError("build_server requires a non-None client to be passed; tests must opt-in via fixtures")

        async def one(specimen: str) -> MetricsRow:
            out_dir = round_dir / specimen
            out_dir.mkdir(parents=True, exist_ok=True)
            try:
                critic_obj = await _run_critic_for_specimen(
                    specimen, payload.prompt, client, round_dir, agent_model=agent_model
                )
                # Persist grade JSON and transcript under round/specimen
                grade_obj = await grade_critic_output(specimen, critic_obj, client, transcript_out_dir=out_dir)
                (out_dir / "grade.json").write_text(grade_obj.model_dump_json(indent=2), encoding="utf-8")
                critic_log = out_dir / "critic" / "events.jsonl"
                grader_log = out_dir / "grader" / "events.jsonl"
                logger.debug("critic transcript: %s", critic_log)
                logger.debug("grader transcript: %s", grader_log)
                row_dict: dict[str, Any] = _metrics_row(grade_obj, specimen=specimen)
                row_model = MetricsRow(**row_dict)
                # Log the full metrics model (structured) for easier downstream parsing
                logger.info("metrics %s", row_model.model_dump(exclude_none=True))
                return row_model
            except Exception as e:
                # Persist detailed traceback per specimen; then re-raise original
                (out_dir / "error.txt").write_text("".join(traceback.format_exception(e)), encoding="utf-8")
                logger.exception("Unhandled error during specimen run", extra={"specimen": specimen})
                raise

        # Run all specimens concurrently and return structured success/failure to the caller.
        results = await asyncio.gather(*[one(s) for s in specimens], return_exceptions=True)

        metrics_list: list[MetricsRow] = []
        # Keep lightweight summary of errors to include in raised message and persist
        errors_serial: list[dict[str, str]] = []
        for spec, res in zip(specimens, results, strict=False):
            if isinstance(res, BaseException):
                # per-specimen error.txt is already written inside `one`; summarize here
                errors_serial.append({"specimen": spec, "type": type(res).__name__, "message": str(res)})
            else:
                metrics_list.append(res)

        # Persist results and/or errors
        if metrics_list:
            (round_dir / "results.json").write_text(
                json.dumps([m.model_dump() for m in metrics_list], indent=2), encoding="utf-8"
            )
        if errors_serial:
            # write a lightweight serialized errors list for human consumption
            (round_dir / "errors.json").write_text(json.dumps(errors_serial, indent=2), encoding="utf-8")
            logger.error(
                "Round completed with specimen errors; see %s/errors.json (first error: %s)",
                round_dir,
                errors_serial[0],
            )
            # Raise to signal a tool error via FastMCP. Include first error for quick visibility.
            first = errors_serial[0]
            raise RuntimeError(
                f"prompt_eval round had errors (e.g., {first['specimen']}: {first['type']}: {first['message']}). "
                f"See {round_dir}/errors.json for details."
            )

        # All specimens succeeded
        state.successful_calls += 1
        return PromptEvalOutput(metrics=metrics_list)

    return mcp, state


async def attach_prompt_eval(
    comp: Compositor,
    *,
    client: OpenAIModelProto,
    name: str = "prompt_eval",
    agent_model: str = "gpt-5",
    run_dir_base: Path | None = None,
):
    """Attach prompt_eval in-proc; return (server, state)."""
    server, state = build_server(client=client, name=name, agent_model=agent_model, run_dir_base=run_dir_base)
    await comp.mount_inproc(name, server)
    return server, state
