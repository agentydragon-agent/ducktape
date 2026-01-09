from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any, Literal

import aiodocker
from pydantic import BaseModel, ConfigDict, Field
from rich.console import Console
from rich.table import Table

from openai_utils.json_schema import openai_json_schema
from openai_utils.model import (
    FunctionCallItem,
    FunctionToolParam,
    OpenAIModelProto,
    ResponsesRequest,
    ToolChoiceFunction,
    UserMessage,
)
from props.core.ids import BaseIssueID, SnapshotSlug
from props.core.models.true_positive import IssueCore, Occurrence
from props.core.runs_context import RunsContext, format_timestamp_session


# ---------- Expectations / Assertions ----------
class AnchorExpectation(BaseModel):
    kind: Literal["anchor"] = "anchor"
    start_window: tuple[int, int] = Field(..., description="Allowed start window [smin, smax]")
    end_window: tuple[int, int] = Field(..., description="Allowed end window [emin, emax]")


class RationaleExpectation(BaseModel):
    kind: Literal["rationale"] = "rationale"
    rubric: str = Field(
        ...,
        description=(
            "Instruction text explaining how the rationale should be corrected; phrase as a positive question where YES means correct behavior"
        ),
    )


class FindingsMatcherExpectation(BaseModel):
    kind: Literal["findings_matcher"] = "findings_matcher"
    matcher: Any  # Accepts arbitrary matcher objects; protocol not yet defined


Expectation = Annotated[
    AnchorExpectation | RationaleExpectation | FindingsMatcherExpectation, Field(discriminator="kind")
]


class GradeRationaleArgs(BaseModel):
    verdict: Literal["YES", "PARTIALLY", "NO"]
    reason: str
    model_config = ConfigDict(extra="forbid")


class OccurrenceCase(BaseModel):
    """One occurrence and its expectations."""

    occurrence: Occurrence
    expectations: list[Expectation] | None = Field(default=None, description="Expectations for this occurrence")


class IssueEvalSpec(BaseModel):
    """One issue under a snapshot with multiple occurrence cases."""

    snapshot: SnapshotSlug
    issue: IssueCore
    cases: list[OccurrenceCase]


# Placeholder for eval samples - populate with real snapshot data as needed
# TODO: Add evaluation test cases from actual snapshots


class SampleRunSummary(BaseModel):
    snapshot: str
    tp_id: BaseIssueID
    total: int
    passed: int
    failed: int
    summary_path: str


class EvalIndex(BaseModel):
    samples: list[SampleRunSummary]


async def _grade_rationale_with_llm(
    client: OpenAIModelProto, original: str, proposed: str, *, rubric: str
) -> dict[str, str]:
    """Force a tool call that returns verdict: YES | PARTIALLY | NO, with reason."""
    if not proposed or not proposed.strip():
        return {"verdict": "NO", "reason": "No suggested rationale provided by linter."}
    tools: list[FunctionToolParam] = [
        FunctionToolParam(
            name="grade_rationale",
            description="Return verdict and brief reason.",
            parameters=openai_json_schema(GradeRationaleArgs),
            strict=True,
        )
    ]
    prompt = (
        "Original issue description:\n"
        + original.strip()
        + "\n\nNew issue description:\n"
        + proposed.strip()
        + "\n\n"
        + rubric.strip()
        + "\n\nQuestion: Is the new description corrected as it should be?"
    )
    req = ResponsesRequest(
        input=[UserMessage.text(prompt)], tools=tools, tool_choice=ToolChoiceFunction(name="grade_rationale")
    )
    resp = await client.responses_create(req)
    # Extract function call robustly; fail fast on missing/invalid
    call: FunctionCallItem | None = next(
        (it for it in resp.output if isinstance(it, FunctionCallItem) and it.name == "grade_rationale"), None
    )
    if call is None:
        raise RuntimeError("grade_rationale function call not returned by model")

    raw_args = call.arguments
    if raw_args is None:
        parsed_args: GradeRationaleArgs = GradeRationaleArgs(verdict="NO", reason="")
    else:
        if isinstance(raw_args, str):
            try:
                loaded = json.loads(raw_args)
            except Exception as e:  # pragma: no cover - defensive error surfacing
                raise RuntimeError("grade_rationale arguments not valid JSON") from e
        elif isinstance(raw_args, dict):
            loaded = raw_args
        else:
            raise RuntimeError(f"grade_rationale arguments unsupported type: {type(raw_args).__name__}")

        try:
            parsed_args = GradeRationaleArgs.model_validate(loaded)
        except Exception as e:
            raise RuntimeError("grade_rationale payload failed validation") from e

    verdict = parsed_args.verdict
    reason = parsed_args.reason.strip()
    if verdict not in ("YES", "PARTIALLY", "NO"):
        raise RuntimeError("grade_rationale returned unexpected verdict")
    return {"verdict": verdict, "reason": reason}


async def eval_issue_spec(
    spec: IssueEvalSpec,
    *,
    client: OpenAIModelProto,
    docker_client: aiodocker.Docker,
    out_dir: Path | str | None = None,
    ctx: RunsContext,
) -> SampleRunSummary:
    """Run lint_issue_run over a list of cases and write an eval summary.

    TODO: Temporarily disabled - lint_issue_run now requires content_root.
    Reimplement to fetch snapshot content from database.
    """
    raise NotImplementedError(
        "eval_issue_spec is temporarily disabled - lint_issue_run now requires content_root. "
        "Reimplement to fetch snapshot content from database."
    )


def _load_samples() -> list[IssueEvalSpec]:
    """Load eval samples from real snapshot data.

    TODO: Populate with actual test cases from current snapshots.
    """
    return []


async def run_all_evals(
    *,
    client: OpenAIModelProto,
    docker_client: aiodocker.Docker,
    root_out: Path | None = None,
    concurrency: int = 4,
    ctx: RunsContext,
) -> EvalIndex:
    """Run all samples concurrently (bounded), print a Rich summary, and return EvalIndex."""
    ts = format_timestamp_session()
    root = Path(root_out) if root_out is not None else ctx.issue_eval_dir("all", ts)

    sem = asyncio.Semaphore(max(1, concurrency))

    async def _run_one(sample: IssueEvalSpec) -> SampleRunSummary:
        async with sem:
            out_dir = root / sample.issue.id
            return await eval_issue_spec(
                spec=sample, client=client, docker_client=docker_client, out_dir=out_dir, ctx=ctx
            )

    entries = await asyncio.gather(*[_run_one(s) for s in _load_samples()])

    eval_index = EvalIndex(samples=list(entries))
    (root / "index.json").write_text(eval_index.model_dump_json(indent=2), encoding="utf-8")

    # Pretty print a concise Rich table summary (in-memory; no read-back)
    table = Table(title="Eval Summary", show_lines=False)
    table.add_column("Specimen")
    table.add_column("Issue")
    table.add_column("Total", justify="right")
    table.add_column("Passed", justify="right", style="green")
    table.add_column("Failed", justify="right", style="red")
    table.add_column("Summary Path")

    for ent in eval_index.samples:
        table.add_row(ent.snapshot, ent.tp_id, str(ent.total), str(ent.passed), str(ent.failed), ent.summary_path)
    Console().print(table)

    return eval_index
