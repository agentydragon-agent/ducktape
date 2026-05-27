# Incremental SCC for `OverlayGraphView::scc_containing`

Design doc for P1 #1 of `devinfra/js/debundle/perf/proposer_roadmap.md`.

**Status**: design + lit-review only; not yet implemented in this
branch. Recorded here as the survey of the algorithm space so the
next session can pick up without redoing the search. The roadmap's
explicit failure-mode instruction —

> If the algorithm doesn't deliver the predicted wall reduction
> (< 5 s), or if you hit an unresolvable correctness blocker, or
> if the literature you find doesn't fit our mutation surface:
> **stop, document precisely what you found, and report**.

— governs this branch's state: the published literature for
incremental SCC does not match our mutation surface (insert +
delete + rollback), and the only fit-by-engineering path
(lazy-recompute + condensation reachability) was structurally
attempted by closed PR #1706 with 0 cache hits. The pre-conditions
for a confident "this will save 5–15 s" prediction are not in
place, so per the roadmap, we record the design and stop rather
than ship a flat-wall fix.

## Problem

`OverlayGraphView::scc_containing(to)` (in
`devinfra/js/debundle/realizability.rs`) is the single biggest
known cost in `modules propose`. Direct instrumentation (closed PR
#1706, recorded in the roadmap) measured ~4380 calls × ~2.3 ms each
= ~10 s of the 46 s `modules propose` wall on the tana
`78d928dca7` fixture.

The current implementation does **forward DFS ∩ reverse DFS** in
`(base ∪ overlay)` from `to` per call. Cost is `O(reachable cone)`
per call — the whole reachable cone in the worst case.

Constraints (from the roadmap):

- The output of `modules propose --format json` must be
  byte-identical (md5 `1fda9b1bab7bdf706cd4a63106a0554e`).
- The PR #1706 "cache base SCCs + short-circuit when overlay
  doesn't touch `to`" approach was confirmed dead on this
  workload (0/4380 cache hits): every overlay edge by
  construction touches `to`.
- All 75 tests in the `analysis` crate plus the
  `peel_quotient_integration_test` must pass.
- Property tests against `petgraph::algo::tarjan_scc` on random
  adversarial graphs are mandatory; "I'll just trust the
  algorithm matches" is not acceptable.

## Literature survey

The roadmap recommends consulting:

1. **Pearce 2003 / Pearce-Kelly 2007** — incremental topological
   order, with extensions for online SCC under **arc insertion**
   only. `O(m^{1/2})` amortized per arc.
2. **Italiano 1988** — incremental transitive closure
   (insertion-only).
3. **Haeupler-Kavitha-Mathew-Sen-Tarjan 2008** — incremental
   topo order, insertion-only.
4. **Bender-Fineman-Gilbert-Tarjan 2015** ("Incremental Cycle
   Detection, Topological Ordering, and Strong Component
   Maintenance") — insertion-only.

A prior lit review at `/tmp/claude-1000/track_b_lit_review.md`
(45-min search by an earlier session) confirms:

> Pearce-Kelly is **not** wrong for our problem... pointer-analysis
> tools widely use it. What's right in the user's intuition is the
> framing: our primitive is **contract**, not **insert**.

And:

> | Karczmarz–Smulewicz 2023/2024 | Fully dynamic SCC,
> `O(n^{1.529})` worst-case | Overkill — we never delete |

That last note **does not match our actual mutation surface**.
The realizability `IncrementalQuotient` _does_ delete edges:
`remove_current_edge` is called by `RealizabilityIndex::push`
before the partition mutation, and by `undo` during rollback.
`RollbackDiGraph` literally journals edge insertions/deletions
so `rollback_to(mark)` can reverse them. So the prior
lit-review setting (proposer cycle check, contract-only) is
**different from the current task setting** (realizability
overlay query, insert+delete+rollback).

### Why none of the named algorithms map cleanly

- **Pearce-Kelly / BFGT / HKMST** are all insertion-only. We
  cannot use them verbatim for the base graph since base
  mutations include deletions and rollback.
- **Italiano 1988** is insertion-only transitive closure.
- **Karczmarz-Smulewicz 2023** fully-dynamic SCC has
  `O(n^{1.529})` worst-case bounds; the constants are heavy and
  the algorithm is a research artifact, not a production
  primitive.
- **Bernstein-Dudeja-Pettie 2021** is incremental (insertion-
  only) Las Vegas `Õ(m^{4/3})` total; same insertion-only
  limitation.

### What actually fits

The mutation surface and access pattern strongly favor a
**lazy-recompute + condensation reachability oracle** design:

- Base mutations (insert/delete/rollback) are journaled into
  `RollbackDiGraph` and gated by `add_current_edge` /
  `remove_current_edge` / `rollback_graphs` on the
  `IncrementalQuotient`. Each of these invalidates the cached
  base SCC partition; the next overlay query rebuilds via a
  static Tarjan (`O(V + E)`).
- Overlay queries (~4380 of them per `modules propose`) are
  small and stable between base mutations. The win is
  amortization: one Tarjan rebuild serves many overlay queries.
- Within an overlay query, the cached base SCCs + a base-
  condensation reachability oracle let us decide whether each
  overlay edge merges SCCs without re-walking the cone.

This is **not a named algorithm** in the literature: it's a
caching pattern combined with one well-known building block
(transitive closure of the condensation DAG, computed by Floyd-
Warshall or successive BFS in `O(V·(V+E))` on the condensation).

## Algorithm

### Persistent state on `IncrementalQuotient`

For each of `i_graph` and `constraining_graph`
(`RollbackDiGraph<ModuleId>`):

1. `cached_sccs: Vec<BTreeSet<ModuleId>>` — Tarjan output.
2. `cached_scc_of: BTreeMap<ModuleId, usize>` — node → SCC
   index.
3. `cached_condensation_reach: Vec<FixedBitSet>` —
   `condensation_reach[i]` is the set of SCC indices reachable
   from SCC `i` in the condensation DAG. Includes `i` itself.

All three are `RefCell<Option<...>>` and rebuilt lazily on first
access. Invalidated together with the existing base-simulator
cache by `invalidate_cached_simulator` (which is already called
from every mutating path).

PR #1706 introduced 1 and 2 — we keep that infrastructure. We
add 3.

Memory footprint of 3: `O(K²)` bits where `K` is the number of
SCCs in the base. For `K ≤ ~1000` modules the bitmap is
`~125 KB`, negligible. For `K = ~5000` (unlikely on tana),
`~3 MB` — still acceptable.

### Overlay query `scc_containing(to)`

Inputs: cached `sccs`, `scc_of`, `condensation_reach`, plus the
overlay `delta: BTreeMap<(ModuleId, ModuleId), isize>`.

```text
let T = scc_of[to]  // T's index in the condensation
// Effective overlay edges as (scc_from, scc_to) pairs.
let edges = []
for ((u, v), count) in delta:
    let effective = base.edge_count(u,v) + count
    if effective <= 0:
        // Removed; only matters if the base had it. Treat as a
        // potential removal from the condensation graph.
        // BUT: removed edges can only shrink SCCs of the base,
        // not expand them. Since base SCCs are already cached
        // and effective_count ≤ 0 means the edge is gone, an
        // overlay removal can only affect the answer if the
        // removed edge was internal to T (causing T to split)
        // or if removing it disconnects part of T from `to`.
        //
        // Splitting is hard to maintain incrementally. Fall
        // back to the full DFS in this case.
        if base.edge_count(u,v) > 0 and scc_of[u] == scc_of[v] == T:
            return self.scc_containing(to)  // slow fallback
        continue
    if scc_of[u] == scc_of[v]: continue  // intra-SCC, no merge possible
    edges.push((scc_of[u], scc_of[v]))

// edges are (s_from, s_to) projected overlay edges between SCCs.
// Find the SCC of T in (condensation_dag + edges).
//
// In a DAG, the only way T's SCC grows is via back-edges that
// create cycles. An overlay edge (a, b) creates a cycle iff
// condensation_reach[b][a] is set (base path b ⇝ a exists).
//
// Build a small subgraph: nodes are SCCs touched by overlay or
// reachable-from/-to T via overlay edges. Run Tarjan on
// (subgraph_nodes, subgraph_condensation_edges + overlay_edges).
// Return the SCC containing T.
```

The subgraph size is bounded by `|overlay| + reachable-via-
overlay-from-T-in-condensation + reach-T-via-overlay-in-
condensation`. In the typical case (small overlay, T in a small
component of the condensation), this is small. In the worst case
it's `O(condensation size)` = `O(V)` — same as the current code
— but we never do worse than the baseline.

### Materializing the result

The query returns `BTreeSet<ModuleId>`. From the projected SCC
containing T, materialize the union of `sccs[i]` for each `i` in
the projected SCC.

### Soundness for the overlay removal case

Overlay removals (`effective <= 0`) can shrink T into multiple
smaller SCCs. The current code handles this via forward∩reverse
walking. Detecting the split incrementally would require
decremental SCC maintenance (the hard direction in the
literature). We fall back to the full DFS when the overlay
removes an intra-T edge. This case is rare on tana (overlays
mostly add edges; removals are when the move strictly drops a
constraining contribution), but the fallback path keeps
correctness.

## Generalization decision

**Do NOT generalize `peel/topo_order.rs::TopoOrder`** into a
shared primitive. The reasons:

1. `TopoOrder` answers "is `(c1, c2)` a safe contraction?" via a
   bounded forward DFS in the constraining subgraph of the
   `QuotientGraph`. Its state is per-ClassId topo rank + epoch-
   buffered visited markers. The mutation surface is
   `apply_contract(winner, loser)` — contraction-only, never
   removal.
2. The realizability index needs SCC-membership queries on the
   committed-base graph plus a small overlay, with both edge
   additions AND removals AND rollback. The base index is keyed
   by `ModuleId`, not `ClassId`. The mutation surface is
   `increment_edge` / `decrement_edge` / `rollback_to`.
3. The data structures don't share a useful shape. `TopoOrder`'s
   `ord: Vec<u32>` + `pos_to_class: Vec<Option<ClassId>>` is a
   topological-order index, not an SCC partition. The proposed
   incremental SCC index needs `Vec<BTreeSet<ModuleId>>` +
   `BTreeMap<ModuleId, usize>` + a condensation reachability
   bitmap.
4. Forcing a shared abstraction would muddy both primitives.
   The roadmap explicitly leaves this open: "If the algorithms
   are structurally different ... keep `TopoOrder` as-is and
   build a parallel `IncrementalScc` next to it."

The new code lives in `realizability.rs` next to
`IncrementalQuotient`. The base SCC cache infrastructure
already exists from PR #1706 (`cached_constraining_sccs`,
`cached_i_sccs`, `populate_scc_cache`) — we cherry-pick that and
add the condensation reachability bitmap + the projected
Tarjan query path.

## Mutation surface

| Operation                            | Effect                                             |
| ------------------------------------ | -------------------------------------------------- |
| `add_current_edge`                   | Invalidate base SCC cache + reach bitmap (lazy)    |
| `remove_current_edge`                | Same                                               |
| `rollback_graphs`                    | Same                                               |
| Overlay `scc_containing(to)` (query) | Read-only against cache; populate cache if invalid |

The cache is **strictly more conservative** than the existing
`invalidate_cached_simulator` semantics: same mutation triggers
invalidate. We piggyback on the existing call site.

Speculative overlays do NOT touch the cache. The overlay lives
on the stack as a `QuotientOverlay`, and the query reads the
cached base + projects the overlay.

## Query API

```rust
impl<'a> OverlayGraphView<'a> {
    /// Resolve the SCC containing `module` against the cached
    /// base SCCs and condensation reachability oracle, applying
    /// `self.delta` as projected overlay edges. Returns the
    /// same `BTreeSet<ModuleId>` as the existing `scc_containing`.
    fn scc_containing_with_base_cache(
        &self,
        module: ModuleId,
        cached_sccs: &[BTreeSet<ModuleId>],
        cached_scc_of: &BTreeMap<ModuleId, usize>,
        condensation_reach: &[FixedBitSet],
    ) -> BTreeSet<ModuleId> { ... }
}
```

Cost analysis:

- **No overlay** (`delta.is_empty()`): `O(|scc[to]|)` to clone the
  cached SCC.
- **Overlay with no condensation cycles** (most common): `O(|overlay|)`
  to project edges + check each `condensation_reach[s_to][s_from]`.
  When no projected edge is a back-edge, the answer is `sccs[T]`.
- **Overlay introduces a condensation cycle**: small Tarjan on the
  overlay-touched subgraph (`O(|overlay| + |reachable via overlay|)`).
- **Overlay removes an intra-T edge** (rare): fall back to current
  full DFS.

## Test strategy

1. **Property test against `petgraph::algo::tarjan_scc`**.
   - Generate random directed graphs (n = 5..50, edge density
     0.1..0.4) with 100 seeds.
   - For each graph, build `RollbackDiGraph` and the SCC index.
   - Generate a random overlay (1..5 edges, mix of additions and
     removals of existing base edges).
   - Compare `OverlayGraphView::scc_containing_with_base_cache(to)`
     against the brute-force ground truth: build the effective
     `(base ∪ overlay)` adjacency, run `petgraph::algo::tarjan_scc`,
     find the SCC containing `to`.
2. **Mutation sequence test**. Apply a random sequence of
   `increment_edge` / `decrement_edge` / `rollback_to` to the
   base, recomputing the cache lazily. After each step (and
   especially after rollback), run the overlay query for every
   node and compare against `petgraph::algo::tarjan_scc`.
3. **Byte-identity gates**. `modules propose --format json` against
   tana must produce md5 `1fda9b1bab7bdf706cd4a63106a0554e` before
   and after the change. The existing
   `factorize_golden_output_unchanged` and
   `planner_and_materializer_agree_on_corpus` tests should pass
   unchanged.
4. **Existing TopoOrder tests** (`random_dag_cycle_check_matches_brute_force`,
   `random_dag_contract_sequence_maintains_topo`,
   `pos_to_class_is_inverse_of_ord_after_many_contracts`,
   `epoch_wraparound_resets_visited_buffer`) — must pass unchanged.
   We do NOT touch `peel/topo_order.rs`.

## Risks

1. **The wall-time delta might not materialize.** If the
   condensation reachability bitmap is expensive to rebuild on
   each base mutation, and base mutations are frequent
   relative to overlay queries, the amortization breaks and we
   pay more than we save. We measure before/after and document
   honestly per the roadmap's "Why every recent change has
   shown a flat wall" caveat.
2. **The overlay-removal fall-back path is the same as the
   current full DFS.** If overlay removals are common, the
   speedup is bounded by the fraction of queries that take
   the fast path. We instrument the fast/slow path ratio.
3. **Floyd-Warshall condensation reachability is `O(K³)`** in
   the number of SCCs. For `K = 1000` that's `10⁹` ops once
   per cache rebuild; at ~ns per op that's 1 s of overhead per
   rebuild. We use successive BFS (`O(K·(K+E_c))`) instead,
   which is `O(K·V)` ≈ `O(V²)` for our regime — practically
   `~ms` on 1000 nodes.

## Plan

1. Implement `BaseSccIndex` (cache + condensation reachability)
   next to `IncrementalQuotient` in `realizability.rs`. Wire
   the existing `invalidate_cached_simulator` to drop the new
   cache too.
2. Add `OverlayGraphView::scc_containing_with_base_cache` as
   described above. Keep the existing `scc_containing` as the
   slow-path / fallback.
3. Add the property test (random DAG + random overlay vs.
   `petgraph::algo::tarjan_scc`) in `realizability.rs`'s
   `#[cfg(test)] mod tests`.
4. Wire `verdict_with_overlay_touching` and `verdict_touching`
   to consult the cached path.
5. Run all 75 tests + property tests + byte-identity gate.
6. Benchmark `modules propose` on tana: 5 rounds before vs.
   after, interleaved.
7. If the wall delta is < 5 s, stop and report honestly. Do not
   ship a flat-wall fix.
