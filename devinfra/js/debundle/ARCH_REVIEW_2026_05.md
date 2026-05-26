# Debundle crate — architecture review (May 2026)

Reviewed against `01c149496` on branch `feat-arch-review-2026-05`. Read on top of `DESIGN.md`, `PIPELINE_SPLIT.md`, `CODE_REVIEW.md`, `AGENTS.md`. Findings are at the design/architecture level; small style points already covered by `CODE_REVIEW.md` are not repeated.

## Executive summary

1. **The Stage A boundary is real but the rest of the per-chunk pipeline is still patch-driven.** `lowering/materialize/mod.rs::materialize_logical_chunk` is 750 lines that thread _five_ loose mutable maps (`binding_assignment`, `bindings_catalogue`, `anonymous_ordinal_assignment`, `module_plans`, `residual_plan_index`) through eight phases of inline + helper-call mutation. There is no `ModulePlanBuilder` type encapsulating these; each helper takes `&mut` to four or five of them. This is the patch-on-patch shape the maintainer suspected.

2. **There are two parallel implementations of "Lemma 2" ordering** — once in `graph.rs::{chunk_linker_order, chunk_source_import_order}` (consumed by the realizability gate's `EsmEvaluationSimulator`), and once in `chunk_factorization.rs::{compute_linker_order, compute_source_import_order}` (consumed by the materializer/emitter). Both compute Tarjan-SCC + minimum-linker-position-per-SCC + `(scc_rank ASC, intra-SCC linker_position DESC)`. DESIGN.md §"Lemma 2" pins them as the _same algorithm with the same answer_; the implementations are textbook duplicate code, and they take _different inputs_ (constraining-edge view vs. `ModuleQuotient`) so they can drift silently. The Pass-2 simulator going TDZ-clean while the emitter produces TDZ at runtime is exactly the failure mode this duplication invites.

3. **`tarjan_scc` runs four-to-five times per chunk over essentially the same graph.** `realizability::check_realizability` runs it twice (Pass 1 over constraining, Pass 2 over full I-graph). `validation::validate_factorization` calls into `check_realizability` and then runs Tarjan a _third_ time over the module quotient to build cycle reports. `chunk_factorization::compute_source_import_order` runs a _fourth_ over the same module quotient. `reports::build_quotient_scc_reports` runs a _fifth_ over the same quotient. With the `IncrementalQuotient` cache + `cached_base_simulator`, the runtime cost is partially amortised, but the _code structure_ still has five hand-written SCC consumers that each project + walk the quotient independently. Folding 3/5 of these into the realizability primitive is a quick win.

4. **There are two distinct types named `ChunkAnalysis`** (`chunk_analysis::ChunkAnalysis`, `artifact::ChunkAnalysis`), both `pub`, both exported through `lib.rs` (via `pub use chunk_analysis::ChunkAnalysis` and via the broader `artifact` re-exports in the parent `pipeline` crate). One is "inputs+IR+caches" for the factorizer; the other is "JSON per-chunk report stub". `CODE_REVIEW.md` notes the rename history but the two structs still coexist. This is genuinely confusing for a reader pattern-matching on the term.

5. **The dual `cross_module_partition_endpoints` / `gate_constraining_partition_endpoints` is the most concrete example of patch-on-patch architecture.** The same projection helper has two versions that differ only in whether they drop cross-module at-init-promoted edges, with the difference documented in a doc-comment "history" log naming three commit SHAs and a regression test ("`12ce3884b` removed the drop … `2d6be2473` silently re-introduced the drop … this sibling helper exists so the gate paths preserve `12ce3884b`'s fix"). The right fix is to push the distinction into the edge itself (an `EdgeRole` enum) so there is one projection helper that consults the role; the current shape encodes a 12-month bug-fix history into two near-identical function names.

6. **Stage A on-disk serialization (in-flight on three sibling branches) currently loses the `Id` hygiene identity across the Stage A/B boundary.** `facts/wire.rs::IdReport` round-trips `(name, ctxt: u32)`, but `SyntaxContext`'s `u32` value is meaningful only within one SWC `Globals` instance. If Stage B re-parses (per `PIPELINE_SPLIT.md`'s recommendation), the freshly-resolved `top_level_id` will have a different `Mark` and the deserialized `Id`s won't compare equal. Same problem hits `OwnerGraph::from_report`, which today already drops `declared: BTreeSet::new()` on round-trip (`graph.rs:362`) — i.e. the existing JSON wire shape already loses the binding identities every downstream `compute_owner_claims`-style consumer needs.

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

### Lemma-2 ordering is implemented twice

The maintainer asks "is anything that walks the owner graph computed in more than one place?" The answer is yes:

| Site                         | Function                                                                                     | Input                               | Output                      |
| ---------------------------- | -------------------------------------------------------------------------------------------- | ----------------------------------- | --------------------------- |
| `graph.rs:1290`              | `chunk_linker_order(edges: &ChunkConstrainingEdgeSet)`                                       | constraining edges + `i_successors` | `BTreeMap<ModuleId, usize>` |
| `graph.rs:1329`              | `chunk_source_import_order(edges, &extra_nodes)`                                             | as above + extras                   | `Vec<ModuleId>`             |
| `chunk_factorization.rs:212` | `compute_linker_order(&ModuleQuotient, _logical_modules)`                                    | the `ModuleQuotient`                | `Vec<ModuleId>`             |
| `chunk_factorization.rs:263` | `compute_source_import_order(&ModuleQuotient, &logical_modules, &linker_position_by_module)` | as above + linker positions         | `Vec<ModuleId>`             |

