# `modules propose` perf roadmap

Current state of the proposer hot loop, the per-call gate path, and
the open optimization backlog. Updated as work lands — historical
profiles are not retained.

## Current wall (2026-05-27)

`modules propose --format json` against the tana `78d928dca7`
fixture, opt build with `-Cdebuginfo=1`:

| Configuration                    | Wall (3-run avg) |
| -------------------------------- | ---------------: |
| Released opt binary              |          ~46.5 s |
| Current devel (post-#1, #4 land) |          ~46.0 s |

`/usr/bin/time -v` on a representative run: user CPU 46.08 s,
system 0.13 s, wall 46.76 s, 98% CPU. **Pure single-threaded
CPU work, no I/O blocking.** Wall ≈ user CPU.

Output md5 `1fda9b1bab7bdf706cd4a63106a0554e`, byte-identical
across runs and against every prior measurement on the post-PK
head.

## Current top symbols (cpu_core self %)

| Self % | Symbol                                                                |
| -----: | --------------------------------------------------------------------- |
| 16.03% | `analysis::realizability::OverlayGraphView::reachable_from`           |
|  9.82% | `peel::quotient::QuotientGraph::translate_verdict_with_owner_modules` |
|  9.76% | `analysis::graph::chunk_source_import_order_from_adjacency`           |
|  8.09% | `core::hash::BuildHasher::hash_one`                                   |

Direct instrumentation (PR #1706) measured **`scc_containing`
taking ~22 % of total wall** on tana — 4380 calls × ~2.3 ms each
= ~10 s of the 46 s. This is the single biggest known cost.

The proposer's hot path is dominated by the **realizability gate**,
not the cycle check. Per `would_be_cycles_after_contract` the gate
runs the ECMA-262 Phase-2 simulator and walks SCCs on the I- and
constraining-edge views; that's where the cycles go.

Call structure:

```
greedy_merge_to_convergence
└── merge_preserves_invariants
    └── would_be_cycles_after_contract               ← PK fast path (cheap)
        └── realizability_index::verdict_after_moving_owners_touching
            └── verdict_with_overlay_touching(to, &overlay)
                ├── constraining_graph.scc_containing(to)   ← 2× reachable_from
                ├── i_graph_view.scc_containing(to)         ← 2× reachable_from
                └── (if SCC ≥ 2 with constraining edge inside):
                    ├── build_simulator(Some(overlay))      ← toposorts + DFS
                    │   └── chunk_source_import_order_from_adjacency
                    └── translate_verdict_with_owner_modules
```

### Why every recent change has shown a flat wall

A pattern worth flagging. Each of the last four landed P1 items
(FxHash on `owner_id_to_idx`, `rank_candidate` linear merge, epoch
buffer for `would_create_cycle`, translate_verdict reverse index,
FxHash for `EsmIGraph::Visitable`) is structurally correct and
byte-identical, but **none moved wall measurably** (variance ~2 s
on a 46 s base = ~4 % noise floor, no individual fix is large
enough to clear it). Cumulatively they remove ceilings that
would surface on different workloads, but on tana the wall is
sticky.

The cleanest evidence we have: scc_containing is genuinely 22 %
of wall by direct timing. That's a real, measurable bottleneck;
the perf-attribution path for the other symbols may be
distributing cost across hot inlined callers in ways that make
"remove 10 % self" not equal "save 10 % wall".

Future optimizations should ideally come with their own direct
timing instrumentation before/after, not just profile-attribution
predictions.

## P1 backlog (in priority order)

### #1 — Incremental SCC maintenance on `IncrementalQuotient` (open)

**The single biggest known win.** Direct instrumentation showed
`scc_containing` taking ~22 % of wall (PR #1706 closed; see
"Dead ends" below for the failed cache-short-circuit attempt and
why this is the next mechanism).

**Prerequisite — gate-path perf counters (landed).**
[`gate_perf_counters.md`](gate_perf_counters.md) ships the permanent
`DEBUNDLE_TIMING=1` counter suite measuring `scc_containing`
calls/time/overlay-shape and base-graph Tarjan calls/time/shape.
Before picking a specific incremental-SCC algorithm, **re-run with
`DEBUNDLE_TIMING=1`** and verify the cost model matches the chosen
design's assumptions:

- Snapshot+clone design works iff `base SCCs ≤ ~1000` and overlay
  `delta.len()` ≪ 50. Median on tana 2026-05-27 was 879 SCCs and 7
  overlay edits — well inside the envelope.
- Decremental incremental design (Pearce-style) is sensitive to the
  fraction of overlay entries that zero out a base edge (`effective
count ≤ 0`). Tana median: 4 of 7 entries (~57 %), so a
  decremental-only algorithm would hit its fallback case often. Use
  the snapshot+clone path or an algorithm with cheap decremental
  edge maintenance.

Maintain the SCC partition through edge add/remove in-place, with
rollback for speculative overlays. Pearce 2003 ("Algorithms for
Computing Strongly Connected Components") and follow-ups give
`O(δ)` amortized incremental algorithms in the same family as the
Pearce-Kelly incremental topological-order algorithm we already
implemented in `peel/topo_order.rs`.

**Reuse path.** If the published incremental-SCC algorithm shares
the same data shape (ordinal `ord[v]` + `pos_to_class[i]` reverse
index + per-insertion forward/backward walks bounded by an
affected region), the right move is to **generalize `TopoOrder`
into a reusable `IncrementalDigraph` primitive** that answers both
topo-order queries (our existing `would_create_cycle` /
`apply_contract`) and SCC-membership queries (the new
`scc_containing` fast path), then thread the new primitive into
both `peel/quotient.rs` and `realizability::OverlayGraphView`.

If the algorithms are structurally different (e.g. SCC
maintenance needs a separate auxiliary structure for the back-DAG
condensation), keep `TopoOrder` as-is and build a parallel
`IncrementalScc` next to it. Don't force a shared abstraction
that muddies the simpler primitive.

First task: read the Pearce 2003 paper (and Italiano 1988 for the
classic). Decide which algorithm to implement. Spec the data
structure. Then dispatch as a real project, not a one-day
refactor.

### #2 — Skip `build_simulator` rebuild when `effective_simulator_inputs` are structurally unchanged

`build_simulator` has a fast path (`overlay_is_simulator_noop`)
but it's strict-zero. A looser check: if the overlay's `i_delta`
adds no NEW `(from, to)` pair (every delta entry references a
base edge that ends with positive count), the simulator's input
set is unchanged — reuse the base simulator. Need to verify
whether the overlay shape often satisfies this in practice.

Targets the simulator-build cost that surfaces after #1 lands.

### #3 — Incrementalize `rebuild_class_to_cycle_indices` (corner-case)

`update_cycle_cache_after_merge` calls
`rebuild_class_to_cycle_indices` after every merge. That function
clears `class_to_cycle_indices` and re-walks the **entire**
`cached_cycles` vec — `O(sum of cycle sizes)` per merge.

Fires only when `cached_cycles` is non-empty (i.e. the partition
has known cycles). On healthy corpora like tana the post-seed
partition is realizable, `cached_cycles` stays near-empty, and
the function returns early. **Defer until profiles show it
firing.**

### #4 — `sync_index_after_merge` to the persistent realizability index

Every merge pushes deltas to `realizability_index`. Cost depends
on the index's internal representation. **Not measured;**
investigate after the per-pop work flattens.

## P2 architectural alternatives (orthogonal to wall)

### #5 — KL/FM refinement pass after greedy

Improves cut quality 10–30 %. Constant wall cost. Worth doing only
if reviewers complain about proposal _quality_ rather than wall
time.

### #6 — Topological-sweep alternative driver

`O(V + E)` total, no cycle check needed. Different output
character than agglomerative greedy. Useful as a baseline to
measure greedy quality against.

### #7 — 32-bit ClassId / OwnerIdx

Halves the cache footprint of edge maps and adjacency vecs.
~5–10 % expected on tana scale. Wide touch surface; defer.

### #8 — Replace greedy entirely (Louvain-with-constraints, spectral)

Uncertain quality; significant project. Last resort.

## `debundle run` (different command, separate roadmap)

The proposer wall sits at ~46 s; the `debundle run` pipeline wall
is a different optimization surface entirely. Top opportunities,
unmeasured against current head:

- **AST-hash codegen cache** — SWC `emit_with` was historically
  ~30 % of `debundle run` cycles. Content-address the
  post-lowering AST; reuse emit if seen. Biggest cold-wall lever;
  architecturally invasive.
- **Chunk-level incremental rebuild** — hash `(upstream_bytes,
spec_slice, ducktape_version)` per chunk; skip lowering +
  codegen + reports for unchanged chunks. ~10× on hot iteration
  cycles, zero on cold. Architecturally invasive.
- **Opt-in heavy reports** — pipeline always emits atoms /
  owner_graph / atomic_units / realizability / factorize /
  peel_candidates JSON. Most consumers want a subset.
  `--reports=<list>` flag, default to current set. 5–15 % cold
  wall.

## Dead ends (record so we don't redo them)

- **Base SCC cache + short-circuit on overlay** (PR #1706,
  closed). Idea: cache `tarjan_scc(base)` and skip the overlay
  walk when the overlay doesn't touch the queried SCC. Killed by
  0/4380 cache hits on tana:
  `verdict_after_moving_owners_touching` always queries the move
  destination `to`, and every overlay edge by construction is
  incident to a moved owner whose post-move module is `to` — so
  the overlay always touches `to`'s SCC. The cache infrastructure
  is correct and byte-identical but adds ~240 lines of dead code
  on this workload. See P1 #1 for the real fix (incremental SCC
  maintenance).

## Landed log

In rough reverse chronological order. Items are removed from the
backlog once they ship.

- Owner→Module reverse index for `translate_verdict_with_owner_modules` (`9c5c369c6`)
- FxHash for `EsmIGraph::Visitable::Map` (`c11770ea2`)
- Release-mode opt build (`916cee026`, in gaffer via `4d292ae94`)
- FxHash on `owner_id_to_idx` (`febf8f76f`)
- `rank_candidate` linear merge (`febf8f76f`; instrumented dead on tana, ceiling removed)
- Epoch buffer for `would_create_cycle` (`d94d29766`)
- `class_neighbors` non-allocating iter (`641d6d9d3`)
- EdgeState — 7 BTree fields → 2 (`6effc3356`)
- Pearce-Kelly + reverse-index (`40182528f`)
- Quotient-share — 3 redundant `build_module_quotient` calls eliminated (`7fb703299`)
- Options-fold — `ChunkAnalysisOptions` + `OwnerGraphOptions` (`6f5eaa619`)
- `write_tree_reports` rayon (`7b69a8c0f`)
- `lower_chunk` rayon (`951957122`)
- `vendor::strip` rayon
- `materialize_artifact_scripts` rayon
- FAS-by-SCC loop → single condensation pass + constraining-only filter (`529d41e80`)
