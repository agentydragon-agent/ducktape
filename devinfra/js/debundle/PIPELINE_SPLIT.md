# Pipeline-split (tombstone)

This document used to describe a Stage A / Stage B split where Stage B
would be a separate Bazel action consuming Stage A's cached JSON
artifact for the materializer. **That plan was abandoned.**

The structural decomposition that did land — a clean Stage A composer
(`stage_one/mod.rs::compute_stage_one_analysis`) that runs parse +
facts + owner_graph + atomic_units behind a single named call — is
still in place and is fine. What was dropped is the cross-process
piece: caching Stage A's output to disk and reading it back from a
materializer running in a different process / Bazel action.

## Why

Re-parsing in Stage B was always cheap (~5–10s on gaffer-scale spec
edits, dominated by parse), and Bazel can cache at the rule's coarser
granularity for the same effect without the per-chunk artifact dance.
The honest cross-process path requires a SWC hygiene-snapshot replay
(`Mark::fresh(parent)` / `apply_mark` sequence serialized and replayed
in Stage B's fresh `Globals` before any `Id` deserializes); that's
real engineering for a small win.

The cache value users actually feel comes from the query-CLI surface
(`atoms`, `coverage`, `describe`, `show-source`, `scc`, `cluster`,
`modules propose`, `gate {list,describe,cut}`) over the existing
Atom-only JSON reports (`owner_graph.json`, `atomic_units.json`,
`cycles.json`, `atomic_unit_conflicts.json`). That surface is already
cross-process safe today and is the active development direction.

## Where the residuals live now

- The on-disk sidecars under `reports/tree/<chunk_id>/chunk_analysis/`
  (`facts.json`, `atomic_units.json`, `manifest.json`) are demoted to
  **in-process debug artifacts** — humans inspecting during a
  materializer run; no separate-process consumer. See
  `WIRE_FORMAT.md` §"The exception: `facts.json` carries
  `SyntaxContext`" for why `facts.json` is same-process-only.
- The `swc_ecma_ast/serde-impl` feature in `MODULE.bazel` was kept as
  plumbing for an `ast.json` artifact that was never written; it can
  be dropped whenever someone cycles on the build.
- The `compute_stage_one_analysis` composer stays. Its value is
  structural readability, not cross-process caching.

## Replaced by

- `WIRE_FORMAT.md` §"Cross-process scope: not a goal" — the live
  rationale + rejected-alternatives list.
- `ARCH_REVIEW_2026_05.md` — the project's open architectural
  backlog.
