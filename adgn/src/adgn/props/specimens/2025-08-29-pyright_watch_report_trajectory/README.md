# Specimen: pyright_watch_report trajectory (agent behavior)

This specimen captures the rollout-level behavior of running the properties checker and an agent on the previous specimen’s Python script, then iterating on transcript filtering to eliminate leakage.

TODO(mpokorny): Demonstrate as example of behavior of "leaving behind past-state comments"

## What this is
- End-to-end trajectory of the Codex fixer (the agent under test) running against the prior specimen `pyright_watch_report.py`.
- Focus: “behavioral” observations — places where the agent exhibited undesirable behavior that only becomes visible at the whole‑run (trajectory) level.

## Reference to prior specimen
- Source specimen: `llm/adgn_llm/specimens/2025-08-29-pyright_watch_report/pyright_watch_report.py`
- Git SHA (for reference): `0dc9c99b9deeb4133ef0917cbf48ca6fa8331bfd`

## How the transcript was filtered
- Script: `llm/adgn_llm/specimens/2025-08-29-pyright_watch_report/filter_codex_jsonl.py`
- Method:
  - Drops only these event types (including when nested under msg.type): `agent_reasoning`, `turn_diff`, `exec_command_output_delta`.
  - Anonymizes strings in all fields:
    1. Collapse any prefix before `llm/properties/` to that anchor (keeps whitelisted paths intact)
    2. Replace the repository root with `/ducktape/` (auto-detected via `git rev-parse --show-toplevel` or provided via `--repo-root`)
    3. Mask the current system username (via `getpass.getuser()`) as `<user>` (e.g., in `ls` owner columns)
  - Works with `.jsonl` and `.jsonl.gz` inputs/outputs; preserves non-JSON lines and still applies anonymization.

### Artifacts (post-filter)
- Filtered JSONL: `llm/adgn_llm/specimens/2025-08-29-pyright_watch_report/pyright_watch_report.codex.filtered.jsonl`
- Compressed: `llm/adgn_llm/specimens/2025-08-29-pyright_watch_report/pyright_watch_report.codex.filtered.jsonl.gz`

## Behavioral findings (trajectory-level)
- Initial run captured absolute local paths and the local username via cwd fields and `ls` outputs — an undesirable behavior when publishing transcripts.
- Post‑filter iterations added:
  - Repo‑root scrubbing to `/ducktape/`
  - Username masking to `<user>`
  - Additional event type drop: `exec_command_output_delta`
- Final re‑audit showed zero off‑allowlist leaks by an independent leak auditor (`git-commit-ai/src/git_commit_ai/scratch/leak_audit.py`).

## Why this specimen exists
This specimen demonstrates an instance of trajectory‑level “bad behavior” — the agent’s initial execution produced environment‑revealing records (cwd, file listings).
The fix involved tightening the transcript filter rather than altering the core specimen.
The goal is to document the behavior, the mitigation, and the minimal filtering necessary to publish a safe rollout‑level patch.
