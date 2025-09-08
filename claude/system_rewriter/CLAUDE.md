# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Scope: This document focuses on the eval toolkit under claude/system_rewriter — scripts for evaluating system prompts for AI coding agents and finding better rewrites, via:
- extracting bad turns from Claude Code/Crush logs,
- rewriting the system prompt via a template,
- sampling alternative responses,
- grading them and reporting results.

Requirements: Python (+ some packages), Node.js.
This directory has a package.json for the mustache runtime used by the Node apply script.

- Install Node deps (from this directory):
```bash
npm install
```

Common commands
- Run all tests: `pytest`
- Lint (repo uses ruff at the root):
```bash
ruff check .
ruff format .
```
- Optional: run root pre-commit over staged/changed files:
```bash
pre-commit run -a
```

End-to-end eval workflow
1) Prepare a dataset of “bad turn” samples
- From Claude Code router traces (CCR): reads ~/.claude-code-router/logs/trace.* and selects conversations where the last user message contains the <bad> marker and the system contains the tools section header.
```bash
python extract_dataset_ccr.py
# writes ./data/dataset_ccr.jsonl
```
- From Crush provider wire logs (OpenAI Responses API): scans provider-wire.log files and keeps Responses API shape (no CCR coercion).
```bash
# single file
python extract_dataset_crush.py --wire-log "$HOME/.crush/logs/provider-wire.log"
# or recursively scan a code root for **/.crush/logs/provider-wire.log*
python extract_dataset_crush.py --scan-dir "$HOME/code"
# writes ./data/dataset_crush.jsonl
```

2) Run an eval with a system template
- Baseline (uses the current effective template snapshot in this repo):
```bash
python run_eval.py \
  --template templates/current_effective_template.txt
```
- Variant template (use your own template file) and/or alternate dataset:
```bash
python run_eval.py \
  --template /absolute/or/repo/path/to/variant_template.txt \
  --dataset ./data/dataset_ccr.jsonl \
  --dataset ./data/dataset_crush.jsonl \
  --n 200 \
  --concurrency 16
```
- Outputs (created under ./runs/…):
  - samples.jsonl: per-sample new assistant candidate and the sampler request/response
  - grades.jsonl: grader tool outputs per sample
  - summary.json: n, mean, 95% CI, counters, and tool-call mix stats
  - report.html: human-readable rows with original/rewritten system, shared prefix, bad branch, alternative, and grade

3) Optional: compare generated sampler requests vs actual CCR requests
```bash
python compare_eval_vs_ccr.py --run-dir ./runs/<timestamp-or-baseline-...> --limit 5
# writes diffs under ./runs/<...>/compare_vs_ccr
```

Node must be on PATH and npm install must have fetched mustache (used by system_rewrite_apply.js). There is no Python fallback; missing Node is a hard error.

High-level architecture
- Dataset loaders
  - extract_dataset_ccr.py parses Claude Code router inbound_request logs and emits JSONL with anthropic_request (CCR shape). It filters on:
    - System contains the tools header substring from constants.TOOLS_HEADER
    - Last user message contains the BAD_MARKER token (“<bad>”)
  - extract_dataset_crush.py parses Crush provider wire logs and emits JSONL with oai_request in Responses API shape; run_eval keeps these native (no CCR coercion).
- System rewrite templating
  - system_rewrite_apply.js reads the original system prompt, extracts four blobs (toolsBlob, envGitBlobs, modelLine, mcpSection), and renders them into your template via mustache. Placeholders can be {{name}} or legacy ${name}. There is no fallback renderer; the Node script is required and will hard‑fail if missing.
- Sampling
  - CCR: OpenAI Chat Completions (native CCR -> Chat), injects rewritten system.
  - Crush: OpenAI Responses (native Responses params), injects rewritten system and slices input up to the last assistant; no format conversion.
  - Token budgets are enforced with MAX_INPUT_TOKENS, MAX_TOTAL_TOKENS, PER_OUTPUT_CAP.
- Grading
  - Builds a grader prompt containing: shared conversation prefix (windowed to fit TARGET_PREFIX_TOKENS), the bad branch (assistant misstep through the user complaint), and the NEW_ASSISTANT_REPLY_JSON. Uses the Responses API with a single function tool grade(score 1–5, rationale) and parses the tool call output.
- Reporting
  - Writes samples.jsonl, grades.jsonl, summary.json, and generates an HTML report using templates/report.html.j2. Tool usage stats (text-only vs with tool_calls; counts/pct by function name) are included in summary.json.

Key files in this directory
- run_eval.py — main orchestrator: rewrite system, sample, grade, aggregate, and render report
- extract_dataset.py / extract_dataset_crush.py — dataset builders from CCR and Crush logs
- compare_eval_vs_ccr.py — diffs generated sampler requests vs live CCR requests for the same correlation IDs
- system_rewrite_apply.js — Node mustache renderer and system blob extractor
- schemas.py — Pydantic models for I/O records
- templates/ — template files (current_effective_template.txt, report.html.j2)

Notes and caveats
- Concurrency: tune --concurrency to avoid rate limits. Progress and error events are appended to runs/<...>/progress.jsonl.
- Token budgets: extremely long contexts are skipped with status=skipped_input_too_large; see counters in summary.json.
- Tool schema mapping: Anthropic tools are normalized to OpenAI Chat function tools; Responses-style input_schema is mapped to parameters when needed.
