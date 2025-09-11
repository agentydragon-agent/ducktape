from __future__ import annotations

import asyncio
import json
import datetime as _dt
from pathlib import Path
from typing import Any, Sequence, Literal, Annotated, Union

from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from rich.console import Console
from rich.table import Table

from adgn_llm.mini_codex.event_renderer import NullConsoleEventRenderer
from adgn_llm.rendering.rich_renderers import render_to_rich
from .lint_issue import lint_issue_run
from .specimen_utils import IssueCore, Occurrence, LineRange


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


Expectation = Annotated[Union[AnchorExpectation, RationaleExpectation], Field(discriminator="kind")]


class CaseSpec(BaseModel):
    """Single eval case specification (1-based inclusive ranges)."""

    path: str
    initial_range: tuple[int, int] = Field(..., description="[start, end] inclusive")
    expectations: list[Expectation] | None = Field(default=None, description="List of expectations for this case")
    entity: str | None = Field(default=None, description="Optional occurrence note (freeform)")


# Canonical dataset: 2025-09-02-ducktape_wt iss-014 (four occurrences)
WT_ISS014_CASES: list[CaseSpec] = [
    CaseSpec(
        path="wt/wt/server/wt_server.py",
        initial_range=(413, 424),
        expectations=[AnchorExpectation(start_window=(410, 412), end_window=(421, 423))],
        entity="StatusSnapshot",
    ),
    CaseSpec(
        path="wt/wt/server/wt_server.py",
        initial_range=(425, 429),
        expectations=[AnchorExpectation(start_window=(422, 424), end_window=(427, 429))],
        entity="WorktreeRuntime",
    ),
    CaseSpec(
        path="wt/wt/server/wt_server.py",
        initial_range=(640, 1144),
        expectations=[AnchorExpectation(start_window=(638, 640), end_window=(1142, 1144))],
        entity="GitStatusdProcess",
    ),
    CaseSpec(
        path="wt/wt/server/wt_server.py",
        initial_range=(1130, 1233),
        expectations=[AnchorExpectation(start_window=(1129, 1130), end_window=(1232, 1233))],
        entity="_record_github_error",
    ),
]


class SampleRunSummary(BaseModel):
    specimen: str
    issue_id: str
    total: int
    passed: int
    failed: int
    summary_path: str


class SampleIndexEntry(BaseModel):
    name: str
    specimen: str
    issue_id: str
    summary: str
    total: int
    passed: int
    failed: int


class EvalIndex(BaseModel):
    samples: list[SampleIndexEntry]


async def _grade_rationale_with_llm(
    client: AsyncOpenAI,
    original: str,
    proposed: str,
    *,
    rubric: str,
    model: str = "gpt-5",
) -> dict[str, str]:
    """Force a tool call that returns verdict: YES | PARTIALLY | NO, with reason."""
    if not proposed or not proposed.strip():
        return {"verdict": "NO", "reason": "No suggested rationale provided by linter."}
    tools = [
        {
            "type": "function",
            "function": {
                "name": "grade_rationale",
                "description": "Return verdict and brief reason.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "verdict": {"type": "string", "enum": ["YES", "PARTIALLY", "NO"]},
                        "reason": {"type": "string"},
                    },
                    "required": ["verdict", "reason"],
                    "additionalProperties": False,
                },
            },
        }
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
    resp = await client.responses.create(
        model=model,
        input=[{"role": "user", "content": prompt}],
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "grade_rationale"}},
    )
    # Extract first tool call output safely
    call = resp.output[0].content[0].tool_call
    data = call.function.arguments
    if isinstance(data, str):
        data = json.loads(data)
    verdict = str(data.get("verdict", "")).upper()
    reason = str(data.get("reason", "")).strip()
    if verdict not in ("YES", "PARTIALLY", "NO"):
        verdict = "NO"
        reason = reason or "Unexpected tool output."
    return {"verdict": verdict, "reason": reason}


