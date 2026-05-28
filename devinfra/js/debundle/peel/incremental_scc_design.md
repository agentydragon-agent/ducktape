# Incremental SCC for `OverlayGraphView::scc_containing`

Design doc for P1 #1 of `devinfra/js/debundle/perf/proposer_roadmap.md`.

**Status**: V1 (snapshot + clone + Tarjan on condensation) is in flight on
`debundle-incremental-scc-impl`; V1.5 (snapshot + targeted reachability on
the condensation) is the lowest-risk narrow implementation; V2
(owner-level SCC index + bidirectional BFS on module quotient) is the best
narrow `scc_containing` model. The preferred faster steady-state design is
the broader class-aware realizability gate below. Counters from PR #1710
are in tree; cheap shape/count counters should stay always-on, while
`DEBUNDLE_TIMING=1` controls profiling output plus wall-clock and
shadow-Tarjan measurements.

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

## Scope and asymptotic target

The narrow optimization target is `OverlayGraphView::scc_containing(to)`.
That improves the inner gate query but does **not** change the outer
greedy driver's worst-case shape.

Notation:

- `O` = owner nodes, `E` = owner edges.
- `M` = current module/class nodes in the quotient.
- `F` = distinct module-edge pairs in one quotient graph.
- `P` = candidate checks that reach the expensive realizability gate.
- `D` = overlay size / moved-owner incident-edge count for one candidate.
- `R` = target-specific reachable region in the maintained quotient view.

Current gate query, for the SCC part only:

```text
O(reachable_forward(to) + reachable_reverse(to)) in the full module graph
```

In the worst case that is `O(M + F)` per `scc_containing` call, and
`verdict_with_overlay_touching` calls it for both the constraining graph
and the I-graph. The full proposer still has the outer `P` factor:

```text
O(P * (D + M + F + simulator/diagnostic costs))  // worst-case sketch
```

The goal of V1.5/V2 is to turn the `M + F` term into an affected-region
term:

```text
O(P * (D + R + simulator/diagnostic costs))
```

Worst-case `R = M + F`, so this is a better parameterization rather
than a better theoretical bound. The expected win comes from the tana
shape: median base condensation is much smaller than the full graph,
overlay is tiny, and the SCC containing the queried target is expected
to be smaller than the whole condensation.

