"""
Leaderboard reporter for eval runs (packaged).

Scans runs/<ts>/ for summary.json and template.txt, maps template content
hashes back to known templates (baseline and proposals), and prints a sorted
leaderboard.

Defaults to rich table output sorted by mean score desc.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from rich.console import Console
from rich.table import Table


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
            mapping[sha1_text(base_tpl.read_text(encoding="utf-8"))] = str(base_tpl)
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


def load_known_templates_from_runs(runs_dir: Path) -> dict[str, str]:
    """Scan runs/*/template.txt and build a mapping hash -> one representative path.
    If multiple runs share the same template hash, keep the lexicographically first path.
    """
    mapping: dict[str, str] = {}
    if not runs_dir.exists():
        return mapping
    for rd in iter_run_dirs(runs_dir):
        t = rd / "template.txt"
        if not t.exists():
            # also check legacy single nested dir
            try:
                subs = [d for d in rd.iterdir() if d.is_dir()]
            except FileNotFoundError:
                subs = []
            if len(subs) == 1:
                t2 = subs[0] / "template.txt"
                if t2.exists():
                    t = t2
        if t.exists():
            try:
                h = sha1_text(t.read_text(encoding="utf-8"))
            except Exception:
                continue
            curr = mapping.get(h)
            label = str(t)
            if curr is None or label < curr:
                mapping[h] = label
    return mapping


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

    mean = _f("mean")

    # Support both ci95 numeric (legacy) and ci95={lcb,ucb} (new)
    ci95_val: float | None = None
    lcb: float | None = None
    ucb: float | None = None

    ci95_field = summ.get("ci95")
    if isinstance(ci95_field, dict):
        # New format inside ci95
        try:
            lcb = float(ci95_field.get("lcb")) if ci95_field.get("lcb") is not None else None
        except Exception:
            lcb = None
        try:
            ucb = float(ci95_field.get("ucb")) if ci95_field.get("ucb") is not None else None
        except Exception:
            ucb = None
        if lcb is not None and ucb is not None:
            ci95_val = max(abs(mean - lcb), abs(ucb - mean))
    else:
        # Legacy numeric ci95
        try:
            ci95_val = float(ci95_field) if ci95_field is not None else None
        except Exception:
            ci95_val = None
        # Try top-level lcb/ucb if present
        if isinstance(summ.get("lcb"), (int, float)):
            lcb = float(summ.get("lcb"))
        if isinstance(summ.get("ucb"), (int, float)):
            ucb = float(summ.get("ucb"))

    # Derive ci95 half-width if missing but bounds present
    if ci95_val is None:
        if lcb is not None and ucb is not None:
            ci95_val = max(abs(mean - lcb), abs(ucb - mean))
        else:
            ci95_val = 0.0

    tooling = summ.get("tooling") or {}
    try:
        with_tools = float(tooling.get("with_tools_pct", 0.0))
    except Exception:
        with_tools = 0.0

    # TODO(mpokorny): deprecate legacy numeric ci95 once all runs use ci95={lcb,ucb}.

    return Row(
        run=run_dir.name,
        mean=mean,
        ci95=float(ci95_val),
        n=int(summ.get("n", 0) or 0),
        lcb=lcb,
        ucb=ucb,
        template_label=label,
        template_hash=thash,
        with_tools_pct=with_tools,
    )


def format_text(rows: list[Row]) -> str:
    out_lines = []
    for r in rows:
        tools_pct = f"{r.with_tools_pct * 100:.1f}%"
        out_lines.append(
            f"{r.mean:.2f} ± {r.ci95:.2f} (n={r.n:>3}, tools={tools_pct:>6})  run={r.run}  prompt={r.template_label}",
        )
    return "\n".join(out_lines)


def format_md(rows: list[Row]) -> str:
    header = (
        "| mean | ci95 | n | tools% | run | template |\n|---:|---:|---:|---:|:---|:---|"
    )
    lines = [header]
    for r in rows:
        lines.append(
            f"| {r.mean:.2f} | {r.ci95:.2f} | {r.n} | {r.with_tools_pct * 100:.1f}% | {r.run} | {r.template_label} |",
        )
    return "\n".join(lines)


def _color_for_hash(hash_hex: str) -> str:
    # Deterministic palette index from hash
    palette = [
        "bright_cyan", "bright_magenta", "bright_green", "bright_yellow",
        "bright_blue", "bright_red", "cyan", "magenta", "green", "yellow",
        "blue", "red",
    ]
    try:
        idx = int(hash_hex[:8], 16) % len(palette)
    except Exception:
        idx = 0
    return palette[idx]


def _relpath(p: str) -> str:
    # Prefer a path relative to current working directory when possible
    try:
        abs_p = str(Path(p).resolve())
    except Exception:
        abs_p = p
    try:
        return os.path.relpath(abs_p, start=os.getcwd())
    except Exception:
        return p


def format_rich_table(rows: list[Row]) -> str:
    """Render a pretty CLI table using rich and return its text output."""
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("lcb", justify="right")
    table.add_column("mean", justify="right")
    table.add_column("ucb", justify="right")
    table.add_column("n", justify="right")
    table.add_column("tools%", justify="right")
    table.add_column("run", justify="left")
    table.add_column("template", justify="left")

    for r in rows:
        # Derive display bounds if missing
        lcb = r.lcb if r.lcb is not None else (r.mean - r.ci95)
        ucb = r.ucb if r.ucb is not None else (r.mean + r.ci95)
        color = _color_for_hash(r.template_hash)
        rel_label = _relpath(r.template_label)
        table.add_row(
            f"{lcb:.2f}",
            f"{r.mean:.2f}",
            f"{ucb:.2f}",
            f"{r.n}",
            f"{r.with_tools_pct * 100:.1f}%",
            r.run,
            f"[{color}]{rel_label}[/]",
        )

    # Render off-screen to avoid duplicate stdout prints; caller prints returned text
    buffer = io.StringIO()
    console = Console(file=buffer, record=True)
    console.print(table)
    return buffer.getvalue()


def generate(
    runs_dir: Path,
    templates_dir: Path,
    sort_key: str = "mean",
    asc: bool = False,
    limit: int | None = None,
) -> str:
    # Prefer mapping built from runs; fall back to templates_dir if empty
    known = load_known_templates_from_runs(runs_dir)
    if not known:
        known = load_known_templates(templates_dir)
    if not runs_dir.exists():
        raise FileNotFoundError(f"No runs dir: {runs_dir}")

    # Build groups by template hash
    by_hash: dict[str, list[Row]] = {}
    for rd in iter_run_dirs(runs_dir):
        row = load_row(rd, known)
        if not row:
            continue
        by_hash.setdefault(row.template_hash, []).append(row)

    # Row sort key
    row_key = {
        "mean": lambda r: r.mean,
        "lcb": lambda r: (r.lcb if r.lcb is not None else (r.mean - r.ci95)),
        "ucb": lambda r: (r.ucb if r.ucb is not None else (r.mean + r.ci95)),
    }[sort_key]

    # Sort within groups and then groups by best row
    groups: list[list[Row]] = []
    for rows in by_hash.values():
        rows.sort(key=row_key, reverse=not asc)
        groups.append(rows)
    groups.sort(key=lambda g: row_key(g[0]) if g else float("-inf"), reverse=not asc)

    # Flatten
    flat_rows: list[Row] = [r for g in groups for r in g]
    if limit is not None:
        flat_rows = flat_rows[: max(0, limit)]

    return format_rich_table(flat_rows)


def parse_args() -> argparse.Namespace:
    # Note: retained for direct CLI use via adgn-sysrw leaderboard; not used as module API.
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
        "--sort",
        choices=["mean", "lcb", "ucb"],
        default="mean",
        help="Sort key (default: mean)",
    )
    ap.add_argument(
        "--asc", action="store_true", default=False, help="Sort ascending"
    )
    ap.add_argument("--limit", type=int, default=None)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    try:
        out = generate(
            runs_dir=args.runs_dir,
            templates_dir=args.templates_dir,
            sort_key=args.sort,
            asc=bool(args.asc),
            limit=args.limit,
        )
    except Exception as e:
        print(str(e), file=sys.stderr)
        return 2
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
