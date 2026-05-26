# Debundler — Open Work Items

Forward-looking gaps in the Rust debundler. Items are written to be removed
once closed; this file is not a changelog.

## Excalidraw live-browser smoke

Build an open-source live-browser smoke test for the debundler against
a Bazel-managed Excalidraw bundle. The motivation: when a debundler
issue surfaces against a private upstream corpus (proxy crash, AST
corruption, missing chunk, emit shape regression, optimisation
behaviour bug), reproducing the failure on Excalidraw lets us share
the repro in a public bug report, write a regression test that runs
in ducktape's open CI, and avoid leaking proprietary upstream bundle
detail. Excalidraw is open-source and broadly representative of "real
React + vendored chunks + dynamic imports + service worker."

### Bundle build

Use a Bazel-managed Excalidraw build. Two viable paths:

- **Pull a prebuilt deploy** (snapshot a specific `excalidraw.com`
  publish). Requires keeping the snapshot fresh enough that
  upstream's auxiliary endpoints (if any) still work. Easier to
  bootstrap.
- **Build from source under Bazel** — Excalidraw's `excalidraw-app/`
  builds with Vite; reproduce that build (npm + vite via
  aspect_rules_js, or via a `genrule` shelling to npm) and feed the
  output into the pipeline. More work upfront, but the bundle is
  reproducible from a single git pin and we control the optimisation
  level / minifier settings.

Either way, the build configuration must produce a realistic
production bundle: minify on, identifier renames,
production-tree-shaken, real chunk-split boundaries. A development
build (with un-mangled names and source maps inlined) won't exercise
the debundler's RE-relevant code paths.

### Spec scope

Not the round-trip minimum — the spec should exercise realistic-ish
module extraction and rename paths, the same shape a private-corpus
spec runs. Concretely:

- `apply_vendor_annotations` + `swap_vendor_chunks` over a couple of
  Excalidraw's actual vendor chunks (React, Roughjs, Pointers, etc.)
  so vendor-swap edge cases (`named_from_default`,
  `named_from_module_default`, default-only, JSON-default) get covered
  on a real bundle, not only synthetic fixtures.
- `materialize_logical_modules` over a handful of pre-identified
  Excalidraw source modules — pick ones whose shape is recognisable
  in the compiled output (a clearly-bounded React component, a pure
  geometry helper, a state slice). Goal: prove the materialiser
  recovers approximately the right symbols/files from a real
  scrambled bundle.
- A small set of `logical_modules` rename entries on identifiers
  visible in the compiled output. Goal: exercise the rename pipeline
  at realistic aggressiveness.
- `emit_browser_harness`, relying on the always-on
  `rewrite_chunk_entry_specifiers` transform, so the output is a
  runnable app the live proxy can serve.

The exact module list / rename list is part of the implementation —
pick stable shapes that are unlikely to drift wildly when Excalidraw
upgrades. Stale picks become a self-test: if the materialiser fails
to find them, that's a real signal (either the bundle moved or our
matchers regressed).

### Smoke target contract

- runs `bazel test //devinfra/js/debundle/excalidraw:load_test` (or
  similar);
- builds the Excalidraw bundle through the shared `debundle_pipeline`
  rule (<pipeline.bzl>);
- starts the live-proxy binary against the resulting harness;
- drives a headless Chromium through the proxy, asserts:
  - no failed asset requests,
  - no console errors,
  - the canvas toolbar is visible (e.g. `[data-testid="toolbar"]`
    or whichever stable selector Excalidraw exposes),
  - a small interaction works (click the rectangle tool, click on
    the canvas, verify a shape was added — proves the React app is
    reactive after debundle).

### Hosting

Self-hosted, no MITM. Private-corpus smokes generally have to MITM the
live host because their auth/data is server-side; Excalidraw runs
entirely in the browser, so a self-hosted bundle is a fully working
app. Self-hosting removes the network dependency and CDN-rotation
flakiness (the test stays green even when excalidraw.com is down) and
matches the "reproduce against Excalidraw" workflow goal — a public,
deterministic smoke that doesn't depend on third-party uptime.