async def eval_lint_issue_cases(
    specimen: str,
    issue_core: IssueCore,
    cases: Sequence[CaseSpec],
    *,
    model: str = "gpt-5",
    gitconfig: str | None = None,
    client: AsyncOpenAI,
    out_dir: Path | str | None = None,
) -> SampleRunSummary:
    """Run lint_issue_run over a list of cases and write an eval summary.

    Returns a structured SampleRunSummary and writes summary.json to out_dir.
    """
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = (
        Path(out_dir) if out_dir is not None else (Path.cwd() / "runs" / "evals" / f"{specimen}_{issue_core.id}_{ts}")
    )
    base.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    passes = 0

    for idx, case in enumerate(cases):
        exps: list[Expectation] = list(case.expectations or [])

        path = case.path
        s, e = case.initial_range
        entity = case.entity or ""

        occ = Occurrence(files={path: [LineRange(start_line=s, end_line=e)]}, note=entity)
        payload = await lint_issue_run(
            specimen=specimen,
            issue_core=issue_core,
            occurrence=occ,
            model=model,
            gitconfig=gitconfig,
            client=client,
            renderer=NullConsoleEventRenderer(),
        )

        # Print the structured output object produced by the agent for this case
        Console().print(f"[bold]{specimen} {issue_core.id} case {idx} {path}[/bold]")
        Console().print(render_to_rich(payload))

        # Effective ranges: if agent omitted corrections entirely or for this path, treat as unchanged
        ca = payload.corrected_anchors
        if ca is None or ca.get(path) is None:
            effective = [(s, e)]
            all_ranges: list[tuple[int, int | None]] = []
        else:
            ranges = ca.get(path) or []
            all_ranges = [(r.start_line, r.end_line) for r in ranges]
            effective = all_ranges or [(s, e)]

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
                    client,
                    issue_core.rationale,
                    payload.suggested_rationale or "",
                    rubric=exp.rubric,
                    model=model,
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

        passes += 1 if case_pass else 0

        # Write per-case payload
        (base / f"case_{idx:02d}_payload.json").write_text(payload.model_dump_json(indent=2), encoding="utf-8")

        item: dict[str, Any] = {
            "index": idx,
            "path": path,
            "entity": entity,
            "initial_range": [s, e],
            "ranges_reported": all_ranges,
            "effective_range": [estart, eend],
            "passed": case_pass,
            "expectations": exp_results,
            "message_excerpt": payload.message_md[:400],
        }
        results.append(item)

    summary_obj = {
        "specimen": specimen,
        "issue_id": issue_core.id,
        "total": len(cases),
        "passed": passes,
        "failed": len(cases) - passes,
        "results": results,
    }
    (base / "summary.json").write_text(json.dumps(summary_obj, indent=2), encoding="utf-8")

    return SampleRunSummary(
        specimen=specimen,
        issue_id=issue_core.id,
        total=len(cases),
        passed=passes,
        failed=len(cases) - passes,
        summary_path=str(base / "summary.json"),
    )


class Sample(BaseModel):
    specimen: str
    issue: IssueCore
    cases: list[CaseSpec]


