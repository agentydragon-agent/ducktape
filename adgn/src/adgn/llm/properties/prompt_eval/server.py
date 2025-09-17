"""Prompt Evaluation MCP server.

- Server name: prompt_eval
- Tool: test_prompt(prompt: str) -> list[dict] of numeric metrics per specimen

Behavior:
- On each call, iterates all known specimens (SpecimenRegistry), runs the critic and grader, and returns only metrics.
- Persists artifacts under adgn_llm/properties/runs/prompt_optimize/<ts>/<round>/<specimen>/ including critic.json, grade.json, and transcripts.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import json
import logging
from pathlib import Path
import traceback
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import GateUntil
from adgn.llm.mini_codex.loggers import TranscriptLoggerHandler
from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.mini_codex.transcript_handler import TranscriptHandler
from adgn.llm.properties.critic import (
    CriticSubmitPayload,
    CriticSubmitState,
    make_critic_submit_server,
)
from adgn.llm.properties.docker_env import properties_docker_spec
from adgn.llm.properties.grade_runner import _metrics_row, grade_critic_output
from adgn.llm.properties.prompts.util import build_scope_text, render_prompt_template
from adgn.llm.properties.prop_utils import pkg_dir
from adgn.llm.properties.specimens.registry import (
    SpecimenRegistry,
    find_specimens_base,
    list_specimen_names,
)

logger = logging.getLogger(__name__)


async def _run_critic_for_specimen(
    specimen: str,
    system_prompt: str,
    client: AsyncOpenAI,
    run_dir: Path,
    *,
    agent_model: str = "gpt-5",
) -> CriticSubmitPayload:
    """Run critic with a custom system prompt (no properties mount); return CriticSubmitPayload model and persist."""
    rec = SpecimenRegistry.load_strict(specimen)
    critic_state = CriticSubmitState()

    # Render user prompt with explicit scope (no property definitions mounted)
    scope_text = build_scope_text(
        rec.manifest.scope.include,
        rec.manifest.scope.exclude,
    )
    user_prompt = render_prompt_template(
        "critic_user_prompt.j2.md",
        scope_text=scope_text,
    )

    async with rec.hydrated_copy(gitconfig=None) as content_root:
        wiring = properties_docker_spec(content_root, mount_properties=False)
        critic_server = make_critic_submit_server(critic_state, name="critic_submit")
        specs = {
            wiring.server_name: wiring.server_spec,
            "critic_submit": make_inproc_slot_spec(critic_server),
        }
        async with McpManager(specs) as mcp:
            handlers = [
                TranscriptHandler(dest_dir=run_dir / specimen / "critic"),
                TranscriptLoggerHandler(run_dir / specimen / "critic"),
                GateUntil(
                    lambda: (critic_state.result is not None)
                    or (critic_state.error is not None),
                ),
            ]
            agent = await MiniCodex.create(
                model=agent_model,
                mcp=mcp,
                system=system_prompt,
                client=client,
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
        (out_dir / "critic_error.json").write_text(
            critic_state.error.model_dump_json(indent=2),
            encoding="utf-8",
        )  # type: ignore[attr-defined]
        raise RuntimeError(
            f"critic error: {critic_state.error.message}",
        )  # surfaced to caller; per-round errors.json aggregates
    assert critic_state.result is not None
    (out_dir / "critic.json").write_text(
        critic_state.result.model_dump_json(indent=2),
        encoding="utf-8",
    )  # type: ignore[attr-defined]
    return critic_state.result


@dataclass
class PromptEvalState:
    successful_calls: int = 0


# Structured return types for prompt_eval.test_prompt (module-level so FastMCP can resolve)
class SpecimenError(BaseModel):
    specimen: str
    type: str
    message: str

    model_config = ConfigDict(extra="forbid")


class PromptEvalFailure(BaseModel):
    kind: Literal["Failure"] = "Failure"
    errors: list[SpecimenError]

    model_config = ConfigDict(extra="forbid")


class PromptEvalSuccess(BaseModel):
    kind: Literal["Success"] = "Success"
    metrics: list[dict[str, Any]]

    model_config = ConfigDict(extra="forbid")


PromptEvalResult = Annotated[
    PromptEvalSuccess | PromptEvalFailure,
    Field(discriminator="kind"),
]


def build_server(
    *,
    client: AsyncOpenAI,
    name: str = "prompt_eval",
    agent_model: str = "gpt-5",
) -> tuple[FastMCP, PromptEvalState]:
    """Build a prompt_eval server that tracks rounds and writes under a fixed run dir.

    Layout (per server instance):
    adgn_llm/properties/runs/prompt_optimize/<ts>/<round>/<specimen>/{critic,grader}/...
    """
    # Freeze base run dir at server construction
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_run_dir = pkg_dir() / "runs" / "prompt_optimize" / ts
    base_run_dir.mkdir(parents=True, exist_ok=True)
    round_idx = {"n": -1}  # mutable cell for closure

    state = PromptEvalState()

    mcp = FastMCP(
        name,
        instructions="Prompt Evaluation server — evaluate candidate critic prompts",
    )
    # TODO(mpokorny): FastMCP wraps tool Exceptions into ToolError, so this tool cannot crash the server;
    # failures propagate as tool errors. We log at ERROR and surface per-specimen/round summaries.

    @mcp.tool()
    async def test_prompt(prompt: str) -> PromptEvalResult:
        """Evaluate a candidate system prompt across all known specimens and return a structured result.

        Returns a discriminated union: PromptEvalSuccess(kind='Success', metrics=...) or
        PromptEvalFailure(kind='Failure', errors=[SpecimenError,...])
        """
        # Next round
        round_idx["n"] += 1
        this_round = round_idx["n"]
        round_dir = base_run_dir / str(this_round)
        round_dir.mkdir(parents=True, exist_ok=True)
        (round_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        print(f"[logs] round root: {round_dir}")

        base = find_specimens_base()
        specimens = list_specimen_names(base)
        # client is required and injected by the caller to avoid implicit network clients
        if client is None:
            raise ValueError(
                "build_server requires a non-None client to be passed; tests must opt-in via fixtures",
            )

        async def one(specimen: str) -> dict[str, Any]:
            out_dir = round_dir / specimen
            out_dir.mkdir(parents=True, exist_ok=True)
            try:
                critic_obj = await _run_critic_for_specimen(
                    specimen,
                    prompt,
                    client,
                    round_dir,
                    agent_model=agent_model,
                )
                # Persist grade JSON and transcript under round/specimen
                grade_obj = await grade_critic_output(
                    specimen,
                    critic_obj,
                    client,
                    transcript_out_dir=out_dir,
                )
                (out_dir / "grade.json").write_text(
                    grade_obj.model_dump_json(indent=2),
                    encoding="utf-8",
                )
                critic_log = out_dir / "critic" / "events.jsonl"
                grader_log = out_dir / "grader" / "events.jsonl"
                print(f"[logs] critic: {critic_log}")
                print(f"[logs] grader: {grader_log}")
                m = grade_obj.metrics
                print(
                    f"[metrics] specimen={specimen} expected={m.expected} reported={m.reported} "
                    f"tp={m.true_positives} fp={m.false_positive} unk={m.unknown} fn={m.false_negatives} "
                    f"fuzzy_precision={m.precision:.3f} fuzzy_recall={m.recall:.3f}",
                )
                return _metrics_row(grade_obj, specimen=specimen)
            except Exception as e:
                # Persist detailed traceback per specimen; then re-raise original
                (out_dir / "error.txt").write_text(
                    "".join(traceback.format_exception(e)),
                    encoding="utf-8",
                )
                logger.exception(
                    "Unhandled error during specimen run",
                    extra={"specimen": specimen},
                )
                raise

        # Run all specimens concurrently and return structured success/failure to the caller.
        results = await asyncio.gather(
            *[one(s) for s in specimens],
            return_exceptions=True,
        )

        metrics_list: list[dict[str, Any]] = []
        errors_objs: list[SpecimenError] = []
        for spec, res in zip(specimens, results, strict=False):
            if isinstance(res, BaseException):
                # per-specimen error.txt is already written inside `one`; summarize here
                errors_objs.append(
                    SpecimenError(
                        specimen=spec,
                        type=type(res).__name__,
                        message=str(res),
                    ),
                )
            else:
                metrics_list.append(res)

        # Persist results and/or errors
        if metrics_list:
            (round_dir / "results.json").write_text(
                json.dumps(metrics_list, indent=2),
                encoding="utf-8",
            )
        if errors_objs:
            # write a lightweight serialized errors list for human consumption
            errors_serial = [e.model_dump(exclude_none=True) for e in errors_objs]
            (round_dir / "errors.json").write_text(
                json.dumps(errors_serial, indent=2),
                encoding="utf-8",
            )
            logger.error(
                "Round completed with specimen errors; see %s/errors.json (first error: %s)",
                round_dir,
                errors_serial[0],
            )
            # Return structured failure to caller; let the agent/handler decide to abort
            return PromptEvalFailure(errors=errors_objs)

        # All specimens succeeded
        state.successful_calls += 1
        return PromptEvalSuccess(metrics=metrics_list)

    return mcp, state
