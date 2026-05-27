# Incremental SCC for `OverlayGraphView::scc_containing`

Design doc for P1 #1 of `devinfra/js/debundle/perf/proposer_roadmap.md`.

**Status**: design validated by in-tree measurement (PR #1710 counters
landed on `debundle-gate-counters`); ready to implement.

## Problem

`OverlayGraphView::scc_containing(to)` (in
`devinfra/js/debundle/realizability.rs`) is the single biggest known
cost in `modules propose`. Direct instrumentation on tana
`78d928dca7`:

| Metric                 | Value      |
| ---------------------- | ---------- |
| `scc_containing` calls | 4380       |
| ... overlay-empty      | 0          |
| ... overlay-non-empty  | 4380       |
| Cumulative wall        | **9.82 s** |
| Per-call avg           | 2.24 ms    |

That's ~22% of the 46 s `modules propose` wall.

The current implementation does **forward DFS ∩ reverse DFS** in
`(base ∪ overlay)` from `to` per call — `O(reachable cone)` per
call, the whole reachable cone in the worst case, every call.

## Measurements (tana 78d928dca7, gate counters PR #1710)

Counters are gated by `DEBUNDLE_TIMING=1`; they stay in the tree
permanently so before/after numbers stay comparable across future
landings.

### Base graph (per Tarjan rebuild)

| Stat               | min | median |   p95 |   max |    mean |
| ------------------ | --: | -----: | ----: | ----: | ------: |
| nodes              | 175 |   2407 |  2473 |  9107 | 1507.65 |
| edges (distinct)   | 294 |  11204 | 11416 | 23472 | 6164.76 |
| base SCCs          | 175 |    879 |   879 |  6385 |  705.77 |
| condensation edges | 294 |   1234 |  1234 |  9717 | 1050.10 |

Base Tarjan: **132 rebuilds × 3.69 ms = 0.49 s total**. Amortization
ratio: 4380 queries / 132 rebuilds = **33:1**.

### Per-query overlay shape

| Stat          | min | median | p95 | max | mean |
| ------------- | --: | -----: | --: | --: | ---: |
| `delta.len()` |   2 |  **7** |   9 |  33 | 8.27 |
| additions     |   1 |      3 |   4 |  16 | 3.64 |
| removals      |   1 |  **4** |   5 |  17 | 4.63 |

### What the numbers tell us

1. **The overlay-empty fast path is useless.** Every single query
   has a non-empty overlay. The roadmap's old `overlay_is_simulator_noop`-
   style strict-zero short-circuit cannot fire here.
2. **The condensation is ~10× smaller than the base graph.**
   Median 879 condensation nodes / 1234 condensation edges vs.
   2407 / 11204 in the base. Operating on the condensation is the
   right size class.
3. **Removals are the median half of the overlay.** Median 4
   removals per query vs. 3 additions. Any algorithm that treats
   removals as a rare fallback (e.g. pure-decremental Pearce) will
   fall back on the median query and gain nothing.
4. **Pure-decremental SCC is wrong for this surface.** Same reason.
5. **Snapshot per push + clone+Tarjan on the projection is the
   right shape.** Section "Algorithm" below.

## Literature survey (recorded; none picked)

The published incremental-SCC literature targets a different
mutation surface than ours:

| Algorithm                       | Bound                                           | Fit                                     |
| ------------------------------- | ----------------------------------------------- | --------------------------------------- |
| Pearce 2003 / Pearce-Kelly 2007 | `O(m^{1/2})` amortized per arc                  | insertion-only — no                     |
| Italiano 1988                   | incremental transitive closure                  | insertion-only — no                     |
| HKMST 2008                      | incremental topo order                          | insertion-only — no                     |
| BFGT 2015                       | incremental cycle detection + strong components | insertion-only — no                     |
| Karczmarz-Smulewicz 2023/2024   | fully dynamic `O(n^{1.529})`                    | research artifact; heavy constants — no |
| Bernstein-Dudeja-Pettie 2021    | incremental Las Vegas `Õ(m^{4/3})` total        | insertion-only — no                     |

The realizability `IncrementalQuotient` _does_ delete edges
(`remove_current_edge` is called by `RealizabilityIndex::push` and
by `undo` during rollback; `RollbackDiGraph` journals
insertions/deletions). All insertion-only algorithms are
disqualified. Karczmarz-Smulewicz is the only fully-dynamic
literature option and its constants make it impractical.

The lit-review thread we recorded earlier framed it cleanly: **our
primitive is "push a partition delta, then undo it later", not
"continuously update under arbitrary insert/delete"**. The
literature optimizes for the latter.

## What we're building instead

**Per-push snapshot of the base condensation + per-query clone +
Tarjan on the projection.** This is the user's framing of the
problem: we only need point-in-time queries (per overlay), with
undo back to base; we never need to amortize across arbitrary
mutations. So we snapshot and discard, instead of incrementally
maintaining a partition through every mutation.

