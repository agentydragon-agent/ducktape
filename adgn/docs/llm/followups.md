# Remaining follow-ups (lint, types, refactors)

This document tracks the remaining cleanup from the current session. Items are grouped by module with concrete acceptance criteria.

## Quick lint fixes (ruff)

- [ ] eval_harness.py: Remove duplicate class definition
  - File: `src/adgn/props/eval_harness.py`
  - Issue: `IssueEvalSpec` is defined twice (lines ~82 and ~420). Keep the first; delete the redefinition.
  - Done when: ruff no longer reports F811 in this file.

## Type fixes (mypy) — high priority

- [ ] specimen_registry.py: jsonnet evaluate_file kwargs
  - File: `src/adgn/props/specimen_registry.py`
  - Error: Unexpected kwargs `jpathdir`, `import_callback` for `_jsonnet.evaluate_file`.
  - Fix: Call via `cast(Any, _jsonnet).evaluate_file(...)` or wrap in a helper typed as `Any` to satisfy stubs.

- [ ] tests: AnyUrl casts for read_resource
  - Files: `tests/agent/test_mcp_integration.py` (lines ~90, 109)
  - Fix: `uri = cast(AnyUrl, "resource://container.info")` before `read_resource` calls, or use helper that accepts str.

- [ ] tests: Guard None before dict indexing
  - File: `tests/agent/test_editor_inproc.py` (multiple lines)
  - Fix: assert dict is not None or early-return before indexing/get(); remove union-attr violations.

- [ ] tests: MiniCodex.create signature and client type
  - Files: `tests/agent/test_exec_roundtrip.py`, `src/adgn/llm/llm_edit.py`, `src/adgn/props/agent_runner.py`, `src/adgn/agent/cli.py`
  - Issues:
    - Provide `handlers=[...]` in `MiniCodex.create` (required now).
    - Client type: pass a `ResponsesClient`-compatible instance (wrap `AsyncOpenAI` or `cast(ResponsesClient, AsyncOpenAI())`).
    - Where code expects `.text` on result, handle `AgentResult | AsyncIterator` union (don’t access `.text` on iterator; run non-stream or consume iterator).

- [ ] event_renderer.py: API rename
  - File: `src/adgn/agent/event_renderer.py`
  - Error: `_render_function_call_output` no longer exists; replace with `emit_function_call_output` or update to current API.

- [ ] lint_issue.py: no-redef variable
  - File: `src/adgn/props/lint_issue.py`
  - Error: Name `f` already defined earlier — rename inner `f` or use a different variable name in the later scope.

- [ ] eval_harness.py: Optional list handling
  - File: `src/adgn/props/eval_harness.py`
  - Issues: `len(list|None)` and indexing on `list|None` — guard `None` before `len()`/indexing.

- [ ] examples: Optional assignment
  - File: `src/adgn/agent/examples/run_minicodex_docker_demo.py`
  - Issue: Assigning `str | None` to `str`; supply default string before assignment.

- [ ] inop/engine/optimizer.py: multiple
  - File: `src/adgn/inop/engine/optimizer.py`
  - Items:
    - Guard optional logger before `.info` (lines ~109, 341).
    - Fix `TruncationConfig` field name to `max_file_size_pattern_analysis`.
    - Ensure provider variable types match actual provider classes (not `PatternSummarizer`).
    - `grading_config` currently optional; pass non-Optional or adjust callee.
    - `MiniCodex.create` client type: cast/wrap to `ResponsesClient`.

## Agent/CLI refactors & invariants

- [ ] McpManager: Meta-resources server (planned)
  - Build `meta_resources` server inside `McpManager` at init; pass `self` as facade implementing `list_resources`/`read_resource`.
  - Tools:
    - `resources.list(server?: str, uri_prefix?: str)` → `{resources:[...]}`
    - `resources.read(server: str, uri: str, start_offset?: int|str|None, max_bytes?: int|str|None)` → window dict
  - After this, remove any remaining agent special-casing (now already removed) and let model call the meta tools.

- [ ] Wire existing specimen hydration ctx manager
  - SpecimenRegistry.hydrated_copy() already exists (async context manager). Wire it into callers that duplicate hydration logic: `specimen-check`, `specimen-discover`, `specimen-grade`, `lint-issue`, `eval-all` (per-case), and any "list occurrences" utilities.
  - Acceptance:
    - Single code path for hydration/cleanup; no temp dirs left behind on error.
    - Call sites use `async with s.hydrated_copy(gitconfig) as root:` to obtain a fresh tree.
    - "List occurrences" uses the hydrated tree where appropriate.

## Docs follow-ups

- [ ] Update docs pointing to specimen loader
  - README reference now mentions `specimen_registry.py`; ensure contents and paths are consistent with the new loader.

## Nice-to-have (later)

- [ ] mypy: Enable `--check-untyped-defs` selectively for key modules (reduce “annotation-unchecked” notes).
- [ ] tests: Add unit tests for `_build_resource_window` (text, blob, mixed; bounded/unbounded; offsets) and `_tool_choice_from_policy`.

---

How to work this list
- Start with ruff quick-fixes and the duplicate class in `eval_harness.py`.
- Do `specimen_registry.py` jsonnet call cast, then re-run mypy to reduce the error surface.
- Sweep tests minimal changes (casts/guards), then the provider/logger fixes in `inop/engine/optimizer.py`.
- Finally, implement the `meta_resources` server inside `McpManager` as designed above and delete any vestigial code paths.

Verification
- Run:
  - `uv run ruff check . --fix`
  - `uv run python -m mypy adgn`
  - Affected tests under `tests/agent/**`.
