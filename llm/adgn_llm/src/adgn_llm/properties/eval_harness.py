from __future__ import annotations

import json
import datetime as _dt
from pathlib import Path
from typing import Any, Sequence, cast

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from .lint_issue import lint_issue_run
from .specimen_utils import Issue, IssueCore, Occurrence, LineRange, load_single_issue


class CaseSpec(BaseModel):
    """Single eval case specification (1-based inclusive ranges)."""

    path: str
    initial_range: tuple[int, int] = Field(..., description="[start, end] inclusive")
    start_window: tuple[int, int] = Field(..., description="Allowed start window [smin, smax]")
    end_window: tuple[int, int] = Field(..., description="Allowed end window [emin, emax]")
    entity: str | None = Field(default=None, description="Optional occurrence note (freeform)")


# Canonical dataset: 2025-09-02-ducktape_wt iss-014 (four occurrences)
WT_ISS014_CASES: list[CaseSpec] = [
    CaseSpec(
        path="wt/wt/server/wt_server.py",
        initial_range=(413, 424),
        start_window=(410, 412),
        end_window=(421, 423),
        entity="StatusSnapshot",
    ),
    CaseSpec(
        path="wt/wt/server/wt_server.py",
        initial_range=(425, 429),
        start_window=(422, 424),
        end_window=(427, 429),
        entity="WorktreeRuntime",
    ),
    CaseSpec(
        path="wt/wt/server/wt_server.py",
        initial_range=(640, 1144),
        start_window=(638, 640),
        end_window=(1142, 1144),
        entity="GitStatusdProcess",
    ),
    CaseSpec(
        path="wt/wt/server/wt_server.py",
        initial_range=(1130, 1233),
        start_window=(1129, 1130),
        end_window=(1232, 1233),
        entity="_record_github_error",
    ),
]


async def eval_lint_issue_cases(
    specimen: str,
    issue_id: str,
    cases: Sequence[CaseSpec],
    *,
    model: str = "gpt-5",
    gitconfig: str | None = None,
    client: AsyncOpenAI | None = None,
    out_dir: Path | str | None = None,
) -> Path:
    """Run lint_issue_run over a list of cases and write an eval summary.

    Returns the summary directory path containing summary.json and per-case payloads.
    """
    # Resolve canonical issue to reuse its properties/rationale
    _sp, _root, issue = load_single_issue(specimen, issue_id, gitconfig)
    issue = cast(Issue, issue)
    core = IssueCore.from_issue(issue)

    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = Path(out_dir) if out_dir is not None else (Path.cwd() / "runs" / "evals" / f"{specimen}_{issue_id}_{ts}")
    base.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    passes = 0

    for idx, case in enumerate(cases):
        path = case.path
        s, e = case.initial_range
        smin, smax = case.start_window
        emin, emax = case.end_window
        entity = case.entity or ""

        occ = Occurrence(files={path: [LineRange(start_line=s, end_line=e)]}, note=entity)
        payload = await lint_issue_run(
            specimen=specimen,
            issue_core=core,
            occurrence=occ,
            model=model,
            gitconfig=gitconfig,
            client=client,
        )

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
        passed = (eend is not None) and (smin <= estart <= smax) and (emin <= eend <= emax)
        passes += 1 if passed else 0

        # Write per-case payload
        (base / f"case_{idx:02d}_payload.json").write_text(payload.model_dump_json(indent=2), encoding="utf-8")

        results.append(
            {
                "index": idx,
                "path": path,
                "entity": entity,
                "initial_range": [s, e],
                "allowed_start": [smin, smax],
                "allowed_end": [emin, emax],
                "ranges_reported": all_ranges,
                "effective_range": [estart, eend],
                "passed": passed,
                "message_excerpt": payload.message_md[:400],
            }
        )

    summary = {
        "specimen": specimen,
        "issue_id": issue_id,
        "total": len(cases),
        "passed": passes,
        "failed": len(cases) - passes,
        "results": results,
    }
    (base / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return base


class DatasetSpec(BaseModel):
    """Dataset: specimen + issue_id + canonical cases."""

    name: str
    specimen: str
    issue_id: str
    cases: list[CaseSpec]


# Registry of datasets to run for eval-all (extend here as we add more)
DATASETS: list[DatasetSpec] = [
    DatasetSpec(
        name="wt_iss014",
        specimen="2025-09-02-ducktape_wt",
        issue_id="iss-014",
        cases=list(WT_ISS014_CASES),
    )
]


async def run_all_evals(
    *,
    model: str = "gpt-5",
    gitconfig: str | None = None,
    client: AsyncOpenAI | None = None,
    root_out: Path | str | None = None,
) -> Path:
    """Run all registered datasets and write an index.json with pointers to summaries."""
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    root = Path(root_out) if root_out is not None else (Path.cwd() / "runs" / "evals" / f"all_{ts}")
    root.mkdir(parents=True, exist_ok=True)
    index: dict[str, Any] = {"datasets": []}
    for ds in DATASETS:
        out_dir = root / ds.name
        out = await eval_lint_issue_cases(
            specimen=ds.specimen,
            issue_id=ds.issue_id,
            cases=ds.cases,
            model=model,
            gitconfig=gitconfig,
            client=client,
            out_dir=out_dir,
        )
        index["datasets"].append(
            {
                "name": ds.name,
                "specimen": ds.specimen,
                "issue_id": ds.issue_id,
                "summary": str(out / "summary.json"),
            }
        )

    (root / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    return root
