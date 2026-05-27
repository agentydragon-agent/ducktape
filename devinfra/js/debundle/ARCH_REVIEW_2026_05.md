# Debundle crate — architecture review (May 2026)

Reviewed against `01c149496` on branch `feat-arch-review-2026-05`. Read on top of `docs/design.md`, `CODE_REVIEW.md`, `AGENTS.md`. Findings are at the design/architecture level; small style points already covered by `CODE_REVIEW.md` are not repeated.

> **Status.** Items handled since the original review have been removed; what remains is the open backlog. The cross-process Stage B plan was also abandoned — items in this review that assumed cross-process caching of Stage A artifacts have been dropped along with it. Narrative + rejected alternatives: `docs/lessons_learned/cross_process_stage_b.md`.

## Open backlog

The original executive-summary item resolved with the `EdgeRole` enum. Remaining work is the section-by-section backlog below.

## Ad-hoc wiring + pipeline-state passing

### `compute_stage_one_analysis` is itself an example of the right direction

`stage_one/mod.rs:72` is a genuinely clean composer. The reason it works is that **the boundary at Stage A is well-defined**: the inputs and outputs are clear, the composer's only job is to call `analyze_chunk` then `compute_owner_graph_and_units_with`. The Stage A composer is exactly the shape every other composite operation in this crate should look like, and is the strongest design point in the recent refactor.

That said, `stage_one/mod.rs:46` notes "Why a free function with no struct fanout" — but the doc-string concedes that the side-effecting interleaving (redundant-hint stderr, top-level-await `bail!`, atomic-unit-rebind folding) **still happens inline at the materializer**. Stage A _separation_ isn't done; the composer is a function-level renaming. Folding those paths into the composer's owners is the next refactor in this area; it cleans up the materializer body even though there's no longer a cross-process consumer waiting on the boundary.

## Duplicated calculations

### `tarjan_scc` over the module quotient: residual walks

After the Lemma-2 unification (`da7e928e2`) and `RealizabilityVerdict::scc_partition()` introduction (`7d2d79bc9`), 5 module-quotient Tarjan walks collapsed into 2:

1. `check_realizability` materialises one SCC partition and exposes it on the verdict; `validate_factorization` and `reports::build_quotient_scc_reports` consume it instead of re-walking.
2. `ChunkFactorization::build_with` caches a `dep_graph_sccs` field used by the materializer/emitter path.

Remaining legitimate walks (different graphs): `validation.rs:437` (FAS iteration, intrinsic), `graph.rs:884` (`promote_at_init_calls` closure fixpoint), `atomic_units.rs:103` (constraining-edge owner SCC).

**Open follow-up.** The two surviving module-quotient walks (verdict-time + factorization-build-time) compute the same partition for different consumers; structurally consolidatable behind a wider API change, but not urgent and not on a hot path.

### `OwnerGraph::from_report` rehydration carries `declared: BTreeSet::new()`

`graph.rs::OwnerGraph::from_report` rehydrates an `OwnerGraph` from its JSON wire shape (`OwnerGraphReport`), but with `declared: BTreeSet::new()` because the report doesn't carry per-node binding sets. The original ARCH_REVIEW note assumed this function was dead — the intended consumer was a hypothetical cross-process Stage B planner — but two production callers ship today:

1. `cli/module.rs::gate_post_edit_partition` — the CLI realizability gate that runs after every spec edit. It deserializes `OwnerGraphReport` from disk, rehydrates via `OwnerGraph::from_report`, then runs the cycle check before letting the edit land. This is the cross-process Stage B in everything but name — just synchronously inside the CLI process rather than as a separate daemon.
2. `peel/quotient.rs::QuotientGraph::from_report` — kernel constructor used by every `from_report_with_partition*` entrypoint and the quotient integration tests.

What's actually worth resolving here is the structural shape: callers re-hydrate with an empty `declared`, which means downstream code that touches `OwnerNode::declared` will silently see "no bindings" instead of the truth. The right fix is either (a) extend `OwnerGraphReport` to carry per-node `declared`, or (b) split into a thin reconstruct-from-graph-shape function that doesn't pretend `declared` is meaningful. Today's signature is a hazard — callers can ask for binding sets and get an empty answer. See also `docs/lessons_learned/cross_process_stage_b.md` — the cross-process variant didn't ship, but the in-process rehydration path did.

## Library-vs-hand-rolled

### `swc_ecma_visit` usage is reasonable

Searched for hand-rolled AST walks that should have been visitors. Found only the explicit top-level iteration in `facts/mod.rs` (`match ModuleItem::Stmt(Stmt::Decl(...))` etc.) which is appropriate because the analysis is fundamentally a top-level-only iteration with structured per-statement output. Subordinate visits (binding-target recording, reference collection, identifier scanning, body-purity) all use `Visit` / `VisitWith` correctly. No fix needed here.