### Workflow rule

When a private-corpus debundler issue is tractable on Excalidraw too,
prefer landing the regression test on this Excalidraw target (or a
smaller minimised e2e under `devinfra/js/debundle/e2e/`) rather than
only fixing it behind the private repo. The latter loses the
public-CI signal and the public-bug-report leverage.

## Logical materialization breadth

The current `materialize_logical_modules` covers top-level
function/class/variable declaration movement and explicit owner assignment.
Still to do:

- Full lowering matrix: binding placement reports, attached side-effects,
  staged-shell edge cases beyond the focused fixture.
- Owner-fragment modeling parity for nested declarations and re-exports.
- Keep new analysis tooling on the existing owner graph and embedded atomic
  DAG side outputs; do not add parallel selected-owner cache formats.

## Materialize-stage hot-loop optimizations

A 2026-05-26 profile (consumer
`<spec>/profile_reports/2026-05-26-post-arch-cleanup/README.md`)
moves the picture forward from the 2026-05-10 / 2026-05-20 reports.
Headline shift: post-arch-cleanup (A–F + ChunkPlanBuilder
extraction + overlay realizability + prepare-chunks visit fusion +
ESM simulator kludge fix), `materialize_logical_chunk` is down
from 41.63% Children % (2026-05-10) to **8.93%**, and the
`build_owner_graph_report` 22.54 s hotspot is gone from the top
hits. The per-candidate hot-loop wins (binding caches, BTreeMap →
HashMap, typed edge IDs, realizability overlay, IR cleanup) are
visibly landed.

The current remaining plan, ordered by leverage:

1. **Replace the inner scan in
   `lowering::exports::trim_dead_named_specifiers`.**
   This is the new top hot loop: **12.62% Children %** under
   `lower_chunk` (>20% of `lower_chunk`'s own time). The shape is
   `Vec<NamedSpecifier>::retain(|spec| consumers.any(|c| c.name ==
spec.name))` — O(N×M) scan, with each comparison going through
   `swc_atoms::Atom::as_str` → `hstr::Atom::as_str` /
   `TaggedValue::data` (`Iterator::any::check::{{closure}}` was
   5.93% self, 9.63% Children %). Convert the inner `any` to a
   precomputed `HashSet<&Atom>` (or `HashSet<JsWord>`) of live
   consumer names materialized once per chunk before the retain.

2. **Stream / shrink `artifact::write_tree_reports`.**
   6.42% Children %; the deepest cost is serde_json pretty-print
   of `DirectoryManifestIndex` / `DirectoryBoundarySummary` under
   `artifact::write_json` (2.79% Children %). Same shape as the
   previously-tracked "compact owner_graph.json writes" item —
   stream JSON directly to disk or shrink the on-wire shape.

3. **`vendor::strip::sweep_unreachable_top_level`.**
   6.40% Children %, newly visible in the top tier. Likely
   amenable to indexed reachability or per-chunk caching, on the
   same theme as item 2 from the older plan
   (reachability allocation).

4. **Use the overlay realizability fast path where hypothetical moves remain.**
   Candidate-style evaluation should use `RealizabilityIndex`'
   `verdict_after_moving_owners_touching` where possible instead of the
   rollbacking push/scope path. This avoids mutating the maintained quotient
   during repeated what-if checks. (Carried forward from
   2026-05-20; still applies wherever push/scope rollbacks are
   reachable.)

5. **Keep harness emission proportional to the work.**
   `emit_browser_harness` is at 11.15% Children % — down from
   ~53% wall (18.78 s / 35.15 s) in the 2026-05-20 baseline. Most
   of what remains (7.50% Children %) is `materialize_artifact_scripts`
   → `write_tree_reports`, i.e. report writes (item 2), not the
   harness JS emission itself. Split browser-harness generation
   from non-browser runs where practical, and avoid recopying
   unchanged non-JS assets.

Older profile follow-ups that still apply:

1. **AST visit churn in `prepare_js_chunks`.** SWC parser / lexer /
   `visit_children_with` still occupy ~10–15% summed across many
   sub-2.5%-self entries (`parse_member_expr_or_new_expr_inner`
   2.19% self; `parse_subscript` 1.80%; `Expr::visit_children_with`
   1.57%; etc.). No single parser symbol is over the priority
   threshold; revisit after items 1–3.

## Graph pass performance and module boundaries

Tighten before the next large peel loop:

- Keep stage telemetry complete (index build/rebuild, fused AST analysis,
  purity, owner-graph construction, atomic-DAG construction, quotient
  construction, validation, lowering, output writing) — useful durations
  should land in the emitted reports.
- Move repeated timing helpers into one shared Rust module once a second
  pass needs them outside the current local macro sites.
- Add focused regression coverage for `ArtifactIndexes` rebuild boundaries
  as more structural artifact mutations are optimized.
- Profile the debundle action around `materialize_logical_modules`
  and `rename_vendor_exports`; avoid whole-graph clone/rescan patterns
  where a graph pass or indexed lookup can answer the same question.
- Consider changing per-chunk `file_records` from an ordered vector of
  `(file, role)` pairs into a typed map if the output consumers do not
  depend on order. Keep the manifest easy to diff and easy to read.

## Factorize / atomic-DAG docs drift

- **"Factorize" remains overloaded.** Broadly, factorization/assembly
  produces the authoritative owner partition (`factor_assembly.rs`),
  while `peel/factorize.rs` produces advisory planner proposals from
  the serialized atomic DAG (surfaced as `debundle modules propose`).
  Keep docs explicit about which one they mean.
- FACTORIZE.md is deleted; its content is folded into `docs/design.md`
  §"Layered mental model" + §"Factor assembly inside `debundle run`".

## Analysis semantics breadth

The focused fixtures exercise the core access model. Validate or extend
behavior for:

- Class fields, static blocks, computed keys, nested function bodies.
- Replayable side-effect attachment.
- Top-level side-effect classification across uncommon initializer shapes.

## Cross-module / imported-binding purity (recursive purity Part 3)

`ChunkCodeGraph` tracks chunk-local function/PlainData purity within
a single source chunk. Imported callees from a different source chunk
(vendor chunks, vite chunk splits) fall through to `unknown_call`
because the importer has no per-function purity for the exporter's
bindings. The downstream cost is each cross-chunk pure-helper needing
a `purity: pure` spec hint in the consumer repo even though its body
would classify pure if it were chunk-local.

Sketch (deferred until residual hint set is dominated by cross-chunk
shapes):

- Per-chunk analysis emits a side-output manifest with each chunk-top
  `Function` and `PlainData` binding's classification.
- When analyzing chunk B that imports `helper` from chunk A's output,
  read A's manifest and seed B's `ChunkCodeGraph` bindings with A's
  per-name verdict.
- Soundness gate: only admit cross-chunk facts when the importer's
  import-specifier names match A's exported chunk-top binding shape
  (e.g. `import { helper }` matches `export const helper = () => …`
  but not a re-export from elsewhere).

Today only one residual cluster in a representative bundle
spec sits cross-chunk (MobX wrapper bindings tracked by the non-emitting
binding-patch stream) and that cluster is the legitimate user of the spec-side
`purity: pure` override — genuinely-impure-but-init-safe vendor
shape, not a pure-by-derivation chain. So Part 3 isn't load-bearing
yet. Land if a future snapshot grows a cross-chunk pure-helper
chain.

Context: <consumer-repo notes on purity recursion>
"Part 3 — cross-module purity" section.

## Corpus breadth

Current passing surface is centered on small synthetic fixtures and the
mock browser bundle. Extend to:

- Large vendor-heavy graphs.
- Unusual dynamic import forms.
- HTML/runtime asset layouts outside the current corpus.

## Rename pipeline: collect → validate → execute _once_

The naturalizer / lowerer currently mutates identifiers in place across
several independently-discovered passes and lets every downstream consumer
(import planning, cross-module binding lookup, fact collection,
source-map fragment emission, export tables) read whatever name happens
to exist when _it_ runs. PR #1627 (`object_literal_import_collapse_test`,
fixed by e0b9c7f) and PR #1631
(`object_literal_return_shorthand_drops_import_test`, fixed by the
heuristic-rename reverse-lookup at
`lowering/plan_references.rs::plan_module_reference_needs`) are both symptoms of
the same shape: a rename happened in one layer and a downstream layer
keyed off the wrong-era name. Each fix has been a localized defensive
patch on the consumer side, which leaves the same trap waiting for the
next consumer that doesn't yet know about the rename.