# Flat list of samples (no dataset abstraction)
SAMPLES: list[Sample] = [
    Sample(
        specimen="2025-09-02-ducktape_wt",
        issue=IssueCore(
            id="iss-014",
            should_flag=True,
            rationale="Delete StatusSnapshot - dead code; never used and should be removed.",
            properties=["no-dead-code"],
        ),
        cases=list(WT_ISS014_CASES),
    ),
    Sample(
        specimen="2025-09-02-ducktape_wt",
        issue=IssueCore(
            id="iss-036",
            should_flag=True,
            rationale=(
                "Prefer a single pre-check + list comprehension for simple arg filtering to reduce nesting and eliminate one-off append/continue state."
            ),
            properties=["minimize-nesting"],
            gap_note=(
                "GAP: Prefer comprehensions for simple filter/map over loops with append/continue when it fits on one readable line."
            ),
        ),
        cases=[
            CaseSpec(
                path="wt/wt/cli.py",
                initial_range=(143, 143),
                expectations=[AnchorExpectation(start_window=(138, 143), end_window=(152, 153))],
                entity="arg filtering loop (prefer comprehension)",
            )
        ],
    ),
    Sample(
        specimen="2025-09-02-ducktape_wt",
        issue=IssueCore(
            id="iss-046",
            should_flag=True,
            rationale="`parse_gitstatusd_response` is a thin wrapper around GitStatusdProtocol; migrate callers to Protocol methods and delete.",
            properties=["no-dead-code"],
        ),
        cases=[
            CaseSpec(
                path="wt/wt/server/gitstatusd_client.py",
                initial_range=(358, 360),
                expectations=[
                    AnchorExpectation(start_window=(356, 358), end_window=(360, 362)),
                    RationaleExpectation(
                        rubric="Original says migrate callers; there are no callers. New rationale should simply prescribe deleting dead code without mentioning callers."
                    ),
                ],
                entity="parse_gitstatusd_response",
            )
        ],
    ),
    Sample(
        specimen="2025-09-02-ducktape_wt",
        issue=IssueCore(
            id="iss-047",
            should_flag=True,
            rationale="`create_gitstatusd_request` is a thin wrapper around GitStatusdProtocol; migrate callers to Protocol methods and delete.",
            properties=["no-dead-code"],
        ),
        cases=[
            CaseSpec(
                path="wt/wt/server/gitstatusd_client.py",
                initial_range=(363, 370),
                expectations=[
                    AnchorExpectation(start_window=(361, 363), end_window=(370, 372)),
                    RationaleExpectation(
                        rubric="Original says migrate callers; there are no callers. New rationale should simply prescribe deleting dead code without mentioning callers."
                    ),
                ],
                entity="create_gitstatusd_request",
            )
        ],
    ),
]


async def run_all_evals(
    *,
    model: str = "gpt-5",
    gitconfig: str | None = None,
    client: AsyncOpenAI,
    root_out: Path | str | None = None,
    concurrency: int = 4,
) -> EvalIndex:
    """Run all samples concurrently (bounded), print a Rich summary, and return EvalIndex."""
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    root = Path(root_out) if root_out is not None else (Path.cwd() / "runs" / "evals" / f"all_{ts}")
    root.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(max(1, concurrency))

    async def _run_one(sample: Sample) -> SampleIndexEntry:
        async with sem:
            out_dir = root / sample.issue.id
            summary = await eval_lint_issue_cases(
                specimen=sample.specimen,
                issue_core=sample.issue,
                cases=sample.cases,
                model=model,
                gitconfig=gitconfig,
                client=client,
                out_dir=out_dir,
            )
            return SampleIndexEntry(
                name=sample.issue.id,
                specimen=sample.specimen,
                issue_id=sample.issue.id,
                summary=summary.summary_path,
                total=summary.total,
                passed=summary.passed,
                failed=summary.failed,
            )

    entries = await asyncio.gather(*[_run_one(s) for s in SAMPLES])

    eval_index = EvalIndex(samples=list(entries))
    (root / "index.json").write_text(eval_index.model_dump_json(indent=2), encoding="utf-8")

    # Pretty print a concise Rich table summary (in-memory; no read-back)
    table = Table(title="Eval Summary", show_lines=False)
    table.add_column("Sample", style="bold")
    table.add_column("Specimen")
    table.add_column("Issue")
    table.add_column("Total", justify="right")
    table.add_column("Passed", justify="right", style="green")
    table.add_column("Failed", justify="right", style="red")

    for ent in eval_index.samples:
        table.add_row(ent.name, ent.specimen, ent.issue_id, str(ent.total), str(ent.passed), str(ent.failed))
    Console().print(table)

    return eval_index