## Encapsulation + module boundaries

### `OwnerGraph` is a struct with public fields

`graph.rs:234`. Five public fields: `nodes`, `edges`, `out_edges`, `in_edges`, `callee_edges`. Every consumer iterating the graph reaches `owner_graph.iter_nodes()` / `iter_edges()` (good), but the fields themselves are `pub` so consumers can also `for edge in &owner_graph.edges` or `for slot in &owner_graph.out_edges[id.0]` (and they do — `realizability.rs:111`, `validation.rs:260`, etc.). This makes the invariants on the CSR structure ("`out_edges[id.0]` lists every `OwnerEdgeId` whose `from == id`, in insertion order") implicit on every reader.

`CODE_REVIEW.md` notes the same issue (P3 "OwnerGraph exposes internal CSR structures"). At architecture level: the right encapsulation is `OwnerGraph` exposing only `iter_nodes`, `iter_edges`, `successors(id) -> impl Iterator<&OwnerEdge>`, `predecessors(id) -> impl Iterator<&OwnerEdge>`, `node(id)`, `edge(eid)`. Today's `pub nodes: Vec<OwnerNode>` invites every consumer to write its own adjacency walk.

### `ModuleQuotient` Derefs to `petgraph::DiGraphMap`

`graph.rs:495`. The inner field is `pub(crate)` after `073493e6d`, but `Deref` and `DerefMut` still expose the full petgraph mutation API to every in-crate caller. No consumer needs the mutation surface (`validation.rs` and `reports.rs` only read). Replace the `DerefMut` impl with named accessors (`all_edges`, `edge_weight`, `contains_edge`, `has_init_order_constraining_edge`) and keep the explicit constructor `build_module_quotient` as the only mutation path. The `Deref` for read-only access can stay if it pulls its weight.

### `ChunkFactorization` is yet another per-chunk IR/report layer

`chunk_factorization.rs:30`. `ChunkFactorization` holds `analysis: Arc<ChunkAnalysis>` plus partition + dep_graph + linker_order + maps. Then `validate()` returns a `FactorizationReport` (`chunk_factorization.rs:180`) which is yet a third "report" type alongside `ChunkAnalysisReport` and the IR `ChunkAnalysis`. The naming hierarchy is:

```
ChunkAnalysis (IR)     // chunk_analysis.rs
  ↓ wrapped in
ChunkFactorization     // chunk_factorization.rs (IR + partition + dep_graph)
  ↓ validate() →
FactorizationReport    // validation.rs (cycles + atomic_unit_conflicts + linker_order)

ChunkAnalysisReport    // artifact.rs (the JSON per-chunk report stub)
  ↓ from_analysis() →
ChunkManifest          // artifact.rs (analysis report + decomposition + metrics)

OwnerGraphReport       // reports/schema.rs (the JSON view of the typed OwnerGraph)
```

Six distinct types in the orbit of "stuff a chunk analysis produced" (after the `ChunkAnalysis`/`ChunkAnalysisReport` split). A reader still can't tell from the name alone which one carries which data without grepping. Some of this is unavoidable (the JSON-wire / typed-IR split is real), but the layering of `ChunkAnalysis` → `ChunkFactorization` → `FactorizationReport` could plausibly collapse to two: an IR with optional partition state + a derive-to-report adapter.

### `pub(crate)` on internals is broad

`OwnerGraph` fields are `pub(crate)` not `pub`, which is the right scope; but `pub(crate)` means every module in the crate can mutate them. With `RealizabilityIndex` holding owner-edge references, `IncrementalQuotient` maintaining bucket state derived from the owner graph, and `OwnerGraph::from_report` reconstructing it from JSON, the _crate-internal_ invariant surface is large. The `no_consumer_calls_is_cross_module_at_init_promotion_directly` test (`graph.rs:1637`) is a tell — when a project starts adding _grep-based invariant tests_ to keep parallel call sites in sync, that's the signal that the type system isn't carrying the invariant.

## Name overloading

Watch out for:

- **`ChunkFactorization` vs `ChunkAnalysis`**: both are per-chunk IR; the difference is whether the partition is applied. Could be `ChunkAnalysis` (no partition) vs `FactorizedChunk` (partition applied) and the meaning would be more obvious.
- **`ChunkAnalysisOptions`** (`spec.rs:104`) is a _spec-side_ per-chunk knob holder; **`OwnerGraphOptions`** (`graph.rs:21`) is the _graph-build-side_ knob holder; the materializer copies one field from the former into the latter (`lowering/materialize/mod.rs:435–439`). The duplication of "options" types with the same one field (`dataflow_aware_s_chain`) is a sign that the type is doing too little — fold them together. (The original motivation for keeping them separate — Stage A cache-key independence — went away when cross-process Stage B was dropped.)
- **`linker_order` (`Vec<String>` in `FactorizationReport`)** vs **`linker_order` (`Vec<ModuleId>` in `ChunkFactorization`)** vs **`chunk_linker_order` (`BTreeMap<ModuleId, usize>` in `graph.rs`)** — three different shapes for "the toposort of the constraining-edge graph", differing in element type and whether it's "list" or "map (position lookup)". Pick one canonical type, derive the others.
- **`UnrealizableScc` (`realizability.rs:50`)** vs **`CycleReport` (`validation.rs:35`)** vs **`QuotientSccReport` (`reports/schema.rs`)** vs **`AtomicUnitConflict` (`factor_assembly.rs:35`)** — four representations of "the spec is unrealizable, here's why" with subtly different fields. `UnrealizableScc` carries `constraining_owner_edges`; `CycleReport` carries `cut` (a minimum cut) + `evidence`; `QuotientSccReport` carries `module_edge_ids` + `constraining_module_edge_ids`. Two of these contain the same data ("the modules in the SCC + the edges in the SCC"), with the cut/evidence/min decoration added by the validator. The right shape is one core type with optional decorations, not four parallel structs.
- **`AnalysisHints`** (`facts/mod.rs`-exported) lives in `facts`, but holds spec-derived data (`declared_pure`, `declared_pure_new`, `declared_pure_members`, `known_effects`). The data is spec-shaped, the type is in facts. Today's pipeline collects the hints before the Stage A composer runs — fine for the in-process flow — but the "Stage A is spec-independent" framing in `docs/lessons_learned/cross_process_stage_b.md` always rested on `AnalysisHints` magically not counting as spec. With cross-process Stage B dropped, the framing is no longer load-bearing, but the module-vs-data-shape mismatch (spec-shaped data living in the facts module) is still ugly and worth a re-home.

## Algorithmic clarity (realizability gate, atom detection)

### The gate is _more_ coherent than the maintainer fears, but its docs make it look like a stack of patches

The realizability gate's actual algorithm, read carefully, is:

> Build the canonical constraining-edge view of the I-graph; the gate accepts iff (a) Tarjan on the constraining-edge view has no multi-module SCC, and (b) for every multi-module SCC in the full I-graph that has at least one constraining edge, the ECMA-262 Phase-2 simulator (rooted at residual, with residual's imports sorted by `source_import_position` and every other module's by `linker_position`) yields a post-order with `post_order[target] < post_order[source]` for every constraining edge.

That's one algorithm with two passes. Pass 1 is a cheap necessary condition (mutual at-init cycles can never be rescued by reordering); Pass 2 is the precise condition (the runtime DFS-simulator decides asymmetric cycles). The 2× Tarjan is structural to the algorithm, not patchy. **This is fine.** The docs/design.md theorem reads cleanly.

~~What's _patchy_ is the `EsmEvaluationSimulator::from_adjacency` (`realizability.rs:306`) constructor: it exists only because the overlay path (`IncrementalQuotient`) has its edges in a different shape than the canonical edge set, so `from_adjacency` rebuilds a fake `ChunkConstrainingEdgeSet { edges: empty_map_for_each_constraining_pair, i_successors }` and feeds it to `build`. This is two structurally identical inputs that diverged because two callers had different sources; the right shape is for `build` to take the two adjacency maps directly. Today's "construct fake edges map" is a kludge to fit the constructor.~~ **Resolved in `944631010`**: `EsmEvaluationSimulator::build` now takes `(i_successors, constraining_pairs, residual)` directly; `from_adjacency` and the fake `ChunkConstrainingEdgeSet` construction are gone. Both the canonical-edge-set path (`check_realizability`) and the overlay path (`IncrementalQuotient::build_simulator_from_scratch`) thread their adjacency maps in unchanged.

### Atomic-units classification has two paths but only one is wired

`atomic_units.rs::compute_atomic_units` is the structural-atom detector (SCCs of the constraining-edge owner graph). `factor_assembly::detect_unit_conflict` is the "did the spec split a unit?" detector. The structural atoms are computed once per chunk (in `compute_owner_graph_and_units_with`), passed through `OwnerGraphAndUnits` to the materializer and into `ChunkFactorization`. Clean — this is the right shape.

