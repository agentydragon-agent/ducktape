# `modules propose` perf roadmap

Current state of the proposer hot loop, the per-call gate path, and
the open optimization backlog. Updated as work lands — historical
profiles are not retained.

## Current wall (2026-05-27)

`modules propose --format json` against the tana `78d928dca7`
fixture, opt build with `-Cdebuginfo=1`:

| Configuration                     | Wall (3-run avg) |
| --------------------------------- | ---------------: |
| Released opt binary               |          ~46.5 s |
| Reference (PK + EdgeState landed) |           46.3 s |

Output md5 `1fda9b1bab7bdf706cd4a63106a0554e`, byte-identical across
runs and against every prior measurement on the post-PK head.

## Current top symbols (cpu_core self %)

| Self % | Symbol                                                                |
| -----: | --------------------------------------------------------------------- |
| 16.03% | `analysis::realizability::OverlayGraphView::reachable_from`           |
|  9.82% | `peel::quotient::QuotientGraph::translate_verdict_with_owner_modules` |
|  9.76% | `analysis::graph::chunk_source_import_order_from_adjacency`           |
|  8.09% | `core::hash::BuildHasher::hash_one`                                   |

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
                        └── iterates ALL owners per verdict (~9709 on tana)
```

## P1 backlog (in priority order)

### #1 — Owner→Module reverse index for `translate_verdict_with_owner_modules`

`translate_verdict_with_owner_modules` (`peel/quotient.rs`)
currently walks every owner per call to find which fall in which
unrealizable SCC. Build a per-call `module_to_owners` inverse from
the passed `owner_modules: &[ModuleId]` once, then iterate per-SCC
in `O(|scc.modules| · avg_owners_per_module)`. Cuts the ~10% self
to ~0.

Smallest contained refactor. High-confidence win.

### #2 — Cache base SCC partition on `IncrementalQuotient`; short-circuit `scc_containing` when overlay doesn't perturb

Every `scc_containing(to)` does 2 fresh `reachable_from` walks on
an overlay view, even when the overlay delta doesn't touch the SCC
of `to`. Cache the base graph's SCC partition (refreshed on
commit, not per speculative check). On `scc_containing(to)`:

- If `overlay.delta` doesn't touch the cached SCC of `to` → return
  cached SCC directly (`O(1)`).
- Otherwise walk only the affected region.

Kills the bulk of the 16% `reachable_from` bucket without touching
the simulator. Larger architectural change than #1 — needs careful
invalidation logic on commit.

### #3 — Skip `build_simulator` rebuild when `effective_simulator_inputs` are structurally unchanged

`build_simulator` has a fast path (`overlay_is_simulator_noop`) but
it's strict-zero. A looser check: if the overlay's `i_delta` adds
no NEW `(from, to)` pair (every delta entry references a base edge
that ends with positive count), the simulator's input set is
unchanged — reuse the base simulator. Need to verify whether the
overlay shape often satisfies this in practice.

### #4 — Swap `RollbackDiGraph`'s internal hasher to FxHash

`core::hash::BuildHasher::hash_one` shows ~8% self in the current
profile, likely from hashbrown probes inside the `RollbackDiGraph`
storage (consulted by every `successors`/`predecessors` call in
the simulator's DFS and the `reachable_from` walks). `rustc-hash`
is already a workspace dep. One-line change if the storage type
allows a hasher parameter.

### #5 — Incrementalize `rebuild_class_to_cycle_indices` (corner-case)

`update_cycle_cache_after_merge` calls `rebuild_class_to_cycle_indices`
after every merge. That function clears `class_to_cycle_indices` and
re-walks the **entire** `cached_cycles` vec — `O(sum of cycle sizes)`
per merge.

Fires only when `cached_cycles` is non-empty (i.e., the partition
has known cycles). On healthy corpora like tana the post-seed
partition is realizable, `cached_cycles` stays near-empty, and the
function returns early. **Defer until profiles show it firing.**

### #6 — `sync_index_after_merge` to the persistent realizability index

Every merge pushes deltas to `realizability_index`. Cost depends on
the index's internal representation. **Not measured;** investigate
after the per-pop work flattens.

## P2 architectural alternatives (orthogonal to wall)

### #7 — KL/FM refinement pass after greedy

Improves cut quality 10–30%. Constant wall cost. Worth doing only if
reviewers complain about proposal _quality_ rather than wall time.

### #8 — Topological-sweep alternative driver

`O(V + E)` total, no cycle check needed. Different output character
than agglomerative greedy. Useful as a baseline to measure greedy
quality against.

### #9 — 32-bit ClassId / OwnerIdx

Halves the cache footprint of edge maps and adjacency vecs. ~5–10%
expected on tana scale. Wide touch surface; defer.

### #10 — Replace greedy entirely (Louvain-with-constraints, spectral)

Uncertain quality; significant project. Last resort.

## `debundle run` (different command, separate roadmap)

The proposer wall sits at ~46 s; the `debundle run` pipeline wall is
a different optimization surface entirely. Top opportunities,
unmeasured against current head:

- **AST-hash codegen cache** — SWC `emit_with` was historically ~30%
  of `debundle run` cycles. Content-address the post-lowering AST;
  reuse emit if seen. Biggest cold-wall lever; architecturally
  invasive.
- **Chunk-level incremental rebuild** — hash `(upstream_bytes,
spec_slice, ducktape_version)` per chunk; skip lowering + codegen
  - reports for unchanged chunks. ~10× on hot iteration cycles, zero
    on cold. Architecturally invasive.
- **Opt-in heavy reports** — pipeline always emits atoms /
  owner_graph / atomic_units / realizability / factorize /
  peel_candidates JSON. Most consumers want a subset.
  `--reports=<list>` flag, default to current set. 5–15% cold wall.

## Landed log

In rough reverse chronological order. Items are removed from the
backlog once they ship.

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
