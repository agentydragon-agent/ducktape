# Incremental SCC for `OverlayGraphView::scc_containing`

Design doc for P1 #1 of `devinfra/js/debundle/perf/proposer_roadmap.md`.

**Status**: V1 (snapshot + clone + Tarjan on condensation) in flight on
`debundle-incremental-scc-impl`; V2 (owner-level SCC index + bidirectional
BFS on module quotient) documented as the eventual target. Counters from
PR #1710 are in tree (`DEBUNDLE_TIMING=1`).

## Problem

`OverlayGraphView::scc_containing(to)` (in
`devinfra/js/debundle/realizability.rs`) is the single biggest known
cost in `modules propose`. Direct instrumentation on tana `78d928dca7`:

| Metric                 | Value      |
| ---------------------- | ---------- |
| `scc_containing` calls | 4380       |
| ... overlay-empty      | 0          |
| ... overlay-non-empty  | 4380       |
| Cumulative wall        | **9.82 s** |
| Per-call avg           | 2.24 ms    |

That's ~22% of the 46 s `modules propose` wall.

The current implementation walks forward DFS ∩ reverse DFS in
`(base ∪ overlay)` from `to` per call — `O(reachable cone)` per call
in the **full module graph** (median 2407 nodes / 11204 edges).

## Measurements (tana 78d928dca7, PR #1710 counters)

### Base graph per Tarjan rebuild

| Stat               | min | median |   p95 |   max |    mean |
| ------------------ | --: | -----: | ----: | ----: | ------: |
| nodes              | 175 |   2407 |  2473 |  9107 | 1507.65 |
| edges (distinct)   | 294 |  11204 | 11416 | 23472 | 6164.76 |
| base SCCs          | 175 |    879 |   879 |  6385 |  705.77 |
| condensation edges | 294 |   1234 |  1234 |  9717 | 1050.10 |

Base Tarjan: 132 rebuilds × 3.69 ms = **0.49 s total**. Amortization
ratio: 4380 queries / 132 rebuilds = **33:1**.

### Per-query overlay shape

| Stat          | min | median | p95 | max | mean |
| ------------- | --: | -----: | --: | --: | ---: |
| `delta.len()` |   2 |  **7** |   9 |  33 | 8.27 |
| additions     |   1 |      3 |   4 |  16 | 3.64 |
| removals      |   1 |  **4** |   5 |  17 | 4.63 |

## Architectural insight: the owner graph is monotone

The "decremental" problem in our setting is an **artifact of indexing
at the module-projection level**, not a property of the underlying
graph.

- **Owner graph** `G_O` (`OwnerGraph` in `crate::graph`): nodes are
  `OwnerId`s, edges are owner→owner with reasons (init, rebind, etc.).
  Built once at startup from the source tree. **Edges never
  disappear during a `modules propose` run.** Monotone (in fact
  constant).
- **Module-level graphs** (`i_graph`, `constraining_graph` in
  `IncrementalQuotient`): projections of `G_O` through the current
  partition `P`. An owner edge `o₁ → o₂` becomes a module edge
  `P(o₁) → P(o₂)`. When the partition changes (an owner moves),
  the same owner edge projects to a different module pair —
  the old projection disappears, the new one appears. That is
  why `remove_current_edge` exists.

So "decremental" = **partition re-projection**, not deletion of
underlying edges.

Consequences:

- The literature's hard direction (decremental SCC under arbitrary
  edge deletion — Karczmarz–Smulewicz 2023/2024 territory) is
  unnecessary for our problem.
- An SCC index over the **owner** graph is insertion-only (in fact
  static for the run). Standard Tarjan, computed once.
- The realizability question reduces to a property of
  `(owner_SCCs, partition)`.

This is what makes V2 — and the underlying simplification — possible.

## V2 algorithm (target): owner-level SCCs + bidirectional BFS

Operates on the owner condensation rather than the module graph,
and answers the query without running Tarjan per call.

### Permanent state (computed once at startup)

```rust
struct OwnerSccIndex {
    /// Tarjan output on G_O.
    owner_sccs: Vec<Vec<OwnerId>>,
    /// owner → its SCC index.
    owner_scc_of: HashMap<OwnerId, usize>,
    /// For each SCC, the cross-SCC outgoing successor SCC indices
    /// (deduplicated).
    cross_scc_out: Vec<Vec<usize>>,
    /// Same, reverse direction.
    cross_scc_in: Vec<Vec<usize>>,
}
```

Owner-SCC Tarjan is run once at the start of `modules propose`.
For tana this is ~`O(|owner_graph|)` — sub-second; amortized into
startup.

### Per-committed-partition state (incrementally maintained)