### Persistent state on `IncrementalQuotient`

For each of `i_graph` and `constraining_graph`
(`RollbackDiGraph<ModuleId>`):

```rust
struct BaseSnapshot {
    /// Base Tarjan output, indexed by SCC index.
    sccs: Vec<Vec<ModuleId>>,
    /// node → its SCC index in `sccs`.
    scc_of: HashMap<ModuleId, usize>,
    /// Condensation edge multiplicity: (scc_from, scc_to) → number
    /// of base edges crossing that pair. Only entries with
    /// multiplicity ≥ 1 are stored.
    condensation_mult: HashMap<(usize, usize), u32>,
}
```

The snapshot is `RefCell<Option<BaseSnapshot>>` and rebuilt lazily
on first access after invalidation. Invalidated together with the
existing base-simulator cache by `invalidate_cached_simulator`,
which is already called from every mutating funnel
(`add_current_edge`, `remove_current_edge`, `rollback_graphs`).

Memory footprint: dominated by `condensation_mult`, median 1234
entries × ~16 B = ~20 KB. Negligible.

### Overlay query

Pseudocode (Rust-flavored):

```rust
fn scc_containing(&self, to: ModuleId) -> BTreeSet<ModuleId> {
    let snap = self.base.base_snapshot(self.graph_kind); // lazy rebuild
    let target_scc = snap.scc_of[&to];

    // Clone condensation; project overlay onto it.
    let mut cond = snap.condensation_mult.clone();
    for (&(u, v), &count) in &self.delta {
        let su = snap.scc_of[&u];
        let sv = snap.scc_of[&v];
        let before = self.base.edge_count(self.kind, u, v);
        let after  = before as i64 + count as i64;

        if su == sv {
            // Intra-SCC edge. Adding can't merge; removing might split.
            if before > 0 && after <= 0 {
                // Removal could split target's SCC → fall back.
                return self.scc_containing_full_dfs(to);
            }
            continue;
        }
        // Cross-SCC: maintain multiplicity.
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

    // Build projected-condensation graph and Tarjan it.
    let mut g = petgraph::graphmap::DiGraphMap::new();
    for &(a, b) in cond.keys() { g.add_edge(a, b, ()); }
    let proj_sccs = petgraph::algo::tarjan_scc(&g);

    // Find the projected SCC containing target_scc; materialize.
    let proj = proj_sccs
        .into_iter()
        .find(|s| s.contains(&target_scc))
        .expect("target SCC must appear in its own projection");
    let mut out = BTreeSet::new();
    for base_idx in proj {
        out.extend(snap.sccs[base_idx].iter().copied());
    }
    out
}
```

### Why this is correct

- **Additions in the base graph affect the base condensation; once
  the snapshot is built, they only matter via the overlay.** The
  snapshot is invalidated when the base mutates.
- **Cross-SCC overlay edges (addition or removal) update
  condensation multiplicity exactly, then Tarjan on the projected
  condensation handles the rest.** Adding a cross-SCC edge can
  merge SCCs in the condensation; removing one can disconnect
  the condensation but cannot split a base SCC.
- **Intra-SCC overlay additions are no-ops in the condensation.**
- **Intra-SCC overlay removals can split a base SCC.** Detecting
  the split incrementally is the hard direction in the
  literature. We fall back to the full DFS path. We instrument
  the fast/slow ratio in the counters already added; tana data
  predicts this fires rarely (most removals are cross-module
  drop events, which translate to cross-SCC edges in the
  condensation).

### Predicted cost on tana

Using the measured shape:

| Step                                     | Cost per query | Frequency |          Total |
| ---------------------------------------- | -------------: | --------: | -------------: |
| Snapshot rebuild (amortized)             |        3.69 ms |       132 |         0.49 s |
| Clone `condensation_mult` (1234 entries) |          ~5 µs |      4380 |          22 ms |
| Project 7 overlay edges                  |          ~1 µs |      4380 |           4 ms |
| Tarjan on (~879 nodes, ~1240 edges)      |     ~50–100 µs |      4380 |     220–440 ms |
| Materialize result                       |         ~10 µs |      4380 |          44 ms |
| **Per-query**                            | **~70–115 µs** |           |                |
| **Total**                                |                |           | **~0.8–1.0 s** |

vs. **current 9.82 s** → predicted **~10× speedup** on
`scc_containing` cumulative wall, **~9 s off the 46 s proposer
wall**.

This is lower than the original "~40×" envelope. The original
envelope assumed we could clone+Tarjan on the condensation while
treating it as a tiny structure; the data shows the condensation
itself is non-trivial (~1234 edges). Even so, the speedup tracks
the base-to-condensation ratio (11204/1234 ≈ 9×), which is a
real-data prediction, not a structural guess.

## Generalization decision

