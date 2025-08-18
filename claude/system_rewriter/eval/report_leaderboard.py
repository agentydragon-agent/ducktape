#!/usr/bin/env python3
"""
Leaderboard reporter for eval runs.

Scans runs/<ts>/ for summary.json and template.txt, maps template content
hashes back to known templates (baseline and proposals), and prints a sorted
leaderboard.

Defaults to text output sorted by mean score desc.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass
class Row:
    run: str
    mean: float
    ci95: float
    n: int
    lcb: float | None
    ucb: float | None
    template_label: str
    template_hash: str
    with_tools_pct: float


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def load_known_templates(templates_dir: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    # baseline
    base_tpl = templates_dir / "current_effective_template.txt"
    if base_tpl.exists():
        try:
            mapping[sha1_text(base_tpl.read_text(encoding="utf-8"))] = str(
                base_tpl
            )
        except Exception:
            pass
    # proposals
    props_dir = templates_dir / "proposals"
    if props_dir.exists():
        for txt in props_dir.rglob("*.txt"):
            try:
                mapping[sha1_text(txt.read_text(encoding="utf-8"))] = str(txt)
            except Exception:
                continue
    return mapping


def iter_run_dirs(runs_dir: Path) -> Iterable[Path]:
    for p in sorted([d for d in runs_dir.iterdir() if d.is_dir()]):
        yield p


def find_summary_and_template(run_dir: Path) -> tuple[Path | None, Path | None]:
    s = run_dir / "summary.json"
    t = run_dir / "template.txt"
    if s.exists() and t.exists():
        return s, t
    # Legacy single nested dir fallback
    try:
        subs = [d for d in run_dir.iterdir() if d.is_dir()]
    except FileNotFoundError:
        return None, None
    if len(subs) == 1 and (subs[0] / "summary.json").exists():
        return subs[0] / "summary.json", subs[0] / "template.txt"
    return None, None


def load_row(run_dir: Path, known: dict[str, str]) -> Row | None:
    s_path, t_path = find_summary_and_template(run_dir)
    if not (s_path and t_path):
        return None
    try:
        summ = json.loads(s_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    try:
        thash = sha1_text(t_path.read_text(encoding="utf-8"))
    except Exception:
        thash = "?"
    label = known.get(thash, thash[:8])
    def _f(key: str, default: float = 0.0) -> float:
        try:
            return float(summ.get(key, default))
        except Exception:
            return default
    tooling = summ.get("tooling") or {}
    with_tools = 0.0
    try:
        with_tools = float(tooling.get("with_tools_pct", 0.0))
    except Exception:
        with_tools = 0.0
    return Row(
        run=run_dir.name,
        mean=_f("mean"),
        ci95=_f("ci95"),
        n=int(summ.get("n", 0) or 0),
        lcb=(summ.get("lcb") if isinstance(summ.get("lcb"), (int, float)) else None),
        ucb=(summ.get("ucb") if isinstance(summ.get("ucb"), (int, float)) else None),
        template_label=label,
        template_hash=thash,
        with_tools_pct=with_tools,
    )


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Report leaderboard for eval runs (runs/<ts> → summary).",
    )
    ap.add_argument(
        "--runs-dir",
        type=Path,
        default=Path(__file__).parent / "runs",
        help="Directory containing run folders (default: ./runs)",
    )
    ap.add_argument(
        "--templates-dir",
        type=Path,
        default=Path(__file__).parent / "templates",
        help="Directory containing templates (default: ./templates)",
    )
    ap.add_argument(
        "--format",
        choices=["text", "json", "md"],
        default="text",
        help="Output format (default: text)",
    )
    ap.add_argument(
        "--sort",
        choices=["mean", "lcb", "ucb"],
        default="mean",
        help="Sort key (default: mean)",
    )
    ap.add_argument(
        "--asc",
        action="store_true",
        default=False,
        help="Sort ascending (default: descending)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of rows shown",
    )
    ap.add_argument(
        "--since",
        type=int,
        default=None,
        help="Only include runs with numeric name >= this timestamp",
    )
    return ap.parse_args()


def format_text(rows: list[Row]) -> str:
    out_lines = []
    for r in rows:
        tools_pct = f"{r.with_tools_pct*100:.1f}%"
        out_lines.append(
            f"{r.mean:.2f} ± {r.ci95:.2f} (n={r.n:>3}, tools={tools_pct:>6})  run={r.run}  prompt={r.template_label}"
        )
    return "\n".join(out_lines)


def format_md(rows: list[Row]) -> str:
    header = "| mean | ci95 | n | tools% | run | template |\n|---:|---:|---:|---:|:---|:---|"
    lines = [header]
    for r in rows:
        lines.append(
            f"| {r.mean:.2f} | {r.ci95:.2f} | {r.n} | {r.with_tools_pct*100:.1f}% | {r.run} | {r.template_label} |"
        )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    runs_dir: Path = args.runs_dir
    templates_dir: Path = args.templates_dir
    known = load_known_templates(templates_dir)

    if not runs_dir.exists():
        print(f"No runs dir: {runs_dir}", file=sys.stderr)
        return 2

    rows: list[Row] = []
    for rd in iter_run_dirs(runs_dir):
        if args.since is not None:
            try:
                if int(rd.name) < int(args.since):
                    continue
            except ValueError:
                # Allow non-numeric names like baseline-<ts>
                # Keep them regardless of --since
                pass
        row = load_row(rd, known)
        if row:
            rows.append(row)

    key = {
        "mean": lambda r: r.mean,
        "lcb": lambda r: r.lcb if r.lcb is not None else (r.mean - r.ci95),
        "ucb": lambda r: r.ucb if r.ucb is not None else (r.mean + r.ci95),
    }[args.sort]
    reverse = not bool(args.asc)
    rows.sort(key=key, reverse=reverse)
    if args.limit is not None:
        rows = rows[: max(0, args.limit)]

    if args.format == "json":
        print(
            json.dumps(
                [
                    {
                        "run": r.run,
                        "mean": r.mean,
                        "ci95": r.ci95,
                        "n": r.n,
                        "lcb": r.lcb,
                        "ucb": r.ucb,
                        "template": r.template_label,
                        "template_hash": r.template_hash,
                        "with_tools_pct": r.with_tools_pct,
                    }
                    for r in rows
                ],
                ensure_ascii=False,
            )
        )
    elif args.format == "md":
        print(format_md(rows))
    else:
        print(format_text(rows))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