The proposed architectural fix is a single **collect → validate → execute
(once)** rename pipeline:

- **Collect**: every rename contributor submits _intents_ into a single
  buffer instead of mutating the AST. Contributors include explicit
  spec-specified renames, naturalizer heuristics (return-object alias
  inference, shorthand-collapse readback, future readable-name
  autonaming), import-induced renames (`{ sA as propKeyA }`),
  collision-resolution renames, and chunk-level renames produced by
  factorize. Each intent is `(scope, original_name, new_name, reason,
priority, invariants_it_assumes)`.

- **Validate**: resolve conflicts deterministically before any AST
  mutation. Priority order is explicit > import-induced > heuristic.
  Surface contradictions (`sA → propKeyA` _and_ `sA → propKeyB` in the
  same scope) as hard errors at validation time, not as silent
  last-write-wins behavior at AST mutation time. Output is a stable,
  read-only mapping `(scope, original_name) → final_name` and the
  inverse `(scope, final_name) → original_name`.

- **Execute once**: one pass applies the resolved mapping to the AST
  _and_ updates every fact table (`runtime_imports`, `referenced_idents`,
  export tables, source-map fragments, cross-module binding indexes) in
  lockstep, keyed by the original name. After execute, no later pass
  invents a rename — every consumer that needs to bridge between
  pre-rename and post-rename names consults the same finalized mapping.

Direct consequence: the family of "X-layer renamed it, Y-layer didn't
notice" bugs collapses to one architectural seam. The
`plan_module_reference_needs` reverse-lookup that fixes #1631 becomes
dead code (the final mapping makes both the body AST and the
`runtime_imports` map agree on a single set of names before planning
runs), and similarly `normalize_relative_module_specifier` from the
#1627 fix could rejoin a normal path-building step rather than living as
a defensive sanitizer at the usage site.

Prerequisite work before designing the pipeline:

1. Inventory every current rename contributor in `lowering/` and
   adjacent files. Examples already known:
   `collect_return_object_alias_renames` and
   `collect_naturalization_renames_from_function` in
   `lowering/naturalize.rs`; `RenameAndShorthandNaturalizer` and
   `naturalize_object_literal_shorthand` in `lowering/visitors.rs`;
   `disambiguate_import_locals` in `lowering/util.rs`; the chunk-level
   `chunk_renames` map that flows out of factorize; and any
   collision-resolution code path that mutates `module_import_renames`
   at the orchestration site. Capture each contributor's _kind_
   (explicit / heuristic / collision / chunk-level), _scope_ (function
   / module / chunk / cross-chunk), and _current side-effect surface_.

2. Inventory every downstream consumer that today reads identifier
   names off the AST or off pre-rename fact maps. Same call sites that
   currently need defensive bridging.

3. Decide on the scope model. Per-function naturalizer renames don't
   need to be visible at chunk scope; chunk_renames don't need to
   reach per-function naturalizer collection. The intent buffer should
   reject cross-scope writes by construction.