A broader optimization boundary could do better: make the whole
realizability gate class-contraction-aware, not just its SCC lookup.
That could remove repeated projection, per-query owner-module
translation, and some simulator rebuilds. See "Better design:
class-aware realizability gate" below.

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
    /// module → owner-SCC indices currently represented in it.
    /// This avoids expanding every owner in large modules during BFS.
    owner_sccs_per_module: HashMap<ModuleId, HashSet<usize>>,
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
    //          per-module by indexing through owner_sccs_per_module[m].
    //
    //    Starting from `to`, BFS forward and reverse simultaneously,
    //    consulting overlay-modified module assignments where applicable.

    let mut forward = HashSet::from([to]);
    let mut queue = VecDeque::from([to]);
    while let Some(m) = queue.pop_front() {
        for s in view.owner_sccs_in_module(m) {
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

## V1.5 algorithm: targeted condensation reachability

V1's data model is right, but the query does more work than the caller
needs. `verdict_with_overlay_touching` asks only for the SCC containing
one target module `to`; it does **not** need every SCC in the projected
condensation.

V1.5 keeps the V1 `BaseSnapshot`, but replaces per-query
clone-and-Tarjan with forward/reverse reachability from `to`'s base SCC
inside the effective condensation graph.

### Additional snapshot state

```rust
struct BaseSnapshot {
    sccs: Vec<Vec<ModuleId>>,
    scc_of: HashMap<ModuleId, usize>,
    condensation_mult: HashMap<(usize, usize), u32>,
    condensation_out: Vec<Vec<usize>>,
    condensation_in: Vec<Vec<usize>>,
}
```

`condensation_out` / `condensation_in` are adjacency lists for keys
whose `condensation_mult > 0`. They are built with the snapshot and
never cloned per query.

### Per-query path

1. Map `to` and every overlay endpoint to a base SCC. If an endpoint
   is absent from the base graph, assign it a synthetic singleton SCC
   in the temporary query view.
2. Project the overlay's module-edge deltas into SCC-edge deltas:
   `(u, v, count) -> (scc(u), scc(v), count)`, aggregating counts.
3. If an overlay removal zeroes an edge whose endpoints are inside
   the same base SCC, fall back to the current full DFS. V1.5 still
   treats base SCCs as atomic, and such a deletion can split one.
4. Run DFS/BFS from `target_scc` over effective outgoing condensation
   edges, where effective count is
   `base_condensation_mult + projected_delta`.
5. Run the same in reverse using `condensation_in`.
6. Intersect the two visited sets and materialize the member modules
   from `snapshot.sccs` plus any synthetic singleton SCCs.

Pseudocode:

```rust
fn scc_containing_via_targeted_snapshot(&self, to: ModuleId) -> BTreeSet<ModuleId> {
    let snap = self.base.base_snapshot(self.graph_kind);
    let Ok(projected) = ProjectedOverlay::new(snap, self.delta) else {
        return self.scc_containing_full_dfs(to);
    };
    let target = projected.scc_of(to);

    let forward = projected.reachable(target, Direction::Forward);
    let reverse = projected.reachable(target, Direction::Reverse);

    projected.materialize(forward.intersection(&reverse))
}
```

`ProjectedOverlay::new` returns a fallback sentinel on intra-base-SCC
edge removal that reaches zero.

### Complexity

Let `C` be base condensation nodes, `A` base condensation edges, `D`
overlay entries, and `R_to` the effective forward+reverse reachable
region from `to` in the condensation.

| Step                         | Cost                  |
| ---------------------------- | --------------------- | ------- | --- |
| Snapshot rebuild             | same as V1, amortized |
| Project overlay              | `O(D)`                |
| Targeted forward/reverse BFS | `O(R_to)`             |
| Materialize result           | `O(                   | SCC(to) | )`  |

Worst case is still `O(C + A)` per query, same asymptotic envelope as
V1's condensation Tarjan. Typical case should be lower because it
doesn't scan unrelated condensation components and does not allocate a
fresh graph for Tarjan.

### When V1.5 is still useful

V1.5 is useful if it is the fastest way to land a measured improvement
or if it gives V2/class-aware work a cheap oracle. It is not a required
predecessor.

The main question it answers is how large `to`'s reachable region is
after projection. If `R_to` is small, V1.5 may already remove enough of
the SCC wall. If `R_to` is often near the whole condensation, V2's
per-query BFS will have the same weakness and the right move is probably
to broaden the optimization boundary rather than only changing the SCC
representation.

### V1.5 edge cases

1. **Synthetic singleton SCCs.** `RollbackDiGraph` only stores edge
   endpoints. A queried module with no base incident edges must behave
   as `{to}` unless the overlay connects it. Overlay-only endpoints need
   temporary SCC ids so additions from/to isolated modules participate
   in reachability.
2. **Parallel edge multiplicity.** Removal of one projected edge does
   not remove the condensation adjacency while either the base
   multiplicity or another overlay addition keeps the effective count
   positive.
3. **Base-internal removals.** If `scc(u) == scc(v)` and an overlay
   removal makes the effective module edge count zero, the base SCC may
   split. Fall back to the current full DFS. A later refinement can
   avoid fallback when the affected base SCC is outside both target
   cones, but the first implementation should be conservative.
4. **Self-loops after projection.** Cross-module overlay edges can
   project to `scc(u) == scc(v)`. Additions are no-ops; removals are
   covered by the base-internal fallback rule.
5. **Both graph kinds.** The same snapshot machinery must serve
   `i_graph` and `constraining_graph`; counters should report fallback
   and reach-size histograms split by graph kind.
6. **Dense storage.** Use dense SCC ids, epoch-marked `Vec`s, and small
   overlay maps. Avoid `BTreeSet` in the hot reachability path; sort
   only at the materialization boundary if deterministic output needs it.

## Better design: class-aware realizability gate

The better optimization boundary is not `OverlayGraphView`; it is the
candidate realizability gate inside `QuotientGraph`.

Today the hot path repeatedly translates through a generic partition
surface:

```text
class contraction -> owner move overlay -> ModuleId quotient -> verdict
                  -> owner-module vector -> class evidence
```

That shape is correct and contained, but it pays an abstraction tax:

- the outer mutation is always a class contraction, not an arbitrary
  owner move;
- `QuotientGraph` already has class membership, class adjacency, and
  candidate heap state;
- most candidate checks only need a boolean answer;
- owner-level diagnostic evidence is needed only on rejection;
- the simulator inputs are mostly stable across candidate checks.

The replacement is a class-aware gate kernel that lives inside or next
to `QuotientGraph` and speaks in the same contraction vocabulary as the
greedy.

### Projection node: `GateNodeId`, not raw `ClassId`

The gate must operate at the same projection level as
`RealizabilityIndex`. That is almost class ids, but not exactly:

- most live classes project to their own non-residual gate node;
- every class whose members are all `gate_residual_owners` projects to
  the residual gate node (`ModuleId::logical(0)` today);
- a contraction can promote a gate-residual-only class into a
  non-residual node when it merges with a non-gate-residual class.

So the kernel should use an explicit dense `GateNodeId`:

```rust
struct GateProjection {
    class_to_gate: Vec<Option<GateNodeId>>,
    gate_to_classes: Vec<SmallVec<[ClassId; 2]>>,
    residual_gate: GateNodeId,
    next_gate: usize,
}
```

This preserves current `class_module_id` semantics without repeatedly
materializing `ModuleId` vectors. A future implementation can keep
`ModuleId` as the physical id if that is less churn, but the design
boundary should be "gate node", not "class id".

### Maintained gate edge state

Maintain the edge buckets the realizability gate actually asks about,
keyed by projected gate-node pair:

```rust
struct GatePairState {
    /// Non-rebind owner edges. Presence means I-graph adjacency.
    i_count: u32,
    /// Init-order-constraining non-rebind evidence. Empty means no
    /// constraining edge for Pass 1 or TDZ diagnostics.
    constraining: ConstrainingBucket,
    /// Rebind evidence. Any cross-gate rebind touching the candidate
    /// target rejects the candidate.
    rebinds: SmallVec<[OwnerEdgeId; 1]>,
}

struct ClassAwareGate {
    projection: GateProjection,
    out: Vec<FxHashMap<GateNodeId, GatePairState>>,
    in_neighbors: Vec<FxHashSet<GateNodeId>>,
    constraining_index: GateReachabilityIndex,
    i_index: GateReachabilityIndex,
    simulator_cache: SimulatorCache,
}
```

Filtering rules must exactly mirror the current gate:

- drop same-gate edges;
- rebind edges do not enter I/constraining adjacency; they live only
  in `rebinds`;
- every non-rebind cross-gate edge enters the I graph, including
  `LazyUse`;
- only `reason.constrains_init_order()` edges enter the constraining
  bucket;
- sequenced constraining evidence follows the existing
  `ConstrainingBucket` rule: keep all non-sequenced evidence and at
  most one sequenced edge per pair for diagnostics;
- use the gate-side endpoint semantics (`EndpointView::Gate`), including
  cross-module promoted-at-init edges.

The committed graph can be maintained by relabeling gate nodes on
contract, merging rows/columns and pair buckets. The hypothetical query
uses a non-mutating `ContractView` that maps `{winner_gate, loser_gate}`
to the post-merge gate node and answers adjacency by looking through
that mapping.

### Boolean query first, diagnostics second

The greedy's pop loop wants to know whether a candidate can commit. It
does not need `CycleEvidence` for every passing candidate.

Primary API:

```rust
impl ClassAwareGate {
    fn would_remain_realizable_after_contract(
        &self,
        winner: ClassId,
        loser: ClassId,
    ) -> bool;

    fn rejection_evidence_after_contract(
        &self,
        winner: ClassId,
        loser: ClassId,
    ) -> CycleEvidence;

    fn commit_contract(&mut self, winner: ClassId, loser: ClassId);
}
```

`merge_preserves_invariants` should call only the boolean path.
`would_be_cycles_after_contract` and rejection diagnostics call the
evidence path only after the boolean path says "reject".

During rollout, the evidence path can delegate to the current
`RealizabilityIndex` after the boolean path rejects. That keeps the
fast path honest while avoiding a big diagnostic rewrite up front.

### Boolean algorithm

For candidate `(winner, loser)`:

1. Compute the post-merge `GateNodeId`. This is the class-aware
   equivalent of `projected_winner_module_after_merge`.
2. Build a cheap `ContractView` that remaps the affected gate nodes to
   the post-merge gate node and hides self-loops.
3. Check cross-rebinds touching the post-merge gate node. If any
   effective rebind remains cross-gate, reject.
4. In the constraining graph, compute the SCC containing the post-merge
   gate node. If it has 2+ nodes, reject immediately. This is Pass 1.
5. In the I graph, compute the SCC containing the post-merge gate node.
   If it has fewer than 2 nodes, accept.
6. Check whether that I-SCC contains any effective constraining pair.
   If not, accept.
7. Run the ESM simulator against the effective I adjacency and
   constraining pairs. If any constraining pair inside the I-SCC has
   TDZ order, reject; otherwise accept.

This is the same verdict logic as `RealizabilityIndex`, but without
constructing a generic owner-move overlay or translating the verdict
back through an owner-module vector on the passing path.

### Reachability indexes

For the constraining-only graph, reuse `TopoOrder` where it exactly
matches the current check: contractions over a class/gate DAG. It can
answer many "would this create a strict cycle through the merged node?"
queries without SCC materialization.

For the I graph, keep a separate index. The I graph includes lazy
edges and can need the actual SCC containing the candidate node, not
just a yes/no cycle test. The narrow V2 owner-SCC idea can still be a
component here, but it should be filtered per graph kind and exposed as
a `GateReachabilityIndex`:

```rust
trait GateReachabilityIndex {
    fn scc_containing_in_contract_view(
        &self,
        target: GateNodeId,
        view: &ContractView,
    ) -> SmallVec<[GateNodeId; 8]>;

    fn commit_contract(&mut self, winner: GateNodeId, loser: GateNodeId);
}
```

Important V2 correction: owner-SCCs are correct only when built over
the edge set for the graph being queried. There must be separate
filtered owner-SCC DAGs for the I graph and the constraining graph.
A full-owner-graph SCC index would over-fuse constraining reachability.

### Simulator strategy

The simulator is the remaining broad cost once SCC lookup is cheap.
Do this in layers:

1. Track whether the candidate changes simulator inputs at all:
   effective I adjacency and effective non-empty constraining pairs.
   If not, reuse the committed simulator.
2. If inputs change, rebuild from dense gate-node adjacency, not from
   `ModuleId` maps. This removes projection and ordered-map overhead
   even before true incremental simulation.
3. Only attempt local/incremental post-order maintenance after a
   separate proof. The simulator's DFS starts at residual and import
   order is global; a local edge change can alter traversal order
   outside the candidate SCC. Exact structural-cache reuse is safe;
   approximate local reuse is not.

### Complexity target

Per candidate pop, the intended boolean fast path is:

```text
O(log heap + affected_gate_edges + reach_constraining + reach_i
  + simulator_delta_or_rebuild_if_needed)
```

Passing candidates avoid:

- `OwnerId -> ModuleId` overlay construction for all incident owner
  edges except where bucket maintenance truly needs it;
- `RealizabilityVerdict` allocation;
- `owner_modules` vector construction;
- per-call `module_to_owners` inverse maps;
- diagnostic owner-id sorting.

Committed merge cost is:

```text
O(deg(winner_gate) + deg(loser_gate) + moved_class_members_for_evidence)
```

plus any reachability-index maintenance. The outer greedy still has its
candidate-pop factor `P`; removing that requires changing the proposer
driver, not the gate.

### Edge cases that must be designed explicitly

1. **Residual projection collapse.** Multiple classes may project to
   the same residual gate node. Raw `ClassId` SCCs are wrong here; use
   `GateNodeId`.
2. **Gate-residual promotion.** Merging a gate-residual-only class with
   a non-gate-residual class can move both winner and loser from the
   residual gate node to a non-residual gate node. This replaces the
   current multi-target push/undo fallback and must be tested directly.
3. **Rebinds.** Cross-rebinds reject via `cross_rebinds`, but never
   participate in I/constraining SCC reachability.
4. **Promoted-at-init edges.** Use gate-side endpoint semantics, not
   lenient quotient-report semantics.
5. **Sequenced evidence.** The boolean path only needs non-empty, but
   diagnostics must preserve `ConstrainingBucket::evidence_edges`
   behavior.
6. **Dead classes and dead gate nodes.** Class ids are stable and
   emptied on contraction. Gate nodes need a similar tombstone or
   remap discipline so stale heap entries can be rejected cheaply.
7. **Diagnostic laziness.** For byte identity, rejected candidates must
   still produce the same `CycleEvidence` ordering as today. Keep the
   current translator as an oracle until the class-native evidence path
   proves identical.

### Rollout shape

The fastest maintainable route is probably:

1. Add counters around the current path for:
   boolean pass/reject count, diagnostic translation calls,
   simulator structural no-op rate, simulator rebuild time, and
   candidate I-SCC/constraining-SCC sizes. Keep cheap shape/count
   counters ungated; gate only report output, wall-clock timings, and
   extra oracle traversals.
2. Add `ClassAwareGate::would_remain_realizable_after_contract` and
   use it only as a shadow oracle against the current
   `RealizabilityIndex`.
3. Switch `merge_preserves_invariants` to the boolean fast path while
   leaving rejection evidence on the old path.
4. Move rejection evidence generation class-native only after snapshot
   and corpus tests prove byte identity.
5. Then decide whether the I-SCC index should be V1.5, V2, or a
   simpler dense targeted BFS based on measured reach sizes.

## TopoOrder reuse decision

For narrow V1/V1.5/V2, **do NOT generalize
`peel/topo_order.rs::TopoOrder`** into a shared primitive. The reasons
stand:

1. `TopoOrder` answers "is `(c1, c2)` a safe contraction?" via a
   bounded forward DFS in the constraining subgraph. Mutation
   surface: `apply_contract(winner, loser)` — contraction-only.
2. The narrow realizability index needs SCC-membership queries on
   the committed-base graph plus a small overlay. Mutation surface:
   `increment_edge` / `decrement_edge` / `rollback_to`. Keyed by
   `ModuleId` (V1/V1.5) or `OwnerId` + partition (V2), not `ClassId`.
3. Data shapes diverge. `TopoOrder` keeps a topological-order
   index; the V1 snapshot keeps a Tarjan partition; the V2 index
   keeps owner-SCC structure + partition view.
4. The roadmap explicitly leaves this open: "If the algorithms
   are structurally different ... build a parallel `IncrementalScc`
   next to it."

V1 lives in `realizability.rs`. V2 introduces `peel/owner_scc_index.rs`
and `peel/partition_view.rs` parallel to (not shared with) `TopoOrder`.

The broader class-aware gate may reuse `TopoOrder`'s contraction-aware
class-DAG state where it exactly matches the constraining-only check.
Do that reuse at the class-aware gate boundary, not inside the narrow
`scc_containing` implementation.

## Test strategy

For the class-aware gate:

1. **Shadow oracle.** For every candidate check in representative
   fixtures, compare `ClassAwareGate::would_remain_realizable_after_contract`
   against the current `RealizabilityIndex` verdict. The boolean path
   must match before it gates production candidates.
2. **Residual projection fixtures.** Cover multiple classes projecting
   to residual, gate-residual promotion to a non-residual gate node, and
   residual-sticky rejected merges.
3. **Edge-kind fixtures.** Pin I-only lazy edges, constraining edges,
   rebind edges, sequenced evidence dedup, and promoted-at-init edges.
4. **Diagnostic byte identity.** For rejected candidates, class-native
   `CycleEvidence` must match the current `translate_verdict...` output
   before replacing the old diagnostic path.
5. **Simulator-cache correctness.** For structural no-op overlays,
   assert committed-simulator reuse matches a fresh simulator rebuild.
   For structural changes, assert dense gate-node rebuild matches the
   current `EsmEvaluationSimulator` inputs.
6. **Corpus byte-identity gate.** `modules propose --format json`
   against tana must produce md5 `1fda9b1bab7bdf706cd4a63106a0554e`
   before and after. Existing `factorize_golden_output_unchanged` and
   `planner_and_materializer_agree_on_corpus` tests pass unchanged.

For narrow V1, V1.5, and V2:

7. **Property test against `petgraph::algo::tarjan_scc`.** Random
   directed graphs (n = 5..50, edge density 0.1..0.4), 100 seeds.
   Random overlay (1..5 edges, mix of additions and removals of
   existing base edges). Compare against brute-force ground truth.
8. **Mutation sequence test.** Random `increment_edge` /
   `decrement_edge` / `rollback_to` on the base, recomputing
   lazily. After each step (especially rollback), run the overlay
   query for every node; compare against `petgraph::algo::tarjan_scc`.
9. **TopoOrder tests untouched.** `peel/topo_order.rs` not
   modified.

V1.5 also needs:

10. **Targeted snapshot parity.** For the same random graph/overlay
    corpus, compare V1.5 against V1 clone+Tarjan and against brute
    force. Include overlay-only singleton endpoints.
11. **Fallback trigger coverage.** Explicit cases where removing the
    last edge inside a base SCC splits it; assert V1.5 falls back and
    matches full DFS.
12. **Reach-size counters.** With `DEBUNDLE_TIMING=1`, record
    condensation forward/reverse visited counts and fallback counts,
    split by graph kind. This decides whether V2 is likely to help.

V2 also needs:

13. **Partition-view-diff round-trip.** Apply a `PartitionViewDiff`,
    query, undo the diff; assert the result matches a fresh view
    built from the modified-then-reverted partition state. Catches
    bugs in incremental `multi_module_sccs` maintenance.
14. **Bidirectional BFS termination.** Adversarial graphs (large
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

### V1.5 risks

1. **Target reach is usually the whole condensation.** Then V1.5 is
   mostly an allocation/Tarjan-constant cleanup, not a structural win.
   The reach-size counters decide this quickly.
2. **Fallback ratio is high.** If many overlays zero out edges inside
   base SCCs, V1.5 falls back to full DFS too often. That is a signal
   to go to V2's owner-level representation or broaden the gate.
3. **Synthetic singleton handling leaks into output ordering.** Keep
   dense temporary ids internal and materialize `BTreeSet<ModuleId>` at
   the boundary to preserve deterministic verdicts.
4. **Overlay aggregation mistakes.** Multiple module-edge edits can
   project to one condensation edge. The projected overlay must
   aggregate counts before reachability; otherwise parallel-edge cases
   will spuriously add or remove reachability.

### V2 risks

1. **Reach in the module quotient is larger than the 10% guess.**
   If it approaches 100% per query, V2 is comparable to V1 in
   per-query cost. The savings from removing per-push rebuild
   (~58% of V1's total) still hold, but the per-query advantage
   shrinks.
2. **PartitionView maintenance complexity.** Three coupled
   structures (`member_count`, `multi_module_sccs`,
   `owner_sccs_per_module`) updated per owner move. Bugs in the
   threshold-crossing logic are a real risk — mitigated by test
   strategy item 5.
3. **Memory.** `owner_sccs_per_module` and `member_count` add per-module
   and per-(SCC, module) maps. Should be bounded: a few hundred KB
   on tana. Not a real risk; flagged for completeness.

### Broad-gate risks

1. **Scope creep.** A class-aware gate touches `QuotientGraph`,
   `RealizabilityIndex`, simulator inputs, and diagnostic translation.
   Do it only after V1.5/V2 measurements show the SCC-only path has
   stopped paying.
2. **Diagnostic drift.** A boolean fast path is easy to make correct;
   lazy evidence is where output drift can hide. Keep the current
   verdict translation as an oracle until byte-identical diagnostics
   are proven.
3. **Multi-target gate-residual transitions.** The current fast path
   assumes one post-merge target module. The class-aware design must
   explicitly preserve the existing scoped push/verdict/undo fallback
   or model those transitions directly.

## Execution guidance

This is not a required staging plan. When implementing, choose the
smartest maintainable solution, even if that means skipping intermediate
V1/V1.5 staging and landing the faster V2 or class-aware gate directly.
Use staging only when it reduces implementation risk, gives an important
measurement, or keeps review size sane. It is acceptable to keep V1
clone+Tarjan only as a debug oracle or temporary fallback during rollout.

Recommended order of decisions:

1. ✅ Initial gate counters are already landed (PR #1710, commit
   `c4341ae2f`). Extend them as cheap always-on counts/histograms;
   `DEBUNDLE_TIMING=1` should only turn on reporting, wall-clock
   timings, and shadow-oracle traversals.
2. Choose the implementation boundary that actually looks best after
   reading the current code: V1.5, V2, or the broader class-aware gate.
   Prefer the faster steady-state design when the complexity is
   tractable.
3. If choosing V1.5, implement the targeted-condensation path:
   - add condensation adjacency (`out` / `in`) to `BaseSnapshot`;
   - add `ProjectedOverlay` with aggregated condensation deltas,
     synthetic singleton endpoint handling, and conservative fallback
     on base-internal edge removals;
   - replace clone+Tarjan with targeted forward/reverse reachability;
   - keep full DFS as the correctness fallback.
4. If choosing V2 directly, maintain `owner_sccs_per_module`, not
   `owners_per_module`, and use V1.5/full-DFS only as rollout
   fallbacks or test oracles if they help.
5. If choosing the class-aware gate directly, start with a boolean
   fast path plus diagnostic-oracle tests, then pull evidence
   translation and simulator input ownership across the boundary.
6. Add counters appropriate to the chosen boundary. Bench-gate: if
   wall delta from current head is < 3 s averaged across 5 interleaved
   rounds, stop and report; do not ship a flat-wall fix.

Possible landing shapes:

- **Single landing:** V1.5 implementation + tests + counters + benchmark
  report, if the diff stays reviewable.
- **Two landings:** snapshot/overlay refactor with oracle tests first,
  targeted reachability + benchmark second.
- **Direct faster landing:** V2 or class-aware gate implementation +
  oracle tests + counters, if it stays coherent and reviewable.

### Future (not in this design's scope)

- KL/FM refinement (P2 #5 in the roadmap) — cut quality, not
  wall.
- 32-bit OwnerIdx / ClassId (P2 #7).
- Topological-sweep alternative driver (P2 #6) — only path here that
  can remove the greedy candidate-pop factor `P`, but it changes output
  character.