```rust
struct PartitionView {
    /// owner-SCC index → module-id → count of SCC members currently
    /// assigned to that module.
    member_count: Vec<HashMap<ModuleId, u32>>,
    /// owner-SCC indices that currently span 2+ modules. Maintained
    /// as a side effect of `member_count` crossing 1↔0 thresholds.
    multi_module_sccs: HashSet<usize>,
    /// module → owner ids currently in it (for BFS expansion).
    owners_per_module: HashMap<ModuleId, HashSet<OwnerId>>,
}
```

Maintenance hooks: every owner move calls
`partition_view.move_owner(o, from_module, to_module)`. That is
`O(1)` per call (decrement, increment, threshold checks).

The hook attaches to the existing `RealizabilityIndex::push` /
`undo` call sites, not the per-edge `add_current_edge` funnel.

### Per-overlay-query algorithm

`scc_containing(to, overlay)` where `overlay` is a list of
hypothetical `(owner, new_module)` moves.

```rust
fn scc_containing(&self, to: ModuleId) -> BTreeSet<ModuleId> {
    // 1. Hypothetical view: clone the diff effects of the overlay
    //    onto member_count / multi_module_sccs. The overlay has
    //    median 7 owners, so this is O(7).
    let view = PartitionViewDiff::new(&self.partition_view);
    for &(o, new_m) in &self.overlay.moves {
        view.move_owner(o, self.partition.module_of(o), new_m);
    }

    // 2. Bidirectional BFS in the module-quotient projection.
    //
    //    Edges:
    //      (a) "fusion edges" for every owner-SCC in view.multi_module_sccs:
    //          the modules in that SCC's footprint are all forced co-SCC.
    //          Treated as bidirectional during BFS.
    //      (b) "directed edges" from cross_scc_out: for each owner-SCC s
    //          with footprint M_s = view.modules(s), and each successor
    //          s' with footprint M_s', add edges M_s × M_s'. Walked
    //          per-node by indexing through owners_per_module[m].
    //
    //    Starting from `to`, BFS forward and reverse simultaneously,
    //    consulting overlay-modified module assignments where applicable.

    let mut forward = HashSet::from([to]);
    let mut queue = VecDeque::from([to]);
    while let Some(m) = queue.pop_front() {
        for o in view.owners_in_module(m) {
            let s = self.index.owner_scc_of[&o];
            // Fusion edges: every other module in s's footprint.
            for &m_next in view.modules_of(s) {
                if m_next != m && forward.insert(m_next) { queue.push_back(m_next); }
            }
            // Directed forward edges.
            for &s_next in &self.index.cross_scc_out[s] {
                for &m_next in view.modules_of(s_next) {
                    if forward.insert(m_next) { queue.push_back(m_next); }
                }
            }
        }
    }

    let mut reverse = HashSet::from([to]);
    // ... same with cross_scc_in.

    forward.intersection(&reverse).copied().collect()
}
```

### Why this is more efficient than V1

What V2 avoids:

1. **Per-push module Tarjan rebuild.** V1: 132 × 3.69 ms = 0.49 s.
   V2: zero. The owner-SCC index is static.
2. **Per-query clone of the condensation map.** V1: 4380 × ~5 µs = 22 ms.
   V2: a small per-query diff (~7 owners).
3. **Per-query full Tarjan over the condensation.** V1: 4380 ×
   ~50–100 µs = 0.22–0.44 s. V2: bidirectional BFS bounded by
   `to`'s reach in the module quotient — usually a small fraction
   of the graph; the base owner-condensation is a DAG so `to`'s SCC
   is `{to}` plus only what overlay cycles add.

### V2 predicted cost on tana

| Step                        | Cost                                    | × frequency | Total      |
| --------------------------- | --------------------------------------- | ----------- | ---------- |
| Owner Tarjan (startup)      | sub-second                              | 1           | <1 s       |
| Per-push view maintenance   | O(owners-moved) ≈ a few µs              | 132         | <10 ms     |
| Per-query overlay diff      | O(\|overlay\|) ≈ 7 µs                   | 4380        | ~30 ms     |
| Per-query bidirectional BFS | O(\|reach of `to`\|) ≈ 10–30 µs typical | 4380        | ~44–130 ms |
| Per-query materialize       | O(\|SCC of `to`\|) ≈ 10 µs              | 4380        | ~44 ms     |
| **Total replacing 9.82 s**  |                                         |             | **~0.2 s** |

Predicted **~50× speedup** on `scc_containing` cumulative time;
**~9.6 s off the 46 s proposer wall**.