The two pairs run the same algorithm on different graph representations. `graph.rs`'s pair is used by the realizability gate's `EsmEvaluationSimulator` (`realizability.rs:281`). `chunk_factorization.rs`'s pair is used by the materializer (`lowering::lower_chunk` consumes `factorization.linker_order` and `factorization.source_import_position`).

Both pairs implement Lemma 2's `(scc_rank ASC, intra-SCC linker_position DESC)` sort with the `usize::MAX` tiebreak; both call `tarjan_scc` and `toposort`. The simulator's tests assert it "mirrors the materializer's emit-time decisions exactly" — but the two implementations are mechanically separate, and the assertion is enforced only by accumulating regression tests. Any future change to the sort rule (residual-aware tiebreaks, vendor-leaf carve-outs, etc.) has to be made in both places.

**Concrete fix.** Delete `chunk_factorization.rs::{compute_linker_order, compute_source_import_order}`. Adapt the factorization to build a `ChunkConstrainingEdgeSet` and call `graph::{chunk_linker_order, chunk_source_import_order}`. The constraining-edge view is the canonical one per `graph.rs:1135` ("MUST drive their topology decisions through this single set so they cannot drift apart") — the materializer was already supposed to do this but the legacy `ModuleQuotient`-based pair was kept on. Removing it forces every Lemma-2-aware caller through one function.

### `tarjan_scc` over the module quotient: five separate walks per chunk

Across the gate + validator + factorization + reports + simulator:

1. `realizability.rs:155` — Pass 1 over `con_graph` (constraining-edge view).
2. `realizability.rs:192` — Pass 2 over `i_graph` (full I-graph view, includes lazy back-edges).
3. `validation.rs:270` — `tarjan_scc(&graph.0)` on the `ModuleQuotient` to build cycle reports for the verdict that _just rejected_.
4. `validation.rs:437` — Tarjan inside `compute_realizability_cut`'s while-loop, called per cycle. Necessary by the algorithm; this is the FAS iteration.
5. `chunk_factorization.rs:268` — `tarjan_scc(&dep_graph.0)` for `compute_source_import_order`.
6. `reports.rs:323` — `tarjan_scc(&factorization.dep_graph.0)` to build `QuotientSccReport`s.
7. `graph.rs:1352` — `tarjan_scc` inside `chunk_source_import_order` (this is the canonical one).
8. `graph.rs:884` — `tarjan_scc` inside `promote_at_init_calls` (call-graph SCC for the closure fixpoint; different graph, legitimate).
9. `atomic_units.rs:103` — `tarjan_scc(&g_atomic)` (constraining-edge owner SCC, structural atoms; different graph, legitimate).

#1, #2, #3, #5, #6, #7 are all SCC walks of related views of the same module quotient. The `RealizabilityIndex` caches its constraining + I-graphs and has a `cached_base_simulator`, so the runtime cost is partially hidden. The _code-structure_ cost is not. A reader auditing "what computes SCCs in this crate?" finds eight call sites and has to manually triage which graphs are actually distinct.

**Concrete fix.** The realizability primitive's verdict should carry its SCC partition. `validate_factorization` should consume that partition to build cycle reports rather than re-walking the quotient. `chunk_factorization::compute_source_import_order` should delegate to `graph::chunk_source_import_order` (see previous point). `reports::build_quotient_scc_reports` should consume the same verdict-carried partition.

### Identical Lemma-2 sort comparator open-coded twice

Compare `graph.rs:1367–1384` (the comparator inside `chunk_source_import_order`) with `chunk_factorization.rs:296–325` (the comparator inside `compute_source_import_order`). Both implement exactly the same `(SCC rank ASC, intra-SCC linker_position DESC, with usize::MAX tiebreak and Less for `Some(\_)`over`None`)` rule. They share the same documentation comment block ("(SCC rank ASC, intra-SCC linker_position DESC) — DESC reverses within each SCC so the cycle dependent comes first…"). Two implementations of the same closure with the same prose — a wholly mechanical reduction.

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

### `RollbackDiGraph`-vs-petgraph parity in tests

`rollback_graph.rs:354` runs `tarjan_scc(&petgraph)` for differential testing against the homegrown rollback graph. The comment in `CODE_REVIEW.md` already flags that `rollback_graph.rs` hand-rolls Tarjan in production code (lines 119–191) when petgraph could do it via a trait impl. Worth re-stating at architecture level: `RollbackDiGraph` is a load-bearing structure (the `IncrementalQuotient` is built on top of it), and the choice to give it its own `successors`/`predecessors`/`tarjan_scc` instead of implementing `petgraph::visit::IntoNeighbors` (or wrapping `DiGraphMap` with rollback semantics) leaves the project maintaining a parallel graph library with its own test surface. This is a multi-session refactor (see §"Multi-session refactors" below).

