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
from . import leaderboard

app = typer.Typer(help="System rewriter toolkit: extract datasets, run evals, and compare against CCR.")


@app.command("run")
def cmd_run(
    template: Path = typer.Argument(..., help="Path to system prompt template (mustache-style: {{toolsBlob}}, etc.)"),
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
    n: Optional[int] = typer.Option(None, "--n", help="Limit number of samples to process"),
    concurrency: int = typer.Option(32, "--concurrency", help="Parallelism for sampling/grading"),
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
    run_dir: Path = typer.Argument(..., help="Path to eval run directory (contains samples.jsonl)"),
    out_dir: Optional[Path] = typer.Option(None, "--out-dir", help="Output directory for diffs"),
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


@app.command("extract")
def cmd_extract(
    source: str = typer.Option("auto", "--source", help="ccr|crush|auto (default: auto)"),
    wire_log: Optional[Path] = typer.Option(None, "--wire-log", help="Crush only: path to provider-wire.log"),
    scan_dir: List[Path] = typer.Option(
        None,
        "--scan-dir",
        help="Crush only: scan DIR recursively for **/.crush/logs/provider-wire.log (repeatable)",
    ),
    output: Optional[Path] = typer.Option(None, "--output", help="Output JSONL path (default depends on source)"),
):
    """Unified dataset extractor for CCR and Crush logs."""
    src = source.lower()
    if src == "auto":
        src = "crush" if (wire_log or (scan_dir and len(scan_dir) > 0)) else "ccr"

    if src == "crush":
        out_path = output or extract_dataset_crush.OUTPUT_PATH
        out_path.parent.mkdir(parents=True, exist_ok=True)
        logs: list[Path] = []
        if wire_log:
            logs = [wire_log]
        else:
            # Prefer default single log if it exists, else scan ~/.crush, else scan provided dirs
            default_log = extract_dataset_crush.DEFAULT_WIRE_LOG
            roots = scan_dir or [Path.home() / ".crush"]
            logs = []
            if isinstance(default_log, Path) and default_log.exists():
                logs.append(default_log)
            logs.extend(extract_dataset_crush.find_wire_logs(roots))
            # Dedup while preserving order
            seen = set()
            logs = [p for p in logs if not (str(p) in seen or seen.add(str(p)))]
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
        return

    if src == "ccr":
        asyncio.run(extract_dataset_ccr.main())
        return

    raise typer.BadParameter("--source must be one of: ccr, crush, auto")


@app.command("leaderboard")
def cmd_leaderboard(
    runs_dir: Path = typer.Option(
        Path(__file__).parent / "runs",
        "--runs-dir",
        help="Directory containing eval runs (runs/<ts>)",
    ),
    templates_dir: Path = typer.Option(
        Path(__file__).parent / "templates",
        "--templates-dir",
        help="Directory containing templates (baseline and proposals)",
    ),
    sort_key: str = typer.Option("mean", "--sort", help="Sort key: mean|lcb|ucb"),
    asc: bool = typer.Option(False, "--asc", help="Sort ascending"),
    limit: int | None = typer.Option(None, "--limit", help="Limit rows"),
    # --since removed; grouping by template consolidates runs regardless of timestamp
):
    out = leaderboard.generate(
        runs_dir=runs_dir,
        templates_dir=templates_dir,
        sort_key=sort_key,
        asc=asc,
        limit=limit,
    )
    print(out)


if __name__ == "__main__":
    app()