The number is uncertain — typical reach in the module quotient on
tana is unmeasured. Plausible range based on the median condensation
size (879 SCC nodes): if reach is ~10% of the condensation per query,
the bidirectional BFS is ~88 nodes × constant per node, which lands
in the 10–30 µs range. If reach is closer to 100%, V2 approaches V1
in cost but still avoids the per-push 0.49 s rebuild — net gain
remains substantial.

### Implementation surface

- **New module** `peel/owner_scc_index.rs`: `OwnerSccIndex`, built
  once at startup.
- **New module** `peel/partition_view.rs`: `PartitionView`,
  `PartitionViewDiff`, maintained alongside the existing
  `RealizabilityIndex`.
- **Wire** the per-owner-move hook into `RealizabilityIndex::push`
  (currently iterates owner edges; adds the move-owner callback
  there).
- **New** `OverlayGraphView::scc_containing_via_owner_index` —
  the BFS implementation above. Old full-DFS retained as the
  ultimate fallback during V2 rollout.

## V1 algorithm (currently in flight): snapshot + clone + Tarjan

The branch `debundle-incremental-scc-impl` is implementing this.
Lower risk, smaller refactor; gets the ~10× win without touching
the gate's data model. Treat V1 as a stepping stone that:

1. Demonstrates the measurement-driven discipline works (we have
   counters; we benchmark; we ship only if wall moves).
2. Removes the per-query full-graph Tarjan, leaving only the
   per-query condensation-Tarjan + per-push module-Tarjan as
   the remaining costs.
3. Sets up the snapshot lifecycle (lazy build, invalidate on
   push/undo) that V2 will reuse (V2's `PartitionView` is the
   owner-level analogue).

### V1 state on `IncrementalQuotient`

For each of `i_graph` and `constraining_graph`:

```rust
struct BaseSnapshot {
    sccs: Vec<Vec<ModuleId>>,
    scc_of: HashMap<ModuleId, usize>,
    condensation_mult: HashMap<(usize, usize), u32>,
}
```

`RefCell<Option<BaseSnapshot>>`, lazy-rebuilt on first access,
invalidated by the existing `invalidate_cached_simulator` funnel
(already called from every mutating site).

### V1 query path

```rust
fn scc_containing(&self, to: ModuleId) -> BTreeSet<ModuleId> {
    let snap = self.base.base_snapshot(self.graph_kind);
    let target = snap.scc_of[&to];
    let mut cond = snap.condensation_mult.clone();
    for (&(u, v), &count) in &self.delta {
        let su = snap.scc_of[&u]; let sv = snap.scc_of[&v];
        let before = self.base.edge_count(self.kind, u, v);
        let after  = before as i64 + count as i64;
        if su == sv {
            if before > 0 && after <= 0 { return self.scc_containing_full_dfs(to); }
            continue;
        }
        match (before > 0, after > 0) {
            (false, true) => *cond.entry((su, sv)).or_insert(0) += 1,
            (true, false) => {
                let m = cond.get_mut(&(su, sv)).expect("base contributed");
                *m -= 1;
                if *m == 0 { cond.remove(&(su, sv)); }
            }
            _ => {}
        }
    }
    let mut g = petgraph::graphmap::DiGraphMap::new();
    for &(a, b) in cond.keys() { g.add_edge(a, b, ()); }
    let proj_sccs = petgraph::algo::tarjan_scc(&g);
    let proj = proj_sccs.into_iter().find(|s| s.contains(&target)).expect("target present");
    proj.into_iter().flat_map(|i| snap.sccs[i].iter().copied()).collect()
}
```

### V1 predicted cost on tana

| Step                                | × 4380 queries |  Total |
| ----------------------------------- | -------------: | -----: |
| Snapshot rebuild (amortized 33:1)   |              — | 0.49 s |
| Clone `condensation_mult`           |          22 ms |        |
| Project 7 overlay edges             |           4 ms |        |
| Tarjan on (~879 nodes, ~1240 edges) |     220–440 ms |        |
| Materialize                         |          44 ms |        |
| **Total**                           | **~0.8–1.0 s** |        |

Predicted **~10× speedup** on `scc_containing`. **~9 s off the
46 s proposer wall.**

## Generalization decision (unchanged from prior draft)

**Do NOT generalize `peel/topo_order.rs::TopoOrder`** into a
shared primitive. The reasons stand:

1. `TopoOrder` answers "is `(c1, c2)` a safe contraction?" via a
   bounded forward DFS in the constraining subgraph. Mutation
   surface: `apply_contract(winner, loser)` — contraction-only.
2. The realizability index needs SCC-membership queries on the
   committed-base graph plus a small overlay. Mutation surface:
   `increment_edge` / `decrement_edge` / `rollback_to`. Keyed by
   `ModuleId` (V1) or `OwnerId` + partition (V2), not `ClassId`.
