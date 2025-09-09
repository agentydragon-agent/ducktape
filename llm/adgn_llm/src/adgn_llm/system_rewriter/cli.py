#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional, List

import typer

from . import run_eval
from . import compare_eval_vs_ccr
from . import extract_dataset_ccr
from . import extract_dataset_crush

app = typer.Typer(
    help="System rewriter toolkit: extract datasets, run evals, and compare against CCR."
)


@app.command("run")
def cmd_run(
    template: Path = typer.Argument(
        ..., help="Path to system prompt template (mustache-style: {{toolsBlob}}, etc.)"
    ),
    dataset: List[Path] = typer.Option(
        None,
        "--dataset",
        "-d",
        help="Dataset JSONL path(s); repeat to mix CCR and Crush samples. Defaults to built-in dataset if omitted.",
    ),
    out_dir: Optional[Path] = typer.Option(
        None,
        "--out-dir",
        help="Output directory. If omitted, writes to runs/<ts>.",
    ),
    n: Optional[int] = typer.Option(
        None, "--n", help="Limit number of samples to process"
    ),
    concurrency: int = typer.Option(
        32, "--concurrency", help="Parallelism for sampling/grading"
    ),
):
    """Run an evaluation end-to-end (rewrite → sample → grade → report)."""
    dsets = dataset or [run_eval.DEFAULT_DATASET_PATH]
    base_out = out_dir if out_dir else None
    asyncio.run(
        run_eval.run_eval(
            template_path=template,
            dataset_paths=dsets,
            base_out=base_out,
            n_limit=n,
            concurrency=concurrency,
        )
    )


@app.command("compare")
def cmd_compare(
    run_dir: Path = typer.Argument(
        ..., help="Path to eval run directory (contains samples.jsonl)"
    ),
    out_dir: Optional[Path] = typer.Option(
        None, "--out-dir", help="Output directory for diffs"
    ),
    limit: int = typer.Option(5, "--limit", help="Max number of samples to compare"),
):
    """Diff eval sampler requests vs actual CCR chat completion requests."""
    out = out_dir or (run_dir / "compare_vs_ccr")
    out.mkdir(parents=True, exist_ok=True)

    samples = compare_eval_vs_ccr.load_samples(run_dir)
    count = 0
    wrote: list[str] = []
    for rec in samples:
        if count >= limit:
            break
        cid = rec.get("correlation_id")
        eval_req = rec.get("request") or {}
        if not cid or not isinstance(eval_req, dict):
            continue
        ccr_req = compare_eval_vs_ccr.find_ccr_openai_request(cid)
        if not ccr_req:
            continue
        # Prepare pretty JSONs
        eval_body = compare_eval_vs_ccr.drop_none(dict(eval_req))
        eval_json = compare_eval_vs_ccr.pretty(eval_body)
        ccr_json = compare_eval_vs_ccr.pretty(ccr_req)
        # Write files
        case_dir = out / f"cid-{cid}"
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "eval_request.json").write_text(eval_json, encoding="utf-8")
        (case_dir / "ccr_request.json").write_text(ccr_json, encoding="utf-8")
        # Diff
        diff_text = compare_eval_vs_ccr.unified_diff_str(
            ccr_json, eval_json, fromfile="ccr_request.json", tofile="eval_request.json"
        )
        (case_dir / "diff.unified.txt").write_text(diff_text, encoding="utf-8")
        wrote.append(str(case_dir))
        count += 1

    summary_path = out / "SUMMARY.txt"
    summary_path.write_text("\n".join(wrote), encoding="utf-8")
    print(json.dumps({"compared": count, "out_dir": str(out)}))


@app.command("extract-ccr")
def cmd_extract_ccr():
    """Extract dataset from CCR router logs to ./data/dataset_ccr.jsonl."""
    # Reuse module's async entrypoint
    asyncio.run(extract_dataset_ccr.main())


@app.command("extract-crush")
def cmd_extract_crush(
    wire_log: Optional[Path] = typer.Option(
        None,
        "--wire-log",
        help="Path to provider-wire.log (overrides scan mode)",
    ),
    scan_dir: List[Path] = typer.Option(
        None,
        "--scan-dir",
        help="Scan DIR recursively for **/.crush/logs/provider-wire.log (repeatable)",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        help="Output JSONL path (default: ./data/dataset_crush.jsonl)",
    ),
):
    """Extract dataset from Crush provider wire logs to ./data/dataset_crush.jsonl."""
    out_path = output or extract_dataset_crush.OUTPUT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)

    logs: list[Path]
    if wire_log:
        logs = [wire_log]
    else:
        roots = scan_dir or [Path.home() / "code"]
        logs = extract_dataset_crush.find_wire_logs(roots)

    total = 0
    with out_path.open("w", encoding="utf-8") as out_f:
        for log_path in logs:
            recs = extract_dataset_crush.process_wire(log_path, require_bad=True)
            for r in recs:
                out_f.write(json.dumps(r, ensure_ascii=False) + "\n")
            total += len(recs)
    print(
        json.dumps(
            {
                "event": "dataset_crush_written",
                "count": total,
                "path": str(out_path),
                "files_scanned": len(logs),
            }
        )
    )


if __name__ == "__main__":
    app()
