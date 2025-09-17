# Remaining follow-ups

## Quality/consistency

- Single AsyncOpenAI client per CLI invocation
  - Where: src/adgn_llm/properties/cli.py (multiple AsyncOpenAI() constructions at 761, 790, 818)
  - Approach: Instantiate once at main() start; pass through to async runners (no new AsyncOpenAI() in sub-branches).
  - Acceptance: No new client constructions inside branches; mypy/ruff clean.

- Path typing for --output-final-message
  - Where: src/adgn_llm/properties/cli.py:760 (TODO comment)
  - Approach: Parse to Path in argparse handling; plumb Path to downstream helpers; normalize write sites.
  - Acceptance: Type is Path end-to-end; unit smoke where possible.

## Lint-issue improvements

- Finalize IssueDoc migration (IssueCore + Occurrence only)
  - Where: src/adgn_llm/properties/lint_issue.py:351–353 (bridge TODO)
  - Approach: Remove legacy Issue usage from CLI path; operate on IssueCore + chosen Occurrence; keep SpecimenRegistry as source.
  - Acceptance: No direct dependency on deprecated Issue in lint path; deprecation warnings disappear.

- BIG_THRESHOLD configurability + tests
  - Where: src/adgn_llm/properties/lint_issue.py:385–467
  - Approach: Env var or CLI flag (e.g., --max-bootstrap-bytes). Add tests for big-file branch (skip showing content; still succeeds).
  - Acceptance: Threshold adjustable; test asserts bootstrap behavior.

- Specimen id handling consistency
  - Where: src/adgn_llm/properties/lint_issue.py:529 (Path(specimen).name)
  - Approach: Accept either slug or manifest path/dir; if path exists, resolve via resolve_manifest_arg; otherwise treat as slug.
  - Acceptance: Works for slug and explicit paths; add a small CLI test.

## Loop control / infra (time-boxed)

- RequireSpecific tool policy in loop control
  - Where: src/adgn_llm/mini_codex/loop_control.py:10–11
  - Approach: Add RequireSpecific(names: tuple[str, ...]) and wire to BaseHandler decisions; add minimal unit tests.

- Event renderer refactor to composable handlers
  - Where: src/adgn_llm/mini_codex/event_renderer.py:32–33; src/adgn_llm/rendering/rich_renderers.py:10–11
  - Approach: Extract formatting/adapters; keep ConsoleEventRenderer thin; optional for now.

- In-proc transport config (JSON → FastMCP factory) [future]
  - Where: src/adgn_llm/mini_codex/mcp_manager.py:202–203
  - Approach: Support a dotted path factory in config; defer until needed.

## Sandboxer follow-ups

- Reintroduce named seatbelt params when safe
  - Where: src/adgn_llm/sandboxer.py:187, 200
  - Approach: Track macOS sandbox-exec param parsing issues; restore (param "WP_*"/"RP_*") once stable; add regression test.

## Misc (inop/sysrw)

- Optimizer metadata: persist grader text + model identities
  - Where: src/adgn_llm/inop/engine/optimizer.py:33–35

- Leaderboard: deprecate legacy numeric ci95
  - Where: src/adgn_llm/sysrw/leaderboard.py:188–189

- Runner configs: per-task Docker config
  - Where: src/adgn_llm/inop/runners/claude_runner.py:56

- Grading strategies: container file collection
  - Where: src/adgn_llm/inop/grading/strategies.py:88–89

- Summarizer: store/log artifacts
  - Where: src/adgn_llm/inop/prompting/summarizer.py:124–125

---

### Suggested order of execution
1) Specimen-grade negatives support
2) CLI client lifecycle + Path typing cleanup
3) Lint-issue consolidation + BIG_THRESHOLD config
4) Small CLI polish (duplicate _detect_tools)
5) Time-boxed infra items as needed
