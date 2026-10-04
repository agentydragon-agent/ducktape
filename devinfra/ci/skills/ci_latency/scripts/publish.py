#!/usr/bin/env python3
"""Render one reviewed, source-pinned report into a self-contained HTML history entry."""
import argparse
import html
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def render(text):
    # Plain text inside <pre> deliberately avoids interpreting untrusted Markdown/HTML.
    return '<!doctype html><html lang="en"><meta charset="utf-8"><title>CI latency</title>' \
        '<style>body{max-width:95ch;margin:2em auto;padding:0 1em;font:16px/1.5 system-ui}' \
        'pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.5 ui-monospace,monospace}</style>' \
        '<h1>CI latency report</h1><pre>' + html.escape(text) + '</pre></html>\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Full SHA of inspected devel commit")
    parser.add_argument("--window-start", required=True, help="UTC ISO-8601")
    parser.add_argument("--window-end", required=True, help="UTC ISO-8601")
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--attribution", type=Path)
    parser.add_argument("--out", required=True, type=Path, help="New empty output directory")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source):
        parser.error("source must be a full SHA")
    def parse(s):
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None or d.utcoffset().total_seconds() != 0:
            parser.error("window must be UTC")
        return d
    if parse(args.window_start) >= parse(args.window_end):
        parser.error("window end must follow start")
    if git("cat-file", "-t", args.source) != "commit":
        parser.error("source is not an available commit")
    if args.out.exists():
        parser.error("output directory already exists; never overwrite a historical entry")
    evidence = json.loads(args.evidence.read_text())
    attribution = json.loads(args.attribution.read_text()) if args.attribution else None
    args.out.mkdir(parents=True)
    report = args.report.read_text()
    (args.out / "report.md").write_text(report)
    (args.out / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    if attribution is not None:
        (args.out / "attribution.json").write_text(json.dumps(attribution, indent=2) + "\n")
    manifest = {"source_devel_commit": args.source, "window_start_utc": args.window_start,
                "window_end_utc": args.window_end, "published_at_utc": datetime.now(timezone.utc).isoformat(),
                "attribution": "measured" if attribution else "not collected"}
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    header = (f"Source devel commit: {args.source}\nWindow (UTC): {args.window_start} – {args.window_end}\n"
              f"Attribution: {manifest['attribution']}\n\n")
    (args.out / "index.html").write_text(render(header + report))


if __name__ == "__main__":
    main()
