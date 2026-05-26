# Debundle crate — architecture review (May 2026)

Reviewed against `01c149496` on branch `feat-arch-review-2026-05`. Read on top of `DESIGN.md`, `PIPELINE_SPLIT.md`, `CODE_REVIEW.md`, `AGENTS.md`. Findings are at the design/architecture level; small style points already covered by `CODE_REVIEW.md` are not repeated.

> **Progress note.** Items handled since the original review have been removed; remaining items are the open backlog. Done so far: Lemma-2 ordering unified on `graph.rs` (`da7e928e2`); `RollbackDiGraph` SCC delegated to petgraph (`b62c9996f`); `artifact::ChunkAnalysis` renamed to `ChunkAnalysisReport`, `ModuleQuotient` inner field tightened to `pub(crate)`, `RealizabilityVerdict::scc_partition()` introduced (3 dep-graph SCC walks merged; 2 remain — see §"`tarjan_scc` over the module quotient" below) (`af45fccdc`, `7d2d79bc9`, `073493e6d`).

## Executive summary

1. **The Stage A boundary is real but the rest of the per-chunk pipeline is still patch-driven.** `lowering/materialize/mod.rs::materialize_logical_chunk` is 750 lines that thread _five_ loose mutable maps (`binding_assignment`, `bindings_catalogue`, `anonymous_ordinal_assignment`, `module_plans`, `residual_plan_index`) through eight phases of inline + helper-call mutation. There is no `ModulePlanBuilder` type encapsulating these; each helper takes `&mut` to four or five of them. This is the patch-on-patch shape the maintainer suspected.

2. **The dual `cross_module_partition_endpoints` / `gate_constraining_partition_endpoints` is the most concrete example of patch-on-patch architecture.** The same projection helper has two versions that differ only in whether they drop cross-module at-init-promoted edges, with the difference documented in a doc-comment "history" log naming three commit SHAs and a regression test ("`12ce3884b` removed the drop … `2d6be2473` silently re-introduced the drop … this sibling helper exists so the gate paths preserve `12ce3884b`'s fix"). The right fix is to push the distinction into the edge itself (an `EdgeRole` enum) so there is one projection helper that consults the role; the current shape encodes a 12-month bug-fix history into two near-identical function names.

3. **Stage A on-disk serialization (in-flight on three sibling branches) currently loses the `Id` hygiene identity across the Stage A/B boundary.** `facts/wire.rs::IdReport` round-trips `(name, ctxt: u32)`, but `SyntaxContext`'s `u32` value is meaningful only within one SWC `Globals` instance. If Stage B re-parses (per `PIPELINE_SPLIT.md`'s recommendation), the freshly-resolved `top_level_id` will have a different `Mark` and the deserialized `Id`s won't compare equal. Same problem hits `OwnerGraph::from_report`, which today already drops `declared: BTreeSet::new()` on round-trip (`graph.rs:362`) — i.e. the existing JSON wire shape already loses the binding identities every downstream `compute_owner_claims`-style consumer needs.

## Ad-hoc wiring + pipeline-state passing

### `materialize_logical_chunk` is a 750-line god function with parallel mutable state

`lowering/materialize/mod.rs:51` onwards. The function builds these mutable maps in interleaved order:

```rust
let mut binding_assignment       = HashMap::<Id, usize>::new();          // line 131
let mut anonymous_ordinal_assignment = BTreeMap::<usize, usize>::new(); // line 132
let mut module_plans             = Vec::new();                           // line 133
let mut bindings_catalogue       = HashMap::<Id, BindingKind>::new();    // line 134
let mut catalogue_index_by_name  = HashMap::<String, BindingKind>::new();// line 146
let mut imported_from_by_src     = BTreeMap::<String, String>::new();    // line 149
let mut unmatched_spec_claims    = Vec::<crate::UnmatchedSpecClaim>::new(); // line 150
let mut residual_plan_index: Option<usize> = None;                       // line 325
```

These get mutated by:

- The `for request in explicit_requests` loop (130 lines, lines 151–261).
- The `for (claimed_name, sibling_set) in &destructure_siblings` loop (lines 285–316).
- The two residual-fallback branches (lines 327–387).
- `fold_rebind_atomic_units(precomputed, &mut binding_assignment, &mut bindings_catalogue, &mut module_plans, residual_plan_index)` (line 497, signature in `rebind_folding.rs:31`).
- `synthesize_mini_factor_plans` (signature in `lowering/plans.rs:157`, ten arguments including _five_ `&mut` references).
- The `project_factorization_modules` map (lines 520–556).
- The "anon_residual_sentinel" appender that pushes a fake module index past `module_plans.len()` (lines 569–582) for transitional behavior.

This is the textbook shape of "each new feature added one parameter and one mutation site". There is no underlying domain object encapsulating "the plan being constructed". A `PlanBuilder` would own those maps and expose three or four methods (`claim_owned_binding`, `claim_imported_binding`, `claim_anonymous_statement`, `pull_destructure_sibling`, `finalize_residual`); every duplicate-claim / cross-claim check, every binding-kind insertion, and every residual sweep would live behind the encapsulation. Today the same lookup `bindings_catalogue` + `binding_assignment` is done in eight different places with subtly different invariants (sometimes the catalogue is keyed by `Id`, sometimes by name string in `catalogue_index_by_name`; `binding_assignment` is `HashMap<Id, usize>` but `bindings_catalogue` is `HashMap<Id, BindingKind>` carrying the same module identity wrapped differently).

**Concrete fix.** Introduce `lowering/materialize/plan_builder.rs` with `struct ChunkPlanBuilder { ... }` and methods. `materialize_logical_chunk` becomes the orchestrator that calls `builder.add_explicit_request(...)`, `builder.pull_destructure_siblings(...)`, `builder.fold_rebind_units(precomputed)`, etc. The body shrinks to maybe 200 lines of straightforward sequencing.

The `lowering/plans.rs::synthesize_mini_factor_plans` 10-arg signature in particular should become a method on the builder.

### `MaterializeLogicalChunkInputs` is a 9-field bag of `&` references

`lowering/materialize/mod.rs:19`. The struct exists only as an argument-list workaround for a 9-arg function call — it doesn't encapsulate anything. Same applies to the next-stage `LowerChunkInputs` (lines 664–683 spell out 16 fields when constructing it). These should be split into smaller domain types: `ChunkContext` (`artifact`, `artifact_indexes`, `chunk_id`, `target_dir`, `report_out_dir`), `ChunkSpec` (`logical_modules`, `chunk_renames`, `unassigned_mode`, `chunk_analysis_options`), and `ChunkAnalysisInputs` (the AST + facts + owner graph). The current bags conceal that `materialize_logical_chunk` actually wants three distinct inputs.

### `apply_member_hints(&mut hints, &m.binding, m.purity, &m.pure_members, m.effect)`

`lowering/materialize/mod.rs:761`. The helper takes five arguments because each was added by a different feature; the natural shape is `hints.absorb_member(&Member)` where `Member` is a typed view over `MemberRequest`. Today's call sites (lines 405–423) destructure `MemberRequest` member-by-member into the helper's loose argument list. Trivial fix.

### `compute_stage_one_analysis` is itself an example of the right direction

`stage_one.rs:72` is a genuinely clean composer. The reason it works is that **the boundary at Stage A is well-defined**: the inputs and outputs are clear, the composer's only job is to call `analyze_chunk` then `compute_owner_graph_and_units_with`. The Stage A composer is exactly the shape every other composite operation in this crate should look like, and is the strongest design point in the recent refactor.

That said, `stage_one.rs:46` notes "Why a free function with no struct fanout" — but the doc-string concedes that the side-effecting interleaving (redundant-hint stderr, top-level-await `bail!`, atomic-unit-rebind folding) **still happens inline at the materializer**. Stage A _separation_ isn't done; the composer is a function-level renaming. The next refactor (post-sidecar) needs to move those side-effecting paths into the composer's owners.

## Duplicated calculations

### `tarjan_scc` over the module quotient: residual walks

After the Lemma-2 unification (`da7e928e2`) and `RealizabilityVerdict::scc_partition()` introduction (`7d2d79bc9`), 5 module-quotient Tarjan walks collapsed into 2:

1. `check_realizability` materialises one SCC partition and exposes it on the verdict; `validate_factorization` and `reports::build_quotient_scc_reports` consume it instead of re-walking.
2. `ChunkFactorization::build_with` caches a `dep_graph_sccs` field used by the materializer/emitter path.

Remaining legitimate walks (different graphs): `validation.rs:437` (FAS iteration, intrinsic), `graph.rs:884` (`promote_at_init_calls` closure fixpoint), `atomic_units.rs:103` (constraining-edge owner SCC).

**Open follow-up.** The two surviving module-quotient walks (verdict-time + factorization-build-time) compute the same partition for different consumers; structurally consolidatable behind a wider API change, but not urgent and not on a hot path.

### `OwnerGraphReport::from_report` drops `declared` on the floor

`graph.rs:362`. The reconstructed `OwnerNode` has `declared: BTreeSet::new()` because the JSON wire shape (`OwnerGraphNodeReport`) doesn't carry the per-node binding set — declared bindings are reported separately on the `BindingReport` rows. The planner side that reconstructs the graph from JSON can therefore not answer "which bindings does this node declare?" — `factor_assembly::compute_owner_claims` (called from `assemble_partition`) walks `owner_graph.nodes[].declared`, so the planner is structurally unable to call it on a reconstructed graph.

In the Stage A sidecar plan, this matters: every Stage B consumer that runs `assemble_partition` against a hydrated graph needs the binding set. The wire format currently in flight on `feat-facts-wire-format` does carry per-statement `declared` via `StatementFactsReport.declared`, which means the Stage A artifact would carry the data and Stage B would have to merge it back into the reconstructed `OwnerGraph`. That merge is invisible to today's `OwnerGraph::from_report` and is itself a duplicated piece of work.

## Library-vs-hand-rolled

### `petgraph::algo::greedy_feedback_arc_set` is used correctly; the surrounding loop is not

`validation.rs:437` runs a while-loop that:

1. Tarjan-SCCs the working graph.
2. Finds a "problematic" SCC.
3. Builds a fresh `petgraph::DiGraph` for that sub-SCC.
4. Runs `greedy_feedback_arc_set` on the sub-graph.
5. Falls back to a manual scan if FAS only flagged lazy edges.
6. Removes one edge, loops.

The Tarjan-SCC + FAS + remove-edge loop is itself a known algorithm shape (iterative FAS-by-SCC). `petgraph` has it built in via `condensation`: condense to a DAG of SCCs, walk the condensation top-down. The current loop is correct but `O(|cycles| · |V| + |E|)` per chunk, when a single condensation pass + FAS-per-condensation-node would be `O(|V| + |E|)`. More importantly, the loop's "fallback to scanning the SCC's edges if FAS only flagged lazy edges" branch (`validation.rs:482`) papers over what looks like a soundness/precision issue in how FAS is being used: FAS doesn't know about edge labels, so it picks whatever it picks; trying to make it pick R/S edges by post-filtering its result is a hack. The right fix is to filter the edge set down to constraining edges _before_ calling FAS, then map the result back. (`greedy_feedback_arc_set` accepts arbitrary graphs; nothing stops the caller from omitting `LazyUse` edges from the working `DiGraph`.) Simpler, faster, no fallback needed.

### Hand-rolled cycle-no-op DFS in `simulate_esm_post_order`

