from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any, Literal

from hamcrest import assert_that
from pydantic import BaseModel, ConfigDict, Field
from rich.console import Console
from rich.table import Table

from adgn.agent.agent_progress import OneLineProgressHandler
from adgn.llm.rendering.rich_renderers import render_to_rich
from adgn.openai_utils.model import (
    FunctionCallItem,
    FunctionToolParam,
    OpenAIModelProto,
    ResponsesRequest,
    ToolChoiceFunction,
    UserMessage,
)
from adgn.props.ids import BaseIssueID
from adgn.props.models.lint import extract_corrections
from adgn.props.models.true_positive import IssueCore, Occurrence
from adgn.props.runs_context import RunsContext, format_timestamp_session
from adgn.props.snapshot_registry import SnapshotRegistry

from .lint_issue import lint_issue_run


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
    matcher: Any


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
    """One issue under a specimen with multiple occurrence cases."""

    specimen: str
    issue: IssueCore
    cases: list[OccurrenceCase]


# Placeholder for eval samples - populate with real specimen data as needed
# TODO: Add evaluation test cases from actual specimens


class SampleRunSummary(BaseModel):
    specimen: str
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
            parameters=GradeRationaleArgs.model_json_schema(),
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
    registry: SnapshotRegistry,
    out_dir: Path | str | None = None,
    ctx: RunsContext,
) -> SampleRunSummary:
    """Run lint_issue_run over a list of cases and write an eval summary.

    Returns a structured SampleRunSummary and writes summary.json to out_dir.
    """
    ts = format_timestamp_session()
    base = Path(out_dir) if out_dir is not None else ctx.issue_eval_dir(f"{spec.specimen}_{spec.issue.id}", ts)

    results: list[dict[str, Any]] = []
    passes = 0

    for idx, case in enumerate(spec.cases):
        exps_raw = case.expectations
        exps: list[Expectation] = list(exps_raw) if exps_raw is not None else []

        occ = case.occurrence
        files_items = list(occ.files.items())
        if len(files_items) != 1:
            raise SystemExit("Case occurrence must target exactly one file")
        path, ranges = files_items[0]
        # Occurrence.files values are list[LineRange] | None in the schema; enforce exactly one range here.
        if ranges is None:
            raise SystemExit(f"Case occurrence for {path} must have exactly one range (got None)")
        if len(ranges) != 1:
            raise SystemExit(f"Case occurrence for {path} must have exactly one range")
        first = ranges[0]
        start_line = first.start_line
        end_line = first.end_line
        entity = occ.note or ""

        payload = await lint_issue_run(
            specimen=spec.specimen,
            issue_core=spec.issue,
            occurrence=occ,
            client=client,
            handlers=[OneLineProgressHandler()],
            registry=registry,
        )

        # Print the structured output object produced by the agent for this case
        Console().print(f"[bold]{spec.specimen} {spec.issue.id} case {idx} {path}[/bold]")
        Console().print(render_to_rich(payload))

        # Effective ranges: derive corrections from AnchorIncorrect findings when present
        corrections = extract_corrections(payload.findings)
        all_ranges = [(r.start_line, r.end_line) for r in corrections[path]]
        effective: list[tuple[int, int | None]] = all_ranges or [(start_line, end_line)]

        estart, eend = effective[0]

        # Evaluate expectations
        case_pass = True
        exp_results: list[dict[str, Any]] = []
        for exp in exps:
            if isinstance(exp, AnchorExpectation):
                smin, smax = exp.start_window
                emin, emax = exp.end_window
                ok = (eend is not None) and (smin <= estart <= smax) and (emin <= eend <= emax)
                exp_results.append(
                    {
                        "kind": "anchor",
                        "start_window": list(exp.start_window),
                        "end_window": list(exp.end_window),
                        "effective_range": [estart, eend],
                        "passed": bool(ok),
                    }
                )
                case_pass = case_pass and ok
            elif isinstance(exp, RationaleExpectation):
                grade = await _grade_rationale_with_llm(
                    client, spec.issue.rationale, payload.suggested_rationale or "", rubric=exp.rubric
                )
                ok = grade.get("verdict") == "YES"
                exp_results.append(
                    {
                        "kind": "rationale",
                        "verdict": grade.get("verdict"),
                        "reason": grade.get("reason"),
                        "rubric": exp.rubric,
                        "passed": bool(ok),
                    }
                )
                case_pass = case_pass and ok
            elif isinstance(exp, FindingsMatcherExpectation):
                # Apply a PyHamcrest matcher to the REAL finding objects (not flattened dicts)
                try:
                    assert_that(payload.findings, exp.matcher)
                    ok = True
                    reason = None
                except AssertionError as e:
                    ok = False
                    reason = str(e)
                exp_results.append({"kind": "findings_matcher", "passed": bool(ok), "reason": reason})
                case_pass = case_pass and ok

        passes += int(case_pass)

        # Write per-case payload
        (base / f"case_{idx:02d}_payload.json").write_text(payload.model_dump_json(indent=2), encoding="utf-8")

        item: dict[str, Any] = {
            "index": idx,
            "path": path,
            "entity": entity,
            "initial_range": [start_line, end_line],
            "ranges_reported": all_ranges,
            "effective_range": [estart, eend],
            "passed": case_pass,
            "expectations": exp_results,
            "message_excerpt": payload.message_md[:400],
        }
        results.append(item)

    summary_obj = {
        "specimen": spec.specimen,
        "tp_id": spec.issue.id,
        "total": len(spec.cases),
        "passed": passes,
        "failed": len(spec.cases) - passes,
        "results": results,
    }
    (base / "summary.json").write_text(json.dumps(summary_obj, indent=2), encoding="utf-8")

    return SampleRunSummary(
        specimen=spec.specimen,
        tp_id=spec.issue.id,
        total=len(spec.cases),
        passed=passes,
        failed=len(spec.cases) - passes,
        summary_path=str(base / "summary.json"),
    )


def _load_samples() -> list[IssueEvalSpec]:
    """Load eval samples from real specimen data.

    TODO: Populate with actual test cases from current specimens.
    """
    # Return empty list for now - add real evaluation cases as needed
    return []


async def run_all_evals(
    *,
    client: OpenAIModelProto,
    registry: SnapshotRegistry,
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
            return await eval_issue_spec(spec=sample, client=client, registry=registry, out_dir=out_dir, ctx=ctx)

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
        table.add_row(ent.specimen, ent.tp_id, str(ent.total), str(ent.passed), str(ent.failed), ent.summary_path)
    Console().print(table)

    return eval_index