Spec-induced atoms (the SCCs of `I ∪ S` under the quotient) are NOT precomputed; they emerge from the realizability primitive. docs/design.md §"Two classes of atom" labels them as a distinct concept. After `7d2d79bc9` the verdict exposes the SCC partition and `validate_factorization` consumes it instead of re-walking; the residual walk lives on `ChunkFactorization::dep_graph_sccs` for the materializer/emitter path (see §"Duplicated calculations" for the open consolidation).

## Test-vs-spec drift

### `#[ignore]`d tests are clean

`e2e/purity_test.rs` is the only file with `#[ignore]`d tests, and each names an explicit "Step D"/"Step E in the purity-desiderata follow-up plan" reason. These are documented future work, not drift. Good shape.

### "v2 hypothesis was wrong" — found one comment

`graph.rs:1322` documents that `chunk_source_import_order`'s `None`-after-`Some` clause is "kept for robustness against future filter changes that might admit non-constraining members" — i.e. defensive code for a hypothesis that hasn't been validated. That's mild; not real drift.

### One TODO mismatch

`TODO.md` mentions a `module merge` task (task #73). The `feat-cli-module-merge` branch is in flight. No drift.

### The docs/design.md vs CODE_REVIEW.md vs README.md vs guide.md split

These files plus AGENTS.md plus RENAME.md document the same project from multiple perspectives. Skimming them, I find:

- docs/design.md is the canonical theorem + algorithm document.
- AGENTS.md is the canonical "how to work on this crate" document.
- CODE_REVIEW.md is a prior code-review backlog (clearly marked, useful).
- README.md is a marketing-shaped pitch with usage.
- guide.md is shorter intro material.
- TODO.md is a 21K-byte backlog.
- ~~FACTORIZE.md~~ — deleted; folded into docs/design.md (May 2026).
- ~~docs/lessons_learned/cross_process_stage_b.md~~ — tombstone; the cross-process Stage B plan it described was abandoned. See `docs/lessons_learned/cross_process_stage_b.md`.
- RENAME.md is a focused doc on the readability rename pass.

## Quick wins (≤30 min each)

1. **Carry chunk-top-level `Mark` on `ChunkContext`** so `top_level_id` lookups don't have to be threaded through every materialize-side function as a separate parameter. With the MLCI split landed the `Mark` now lives on `LowerChunkAst`, but it's still threaded through ~8 helpers below `lower_chunk`. Folding the `top_level_id` helper onto a small `ChunkContext` accessor would let helpers take just that context instead.

## Concerns to discuss before deciding

### Should `ChunkAnalysisReport` be auto-derived from the IR?

After the rename, `chunk_analysis::ChunkAnalysis` (IR) and `artifact::ChunkAnalysisReport` (JSON wire) still coexist as parallel definitions. The longer-term question is whether the report shape should be derived from the IR shape via a wire-format adapter (the way `OwnerGraph` ↔ `OwnerGraphReport` works). If yes, the two types collapse into one IR + one auto-derived report.

**Decision needed**: whether the report types are auto-derivable from IR types, or whether they intentionally diverge (e.g. the report has fields the IR doesn't, like `parser: ParserOptionsRecord` for reproducibility).

### Should the gate and the materializer share `EsmEvaluationSimulator`?

Today the simulator in `realizability.rs` is the gate's `cross-checks the materializer would have produced this evaluation order` mechanism. The materializer's own `lowering/imports_cross.rs::cross_module_imports_for_plan` actually produces the import order. If a future refactor moves the import-order computation into one place, the simulator's purpose changes: it stops being "predict what the materializer will do" and becomes "compute the post-order DFS the runtime will produce". Both consume `chunk_linker_order` / `chunk_source_import_order` from `graph.rs` (now the sole source of truth after `da7e928e2`), so today they cannot drift. If a future regression reintroduces a parallel ordering helper, the simulator breaks; the structural defense is keeping the canonical-edge-set API as the only entry point.

### Do anonymous statements deserve a first-class `OwnerKind`?

Today an "anonymous statement" is just an `OwnerNode` with empty `declared`. The materializer (`lowering/materialize/mod.rs`) special-cases them via `anonymous_statement_ordinals` + an explicit `anon_residual_sentinel` ModuleId (line 569). The realizability gate doesn't distinguish them. Several diagnostics use the placeholder `<anon stmt #ord>` (`validation.rs:181`). This is a coherent piece of vocabulary that should perhaps be an `OwnerNode::kind` variant rather than a sentinel "empty declared bindings". Worth thinking about at the next refactor — not blocking.

---

**Reviewer note.** This file is a living backlog; resolved items get deleted, not struck through. The original HEAD reference (`01c149496`) is historical — line numbers in remaining items may drift and should be re-resolved against current HEAD before acting.
