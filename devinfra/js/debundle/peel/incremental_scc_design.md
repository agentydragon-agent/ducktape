# Conditional SCC Gate Design

This is a future-plan reference for `OverlayGraphView::scc_containing`
and related proposer gate work. It is not an active implementation plan:
current optimized tana proposer wall is 3.54s, and gate diagnostics are
not the active bottleneck.

## Current decision

Do not implement incremental SCC maintenance unless a fresh optimized
profile shows `scc_containing` hot again. If proposer wall becomes
material, start with the current gate counters and choose the
optimization boundary from the new profile.

The preferred boundary, if simulator or diagnostic work is hot, is a
boolean `RealizabilityIndex` query rather than an SCC-only patch. The
candidate-pop loop needs pass/reject; full `CycleEvidence` should remain
lazy and diagnostic-only.

## Scope

The narrow SCC target replaces this per-query shape:

```text
O(reachable_forward(to) + reachable_reverse(to))
```

with an affected-region query over a maintained quotient view:

```text
O(D + R)
```

where:

- `D` is the overlay size / moved-owner incident-edge count for one
  candidate;
- `R` is the target-specific reachable region in the maintained quotient
  view.

Worst-case `R` is still the whole quotient graph, so this is a better
parameterization rather than a better theoretical bound. Removing the
outer greedy candidate-pop factor requires a different proposer driver,
for example the topological-sweep alternative in
`devinfra/js/debundle/perf/proposer_roadmap.md`.

## Preferred future order

1. Collect a fresh optimized profile plus `DEBUNDLE_TIMING=1` counters.
2. If simulator/diagnostic work is hot, add a boolean
   `RealizabilityIndex` query:
   - reject cross-gate rebinds touching the post-move target;
   - reject constraining SCCs containing the target with size >= 2;
   - accept I-SCC size < 2;
   - accept I-SCCs without an effective constraining pair;
   - build/run the simulator only when cheaper tests cannot decide.
3. If `scc_containing` itself is hot, choose between V1.5 targeted
   condensation reachability, V2 owner-SCC indexing, or the broader
   class-aware gate.
4. Keep the existing full verdict/evidence path as an oracle and as the
   diagnostics path.
5. Ship only if byte-identical proposal JSON still holds and wall moves
   outside normal run-to-run noise.

## V1.5: targeted condensation reachability

V1.5 keeps a per-base-graph snapshot:

```rust
struct BaseSnapshot {
    sccs: Vec<Vec<ModuleId>>,
    scc_of: HashMap<ModuleId, usize>,
    condensation_mult: HashMap<(usize, usize), u32>,
    condensation_out: Vec<Vec<usize>>,
    condensation_in: Vec<Vec<usize>>,
}
```

Per query:

1. Map `to` and overlay endpoints to base SCCs, using synthetic
   singleton SCCs for endpoints absent from the base graph.
2. Project module-edge deltas into SCC-edge deltas.
3. If an overlay removal zeroes an edge inside one base SCC, fall back
   to the current full DFS because the base SCC may split.
4. Run forward and reverse reachability from `target_scc` over effective
   condensation edges.
5. Intersect the visited sets and materialize member modules.

This is the lowest-risk SCC-only design because it keeps the current
module-projection model and needs only localized query changes.

## V2: owner-SCC index plus partition view

The underlying owner graph is constant during `modules propose`; only
its projection through the current module partition changes. V2 exploits
that by computing owner SCCs once and maintaining a partition view:

```rust
struct OwnerSccIndex {
    owner_sccs: Vec<Vec<OwnerId>>,
    owner_scc_of: HashMap<OwnerId, usize>,
    cross_scc_out: Vec<Vec<usize>>,
    cross_scc_in: Vec<Vec<usize>>,
}

struct PartitionView {
    member_count: Vec<HashMap<ModuleId, u32>>,
    multi_module_sccs: HashSet<usize>,
    owner_sccs_per_module: HashMap<ModuleId, HashSet<usize>>,
}
```

Every owner move updates `PartitionView` in the same push/undo lifecycle
as `RealizabilityIndex`. Per-overlay queries apply a temporary diff,
run bidirectional BFS through represented owner SCCs, and materialize
the modules in the target component.

V2 is the faster steady-state SCC design, but it has more maintenance
surface than V1.5.

## Edge cases to cover

- Overlay endpoints absent from the base graph.
- Overlay removals that can split one base SCC.
- Duplicate owner moves in one candidate overlay.
- Push/undo rollback of `PartitionView` and any boolean index state.
- Multi-target or non-standard gate transitions that cannot be modeled
  as one post-merge target module; these must fall back to scoped
  push/verdict/undo or be modeled explicitly.
- Diagnostic drift: boolean pass/reject must stay byte-identical to the
  full verdict path for emitted proposals and reported blockers.

## Tests and gates

- Unit tests for empty overlays, absent endpoints, base-internal edge
  removal fallback, duplicate moves, and rollback.
- Oracle tests comparing boolean results with the current full verdict
  path across synthetic graphs and the tana fixture.
- Corpus gate: `modules propose --format json` remains byte-identical
  against current head.
- Benchmark gate: optimized wall improves by at least 3s averaged across
  interleaved runs, or the change does not ship as a perf fix.
