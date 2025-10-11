# Remaining follow-ups (targeted)

This document tracks what’s left to tidy up after recent refactors. Closed items from the previous list have been removed.

## Docs

– (none)

- [ ] Cross-reference seatbelt TODO
  - Add a short note in relevant docs (sandboxer pages, MCP presets) pointing to `adgn/docs/seatbelt/TODO.md` for the living SBPL feature list and gaps.

## Seatbelt library polish (tracked primarily in adgn/docs/seatbelt/TODO.md)

- [ ] Validator: structured findings (codes/severity) and optional raise-on-must-fix.
- [ ] Compiler: remove or gate the implicit trace file write rule; keep compile “magic-free”.
- [ ] CLI shim for `validate`, `compile`, `run` for quick manual checks.

## Tests (nice-to-have)

- [ ] Add unit tests for `_tool_choice_from_policy` (accepts required/auto/none and single specific function name; rejects multiple names).
- [ ] Add resource-window tests if implemented (`_build_resource_window` placeholder from earlier notes).

## Verification

- Lint/types: `uv run ruff check . --fix`, `uv run python -m mypy adgn`
- Targeted tests: `pytest -q adgn/tests/agent`, plus any new seatbelt/approval tests as added.

## Approvals / Proposals

- [ ] Add HTTP endpoint to create proposals via MCP proposer
  - POST `/api/agents/{agent_id}/proposals {content}` calling `approval_policy.proposer.create_proposal`.
  - Update UI E2E to create proposals via HTTP instead of direct SQLite insert.
- [ ] Ensure proposer/admin servers are mounted by default for live agents
  - Mount `approval_policy.proposer` and `approval_policy.admin` with the reader.
- [ ] Add MCP-level tests for proposer flow
  - Create → visible via reader resources/snapshot; Withdraw → removed.

## Resources / Compositor

- [ ] Expand resources server coverage
  - Exercise `resources.list/read` via typed clients to validate Pydantic types.
- [ ] Add helper for invoking proposer MCP in tests (non-HTTP) if needed.
- [ ] Confirm mount failure surfaces and tool listing via proxy in meta tests.

## WT CLI / Daemon

- [ ] Add skip marker for AF_UNIX-blocked environments (current guidance: run with escalation).
- [ ] Document `wt_cli` / `wtcli` fixtures and the escalation requirement in AGENTS.md.

## AnyIO / Async Cleanups

- [ ] Sweep remaining `anyio.run(...)` in tests and convert to async tests where practical.
  - Keep intentional uses inside embedded stdio server scripts.

## Code / Comments Hygiene

- [ ] Remove stale comments referencing named volumes (e.g., containerized_claude runner).
- [ ] Update docs to fully drop named volumes and describe proposer/admin/reader flows.

## CI / Tooling

- [ ] Wire `tools/detect_trivial_aliases.py` into pre-commit/CI (report-only; scope to tests).
- [ ] Split CI lanes for WT (AF_UNIX enabled/escalated) and Docker-required tests (`-m requires_docker`).

## NotifyingFastMCP / Hooks

- [ ] Investigate replacing private attr overrides/type-ignores with public hooks if FastMCP exposes them.
- [ ] Consider a typed context shim cleanup for request context if any legacy accessor remains.

## Policy Gateway / Errors

- [ ] Document the policy-gateway stamp on errors (stamp-first detection), with example payloads and client guidance.
- [ ] Add an HTTP-backed spoofing test (mount remote server over Streamable HTTP) to verify stamp remap to `policy_backend_reserved_misuse` end-to-end.
- [ ] Add a result-path remap test where `CallToolResult.is_error` returns stamped `ErrorData` to ensure middleware remaps misuse.
- [ ] Open/track an upstream FastMCP issue to preserve structured `ErrorData` for in-proc raised exceptions so the stamp is visible consistently.
- [ ] Optional: introduce a typed union in `error.data` (e.g., `{kind, name, reason?, decision?}`) and update docs to prefer parsing it over codes/messages.
