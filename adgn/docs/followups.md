# OpenAI isolation layer refactor — status and next steps

## Quality/consistency

- OpenAI client lifecycle (partially complete)
  - Status: Properties CLI and Typer app construct a single `RetryingOpenAIModel(OpenAIModel(AsyncOpenAI()))` and pass it down. LLM edit does the same per invocation.
  - Outstanding Where: src/adgn/agent/cli.py, src/adgn/props/prompt_eval/server.py, src/adgn/props/cluster_unknowns.py
  - Next: Provide a module-level factory for a single `AsyncOpenAI` per process and inject the typed client everywhere; remove ad-hoc `AsyncOpenAI()` constructions.
  - Acceptance: All CLIs/services use a single constructed client per process; no direct `AsyncOpenAI()` in branches.

- Responses adapter streaming support (deprioritized)
  - Where: src/adgn/openai_utils/model.py (ResponsesRequest.stream flag not wired)
  - Decision: Keep non-streaming path only; streaming not needed for current CLIs.
  - If needed later: add typed streaming surface or an aggregator to `ResponsesResult`.

- Path typing for --output-final-message
  - Where: src/adgn/props/cli.py (argparse string passed where Path is expected)
  - Next: Parse to `Path` at argparse boundary; plumb `Path` through; normalize writes.
  - Acceptance: Type is `Path` end-to-end; smoke test where possible.

## Lint-issue path

- DONE: Issue model migration
  - Status: Lint flow operates on `IssueCore` + selected `Occurrence`; no direct legacy `Issue` dependency in CLI path.

- Client typing insulation
  - Where: src/adgn/props/lint_issue.py (functions typed `client: AsyncOpenAI`)
  - Next: Change signatures to accept `ResponsesClient` (our provider interface) and pass typed client; remove SDK type from annotation/imports.

- BIG_THRESHOLD configurability + tests
  - Where: src/adgn/props/lint_issue.py
  - Next: Add env/flag (e.g., `--max-bootstrap-bytes`); test big-file bootstrap behavior.

- Specimen id handling consistency
  - Where: src/adgn/props/lint_issue.py (uses `Path(specimen).name`)
  - Next: Accept slug or manifest path/dir; resolve via a helper when a path is provided.

## Loop control / agent

- DONE: RequireSpecific policy
  - Where: src/adgn/agent/loop_control.py
  - Status: Implemented; agent maps single-name RequireSpecific to Responses `tool_choice`.
  - Optional next: Consider multi-name support or keep single-name constraint explicit.

- Event renderer refactor (optional)
  - Where: src/adgn/agent/event_renderer.py; src/adgn/llm/rendering/rich_renderers.py
  - Next: Extract formatting/adapters; keep ConsoleEventRenderer thin.

- In-proc transport config (future)
  - Where: src/adgn/agent/mcp_manager.py
  - Next: Support dotted-path factory in config if/when required.

## Sandboxer

- Seatbelt named params (revisit later)
  - Where: src/adgn/llm/sandboxer.py:187, 200
  - Next: Restore macOS sandbox-exec named params once parsing issues are resolved; add regression test.

## INOP/Optimizer and logging wrapper

- Unify logging model surface
  - Where: src/adgn/inop/clients/logging_openai_client.py
  - Next: Add a tiny adapter to satisfy `ResponsesClient` (wrapping `responses.create(**kwargs)`) or migrate INOP paths to the typed request/response layer.

## Docs and polish

- DONE: Swept stale `src/adgn_llm` references in docs/specimens; updated to current `src/adgn/...` layout.
- Remove duplicate helpers (e.g., `_detect_tools`) if duplicated across CLIs.

---

### Suggested order of execution
1) Client lifecycle: shared factory + signatures to `ResponsesClient`
2) Path typing cleanup for `--output-final-message`
3) Lint-issue: BIG_THRESHOLD config + specimen-id handling
4) INOP logging adapter to `ResponsesClient`
5) Optional renderer/transport polish as needed
