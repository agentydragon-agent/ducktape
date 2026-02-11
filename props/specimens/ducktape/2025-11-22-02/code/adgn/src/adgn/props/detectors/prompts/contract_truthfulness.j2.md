{% extends "_base.j2.md" %}
{% set read_only = true %}
{% set include_tools = false %}
{% set include_reporting = false %}

{% block title %}End‑to‑End Truthfulness & Contract Fixer — Agent Runbook{% endblock %}

{% block body %}
## Purpose
- Produce an exhaustive, human‑useful assessment of truthfulness across the end‑to‑end path (CLI → client → protocol/RPC → server). List violations clearly; do not produce diffs.
- Cover: flag/param propagation, request/response shapes (types/fields), error semantics (what is raised/returned), and “no swallow” expectations.
- Target exhaustive coverage within scope; if budget/token constraints force a cutoff, stop after N findings (N=10) and include a backlog of remaining items.

## Method (Outcome‑First)
- Read code first: map CLI flags/params → client builders → RPC payloads → server handlers.
- Only use tools as hints (no raw dumps in final). Validate each candidate by reading code and constructing a compact proof, not by pasting analyzer output.
- Prefer precise anchors (file:1‑based lines, function/class names) and short rationales over long excerpts.

## Output Contract (Required)
- First: a short human summary (bulleted) with counts by category and noteworthy modules; mention any cutoff/backlog.
- Then: a single JSON object named REPORT with fields (no diffs required):
  ```json
  {
    "summary": {"by_category": {"flag-propagation-fidelity": 0, "truthfulness": 0, "structured-data-over-untyped-mappings": 0, "no-swallowing-errors": 0}},
    "findings": [
      {
        "id": "cli-flag-force",
        "kind": "flag|param|return|error_semantics",
        "property": "flag-propagation-fidelity|truthfulness|structured-data-over-untyped-mappings|no-swallowing-errors",
        "path": "wt/wt/server/wt_server.py",
        "start_line": 1200,
        "end_line": 1220,
        "anchors": ["cli: wt/wt/cli.py:210-230", "client: wt/wt/client/worktree_utils.py:140-175", "server: wt/wt/server/wt_server.py:2080-2120"],
        "payload_delta": {"expected": {"force": true}, "observed": {"force": null}},
        "rationale": "CLI parses --force, but client does not send it and server behaves as always-force. Behavior diverges from intent.",
        "confidence": 0.9
      }
    ],
    "progress": {"assessed_count": 0, "backlog": ["daemon.startup-timeout", "status.pagination"], "cutoff": false}
  }
  ```

## Process (Reference; Adapt As Needed)
1) Enumerate candidates:
   - Flags/params: grep CLI (click/Typer) and client builders for names/defaults.
   - RPC methods: list handlers and payload models; note expected fields and shapes.
2) Trace flows per candidate: CLI → client → payload → server handler; identify expected keys and behavior.
3) Confirm divergences: construct a compact proof from code reads; use minimal probes only when necessary (e.g., help text or a controlled in‑container echo) — no raw dumps in final.
4) For each violation, write a concise rationale and anchors; optionally include a one‑line “suggested fix” in prose if obvious (no diffs).
5) Emit REPORT JSON. If a cutoff occurs, populate progress.backlog with concise next‑targets.

## Command Snippets (For Navigation; Do Not Paste Outputs)
- Search: `rg -n "@app\.command|add_argument\(|Typer\(|choices=|Enum\(" /workspace`
- Read with lines: `nl -ba -w1 -s ' ' /workspace/path.py | sed -n '120,160p'`
- Fast hints (optional): `pyright --outputjson /workspace`, `ruff check --output-format json /workspace`, `pylint -j0 --output-format=json /workspace/wt`
- Jumping around: `ctags -R -f /tmp/tags /workspace` then grep tags for defs/refs.

## Safety/Guardrails
- Never blanket‑catch exceptions; surface tool errors and continue.

## Notes
- Apply properties strictly; do not stretch definitions.
{% endblock %}
