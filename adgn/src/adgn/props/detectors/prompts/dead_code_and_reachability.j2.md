{% extends "_base.j2.md" %}
{% set read_only = true %}
{% set include_tools = false %}
{% set include_reporting = false %}

{% block title %}Dead Code & Reachability Proof — Agent Runbook{% endblock %}

{% block body %}
## Purpose
- Produce an exhaustive, deduplicated, human‑useful report of dead/unreachable code and redundant/subsumed conditionals — powered primarily by your reasoning and code understanding. Use tools only as spotters/hints.
- Aim to cover all relevant code within scope. If budget/token constraints force a cutoff, stop after N findings (N=10) and include a backlog of remaining areas/targets.
- For every reported item, include minimal concrete anchors and a short rationale; where you claim unreachability, include a compact proof.

## Method (Outcome‑First)
- Read code and build a mental model first; identify entrypoints and plausible flows. Only then consult tools as hints.
- When a tool suggests a candidate, validate it by reading the code and constructing a short proof (or discard it).
- Prefer precise anchors (function/class names and 1‑based line ranges) over long code dumps. Never paste raw tool JSON.

## Output Contract (Required)
- Print a short human summary first (bulleted, grouped by category). Mention any cutoff/backlog.
- Then print a single JSON object named REPORT with fields:
  ```json
  {
    "summary": {"by_category": {"no-dead-code": 0, "redundant-guard": 0, "unreachable-arm": 0}},
    "findings": [
      {
        "category": "no-dead-code|redundant-guard|unreachable-arm",
        "path": "wt/wt/module.py",
        "start_line": 123,
        "end_line": 128,
        "rationale": "Why this is dead/redundant, in one or two sentences.",
        "proof": ["No inbound references from exported call sites", "Argparse choices exclude 'turbo' so arm is unreachable"],
        "confidence": 0.9,
        "property": "no-dead-code|minimize-nesting|flag-propagation-fidelity|…",
        "anchors": ["def foo()", "match mode:"]
      }
    ],
    "progress": {"assessed_count": 0, "backlog": ["path/module.py:symbol", "..."], "cutoff": false}
  }
  ```
- Do not include raw tool outputs in REPORT. If you used tools, summarize their role inside "proof".

## Process (Reference; You May Adapt)
1) Inventory exported/public entrypoints (CLI/HTTP/API) to focus reachability checks; note high‑risk modules.
2) Dead code scan (reasoning‑first):
   - Build inbound reference sets for top‑level symbols (rg search + confirmation by reading call sites).
   - Classify dead/test‑only vs internal‑only. For dead items, add a one‑line proof.
   - Optionally consult Vulture to spot misses; validate every candidate by hand.
3) Unreachable/missing arms:
   - For choices/Enums vs match/if‑elif arms, flag missing/unreachable cases with anchors (choices def + arm lines) and a sentence why.
4) Redundant/subsumed guards:
   - Within a function, flag tautologies, contradictions, and trivial nested guards; cite the parent guard and the redundant site.
5) Summarize and emit REPORT JSON (no raw analyzer dumps). If you cut off early, include a concise backlog list for follow‑up.

## Consolidate Proofs
   - For each branch/type:
     - Either collect a compact chain: entrypoint → … → branch (files:lines), or state “no path; unreachable”.
   - Write `/tmp/reachability_proofs.md` grouping by module/function.

## Emit Findings
  - Produce the REPORT JSON exactly as specified above. Do not inline raw tool outputs.
  - Optionally write compact evidence files under `/tmp` (e.g., `/tmp/reachability_proofs.md`) to support your reasoning. Summarize their contents in the REPORT `proof` fields rather than dumping them.

## Command Snippets
- Baseline (discrete):
  - `ruff check --output-format json /workspace > /tmp/ruff.json`
  - `mypy --hide-error-context --show-error-codes /workspace > /tmp/mypy.txt` (or `--strict` if appropriate)
  - `vulture /workspace --min-confidence 60 --sort-by-size > /tmp/vulture.txt` (or use JSON if available)
  - `adgn-detectors-custom --root /workspace --out /tmp/custom-findings.json`
- Find choices/Enums: `rg -n "choices=\[|choices=\(|Enum\(" /workspace`
- Find match/case: `rg -n "^\s*match\s|^\s*case\s" /workspace`
- Isinstance chains: `rg -n "isinstance\(.*?,\s*\(" /workspace`
- Read with lines: `nl -ba -w1 -s ' ' /workspace/path/to/file.py | sed -n '120,180p'`

## Tooling Hints (Optional; Do Not Paste Raw Output)
- `pyright --outputjson /workspace` (reportUnreachableCode; fast hints)
- `bandit -q -r /workspace -f json` (security smells)
- `radon cc -s -j /workspace` and `xenon --max-absolute A --max-modules B --max-average B /workspace` (complexity hotspots)
- `pylint -j0 --output-format=json /workspace/wt` (design/architecture hints)
- `ctags -R -f /tmp/tags /workspace` then grep tags for defs/refs to build proofs
- `jscpd --path /workspace --reporters json` (duplication hotspots)
- `lint-imports -c importlinter.cfg` (boundaries; agent may scaffold a minimal config if absent)
- `pyan /workspace/**/*.py --uses --no-defines -o /tmp/callgraph.dot` (call graph hints)

## Final Message Formatting
- First: a concise human summary (bulleted) with counts per category and 2–3 high‑risk modules.
- Then: a single fenced JSON block named REPORT exactly as specified above.

## Heuristics & Confidence
- Prefer typed proofs (Mypy + Enums/choices) over rg‑only hints; annotate confidence accordingly.
- Treat registry/plugin interfaces as dynamic entrypoints; avoid false positives unless registry scan proves otherwise.

## Safety/Guardrails
- Never blanket‑catch exceptions; surface tool errors and continue.

## TODOs
- Identify target app CLI entrypoints (console scripts or modules) and any subpackages to exclude from analysis.
- If HTTP route decorations are non‑standard, provide route patterns; otherwise index FastAPI/Flask decorators by default.
- Provide exclude globs for generated/vendor directories to reduce noise.

## Notes
- Apply properties strictly; do not stretch definitions.
- Keep rationales short and objective; defer edits to a separate “enforce” path if desired.
{% endblock %}
