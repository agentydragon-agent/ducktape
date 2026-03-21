---
name: verify-docs
description: Verify documentation claims against actual code, finding and fixing stale or incorrect docs. Audit AGENTS.md/README.md/STYLE.md for token efficiency — cut what strong LLMs already know, keep local specifics and gotchas. Use when asked to review docs, trim docs, or check docs are accurate.
allowed-tools: Bash Read Grep Glob Edit Write Agent
---

# Verify and Optimize Documentation

Audit repo documentation for correctness and token efficiency.

## Principles

Docs are primarily consumed by LLM agents. Strong LLMs already know Python, k8s, general SE practices, well-known APIs. Only document:

- **Local specifics**: bespoke APIs, repo-specific patterns, non-obvious config
- **Gotchas**: things that previously broke, counterintuitive behavior
- **Deviations**: where this repo does something non-standard

Cut everything a strong LLM could derive from reading the code or from general knowledge.

## File hierarchy

| File        | Role                                     |
| ----------- | ---------------------------------------- |
| `CLAUDE.md` | Always just `@AGENTS.md`                 |
| `AGENTS.md` | Transcludes README + agent prescriptions |
| `README.md` | What it is, how to run (humans + agents) |
| `STYLE.md`  | Repo-wide style rules (root only)        |

`AGENTS.md` should transitively transclude (`@file`) things agents always need. For rarely-needed docs, reference them (link/path) so agents read on demand.

Sub-package `AGENTS.md` must not repeat parent-level instructions.

## Audit procedure

1. **Inventory**: Glob for `**/AGENTS.md`, `**/README.md`, `**/CLAUDE.md`, `**/STYLE.md`
2. **Structural check**: Verify each `CLAUDE.md` is just `@AGENTS.md`. Verify `AGENTS.md` files start with `@README.md` where a README exists.
3. **Staleness check**: For each claim in docs (file paths, function signatures, env vars, CLI flags, Bazel targets), grep the codebase to verify it still exists and is accurate. Flag stale references.
4. **Token audit**: For each doc, flag:
   - General SE knowledge LLMs already have (e.g., "pytest uses fixtures for shared setup")
   - Restated type signatures or parameter lists
   - Explanatory prose that doesn't add info beyond what the code shows
   - Redundant examples (one is enough per pattern)
   - Content duplicated between parent and child AGENTS.md
5. **Classify kept content**: Confirm remaining content falls into: local specifics, gotchas, deviations, bespoke API details, or recovery procedures for past failures.
6. **Propose changes**: Present a concrete diff or list of cuts with rationale. Group by file.

## What to cut (examples)

- "Framework: pytest with pytest-asyncio" — LLMs know pytest
- "Fixtures for shared setup" — obvious
- Explaining what `pathlib.Path` is or why to prefer it
- Lengthy examples of standard Python patterns (comprehensions, async/await)
- Docstring style rules that restate PEP 257

## What to keep (examples)

- `pytest_bazel.main()` requirement — non-obvious, caused silent test passes
- Session start hook recovery — bespoke, multi-step, previously caused outages
- BuildBuddy RBE setup — bespoke API, not widely known
- `dangerouslyDisableSandbox` for network commands — local gotcha
- `live_openai_py_test` macro — repo-specific Bazel macro
- Never amend pushed commits — repo policy (could be either way)

## Prefer references over inline context

When docs need to convey knowledge available elsewhere, reference the source rather than restating it. Prescribe agents to fetch context on demand (WebFetch a URL, invoke a skill, read a file) instead of embedding the full content.

Good references: GitHub issue/PR URLs, upstream doc URLs, file paths with `@`-transclusion or `<path>` links, skill invocations (`/skill-name`).

This keeps docs small and avoids staleness from duplicated content. The agent can always fetch the authoritative source when it needs the detail.