4. Design must not block on landing #1631-style defensive fixes — those
   should land case by case as they're discovered, with this TODO
   updated to note when a defensive patch becomes architecturally
   redundant. Removing the defensive patches is part of the
   pipeline-landing cleanup, not the architecture work itself.

Likely multiple PRs.

## RenameLedger (PR2) open questions

Before implementing the "Rename pipeline: collect → validate →
execute _once_" architecture above, pin these three design questions:

1. **Conflict policy for same-priority heuristic disagreements.** When
   two heuristic contributors propose conflicting renames at the same
   priority (e.g. `collect_return_object_alias_renames` says `sA →
propKeyA` and `collect_naturalization_renames_from_function` says
   `sA → propKeyB`), does the ledger panic at seal citing both
   submitters, or silently suppress the lower one? Default proposal:
   panic loudly, with both contributors named in the error — silent
   suppression is the trap PR2 is meant to close.
2. **Disambiguation name minter.** `disambiguate_import_locals` today
   appends `_1`, `_2`, ... suffixes until a free name is found. When
   that becomes a `RenameLedger` method (so the ledger owns "what
   names are taken in this chunk"), does the scheme stay as-is, or
   switch to something more readable (`name_from_module`, etc.)?
   Default proposal: keep `_N` scheme; readability is a separate
   concern best handled by a later naturalizer pass.
3. **Structural mutations during COLLECT.** Today
   `materialize_logical_modules` moves declarations between modules
   in-place during the collect phase. Tighten the contract to either:
   - "no structural moves between seal and execute" (pragmatic — most
     moves already happen pre-seal, and the type-level barrier
     `&Module` in non-execute passes lands cleanly), or
   - "all structural moves pre-COLLECT" (cleaner architecturally but
     requires reordering the materializer to compute a final body
     order before any rename intents are submitted).

## Reinvented-wheel audit findings (recorded, no immediate action)

A high-level audit (see chat session
01VmZmgJmMUXFECyQGtsrBMd, after the `ModuleQuotient` Deref-newtype
refactor) surveyed the debundler for places where we hand-roll
something a stdlib / petgraph / swc helper provides. Most findings
came back "appropriate / not actually a reinvention". The ones
below are recorded for visibility, with the explicit decision
that they're not worth doing right now.

### `ChunkTable` interner stays

`ids.rs`'s `ChunkTable` maps chunk paths (`String`) → dense
`ChunkId(usize)` handles. Superficially looks like the same shape
as the retired `BindingTable`, but the value proposition is
different:

- `ChunkId(usize)` is `Copy`, 8 bytes — flows through ~106 sites
  by value. Swapping to `Atom` (the `BindingName → Id` migration's
  natural answer) loses `Copy` semantics: `Atom` is `Clone`-not-
  `Copy` (Arc-backed), forcing `.clone()` at every handle-passing
  site.
- swc's `Atom` global interning is tuned for short repeated JS
  identifiers, not 30-character file paths. The interning win
  evaporates for the actual chunk-key shape.
- The dense indexing is used by storage like
  `Vec<JsChunk>`-indexed-by-`ChunkId.0` and by stable round-trip
  ordering in `ChunkBundle.chunk_order`.

Keep `ChunkTable` as-is.

### `OwnerGraph` hand-rolled CSR stays

`graph.rs`'s `OwnerGraph` stores `Vec<OwnerEdge>` plus
`Vec<Vec<OwnerEdgeId>>` (out_edges / in_edges) CSR adjacency. This
isn't directly replaceable by petgraph because the design
intentionally carries **multiple reasons per `(from, to)` pair as
separate edges**, deterministically sorted by
`(from, to, reason.kind, statement_ordinal, binding)` for stable
report output. petgraph's `DiGraph`/`DiGraphMap` would force a
single edge per pair or push the multi-reason list into a single
edge weight (which is what `ModuleQuotient` does at the quotient
level, where dedup is wanted). Keep the owner-level CSR.

### `LazyBoundary` + `lazy_visit_*` helpers stay

`facts.rs`'s `LazyBoundary` trait and `descend_lazy` /
`lazy_visit_function` / `lazy_visit_class_member` family aren't a
reinvention of `swc_ecma_visit::Visit` — they're a layer **on top
of** `Visit` that lets the collector track lazy vs eager scope
context (function bodies, class instance fields, getter/setter
bodies) without each visitor re-implementing the boundary logic.
The visitor merge (#1671) already collapsed the per-collector
boilerplate to one shared collector that uses the helpers; no
further win available without a generic-walker macro that wouldn't
read cleaner than the current shape.

### Manual `VisitMut` impls in `lowering/` stay

`IdentifierRenamer`, `RenameAndShorthandNaturalizer`,
`ShorthandNaturalizer`, etc. each implement custom `VisitMut`
visitors. These are domain-specific transformations swc doesn't
expose — the right use of swc's `VisitMut` trait, not a wheel
reinvention.

### Dense-int newtypes stay

`OwnerId`, `OwnerEdgeId`, `StatementOrdinal`, `LogicalModuleIndex`,
`ModuleId`, `ChunkId` are all `pub struct Foo(pub usize)` newtypes.
Crates like `typed_index_collections` / `slotmap` would provide
marginal type-system safety on `Vec` indexing, at the cost of a
dep + per-storage-site conversion. Plain newtypes are standard
compiler-IR practice; keep.

### String-based ID round-tripping (`"owner:N"`, `"logical:N"`) stays

`reports.rs`'s `owner_key` / `module_key` / `module_id_from_key`
serialize typed IDs to human-readable strings for JSON reports
and parse them back. Reasonable for the
serialization-boundary use; not gymnastics.

### `HashMap` + post-hoc `sort()` patterns

~40 sites collect into a `HashMap` / `Vec` and `.sort()` for
deterministic output. `BTreeMap` / `IndexMap` would eliminate
the sort at the cost of slightly different iteration semantics.
Most sites are one-shot init / report generation (not hot path);
worth converting a few specific report-generation sites to
`BTreeMap` for semantic clarity (the sorted order is the point,
not an afterthought), but no urgent action.

## CLI gaps found while surveying real specs

Rough edges hit during a real-corpus survey (2026-05-26, the real-corpus
web spec via the new top-level CLI). Each is a small `bindings ...` /
`modules ...` addition; nothing structural.

- **`modules list --empty` shows every empty module, including ones
  preserved by a `comment:`.** The actually-actionable subset is
  "empty AND no comment" — i.e. the auto-deletable set. Add a
  `--auto-deletable` filter (or expose `--empty --no-comment`) so
  `debundle modules list --auto-deletable --format json | jq -r '.modules[].path' | xargs rm`
  is the safe one-liner for sweeping drained cruft.
- **`modules list` member-count is the only signal of module size**;
  there's no quick way to spot a module whose member count is right
  but whose `anonymous_statements:` count is huge (the residual case).
  An optional `--with-anonymous` flag exposing that count alongside
  `member_count` would let `debundle modules list --residual --with-anonymous`
  surface the residual sentinel's anonymous-statement drift over time.
- ~~**No `debundle cycles ...` namespace.**~~ Shipped as
  `debundle gate {list,describe,cut}` (the unit is the blocking SCC,
  not a cycle — a single SCC can carry exponentially many simple
  cycles, so the CLI exposes the cut as a primitive but deliberately
  not a `cycle list`). `cycles.json` is now the trimmed wire shape
  `[{id, modules, cut}]`; `describe <id>` re-derives the per-edge
  evidence on demand from `owner_graph.json` + the SCC's module set,
  matching the per-rejection stderr summary the gate emits today.
