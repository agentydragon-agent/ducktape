# `modules propose` perf roadmap

Current state and future optimization plan for the proposer hot path.
This is an active roadmap: it lists open or conditional next work, not
completed implementation history.

## Current state

`modules propose --format json` against the tana `78d928dca7` fixture,
using a local source `-c opt` debundle binary:

| Metric                     |  Value |
| -------------------------- | -----: |
| Wall                       |  3.54s |
| Proposals                  |     93 |
| `scc_containing` calls     |     10 |
| `scc_containing` wall      | 0.041s |
| `verdict_touching` calls   |      5 |
| Overlay simulator rebuilds |      5 |
| Overlay simulator wall     | 0.148s |
| Diagnostic translations    |      6 |

The current proposer-latency problem is fixed. A source `fastbuild`
binary measured 124.31s on the same workload; do not use fastbuild
numbers for Rust wall comparisons.

The hot path now asks a boolean question and avoids diagnostic evidence
generation:

```text
greedy_merge_to_convergence
└── merge_preserves_invariants
    └── check_merge_boolean
        └── would_violate_cycle_gate_after_contract
            └── merge_creates_new_constraining_cycle
```

The full verdict/evidence path remains for `contract` and explicit
diagnostic queries:

```text
contract / explicit diagnostic query
└── would_be_cycles_after_contract
    └── realizability_index::verdict_after_moving_owners_touching
        └── verdict_with_overlay_touching(to, &overlay)
            ├── constraining_graph.scc_containing(to)
            ├── i_graph_view.scc_containing(to)
            └── build_simulator / translate_verdict_with_owner_modules
```

## Optimization policy

Do not implement more proposer gate machinery from old profiles. If
proposer latency becomes important again:

1. Build and run an optimized binary (`-c opt`).
2. Capture `DEBUNDLE_TIMING=1` counters on the corpus that matters.
3. Use direct counters for the suspected boundary; profile attribution
   alone is not enough for this code path.
4. Stop if the measured wall delta is inside normal run-to-run noise.

Cheap integer/shape counters should stay always-on. Wall-clock timing,
stderr reports, and shadow graph traversals stay behind
`DEBUNDLE_TIMING=1`.

## P1 backlog

There is no active P1 proposer-latency blocker.

### #1 — Fresh post-fix profile

If proposer wall becomes material again, collect a fresh optimized
profile and fresh `DEBUNDLE_TIMING=1` report. Treat that as the new
source of truth for choosing work.

### #2 — Broaden the boolean gate into `RealizabilityIndex` (conditional)

Do this only if a fresh profile shows simulator/diagnostic work hot
outside the quotient cycle gate. Add a
`would_remain_realizable_after_moving_owners_touching`-style boolean
query to `RealizabilityIndex` and short-circuit in order:

- cross-gate rebind touching the post-move target rejects;
- constraining SCC containing the target with size >= 2 rejects;
- I-SCC size < 2 accepts;
- I-SCC without an effective constraining pair accepts;
- only then build/run the simulator.

Keep the full verdict/evidence path as the diagnostics path and as a
debug oracle.

### #3 — Incremental SCC maintenance on the gate view (conditional)

Do this only if a fresh profile shows `scc_containing` hot again. The
narrow snapshot+clone design works iff `base SCCs <= ~1000` and overlay
`delta.len()` is much smaller than 50; tana's observed shape fits that
envelope. Prefer the broader class-aware gate boundary if it stays
reviewable, because it also removes projection and diagnostic overhead.

### #4 — Skip `build_simulator` rebuild when simulator inputs are unchanged (conditional)

`build_simulator` has a strict-zero fast path
(`overlay_is_simulator_noop`). A looser check could reuse the base
simulator when the overlay's `i_delta` adds no new `(from, to)` pair and
only references base edges that remain positive. Verify this against a
fresh profile before implementing it.

### #5 — Incrementalize `rebuild_class_to_cycle_indices` (corner-case)

`update_cycle_cache_after_merge` calls
`rebuild_class_to_cycle_indices` after every merge. That function clears
`class_to_cycle_indices` and re-walks the entire `cached_cycles` vec:
`O(sum of cycle sizes)` per merge.

This matters only when `cached_cycles` is non-empty. Defer until
profiles show it firing.

### #6 — `sync_index_after_merge` to the persistent realizability index

Every merge pushes deltas to `realizability_index`. Cost depends on the
index's internal representation. Investigate only if a fresh profile
shows this as material.

## P2 alternatives

### #7 — KL/FM refinement pass after greedy

Improves cut quality, not wall. Worth doing if proposal quality becomes
the bottleneck.

### #8 — Topological-sweep alternative driver

`O(V + E)` total, no cycle check needed. Different output character than
agglomerative greedy. Useful as a quality/perf baseline, not a drop-in
implementation detail.

### #9 — 32-bit ClassId / OwnerIdx

Halves cache footprint of edge maps and adjacency vecs. Expected impact
is modest; touch surface is wide.

### #10 — Replace greedy entirely

Louvain-with-constraints, spectral methods, or similar could change the
quality/perf tradeoff but are a separate design project.

## `debundle run`

The `debundle run` pipeline wall is a different optimization surface.
Current unmeasured opportunities:

- **AST-hash codegen cache**: content-address the post-lowering AST and
  reuse SWC emit output when unchanged.
- **Chunk-level incremental rebuild**: hash `(upstream_bytes,
spec_slice, ducktape_version)` per chunk and skip lowering, codegen,
  and reports for unchanged chunks.
- **Opt-in heavy reports**: add `--reports=<list>` so consumers can skip
  atoms / owner_graph / atomic_units / realizability / factorize /
  peel_candidates reports they do not need.

## Avoid

- Do not revive the base-SCC cache + overlay-short-circuit approach.
  The proposer queries the move destination `to`, and candidate overlay
  edges are incident to `to`, so the overlay touches the queried SCC in
  the representative workload.