`realizability.rs:366–428`. The simulator implements a DFS-with-cycle-no-op manually, with explicit `Frame::Enter` / `Frame::Finish` work-stack frames. The simulator is the right algorithm — the ECMA-262 spec is explicitly post-order DFS — but the implementation could use `petgraph::visit::DfsPostOrder` if we built a small wrapper that respects the `sorted_successors` ordering decision. Today's hand-rolled stack is fine in isolation, but it's another instance of "we built a custom traversal because the existing one didn't take a sort-key parameter." A `petgraph::visit::DfsPostOrder` over a graph wrapper that lazily reorders neighbors would let the simulator focus on the _semantic_ check (post-order indices) rather than the DFS bookkeeping.

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
- **`ChunkAnalysisOptions`** (`spec.rs:104`) is a _spec-side_ per-chunk knob holder; **`OwnerGraphOptions`** (`graph.rs:21`) is the _graph-build-side_ knob holder; the materializer copies one field from the former into the latter (`lowering/materialize/mod.rs:435–439`). The duplication of "options" types with the same one field (`dataflow_aware_s_chain`) is a sign that the type is doing too little — fold them together once Stage A is genuinely cacheable (Stage A's cache key needs `OwnerGraphOptions`, so the spec/graph boundary forces a copy today).
- **`linker_order` (`Vec<String>` in `FactorizationReport`)** vs **`linker_order` (`Vec<ModuleId>` in `ChunkFactorization`)** vs **`chunk_linker_order` (`BTreeMap<ModuleId, usize>` in `graph.rs`)** — three different shapes for "the toposort of the constraining-edge graph", differing in element type and whether it's "list" or "map (position lookup)". Pick one canonical type, derive the others.
- **`UnrealizableScc` (`realizability.rs:50`)** vs **`CycleReport` (`validation.rs:35`)** vs **`QuotientSccReport` (`reports/schema.rs`)** vs **`AtomicUnitConflict` (`factor_assembly.rs:35`)** — four representations of "the spec is unrealizable, here's why" with subtly different fields. `UnrealizableScc` carries `constraining_owner_edges`; `CycleReport` carries `cut` (a minimum cut) + `evidence`; `QuotientSccReport` carries `module_edge_ids` + `constraining_module_edge_ids`. Two of these contain the same data ("the modules in the SCC + the edges in the SCC"), with the cut/evidence/min decoration added by the validator. The right shape is one core type with optional decorations, not four parallel structs.
- **`AnalysisHints`** (`facts/mod.rs`-exported) lives in `facts`, but holds spec-derived data (`declared_pure`, `declared_pure_new`, `declared_pure_members`, `known_effects`). The data is spec-shaped, the type is in facts. This becomes a problem at Stage A serialization time: Stage A _needs_ the hints (purity inference reads them) but the hints come from the spec which is Stage B's input. Today's pipeline collects them before Stage A runs — fine — but the Stage A cache key has to include the hints, which violates the "Stage A is spec-independent" framing in `PIPELINE_SPLIT.md`.

## Algorithmic clarity (realizability gate, atom detection)

### The gate is _more_ coherent than the maintainer fears, but its docs make it look like a stack of patches

The realizability gate's actual algorithm, read carefully, is:

> Build the canonical constraining-edge view of the I-graph; the gate accepts iff (a) Tarjan on the constraining-edge view has no multi-module SCC, and (b) for every multi-module SCC in the full I-graph that has at least one constraining edge, the ECMA-262 Phase-2 simulator (rooted at residual, with residual's imports sorted by `source_import_position` and every other module's by `linker_position`) yields a post-order with `post_order[target] < post_order[source]` for every constraining edge.

That's one algorithm with two passes. Pass 1 is a cheap necessary condition (mutual at-init cycles can never be rescued by reordering); Pass 2 is the precise condition (the runtime DFS-simulator decides asymmetric cycles). The 2× Tarjan is structural to the algorithm, not patchy. **This is fine.** The DESIGN.md theorem reads cleanly.

What's _patchy_ is:

1. The `gate_constraining_partition_endpoints` / `cross_module_partition_endpoints` split (covered in Executive summary #2).
2. The promoted-edge logic. `EdgeReason::at_init_callee_owner` (`graph.rs:75`) is a side channel on every edge that exists _only_ to decide whether `is_cross_module_at_init_promotion` drops the edge in the lenient view. The data flows through serialization (`EdgeReason::synthetic_with_callee`), through the canonical edge set, through the gate-side endpoints helper. It's loadbearing for soundness (per the `promoted_edge_in_aggregator_cycle_is_unrealizable` regression), but the _concept_ "this is a promoted edge, the gate sees it differently from the emitter" is encoded as a flag on every edge plus a pair of projection helpers plus a documentation history log. Cleaner: an explicit `EdgeRole { Direct, PromotedAtInit { callee_owner: OwnerId } }` enum, with the projection helper consulting the role and the gate/emitter rules being a single `match`.
3. The `EsmEvaluationSimulator::from_adjacency` (`realizability.rs:306`) constructor exists only because the overlay path (`IncrementalQuotient`) has its edges in a different shape than the canonical edge set. So `from_adjacency` rebuilds a fake `ChunkConstrainingEdgeSet { edges: empty_map_for_each_constraining_pair, i_successors }` and feeds it to `build`. This is two structurally identical inputs that diverged because two callers had different sources; the right shape is for `build` to take the two adjacency maps directly. Today's "construct fake edges map" is a kludge to fit the constructor.

### Atomic-units classification has two paths but only one is wired

`atomic_units.rs::compute_atomic_units` is the structural-atom detector (SCCs of the constraining-edge owner graph). `factor_assembly::detect_unit_conflict` is the "did the spec split a unit?" detector. The structural atoms are computed once per chunk (in `compute_owner_graph_and_units_with`), passed through `OwnerGraphAndUnits` to the materializer and into `ChunkFactorization`. Clean — this is the right shape.

Spec-induced atoms (the SCCs of `I ∪ S` under the quotient) are NOT precomputed; they emerge from the realizability primitive. DESIGN.md §"Two classes of atom" labels them as a distinct concept. After `7d2d79bc9` the verdict exposes the SCC partition and `validate_factorization` consumes it instead of re-walking; the residual walk lives on `ChunkFactorization::dep_graph_sccs` for the materializer/emitter path (see §"Duplicated calculations" for the open consolidation).

### Tests for `at_init_promotion_drop_unsound_in_cycle` flag exactly the right kind of pattern

`realizability.rs:1986` (`promoted_edge_in_aggregator_cycle_is_unrealizable`) is a test that exists to pin the _re-introduction_ of a previously-fixed bug. The doc-comment narrates the SHA-by-SHA history. Reading that doc-comment is what a regression test should _avoid_ requiring — the structural fix is to make the bug structurally impossible. Today the gate-side / lenient endpoints split is doc-and-test-pinned; an `EdgeRole`-typed solution would let the type checker carry the invariant.

## Pipeline-split residuals

The three branches in flight at review time (`feat-cli-module-merge`, `feat-facts-wire-format`, `feat-stage-a-sidecars`) have all landed. The remaining concerns are:

### `Id` round-trip is still `Globals`-bound

`facts/wire.rs::IdReport` serializes `(name: Atom, ctxt: u32)`. The `u32` is the `SyntaxContext`'s internal representation. **`SyntaxContext` values are meaningful only within the same SWC `Globals` instance.** If Stage B re-parses the chunk in a fresh `Globals`, the resolver issues fresh `Mark`s and the `top_level_id`-produced `Id`s won't compare equal to deserialized ones with the old `u32`.

The `facts_round_trip_unit` test covers same-process round-trip where the `Globals` is the same. The test the wire format actually needs is the **cross-`Globals` test**: parse → serialize → drop `Globals` → re-parse in fresh `Globals` → deserialize → assert `top_level_id` matches. Until that test exists and passes, cross-process Stage B is unsound.

The fix: don't serialize `SyntaxContext`. Carry the binding `Atom` plus an enum tag (`TopLevel | ImportedFromChunk(...) | Global`). Stage B reconstructs `Id`s via `top_level_id(name, chunk_top_level_mark)` from its own re-parse.

### Stage A side effects are still in the materializer's process

Today the pipeline runs everything inline in `materialize_logical_chunk`, including side-effecting actions (top-level-await `bail!`, redundant-hint stderr). When Stage A becomes its own Bazel action, those side effects need to move out of the materializer's process: produce a Stage A artifact + log warnings as part of that action; the materializer loads the artifact and doesn't re-emit. Today the warnings are stderr from the materializer; that has to change. Worth pinning a TODO in `stage_one.rs` so the reader knows the next step.

## Test-vs-spec drift

### `#[ignore]`d tests are clean

`e2e/purity_test.rs` is the only file with `#[ignore]`d tests, and each names an explicit "Step D"/"Step E in the purity-desiderata follow-up plan" reason. These are documented future work, not drift. Good shape.

### "v2 hypothesis was wrong" — found one comment

`graph.rs:1322` documents that `chunk_source_import_order`'s `None`-after-`Some` clause is "kept for robustness against future filter changes that might admit non-constraining members" — i.e. defensive code for a hypothesis that hasn't been validated. That's mild; not real drift.

### One TODO mismatch

`TODO.md` mentions a `module merge` task (task #73). The `feat-cli-module-merge` branch is in flight. No drift.

### The DESIGN.md vs CODE_REVIEW.md vs README.md vs guide.md split

These four files plus AGENTS.md plus RENAME.md plus PIPELINE_SPLIT.md document the same project from multiple perspectives. Skimming them, I find:

- DESIGN.md is the canonical theorem + algorithm document.
- AGENTS.md is the canonical "how to work on this crate" document.
- CODE_REVIEW.md is a prior code-review backlog (clearly marked, useful).
- README.md is a marketing-shaped pitch with usage.
- guide.md is shorter intro material.
- TODO.md is a 21K-byte backlog.
- ~~FACTORIZE.md~~ — deleted; folded into DESIGN.md (May 2026).
- RENAME.md is a focused doc on the readability rename pass.

This is a lot. There is one bit of genuine drift: `PIPELINE_SPLIT.md` describes `factor_assembly::compute_owner_claims` as a public API ("apply spec → claims (factor*assembly::compute_owner_claims)") but `factor_assembly.rs:90` has it as `fn compute_owner_claims` — \_private*. Minor, but evidence that PIPELINE_SPLIT.md was written before the implementation it describes.

## Quick wins (≤30 min each)

1. **Make `factor_assembly::compute_owner_claims` `pub`** to match `PIPELINE_SPLIT.md`'s assertion. If the doc is wrong, fix the doc.

2. **Carry chunk-top-level `Mark` on the typed `Partition`** (or on a `ChunkContext` wrapper) so `top_level_id` lookups don't have to be threaded through every materialize-side function as a separate parameter. Today `lowering/materialize/mod.rs:100` reads it from the AST and threads it through eight call sites.

3. **Pull `apply_member_hints`'s five arguments into `Member::collect_hints(&self, hints: &mut AnalysisHints)`**. Five-arg helper goes away; call site (`lowering/materialize/mod.rs:405–423`) becomes `for m in &req.members { m.collect_hints(&mut hints); }`.

4. **Add a single `EdgeRole` enum** as a field of `EdgeReason` (variants `Direct` / `PromotedAtInit { callee_owner }`) so the gate/lenient projection helpers can fold into one helper that consults the role. Removes the dual `*_partition_endpoints` helpers + their commit-SHA history doc-comments.

5. **`lowering/plans.rs::synthesize_mini_factor_plans` → method on a builder**. Ten-arg function with five `&mut` references becomes `builder.synthesize_mini_factors(precomputed, body, target_dir)`.

## Multi-session refactors (1–3 day projects)

### 1. `ChunkPlanBuilder` extraction

`lowering/materialize/mod.rs::materialize_logical_chunk` (~750 lines) should be split into:

- `ChunkPlanBuilder` (~200 lines) owning the five mutable maps, with methods `add_explicit_request`, `pull_destructure_siblings`, `add_residual_sweep`, `fold_rebind_units`, `synthesize_mini_factors`, `finalize() -> ChunkPlan`.
- `materialize_logical_chunk` shrunk to ~150 lines of sequencing: parse → analyze → build plan → factorize → validate → lower.
- The `MaterializeLogicalChunkInputs` 9-field bag split into `ChunkContext` + `ChunkSpec` + `ChunkAnalysisInputs`.

Entry point: extract `ChunkPlanBuilder` first (its construction lives in lines 130–387 of `materialize/mod.rs`); the rest follows naturally.

### 2. `EdgeRole` enum on `EdgeReason`

Folds the dual `cross_module_partition_endpoints` / `gate_constraining_partition_endpoints` into one. Once added, the projection helper consults `edge.reason.role` and applies the correct rule per consumer (gate vs emitter vs reports). The `at_init_callee_owner: Option<OwnerId>` field becomes an `EdgeRole::PromotedAtInit { callee_owner }` variant. The cross-grep-test `no_consumer_calls_is_cross_module_at_init_promotion_directly` (`graph.rs:1637`) goes away — it was a workaround for not having the enum.

Entry point: introduce `enum EdgeRole`; thread it through edge construction in `build_owner_graph_with` + `promote_at_init_calls`; replace the two endpoint helpers with one that takes an `EdgeRole`-aware consumer policy.

## Concerns to discuss before deciding

### Should Stage A be one file or many?

`PIPELINE_SPLIT.md` recommends one (Option 1 JSON pretty). `feat-stage-a-sidecars` is heading for three or four. Per §"Pipeline-split risks" above, the file split needs justification by per-CLI consumption patterns. If none of the read-only CLIs (`scc`, `atoms`, `coverage`, `describe`, `cluster`, `modules merge`) actually need partial loads, collapse to one. If yes, document the load pattern.

**Decision needed before**: `feat-stage-a-sidecars` lands.

### Does the wire format really need to round-trip `SyntaxContext`?

`facts/wire.rs::IdReport` carries `ctxt: u32`. Per §"Pipeline-split risks", this round-trip is `Globals`-bound and breaks cross-process. The fix may be to **drop the field** and have Stage B reconstruct `Id`s via `top_level_id(name, chunk_top_level_mark)` from a re-parsed AST. But that assumes every `Id` Stage A serializes is chunk-top-level; if any lazy_reads carry non-top-level `Id`s, this assumption fails.

**Decision needed before**: `feat-facts-wire-format` lands.

This is the single biggest correctness risk in the in-flight work. A unit test that round-trips through two `Globals` instances would settle it conclusively — recommend adding one immediately on `feat-facts-wire-format` before merging.

### Should `ChunkAnalysisReport` be auto-derived from the IR?

After the rename, `chunk_analysis::ChunkAnalysis` (IR) and `artifact::ChunkAnalysisReport` (JSON wire) still coexist as parallel definitions. The longer-term question is whether the report shape should be derived from the IR shape via a wire-format adapter (the way `OwnerGraph` ↔ `OwnerGraphReport` works). If yes, the two types collapse into one IR + one auto-derived report.

**Decision needed**: whether the report types are auto-derivable from IR types, or whether they intentionally diverge (e.g. the report has fields the IR doesn't, like `parser: ParserOptionsRecord` for reproducibility).

### Should the gate and the materializer share `EsmEvaluationSimulator`?

Today the simulator in `realizability.rs` is the gate's `cross-checks the materializer would have produced this evaluation order` mechanism. The materializer's own `lowering/imports_cross.rs::cross_module_imports_for_plan` actually produces the import order. If a future refactor moves the import-order computation into one place, the simulator's purpose changes: it stops being "predict what the materializer will do" and becomes "compute the post-order DFS the runtime will produce". Both consume `chunk_linker_order` / `chunk_source_import_order` from `graph.rs` (now the sole source of truth after `da7e928e2`), so today they cannot drift. If a future regression reintroduces a parallel ordering helper, the simulator breaks; the structural defense is keeping the canonical-edge-set API as the only entry point.

### Do anonymous statements deserve a first-class `OwnerKind`?

Today an "anonymous statement" is just an `OwnerNode` with empty `declared`. The materializer (`lowering/materialize/mod.rs`) special-cases them via `anonymous_statement_ordinals` + an explicit `anon_residual_sentinel` ModuleId (line 569). The realizability gate doesn't distinguish them. Several diagnostics use the placeholder `<anon stmt #ord>` (`validation.rs:181`). This is a coherent piece of vocabulary that should perhaps be an `OwnerNode::kind` variant rather than a sentinel "empty declared bindings". Worth thinking about at the next refactor — not blocking.

---

**Reviewer note.** All file/line references are at HEAD = `01c149496`. The maintainer should treat this report as a backlog input, not a definitive ordering. The most valuable single change is probably the `ChunkPlanBuilder` extraction (Multi-session refactor #1) — it removes the most code, eliminates the most state-passing, and makes the materializer readable in one sitting. The most urgent before any other change is settling the `Id` round-trip question in `feat-facts-wire-format` before that branch lands.
