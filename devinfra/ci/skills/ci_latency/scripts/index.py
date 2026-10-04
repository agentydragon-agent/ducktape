#!/usr/bin/env python3
"""Regenerate orphan-branch index from all pinned entries; run in history worktree."""

import html
import json
from pathlib import Path

entries = []
for file in sorted(Path("runs").glob("*/manifest.json"), reverse=True):
    meta = json.loads(file.read_text())
    label = file.parent.name
    entries.append((label, meta["source_devel_commit"], meta["window_start_utc"], meta["attribution"]))
if not entries:
    raise SystemExit("no history entries")
links = "\n".join(
    f'<li><a href="runs/{html.escape(label, quote=True)}/index.html">{html.escape(label)}</a> '
    f"(window {html.escape(window)}, devel {html.escape(commit)}, attribution {html.escape(attr)})</li>"
    for label, commit, window, attr in entries
)
Path("index.html").write_text(
    '<!doctype html><html lang="en"><meta charset="utf-8"><title>CI latency history</title>'
    "<h1>CI latency history</h1><p>Newest first; each entry is pinned to an inspected devel commit. "
    "Samples are not necessarily comparable.</p><ul>" + links + "</ul></html>\n"
)
