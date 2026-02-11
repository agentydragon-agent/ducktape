#!/usr/bin/env python3
"""
pyright_watch_report.py

Analyze which include/exclude patterns from pyrightconfig.json account for most watched files,
approximate the effective watched file set, and dump the full list for inspection.

Usage:
  python3 pyright_watch_report.py --root . --config pyrightconfig.json --dump pyright_watched_files.txt

If --config is omitted, the script will look for pyrightconfig.json in --root, then fall back
to any "pyrightconfig.json.*" file under root (e.g., backups) and pick the first match.

Notes:
- This is an approximation of Pyright's watcher scope. It treats include/exclude as glob patterns
  (like '**/.git') and computes matches using Python's glob/fnmatch. Pyright may also add additional
  dirs (e.g., search paths) and its internal watcher (chokidar) behavior can differ subtly.
- Still, this gives a high-signal view of which patterns are dominating the watched surface area.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
import fnmatch
import json
import os
from pathlib import Path
import sys
import time

# Align with Pyright focus: Python source + type stubs
CODE_EXTS = {".py", ".pyi"}


def load_config(config_path: Path | None, root: Path) -> tuple[Path | None, dict]:
    candidates: list[Path] = []
    if config_path:
        candidates.append(config_path)
    candidates.append(root / "pyrightconfig.json")
    # Add disabled/backup variants
    for p in sorted(root.glob("pyrightconfig.json*")):
        if p.name != "pyrightconfig.json":
            candidates.append(p)

    for cand in candidates:
        if cand.is_file():
            try:
                return cand, json.loads(cand.read_text())
            except Exception:
                pass
    return None, {}


def normalize_pattern(pat: str) -> str:
    # Normalize to POSIX-style for fnmatch consistency
    return pat.replace("\\", "/")


def expand_include_patterns(patterns: list[str]) -> list[str]:
    """
    Pyright treats plain directory entries in "include" as recursive directories.
    Expand such entries to "<dir>/**". Treat "." as the entire tree ("**/*").
    Leave globbed patterns unchanged.
    """
    out: list[str] = []
    for p in patterns:
        q = normalize_pattern(p)
        if q in (".", "./"):
            out.append("**/*")
        elif any(ch in q for ch in "*?[]"):
            out.append(q)
        else:
            out.append(q.rstrip("/") + "/**")
    return out


def rel(path: Path, root: Path) -> str:
    return normalize_pattern(str(path.relative_to(root)))


def matches_any(path_rel: str, patterns: Iterable[str]) -> bool:
    return any(
        fnmatch.fnmatch(path_rel, normalize_pattern(p))
        or fnmatch.fnmatch("/" + path_rel, normalize_pattern(p))
        for p in patterns
    )


def gather_files_single_pass(
    root: Path,
    include: list[str],
    exclude: list[str],
    only_code: bool,
    progress: bool,
) -> tuple[set[Path], dict[str, int]]:
    """
    Walk the tree once, honoring include/exclude patterns and optional code-only filter.
    Also compute per-exclude-pattern impact counts in a single pass.
    """
    include = expand_include_patterns(include)
    exclude = [normalize_pattern(p) for p in exclude]

    kept_union: set[Path] = set()
    exclude_hits: dict[str, int] = dict.fromkeys(exclude, 0)

    # No directory pruning: we must traverse excluded roots to attribute cost accurately

    scanned_dirs = 0
    scanned_files = 0
    last_print = time.monotonic()

    for dirpath, _dirnames, filenames in os.walk(root):
        dp = Path(dirpath)
        scanned_dirs += 1

        # For files in this directory, check include/exclude
        for fn in filenames:
            p = dp / fn
            rp = rel(p, root)
            scanned_files += 1

            # Track exclude impact first against the pre-exclude set of files that match include
            inc = matches_any(rp, include)
            if not inc:
                # periodic progress
                if progress and time.monotonic() - last_print >= 1.0:
                    sys.stderr.write(
                        f"scan dirs={scanned_dirs} files={scanned_files} kept={len(kept_union)} at {rp}\n",
                    )
                    sys.stderr.flush()
                    last_print = time.monotonic()
                continue

            # Count which excludes would hit this file (for impact metric)
            matched_any_excl = False
            for pat in exclude:
                if matches_any(rp, [pat]):
                    exclude_hits[pat] += 1
                    matched_any_excl = True

            # Apply final keep predicate
            if only_code and p.suffix not in CODE_EXTS:
                # periodic progress
                if progress and time.monotonic() - last_print >= 1.0:
                    sys.stderr.write(
                        f"scan dirs={scanned_dirs} files={scanned_files} kept={len(kept_union)} at {rp}\n",
                    )
                    sys.stderr.flush()
                    last_print = time.monotonic()
                continue
            if matched_any_excl:
                if progress and time.monotonic() - last_print >= 1.0:
                    sys.stderr.write(
                        f"scan dirs={scanned_dirs} files={scanned_files} kept={len(kept_union)} at {rp}\n",
                    )
                    sys.stderr.flush()
                    last_print = time.monotonic()
                continue

            kept_union.add(p)

            if progress and time.monotonic() - last_print >= 1.0:
                sys.stderr.write(
                    f"scan dirs={scanned_dirs} files={scanned_files} kept={len(kept_union)} at {rp}\n",
                )
                sys.stderr.flush()
                last_print = time.monotonic()

    return kept_union, exclude_hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path.cwd()), help="Workspace root directory")
    ap.add_argument(
        "--config",
        default=None,
        help="Path to pyrightconfig.json (optional)",
    )
    ap.add_argument(
        "--dump",
        default=None,
        help="Path to dump watched file list (optional)",
    )
    ap.add_argument(
        "--only-code",
        action="store_true",
        help="Count only code files (.py, .pyi)",
    )
    ap.add_argument(
        "--no-progress",
        dest="progress",
        action="store_false",
        help="Disable periodic progress output",
    )
    ap.set_defaults(progress=True)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    config_path = Path(args.config).resolve() if args.config else None

    cfg_file, cfg = load_config(config_path, root)

    include = cfg.get("include") or ["."]
    exclude = cfg.get("exclude") or [
        "**/.git",
        "**/.venv",
        "**/__pycache__",
        "**/node_modules",
        "build",
        "dist",
        ".mypy_cache",
    ]

    # Normalize excludes
    exclude = [normalize_pattern(p) for p in exclude]

    # Single-pass gather with per-exclude impact
    kept_union, exclude_hits = gather_files_single_pass(
        root,
        include,
        exclude,
        only_code=args.only_code,
        progress=args.progress,
    )

    # Compute per-include kept counts by filtering kept_union once
    per_include_kept: dict[str, int] = {}
    for pat in include:
        per_include_kept[pat] = sum(
            1 for p in kept_union if matches_any(rel(p, root), [pat])
        )

    # Unique contribution per include in listed order (order-sensitive)
    seen: set[Path] = set()
    per_include_unique: list[tuple[str, int]] = []
    # Preserve include order from config
    for pat in include:
        uniq_count = 0
        for p in sorted(kept_union):
            if p in seen:
                continue
            if matches_any(rel(p, root), [pat]):
                uniq_count += 1
                seen.add(p)
        per_include_unique.append((pat, uniq_count))

    # Top excludes by impact
    exclude_impact: list[tuple[str, int]] = sorted(
        exclude_hits.items(),
        key=lambda x: x[1],
        reverse=True,
    )

    # Totals
    total_files = len(kept_union)
    total_code = sum(1 for p in kept_union if p.suffix in CODE_EXTS)

    print("pyright_watch_report")
    print(f"root: {root}")
    if cfg_file:
        print(f"config: {cfg_file}")
    else:
        print("config: <not found, using defaults>")
    print(f"include ({len(include)}): {include}")
    print(f"exclude ({len(exclude)}): {exclude}")
    print()

    print(f"Total watched files (approx): {total_files}")
    print(f"  of which code (.py/.pyi/.pyx): {total_code}")
    print()

    # Per-include stats (kept)
    incl_stats: list[tuple[str, int]] = sorted(
        ((pat, per_include_kept.get(pat, 0)) for pat in include),
        key=lambda x: x[1],
        reverse=True,
    )
    print("Per-include kept file counts (descending):")
    for pat, cnt in incl_stats:
        print(f"  {pat:40s} {cnt:8d}")
    print()

    print("Per-include unique additional files (order-sensitive):")
    for pat, cnt in per_include_unique:
        print(f"  {pat:40s} +{cnt:7d}")
    print()

    print("Top excludes by impact (files removed from pre-exclude set):")
    for pat, cnt in exclude_impact[:20]:
        print(f"  {pat:40s} -{cnt:7d}")
    print()

    # Dump file list if requested
    dump_path: Path = (
        Path(args.dump).resolve()
        if args.dump
        else (root / "scratch/pyright_watched_files.txt")
    )
    try:
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        with dump_path.open("w", encoding="utf-8") as f:
            for p in sorted(kept_union):
                f.write(str(p) + "\n")
        print(f"Dumped {len(kept_union)} files to {dump_path}")
    except Exception as e:
        print(f"WARN: failed to write dump file: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
