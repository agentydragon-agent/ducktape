# OpenAI isolation layer refactor — updated followups

This list reflects current gaps after recent refactors. Removed items were completed (client factory adoption, Path typing, typed clients across flows).

## Quality/consistency

## Lint-issue path (next)

- BIG_THRESHOLD configurability + tests
  - Where: `src/adgn/props/lint_issue.py` (constant `BIG_THRESHOLD = 20480`)
  - Action: expose as CLI option/env (e.g., `--max-bootstrap-bytes`) and add tests for big-file bootstrap behavior.

- Specimen id handling consistency
  - Where: `src/adgn/props/lint_issue.py` uses `Path(specimen).name` in one path and slug elsewhere.
  - Action: accept slug or manifest path/dir; resolve via a small helper to keep UX flexible and consistent.

## Seatbelt/sandbox

- Tracking moved to `adgn/docs/seatbelt/TODO.md` (living list).
  - Action: keep sandboxer docs/presets pointing to that file; avoid duplicating SBPL details here.

## INOP/Optimizer

Follow-ups (polish):
  - Ensure grading configs are validated early with clear messages (already raises if missing; consider friendlier CLI surfacing).
  - Optional: add debug logging toggles surfaced through CLI to pass `enable_debug_logging=True`.

## Docs and polish

- Remove duplicate helpers if any remain (e.g., tool-detection helpers across CLIs).
- Update any lingering references to legacy specimen loader paths; prefer `adgn/src/adgn/props/specimens/registry.py`.

## Loop control / agent (backlog)

- Optional event rendering polish: keep DisplayEventsHandler thin and extract formatting helpers as needed.

---

### Suggested order
1) Lint-issue: BIG_THRESHOLD option + tests; specimen id resolver helper
2) Docs: references and helper dedupe
3) INOP polish: config validation messages and debug toggle

## Properties Cleanup — tracking

- Scoped try/except and no swallow
  - Narrow broad `except Exception` in boundary code where feasible and ensure logging context.
  - Notable hotspots: `openai_utils/http_logging.py` send/append paths; matrix client sync loop backoff; UI websocket sender loop error path.

- Clear units and naming
  - Review `deadline` vs `timeout` naming in async waits for consistency.

- Barrel imports / public API surfaces
  - If `src/adgn/tana/tana_lib/__init__.py` and `src/adgn/inop/grading/__init__.py` are truly public: add short docstring markers; else avoid barrels.

- Tests: pytest fixtures
  - Continue preferring `tmp_path` for script files in helpers.

## MiniCodex UI — next steps (prioritized)

1) Runs History tab (high): list runs, resume context
2) Degraded state dot (high): indicate failing MCP servers
3) WS reconnect/backoff (med)
4) Non-destructive lifecycle controls (med)
5) Chat virtualization (med)
6) A11y polish (low)
7) CI smoke via Playwright (low)
