# Remaining follow-ups (targeted)

This document tracks what's left to tidy up after recent refactors. Closed items from the previous list have been removed.

## MCP Migration Status

**The MCP-based management UI implementation is complete** (Phases 0-4, Waves 1-4). See **../MCP_MIGRATION_SUMMARY.md** for full details.

**Remaining**: Phase 5 cleanup (remove legacy WebSocket code, final consistency pass)

---

## Docs

- [ ] Update MCP runtime docs once loop hooks + DB server land (ensure `docs/mcp-runtime/*` align with code).
- [ ] Document the chat inbox architecture (human MCP sidecar + runtime bridge feeding UiState) once landing.
- [ ] Promote `ember/docs/pilot_plan.md` after v0 bake (ensure README links stay accurate).
- [ ] Cross-reference seatbelt TODO
  - Add a short note in relevant docs (sandboxer pages, MCP presets) pointing to `adgn/docs/seatbelt/TODO.md` for the living SBPL feature list and gaps.

## Loop Hooks / DB surfaces

- [ ] Implement loop hook tooling (`loop.enable_hook/disable_hook`) with per-hook resources (`loop://hooks/{id}`) and sandboxed execution.
- [ ] Add orchestrator bridge delivering coalesced notifications into hooks (current handlers-only path).
- [ ] Ship the read-only DB MCP server (`db://view/*` / `query`) plus hook input hydration.
- [ ] Add coverage for hook enable/disable and hydrated inputs once APIs exist.

## Chat / UI delivery

- [ ] Promote the MCP-native chat inbox (`ui://chat/inbox`, `chat_read_since`) and dual subscriptions; retire the process bus once parity is confirmed.
- [ ] Ensure runtime bridges human chat MCP notifications into `UiState` (user messages) and writes assistant outputs through `chat.assistant.post`.
- [ ] Update UI handler prompts/tests to consume the new chat resource flow.
- [ ] Add fixtures exercising the MCP chat inbox end-to-end.
- [ ] Remove the legacy `ui` MCP server and migrate assistant output to `chat.assistant.post` plus `loop.yield_turn`.

## Seatbelt library polish (tracked primarily in adgn/docs/seatbelt/TODO.md)

- [ ] Validator: structured findings (codes/severity) and optional raise-on-must-fix.
- [ ] Compiler: remove or gate the implicit trace file write rule; keep compile “magic-free”.
- [ ] CLI shim for `validate`, `compile`, `run` for quick manual checks.

## Tests (nice-to-have)

- [ ] Add unit tests for `_tool_choice_from_policy` (accepts required/auto/none and single specific function name; rejects multiple names).
- [ ] Add resource-window tests if implemented (`_build_resource_window` placeholder from earlier notes).

## Pre-existing Test Infrastructure Issues

**These are NOT related to MCP migration - they existed before and require separate fixes:**

### 1. ResponseUsage Validation Errors
**Issue**: OpenAI SDK updated `ResponseUsage` model to require `input_tokens_details` and `output_tokens_details` fields
```python
# Old (working):
ResponseUsage(input_tokens=0, output_tokens=1, total_tokens=1)

# New (required):
ResponseUsage(
    input_tokens=0,
    output_tokens=1,
    total_tokens=1,
    input_tokens_details=InputTokensDetails(...),  # NOW REQUIRED
    output_tokens_details=OutputTokensDetails(...)  # NOW REQUIRED
)
```
**Fix needed**: Update `openai_utils/model.py` and test factories to include token details
**Tests affected**: `test_messages_forwarding.py`, `test_mcp_notifications_flow.py` (13 failures)

### 2. CallToolResult API Changes
**Issue**: FastMCP `CallToolResult` constructor now requires a `meta` parameter
```python
# Old (working):
CallToolResult(content=[...], isError=False)

# New (required):
CallToolResult(content=[...], isError=False, meta={})  # meta is required
```
**Fix needed**: Update all `CallToolResult` construction sites to include `meta` parameter
**Tests affected**: `test_reducer.py`, `test_history_fold_typed.py` (3 failures)
**Impact**: This is a breaking change in FastMCP/MCP SDK - check if we're on a version that requires it

### 3. Event Loop Conflicts
**Issue**: `asyncio.Runner.run()` cannot be called from within an already-running event loop
```python
# Fails when already in async context:
def test_something():
    runner = asyncio.Runner()
    runner.run(async_function())  # RuntimeError: Runner.run() cannot be called from a running event loop
```
**Fix needed**: Convert tests to native async or use `asyncio.run()` in sync contexts only
**Tests affected**: `test_editor_inproc.py`, `test_ui_agent_integration.py`, `test_policy_state_management.py`, etc. (20+ failures)
**Root cause**: Tests mixing sync/async contexts incorrectly - need to either:
  - Use `@pytest.mark.asyncio` and make tests fully async
  - OR ensure `Runner.run()` only called from sync (non-event-loop) contexts

## Verification

- Lint/types: `uv run ruff check . --fix`, `uv run python -m mypy adgn`
- Targeted tests: `pytest -q adgn/tests/agent`, plus any new seatbelt/approval tests as added.

## Agent State Notifications

- [ ] **Wire agent state notifications for live UI updates**
  - Currently: `resource://agents/{id}/state` resource exists but doesn't emit notifications
  - Needed: When agent state changes (new messages, tool calls, state transitions), broadcast `resource_updated`
  - Implementation: Wire compositor/session events → `server.broadcast_resource_updated(resources.agent_state(agent_id))`
  - Similar pattern to policy notifications (see `agents.py:380-400` for policy notifier wiring)
  - Events to wire: user prompt, assistant message, tool call execution, approval decisions

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
- [ ] Implement pinned subscription semantics (respect `SubscriptionRecord.pinned`) and expose `list_resource_templates` once templates API is finalised.

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

- [ ] Wire `adgn-trivial-patterns` into pre-commit/CI (report-only; scope to tests).
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