### Hand-rolled cycle-no-op DFS in `simulate_esm_post_order`

`realizability.rs:366–428`. The simulator implements a DFS-with-cycle-no-op manually, with explicit `Frame::Enter` / `Frame::Finish` work-stack frames. The simulator is the right algorithm — the ECMA-262 spec is explicitly post-order DFS — but the implementation could use `petgraph::visit::DfsPostOrder` if we built a small wrapper that respects the `sorted_successors` ordering decision. Today's hand-rolled stack is fine in isolation, but it's another instance of "we built a custom traversal because the existing one didn't take a sort-key parameter." A `petgraph::visit::DfsPostOrder` over a graph wrapper that lazily reorders neighbors would let the simulator focus on the _semantic_ check (post-order indices) rather than the DFS bookkeeping.

### `swc_ecma_visit` usage is reasonable

Searched for hand-rolled AST walks that should have been visitors. Found only the explicit top-level iteration in `facts/mod.rs` (`match ModuleItem::Stmt(Stmt::Decl(...))` etc.) which is appropriate because the analysis is fundamentally a top-level-only iteration with structured per-statement output. Subordinate visits (binding-target recording, reference collection, identifier scanning, body-purity) all use `Visit` / `VisitWith` correctly. No fix needed here.

## Encapsulation + module boundaries

### `OwnerGraph` is a struct with public fields

`graph.rs:234`. Five public fields: `nodes`, `edges`, `out_edges`, `in_edges`, `callee_edges`. Every consumer iterating the graph reaches `owner_graph.iter_nodes()` / `iter_edges()` (good), but the fields themselves are `pub` so consumers can also `for edge in &owner_graph.edges` or `for slot in &owner_graph.out_edges[id.0]` (and they do — `realizability.rs:111`, `validation.rs:260`, etc.). This makes the invariants on the CSR structure ("`out_edges[id.0]` lists every `OwnerEdgeId` whose `from == id`, in insertion order") implicit on every reader.

`CODE_REVIEW.md` notes the same issue (P3 "OwnerGraph exposes internal CSR structures"). At architecture level: the right encapsulation is `OwnerGraph` exposing only `iter_nodes`, `iter_edges`, `successors(id) -> impl Iterator<&OwnerEdge>`, `predecessors(id) -> impl Iterator<&OwnerEdge>`, `node(id)`, `edge(eid)`. Today's `pub nodes: Vec<OwnerNode>` invites every consumer to write its own adjacency walk.

### `ModuleQuotient` Derefs to `petgraph::DiGraphMap`

`graph.rs:495`. `pub struct ModuleQuotient(pub DiGraphMap<ModuleId, EdgeMetadata>)` with `Deref` and `DerefMut` to the inner graph. The doc-comment says the newtype exists "so the semantic name 'the I∪S module-dep quotient' stays distinct" — but with `DerefMut` exposing the petgraph mutation API, the name distinction is the only thing preserved. Any caller can `quotient.0.add_edge(...)` or `*quotient = DiGraphMap::new()`. Two genuine consumers (`validation.rs`, `reports.rs`) read it; no consumer needs the mutation surface. Make the inner field crate-private, expose `all_edges`, `edge_weight`, `contains_edge`, `has_init_order_constraining_edge`, and the explicit constructor `build_module_quotient`. (See also `CODE_REVIEW.md` P3 entry, which says the same.)

### Two `ChunkAnalysis` types

`chunk_analysis.rs:26` (`ChunkAnalysis` for factorize-time IR) and `artifact.rs:261` (`ChunkAnalysis` for the JSON report). Both `pub`. The `chunk_analysis::ChunkAnalysis` is re-exported by `lib.rs:37`. The `artifact::ChunkAnalysis` is in the outer pipeline crate but it's adjacent in the same crate root, and `ChunkManifest::from_analysis(analysis: &ChunkAnalysis, ...)` (`artifact.rs:319`) takes the _artifact_ version — so the type signature is ambiguous to a reader who has only one of the two in scope.