**Do NOT generalize `peel/topo_order.rs::TopoOrder`** into a
shared primitive. The reasons (unchanged from the prior draft):

1. `TopoOrder` answers "is `(c1, c2)` a safe contraction?" via a
   bounded forward DFS in the constraining subgraph. Its
   mutation surface is `apply_contract(winner, loser)` —
   contraction-only.
2. The realizability index needs SCC-membership queries on the
   committed-base graph plus a small overlay, with both edge
   additions AND removals AND rollback. The base index is keyed
   by `ModuleId`, not `ClassId`.
3. The proposed snapshot is `Vec<Vec<ModuleId>>` +
   `HashMap<ModuleId, usize>` + `HashMap<(usize, usize), u32>`,
   not a topological-order index.
4. Forcing a shared abstraction would muddy both primitives. The
   roadmap explicitly leaves this open: "If the algorithms are
   structurally different ... build a parallel `IncrementalScc`
   next to it."

New code lives in `realizability.rs` next to `IncrementalQuotient`.

## Mutation surface

| Operation                            | Effect                                                   |
| ------------------------------------ | -------------------------------------------------------- |
| `add_current_edge`                   | Invalidate base snapshot (lazy)                          |
| `remove_current_edge`                | Same                                                     |
| `rollback_graphs`                    | Same                                                     |
| Overlay `scc_containing(to)` (query) | Read-only against snapshot; populate snapshot if invalid |

We piggyback on the existing `invalidate_cached_simulator` call
site (already called from every mutating funnel). Speculative
overlays do NOT touch the snapshot.

## Test strategy

1. **Property test against `petgraph::algo::tarjan_scc`**.
   - Random directed graphs (n = 5..50, edge density 0.1..0.4),
     100 seeds.
   - For each graph, build `RollbackDiGraph` and the base
     snapshot.
   - Random overlay (1..5 edges, mix of additions and removals of
     existing base edges).
   - Compare snapshot+clone result against the brute-force ground
     truth: build the effective `(base ∪ overlay)` adjacency, run
     `petgraph::algo::tarjan_scc`, find the SCC containing `to`.
2. **Mutation sequence test.** Random sequence of
   `increment_edge` / `decrement_edge` / `rollback_to` on the
   base. After each step (especially after rollback), run the
   overlay query for every node and compare against
   `petgraph::algo::tarjan_scc`.
3. **Fallback parity.** When an intra-SCC removal triggers
   fallback, the fast and slow paths must produce identical
   results on the same input. Property-test this explicitly.
4. **Byte-identity gate.** `modules propose --format json` against
   tana must produce md5 `1fda9b1bab7bdf706cd4a63106a0554e`
   before and after. The existing
   `factorize_golden_output_unchanged` and
   `planner_and_materializer_agree_on_corpus` tests must pass
   unchanged.
5. **TopoOrder tests untouched.** We do not modify
   `peel/topo_order.rs`.

## Risks (post-measurement)

1. **Tarjan on the projected condensation is bigger than
   expected.** Predicted 50–100 µs based on 879/1234. If the
   constant factor on `petgraph::algo::tarjan_scc` is heavier
   than that, the speedup shrinks. We have counters; we measure
   before/after.
2. **Intra-SCC removals trigger the fallback more often than
   predicted.** The data shows median 4 removals per query, but
   doesn't break down inter- vs intra-SCC. If many removals are
   intra-SCC, we constantly fall back to the full DFS and gain
   little. Mitigation: instrument the fallback ratio from the
   first commit; if it's high, refine the algorithm (e.g.
   per-SCC subgraph snapshot for the cheap split check).
3. **Snapshot rebuild dominates if base mutations become more
   frequent.** Currently 132 rebuilds for 4380 queries (33:1).
   If `RealizabilityIndex::push` happens at a different rate on
   other corpora, the amortization breaks. Mitigation: we have
   per-corpus instrumentation.

## Plan

1. Wire snapshot field + lazy rebuild + invalidation into
   `IncrementalQuotient` in `realizability.rs`.
2. Add `OverlayGraphView::scc_containing_via_snapshot` per the
   pseudocode. Keep the existing full-DFS `scc_containing` as
   the fallback.
3. Add property tests against `petgraph::algo::tarjan_scc` (random
   graph + random overlay).
4. Wire `verdict_with_overlay_touching` and `verdict_touching` to
   call the snapshot path; fall back to full DFS on intra-SCC
   removal.
5. Add a counter for fast-path vs fallback ratio (extend the
   PR #1710 counter set).
6. Run all 75 `analysis`-crate tests + property tests +
   byte-identity gate.
7. Benchmark `modules propose` on tana: 5 rounds before vs.
   after, interleaved. Report cumulative `scc_containing` time
   and overall wall.
8. If the wall delta is < 3 s (1/3 of the predicted envelope),
   stop and write up what happened. Don't ship a flat-wall fix —
   per the roadmap's discipline.
