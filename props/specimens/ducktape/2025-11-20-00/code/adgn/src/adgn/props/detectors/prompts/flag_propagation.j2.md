{% extends "_base.j2.md" %}
{% set read_only = true %}
{% set include_tools = false %}
{% set include_reporting = false %}

{% block title %}Flag/Mode Propagation & Boundary Verification — Agent Runbook{% endblock %}

{% block body %}
## Purpose
- Produce an end‑to‑end assessment of all relevant flags/modes within scope (e.g., `--force`, `--dry-run`, `--timeout`): do they propagate from CLI → client → protocol → server and have the claimed effects? Use tools only to assist; your output must be a clear, reasoned report.
  - If budget or token constraints force a cutoff, stop after N findings (N=10), and include a backlog of remaining flags with a brief note for each.

## Method (Outcome‑First)
- Read the CLI and handler code to understand flow; only then run probes.
- Use minimal, surgical probes (e.g., head/tail of help text; small payload capture shims) and summarize deltas. Never paste raw dumps into the final report.

## Output Contract (Required)
- Print a short human summary (flags checked; high‑level results and any cutoff/backlog info).
- Then print a single JSON object named REPORT with fields:
  ```json
  {
    "flags": ["--dry-run", "--timeout", "... all assessed flags ..."],
    "findings": [
      {
        "flag": "--dry-run",
        "result": "propagates|no-op|mismatch",
        "anchors": ["cli: src/app.py:45-60", "client: src/client.py:88-96", "server: src/handler.py:120-142"],
        "payload_delta": {"expected": {"dry_run": true}, "observed": {"dry_run": false}},
        "rationale": "CLI parses flag but client drops it; server uses hard-coded default.",
        "property": "flag-propagation-fidelity|truthfulness",
        "confidence": 0.9
      }
    ],
    "progress": {
      "assessed_count": 0,
      "backlog": ["--flag-x", "--flag-y"],
      "cutoff": false
    }
  }
  ```
- Do not include raw help text or capture logs; summarize in rationale.

## Process (Reference; Adapt As Needed)
1) Enumerate all candidate flags (grep + help text). Order by impact for efficiency, but the target is exhaustive coverage.
2) For each flag, trace CLI → client → server (read code; rg as needed) and note expected payload keys/handlers.
3) Run a minimal probe to confirm behavior and payload delta; capture only what you need to write the rationale.
4) Decide and add a REPORT item with anchors and a one‑paragraph rationale.

## Command Snippets (Examples)
- Search and read:
  - `rg -n "--force|--dry-run|--timeout" /workspace`
  - `nl -ba -w1 -s ' ' /workspace/path/to/file.py | sed -n '120,160p'`
- Optional hints (no raw dumps in final):
  - `pyright --outputjson /workspace` for unreachable code hints.
  - `ruff check --output-format json /workspace` for quick lint cues.
  - `pylint -j0 --output-format=json /workspace/wt` to spot design/architecture smells.
  - `ctags -R -f /tmp/tags /workspace` then grep tags to follow defs/refs while proving propagation paths.
- Capture shim (HTTP outline):
  ```python
  # /tmp/shims/capture.py
  import json, os, sys
  from datetime import datetime
  import requests
  _orig = requests.Session.request
  def _cap(self, method, url, **kw):
      body = kw.get('data') or kw.get('json')
      with open('/tmp/payloads.jsonl', 'a', encoding='utf-8') as f:
          f.write(json.dumps({'ts': datetime.utcnow().isoformat(), 'method': method, 'url': url, 'body': body})+'\n')
      return _orig(self, method, url, **kw)
  requests.Session.request = _cap
  ```
  - Activate: `PYTHONPATH=/tmp/shims <cli> <args>`

## Decision Heuristics
- Treat missing payload deltas as “no‑op flag” unless help explicitly states “no effect in mode X”.
- Consider server hard‑codes as higher severity when they defeat user intent.
- Prefer precise anchors at the boundary (client payload builder, server handler) and at the CLI parser site for context.

## Safety/Guardrails
- Never blanket‑catch exceptions; surface tool errors and continue with remaining steps.

## TODOs
- If the target CLI requires a local daemon, document how to start/stop it offline and expected log/socket locations; otherwise skip daemon flows.
- Provide sample fixtures/config if specific flows require inputs (no secrets).

## Notes
- Apply properties strictly by their definitions when deciding applicability.
- Keep rationales short and objective; defer edits/fixes to a separate “enforce” step if desired.
{% endblock %}