3. Data shapes diverge. `TopoOrder` keeps a topological-order
   index; the V1 snapshot keeps a Tarjan partition; the V2 index
   keeps owner-SCC structure + partition view.
4. The roadmap explicitly leaves this open: "If the algorithms
   are structurally different ... build a parallel `IncrementalScc`
   next to it."

V1 lives in `realizability.rs`. V2 introduces `peel/owner_scc_index.rs`
and `peel/partition_view.rs` parallel to (not shared with) `TopoOrder`.

## Test strategy

For both V1 and V2:

1. **Property test against `petgraph::algo::tarjan_scc`.** Random
   directed graphs (n = 5..50, edge density 0.1..0.4), 100 seeds.
   Random overlay (1..5 edges, mix of additions and removals of
   existing base edges). Compare against brute-force ground truth.
2. **Mutation sequence test.** Random `increment_edge` /
   `decrement_edge` / `rollback_to` on the base, recomputing
   lazily. After each step (especially rollback), run the overlay
   query for every node; compare against `petgraph::algo::tarjan_scc`.
3. **Byte-identity gate.** `modules propose --format json` against
   tana must produce md5 `1fda9b1bab7bdf706cd4a63106a0554e`
   before and after. Existing `factorize_golden_output_unchanged`
   and `planner_and_materializer_agree_on_corpus` tests pass
   unchanged.
4. **TopoOrder tests untouched.** `peel/topo_order.rs` not
   modified.

V2 also needs:

5. **Partition-view-diff round-trip.** Apply a `PartitionViewDiff`,
   query, undo the diff; assert the result matches a fresh view
   built from the modified-then-reverted partition state. Catches
   bugs in incremental `multi_module_sccs` maintenance.
6. **Bidirectional BFS termination.** Adversarial graphs (large
   dense cycles in the owner condensation, full-graph reach from
   `to`) — assert termination and correctness even when reach is
   100%.

## Risks

### V1 risks

1. **Tarjan on the projected condensation is bigger than expected.**
   We have counters; we measure before/after.
2. **Intra-SCC removals trigger fallback more often than predicted.**
   The PR #1710 counters can be extended to track the fast/fallback
   ratio. If high, V2's owner-level reformulation avoids the
   intra-SCC fallback entirely (the fusion-edge mechanism handles
   what V1 falls back on).
3. **The 0.49 s base-rebuild cost.** V1 doesn't address this. V2
   does.

### V2 risks

1. **Reach in the module quotient is larger than the 10% guess.**
   If it approaches 100% per query, V2 is comparable to V1 in
   per-query cost. The savings from removing per-push rebuild
   (~58% of V1's total) still hold, but the per-query advantage
   shrinks.
2. **PartitionView maintenance complexity.** Three coupled
   structures (`member_count`, `multi_module_sccs`,
   `owners_per_module`) updated per owner move. Bugs in the
   threshold-crossing logic are a real risk — mitigated by test
   strategy item 5.
3. **Memory.** `owners_per_module` and `member_count` add per-module
   and per-(SCC, module) maps. Should be bounded: a few hundred KB
   on tana. Not a real risk; flagged for completeness.

## Plan

### Phase 1 (in flight): V1

1. ✅ Land gate counters (PR #1710, commit `c4341ae2f`).
2. ⏳ Implement V1 on `debundle-incremental-scc-impl`. Bench-gate:
   if wall delta < 3 s averaged 5 rounds, **stop and report** —
   don't ship a flat-wall fix. Extend counters with fast/fallback
   ratio.

### Phase 2: V2

3. Add `OwnerSccIndex` (one-time Tarjan + cross-SCC adjacency).
4. Add `PartitionView` with incremental maintenance hooked into
   `RealizabilityIndex::push` / `undo`. Property tests for
   diff/undo round-trip.
5. Add `OverlayGraphView::scc_containing_via_owner_index` —
   bidirectional BFS implementation. Property tests.
6. Wire `verdict_with_overlay_touching` / `verdict_touching` to
   V2 path; keep V1 + full-DFS as cascading fallbacks during
   rollout.
7. Bench-gate: if wall delta vs. V1 is < 2 s averaged 5 rounds,
   stop and write up; V2 may be over-engineering for the
   remaining headroom.
8. Once V2 is established, remove V1's `BaseSnapshot` and its
   clone-and-Tarjan path; V2 supersedes it.

### Future (not in this design's scope)

- KL/FM refinement (P2 #5 in the roadmap) — cut quality, not
  wall.
- 32-bit OwnerIdx / ClassId (P2 #7).
- Topological-sweep alternative driver (P2 #6).
