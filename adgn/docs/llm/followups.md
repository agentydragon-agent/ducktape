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