**Concrete fix.** Rename `artifact::ChunkAnalysis` to `ChunkAnalysisReport` (it's a serializable report and the field shapes match `ChunkManifest` almost exactly). `chunk_analysis::ChunkAnalysis` keeps the unqualified name; readers stay oriented.

### `ChunkFactorization` is the second `ChunkAnalysis` in disguise

`chunk_factorization.rs:30`. `ChunkFactorization` holds `analysis: Arc<ChunkAnalysis>` plus partition + dep_graph + linker_order + maps. Then `validate()` returns a `FactorizationReport` (`chunk_factorization.rs:180`) which is also a third "report" type alongside `ChunkAnalysis` (report) and `ChunkAnalysis` (IR). The naming hierarchy is:

```
ChunkAnalysis (IR)     // chunk_analysis.rs
  ↓ wrapped in
ChunkFactorization     // chunk_factorization.rs (IR + partition + dep_graph)
  ↓ validate() →
FactorizationReport    // validation.rs (cycles + atomic_unit_conflicts + linker_order)

ChunkAnalysis (report) // artifact.rs (different type, same name)
  ↓ from_analysis() →
ChunkManifest          // artifact.rs (analysis report + decomposition + metrics)

OwnerGraphReport       // report_schema.rs (the JSON view of the typed OwnerGraph)
```

That's seven distinct types (`ChunkAnalysis` ×2, `ChunkFactorization`, `FactorizationReport`, `ChunkAnalysis` (report sense), `ChunkManifest`, `OwnerGraphReport`) all in the orbit of "stuff a chunk analysis produced". A reader can't tell from the name alone which one carries which data without grepping. Some of this is unavoidable (the JSON-wire / typed-IR split is real), but the naming compounds the difficulty.

### `pub(crate)` on internals is broad

`OwnerGraph` fields are `pub(crate)` not `pub`, which is the right scope; but `pub(crate)` means every module in the crate can mutate them. With `RealizabilityIndex` holding owner-edge references, `IncrementalQuotient` maintaining bucket state derived from the owner graph, and `OwnerGraph::from_report` reconstructing it from JSON, the _crate-internal_ invariant surface is large. The `no_consumer_calls_is_cross_module_at_init_promotion_directly` test (`graph.rs:1637`) is a tell — when a project starts adding _grep-based invariant tests_ to keep parallel call sites in sync, that's the signal that the type system isn't carrying the invariant.

## Name overloading

In addition to `ChunkAnalysis` ×2 (covered above), watch out for:

- **`ChunkFactorization` vs `ChunkAnalysis`**: both are per-chunk IR; the difference is whether the partition is applied. Could be `ChunkAnalysis` (no partition) vs `FactorizedChunk` (partition applied) and the meaning would be more obvious.
- **`ChunkAnalysisOptions`** (`spec.rs:104`) is a _spec-side_ per-chunk knob holder; **`OwnerGraphOptions`** (`graph.rs:21`) is the _graph-build-side_ knob holder; the materializer copies one field from the former into the latter (`lowering/materialize/mod.rs:435–439`). The duplication of "options" types with the same one field (`dataflow_aware_s_chain`) is a sign that the type is doing too little — fold them together once Stage A is genuinely cacheable (Stage A's cache key needs `OwnerGraphOptions`, so the spec/graph boundary forces a copy today).
- **`linker_order` (`Vec<String>` in `FactorizationReport`)** vs **`linker_order` (`Vec<ModuleId>` in `ChunkFactorization`)** vs **`chunk_linker_order` (`BTreeMap<ModuleId, usize>` in `graph.rs`)** — three different shapes for "the toposort of the constraining-edge graph", differing in element type and whether it's "list" or "map (position lookup)". Pick one canonical type, derive the others.
- **`UnrealizableScc` (`realizability.rs:50`)** vs **`CycleReport` (`validation.rs:35`)** vs **`QuotientSccReport` (`report_schema.rs`)** vs **`AtomicUnitConflict` (`factor_assembly.rs:35`)** — four representations of "the spec is unrealizable, here's why" with subtly different fields. `UnrealizableScc` carries `constraining_owner_edges`; `CycleReport` carries `cut` (a minimum cut) + `evidence`; `QuotientSccReport` carries `module_edge_ids` + `constraining_module_edge_ids`. Two of these contain the same data ("the modules in the SCC + the edges in the SCC"), with the cut/evidence/min decoration added by the validator. The right shape is one core type with optional decorations, not four parallel structs.
- **`AnalysisHints`** (`facts/mod.rs`-exported) lives in `facts`, but holds spec-derived data (`declared_pure`, `declared_pure_new`, `declared_pure_members`, `known_effects`). The data is spec-shaped, the type is in facts. This becomes a problem at Stage A serialization time: Stage A _needs_ the hints (purity inference reads them) but the hints come from the spec which is Stage B's input. Today's pipeline collects them before Stage A runs — fine — but the Stage A cache key has to include the hints, which violates the "Stage A is spec-independent" framing in `PIPELINE_SPLIT.md`.

## Algorithmic clarity (realizability gate, atom detection)

### The gate is _more_ coherent than the maintainer fears, but its docs make it look like a stack of patches

The realizability gate's actual algorithm, read carefully, is:

> Build the canonical constraining-edge view of the I-graph; the gate accepts iff (a) Tarjan on the constraining-edge view has no multi-module SCC, and (b) for every multi-module SCC in the full I-graph that has at least one constraining edge, the ECMA-262 Phase-2 simulator (rooted at residual, with residual's imports sorted by `source_import_position` and every other module's by `linker_position`) yields a post-order with `post_order[target] < post_order[source]` for every constraining edge.

That's one algorithm with two passes. Pass 1 is a cheap necessary condition (mutual at-init cycles can never be rescued by reordering); Pass 2 is the precise condition (the runtime DFS-simulator decides asymmetric cycles). The 2× Tarjan is structural to the algorithm, not patchy. **This is fine.** The DESIGN.md theorem reads cleanly.

What's _patchy_ is:

1. The `gate_constraining_partition_endpoints` / `cross_module_partition_endpoints` split (covered in Executive summary #4).
2. The promoted-edge logic. `EdgeReason::at_init_callee_owner` (`graph.rs:75`) is a side channel on every edge that exists _only_ to decide whether `is_cross_module_at_init_promotion` drops the edge in the lenient view. The data flows through serialization (`EdgeReason::synthetic_with_callee`), through the canonical edge set, through the gate-side endpoints helper. It's loadbearing for soundness (per the `promoted_edge_in_aggregator_cycle_is_unrealizable` regression), but the _concept_ "this is a promoted edge, the gate sees it differently from the emitter" is encoded as a flag on every edge plus a pair of projection helpers plus a documentation history log. Cleaner: an explicit `EdgeRole { Direct, PromotedAtInit { callee_owner: OwnerId } }` enum, with the projection helper consulting the role and the gate/emitter rules being a single `match`.
3. The `EsmEvaluationSimulator::from_adjacency` (`realizability.rs:306`) constructor exists only because the overlay path (`IncrementalQuotient`) has its edges in a different shape than the canonical edge set. So `from_adjacency` rebuilds a fake `ChunkConstrainingEdgeSet { edges: empty_map_for_each_constraining_pair, i_successors }` and feeds it to `build`. This is two structurally identical inputs that diverged because two callers had different sources; the right shape is for `build` to take the two adjacency maps directly. Today's "construct fake edges map" is a kludge to fit the constructor.

### Atomic-units classification has two paths but only one is wired

`atomic_units.rs::compute_atomic_units` is the structural-atom detector (SCCs of the constraining-edge owner graph). `factor_assembly::detect_unit_conflict` is the "did the spec split a unit?" detector. The structural atoms are computed once per chunk (in `compute_owner_graph_and_units_with`), passed through `OwnerGraphAndUnits` to the materializer and into `ChunkFactorization`. Clean — this is the right shape.

Spec-induced atoms (the SCCs of `I ∪ S` under the quotient) are NOT precomputed; they emerge from the realizability primitive. DESIGN.md §"Two classes of atom" labels them as a distinct concept. Today the validator and the realizability primitive each compute them separately (Pass 1 + validation Tarjan); the two computations should be one (see §"Duplicated calculations").

### Tests for `at_init_promotion_drop_unsound_in_cycle` flag exactly the right kind of pattern

`realizability.rs:1986` (`promoted_edge_in_aggregator_cycle_is_unrealizable`) is a test that exists to pin the _re-introduction_ of a previously-fixed bug. The doc-comment narrates the SHA-by-SHA history. Reading that doc-comment is what a regression test should _avoid_ requiring — the structural fix is to make the bug structurally impossible. Today the gate-side / lenient endpoints split is doc-and-test-pinned; an `EdgeRole`-typed solution would let the type checker carry the invariant.

## Pipeline-split risks (factor in the three in-flight branches)

The three in-flight branches are:

- **`feat-cli-module-merge`** — adds a `module merge` CLI subcommand.
- **`feat-facts-wire-format`** — adds wire-format serialization for `StatementFacts` (`facts/wire.rs`).
- **`feat-stage-a-sidecars`** — adds Stage A on-disk JSON sidecars.

### `feat-facts-wire-format`: the `Id` round-trip is the major risk

`facts/wire.rs::IdReport` serializes `(name: Atom, ctxt: u32)`. The `u32` is the `SyntaxContext`'s internal representation. **`SyntaxContext` values are meaningful only within the same SWC `Globals` instance.** If Stage B re-parses the chunk (`PIPELINE_SPLIT.md` recommends this — Option 1 under "What about the AST"), the resolver pass issues fresh `Mark`s, and the `top_level_id`-produced `Id`s won't compare equal to deserialized ones with the old `u32`.

This is testable today: write a unit test that

1. Parses a chunk in one `Globals` scope, runs `analyze_chunk`, serializes via `from_facts`.
2. Drops the `Globals`, parses the same chunk in a fresh `Globals` scope.
3. Deserializes via `to_facts`, calls `top_level_id` on a top-level binding name.
4. Asserts the result `Id` equals the deserialized one.

I believe this currently _would_ fail — though the wire format's `facts_round_trip_unit` test only covers same-process round-trip, where the `Globals` is the same. The test the wire format actually needs is the cross-`Globals` test.

The fix: don't serialize `SyntaxContext`. Stage A serializes `Atom` (the name) plus _whatever metadata Stage B needs to reconstruct the `SyntaxContext`_. For chunk-top-level bindings that's "this name was bound at chunk top level", and Stage B applies `top_level_id(name, chunk_top_level_mark)` to materialize the `Id`. For non-top-level bindings (does the wire format need to carry any? — `lazy_reads` can reference globals, captured names, etc.) we'd need to think harder.

The reachable simplification: the wire format only needs to carry the binding _name_ (the `Atom`), plus an enum tag (`TopLevel | ImportedFromChunk(...) | Global`). Stage B reconstructs `Id`s using its own `top_level_mark`. This avoids round-tripping a meaningless `u32` and makes the wire format `Globals`-agnostic.

This change is structurally large for the in-flight branch — recommend the maintainer of `feat-facts-wire-format` consider it before landing.

### `feat-stage-a-sidecars`: per-concept JSON sidecars vs. one artifact

`PIPELINE_SPLIT.md` recommends Option 1 (one JSON pretty file) but the in-flight `feat-stage-a-sidecars` branch's `output_layout.rs` diff adds three constants (`CHUNK_ANALYSIS_AST_REPORT = "ast.json"`, `CHUNK_ANALYSIS_ATOMIC_UNITS_REPORT = "atomic_units.json"`, `CHUNK_ANALYSIS_MANIFEST_REPORT = "manifest.json"`) — i.e. it's heading for the _multiple files_ shape. Per the PIPELINE_SPLIT.md table, this trades:

- **Pro**: each file is consumable in isolation; e.g. `units` CLI loads only `atomic_units.json`.
- **Con**: load-time hits per file are additive; the existing 3 MB `owner_graph.json` for gaffer becomes 3 MB × N files; the cache-key invalidation surface widens (any file's mtime drift redo-triggers Stage B).

The PIPELINE_SPLIT.md "Recommendation" section actually recommends one file with Option 1 first ("Start with Option 1 (JSON pretty)"). The in-flight branch is going further than the doc recommends. Worth a conversation before landing.

The deeper concern: at gaffer scale the `owner_graph.json` is **3 MB pretty-printed**. Sharding it into 4–5 files doesn't reduce that, it _multiplies_ the read/parse cost. The right answer is probably what `PIPELINE_SPLIT.md` calls Option 4 (binary primary + JSON debug), but landed in a _later_ PR after measuring whether load-time is actually a hot spot. The in-flight branch is doing the file split without that measurement.

**Concrete recommendation for the maintainer**: ask the `feat-stage-a-sidecars` author whether the split into `ast.json` + `atomic_units.json` + `manifest.json` is justified by per-consumer load patterns (i.e. is there a CLI that wants `atomic_units` but not `ast`?). If not, collapse to one file. If yes, document which CLI consumes which file, so future readers see the rationale.

### `feat-cli-module-merge`: doesn't materially conflict with this review

`module merge` reads the Stage A artifact and proposes spec edits. It depends on (a) the artifact existing (so it sits downstream of `feat-stage-a-sidecars`) and (b) the structural-atom detection (which already exists, cleanly, in `atomic_units::compute_atomic_units`). No architectural conflict with the points above.

### General observation on the pipeline split

The PIPELINE*SPLIT.md plan is good, \_for the right level of plumbing*. The current Stage A composer (`stage_one.rs`) is a step toward the split. The next step (sidecar JSON) is in flight. Both are correct.

But the Stage A boundary's _bigger_ payoff would be at the **call-site level**: today the pipeline runs everything inline in `materialize_logical_chunk`, including side-effecting actions (top-level-await `bail!`, redundant-hint stderr). When Stage A becomes its own Bazel action, those side effects move _out of the materializer's process_ and become "produce a Stage A artifact + log warnings as part of that action". The materializer process loads the artifact and _doesn't_ re-emit warnings. The split's correctness depends on the warnings being part of the Stage A artifact's success/failure, not the materializer's. Today the warnings are stderr from the materializer; that has to change. Worth pinning a TODO somewhere in `stage_one.rs` so the reader knows the next step.

## Test-vs-spec drift

### `#[ignore]`d tests are clean

`e2e/purity_test.rs` is the only file with `#[ignore]`d tests, and each names an explicit "Step D"/"Step E in the purity-desiderata follow-up plan" reason. These are documented future work, not drift. Good shape.

### "v2 hypothesis was wrong" — found one comment

`graph.rs:1322` documents that `chunk_source_import_order`'s `None`-after-`Some` clause is "kept for robustness against future filter changes that might admit non-constraining members" — i.e. defensive code for a hypothesis that hasn't been validated. That's mild; not real drift.

### One TODO mismatch

`TODO.md` mentions a `module merge` task (task #73). The `feat-cli-module-merge` branch is in flight. No drift.

### The DESIGN.md vs CODE_REVIEW.md vs README.md vs guide.md split

These four files plus AGENTS.md plus RENAME.md plus FACTORIZE.md plus PIPELINE_SPLIT.md document the same project from seven perspectives. Skimming them, I find:

- DESIGN.md is the canonical theorem + algorithm document.
- AGENTS.md is the canonical "how to work on this crate" document.
- CODE_REVIEW.md is a prior code-review backlog (clearly marked, useful).
- README.md is a marketing-shaped pitch with usage.
- guide.md is shorter intro material.
- TODO.md is a 21K-byte backlog.
- FACTORIZE.md is a focused doc on the factorization step.
- RENAME.md is a focused doc on the readability rename pass.

This is a lot. There is one bit of genuine drift: `PIPELINE_SPLIT.md` describes `factor_assembly::compute_owner_claims` as a public API ("apply spec → claims (factor*assembly::compute_owner_claims)") but `factor_assembly.rs:90` has it as `fn compute_owner_claims` — \_private*. Minor, but evidence that PIPELINE_SPLIT.md was written before the implementation it describes.

## Quick wins (≤30 min each)

1. **Rename `artifact::ChunkAnalysis` → `ChunkAnalysisReport`**. The name disambiguates from `chunk_analysis::ChunkAnalysis`. Mechanical rename, all callers visible.

2. **Delete `chunk_factorization::{compute_linker_order, compute_source_import_order}`**. Build a `ChunkConstrainingEdgeSet` in `ChunkFactorization::build_with` (from the owner graph + partition) and call `graph::{chunk_linker_order, chunk_source_import_order}` instead. Removes ~120 lines of duplicate code.

3. **Make `factor_assembly::compute_owner_claims` `pub`** to match `PIPELINE_SPLIT.md`'s assertion. If the doc is wrong, fix the doc.

4. **Remove the `_callee_module` parameter from `edge_contribution`**. `realizability.rs:614` already has the comment "The `_callee_module` parameter is retained on the signature so call sites that still thread it through don't need their signatures changed; it is no longer consulted." Just remove it from callers (`realizability.rs:611`'s only consumer is callsite-internal); the comment can go.

5. **Make `ModuleQuotient`'s inner field `pub(crate)`** (currently `pub`). Today nothing external depends on the `pub` exposure; the `Deref` is enough for external callers that need read-only access.

6. **Add a `RealizabilityVerdict::scc_partition()` method** that returns the `BTreeMap<ModuleId, usize>` SCC labels computed by Pass 1 + Pass 2. Then `validate_factorization` can build cycle reports from the partition without re-Tarjan-ing the quotient. Drops one `tarjan_scc` call per chunk.

7. **Carry chunk-top-level `Mark` on the typed `Partition`** (or on a `ChunkContext` wrapper) so `top_level_id` lookups don't have to be threaded through every materialize-side function as a separate parameter. Today `lowering/materialize/mod.rs:100` reads it from the AST and threads it through eight call sites.

8. **Pull `apply_member_hints`'s five arguments into `Member::collect_hints(&self, hints: &mut AnalysisHints)`**. Five-arg helper goes away; call site (`lowering/materialize/mod.rs:405–423`) becomes `for m in &req.members { m.collect_hints(&mut hints); }`.

9. **Add a single `EdgeRole` enum** as a field of `EdgeReason` (variants `Direct` / `PromotedAtInit { callee_owner }`) so the gate/lenient projection helpers can fold into one helper that consults the role. Removes the dual `*_partition_endpoints` helpers + their commit-SHA history doc-comments.

10. **`lowering/plans.rs::synthesize_mini_factor_plans` → method on a builder**. Ten-arg function with five `&mut` references becomes `builder.synthesize_mini_factors(precomputed, body, target_dir)`.

## Multi-session refactors (1–3 day projects)

### 1. `ChunkPlanBuilder` extraction

`lowering/materialize/mod.rs::materialize_logical_chunk` (~750 lines) should be split into:

- `ChunkPlanBuilder` (~200 lines) owning the five mutable maps, with methods `add_explicit_request`, `pull_destructure_siblings`, `add_residual_sweep`, `fold_rebind_units`, `synthesize_mini_factors`, `finalize() -> ChunkPlan`.
- `materialize_logical_chunk` shrunk to ~150 lines of sequencing: parse → analyze → build plan → factorize → validate → lower.
- The `MaterializeLogicalChunkInputs` 9-field bag split into `ChunkContext` + `ChunkSpec` + `ChunkAnalysisInputs`.

Entry point: extract `ChunkPlanBuilder` first (its construction lives in lines 130–387 of `materialize/mod.rs`); the rest follows naturally.

### 2. Unify Lemma-2 ordering on `graph.rs` exclusively

Once #1 is done, the chunk_factorization-side `compute_linker_order` / `compute_source_import_order` go away (Quick Win #2). Make `ChunkFactorization` consume `ChunkConstrainingEdgeSet` directly; `graph.rs` becomes the sole source of truth for the constraining-edge view and its ordering. This is structurally aligned with `graph.rs:1135`'s invariant doc-comment ("MUST drive their topology decisions through this single set so they cannot drift apart") which today is enforced only by code review.

Entry point: introduce a `ChunkConstrainingEdgeSet` field on `ChunkFactorization`, populated in `build_with`, then port the materializer's consumers off the `ModuleQuotient`-based linker maps onto the constraining-edge-set-based ones from `graph.rs`.

### 3. `RealizabilityVerdict`-as-SCC-partition

Instead of `RealizabilityVerdict { unrealizable_sccs: Vec<UnrealizableScc>, cross_rebinds: Vec<CrossRebindEdge> }`, expose `RealizabilityVerdict::partition() -> SccPartition` where `SccPartition` carries the full SCC labeling (every module mapped to an SCC id). The unrealizable subset is the labels with `len > 1` and at least one constraining edge inside. `validate_factorization` and `reports::build_quotient_scc_reports` consume the partition directly; they no longer call `tarjan_scc` themselves.

Entry point: add `partition: SccPartition` to the verdict; populate it inside `check_realizability`'s existing Pass 1; adapt `validate_factorization` (`validation.rs:241–323`) to use it.

### 4. `EdgeRole` enum on `EdgeReason`

Folds the dual `cross_module_partition_endpoints` / `gate_constraining_partition_endpoints` into one. Once added, the projection helper consults `edge.reason.role` and applies the correct rule per consumer (gate vs emitter vs reports). The `at_init_callee_owner: Option<OwnerId>` field becomes an `EdgeRole::PromotedAtInit { callee_owner }` variant. The cross-grep-test `no_consumer_calls_is_cross_module_at_init_promotion_directly` (`graph.rs:1637`) goes away — it was a workaround for not having the enum.

Entry point: introduce `enum EdgeRole`; thread it through edge construction in `build_owner_graph_with` + `promote_at_init_calls`; replace the two endpoint helpers with one that takes an `EdgeRole`-aware consumer policy.

### 5. `RollbackDiGraph` ↔ petgraph parity

`RollbackDiGraph` (`rollback_graph.rs`) is a 369-line custom graph with manual `successors`/`predecessors`/`tarjan_scc` (per `CODE_REVIEW.md` P3, line 96). The rollback semantics are useful (the `IncrementalQuotient` depends on them), but the rest of the API surface should be petgraph-compatible. Concrete shape: `RollbackDiGraph` implements `petgraph::visit::IntoNeighbors` / `IntoNeighborsDirected` / `GraphProp`, so `petgraph::algo::tarjan_scc` works directly on it. The hand-rolled Tarjan goes away. The differential test (`tarjan_scc(&petgraph)` vs `RollbackDiGraph::tarjan_scc`) goes away — there's only one implementation.

Entry point: implement the petgraph visit traits on `RollbackDiGraph`; delete the manual Tarjan; convert callers to `petgraph::algo::tarjan_scc(&*rollback_graph)`.

## Concerns to discuss before deciding

### Should Stage A be one file or many?

`PIPELINE_SPLIT.md` recommends one (Option 1 JSON pretty). `feat-stage-a-sidecars` is heading for three or four. Per §"Pipeline-split risks" above, the file split needs justification by per-CLI consumption patterns. If none of the planned CLIs (`peel scc`, `peel units`, `peel patch-plan`, `binding describe`, `cluster`, `module merge`) actually need partial loads, collapse to one. If yes, document the load pattern.

**Decision needed before**: `feat-stage-a-sidecars` lands.

### Does the wire format really need to round-trip `SyntaxContext`?

`facts/wire.rs::IdReport` carries `ctxt: u32`. Per §"Pipeline-split risks", this round-trip is `Globals`-bound and breaks cross-process. The fix may be to **drop the field** and have Stage B reconstruct `Id`s via `top_level_id(name, chunk_top_level_mark)` from a re-parsed AST. But that assumes every `Id` Stage A serializes is chunk-top-level; if any lazy_reads carry non-top-level `Id`s, this assumption fails.

**Decision needed before**: `feat-facts-wire-format` lands.

This is the single biggest correctness risk in the in-flight work. A unit test that round-trips through two `Globals` instances would settle it conclusively — recommend adding one immediately on `feat-facts-wire-format` before merging.

### Two `ChunkAnalysis` types — rename one or merge them?

`artifact::ChunkAnalysis` (report) and `chunk_analysis::ChunkAnalysis` (IR) coexist. The quick fix is to rename one (Quick Win #1). The longer-term question is whether the report shape should be derived from the IR shape via a wire-format adapter (the way `OwnerGraph` ↔ `OwnerGraphReport` works). If yes, the two types collapse into one IR + one auto-derived report.

**Decision needed**: whether the report types are auto-derivable from IR types, or whether they intentionally diverge (e.g. the report has fields the IR doesn't, like `parser: ParserOptionsRecord` for reproducibility).

### Should the gate and the materializer share `EsmEvaluationSimulator`?

Today the simulator in `realizability.rs` is the gate's `cross-checks the materializer would have produced this evaluation order` mechanism. The materializer's own `lowering/imports_cross.rs::cross_module_imports_for_plan` actually produces the import order. If a future refactor moves the import-order computation into one place, the simulator's purpose changes: it stops being "predict what the materializer will do" and becomes "compute the post-order DFS the runtime will produce". Whether to make that refactor depends on how often the simulator and the materializer can drift; today they cannot, because both consume `chunk_linker_order` / `chunk_source_import_order` from `graph.rs`. So as long as those two functions stay sole-source-of-truth, the simulator is safe. If the chunk_factorization-side ordering helpers come back (regression), the simulator breaks. The defense is encoding this in the type system (Multi-session refactor #2).

### Do anonymous statements deserve a first-class `OwnerKind`?

Today an "anonymous statement" is just an `OwnerNode` with empty `declared`. The materializer (`lowering/materialize/mod.rs`) special-cases them via `anonymous_statement_ordinals` + an explicit `anon_residual_sentinel` ModuleId (line 569). The realizability gate doesn't distinguish them. Several diagnostics use the placeholder `<anon stmt #ord>` (`validation.rs:181`). This is a coherent piece of vocabulary that should perhaps be an `OwnerNode::kind` variant rather than a sentinel "empty declared bindings". Worth thinking about at the next refactor — not blocking.

---

**Reviewer note.** All file/line references are at HEAD = `01c149496`. The maintainer should treat this report as a backlog input, not a definitive ordering. The most valuable single change is probably the `ChunkPlanBuilder` extraction (Multi-session refactor #1) — it removes the most code, eliminates the most state-passing, and makes the materializer readable in one sitting. The most urgent before any other change is settling the `Id` round-trip question in `feat-facts-wire-format` before that branch lands.
