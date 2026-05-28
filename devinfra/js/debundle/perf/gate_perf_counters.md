# Gate-path perf counters and timing report

Permanent diagnostic counters for the proposer's realizability gate
hot path. Cheap shape/count counters are always recorded. The
`DEBUNDLE_TIMING` environment variable enables stderr reporting,
wall-clock timing, and the expensive shadow base-Tarjan measurement.
The implementation lives in
`devinfra/js/debundle/realizability.rs::gate_perf_counters`, exposed
through the `SccTimingReporter` RAII guard.

## What's instrumented

The counters cover the path through
`IncrementalQuotient::verdict_with_overlay_touching` (the proposer's
inner loop) plus its no-overlay cousin
`IncrementalQuotient::verdict_touching`:

1. **`OverlayGraphView::scc_containing` calls** — total count, split
   `overlay-empty` (`delta.is_empty()`) vs `overlay-non-empty`.
2. **`scc_containing` cumulative time** — sum of per-call wall
   durations measured via `Instant::elapsed()`. Per-call average is
   reported as `cumulative / count`. Timing is collected only when
   `DEBUNDLE_TIMING=1`.
3. **Overlay shape histograms** — `delta.len()`, `additions` (overlay
   entries whose effective edge count > 0 after combining with the
   base), `removals` (effective count ≤ 0). Each histogram tracks
   `count`, `min`, `median`, `p95`, `max`, `mean` via a 4096-entry
   reservoir.
4. **Verdict counters** — `verdict_touching` calls, overlay-call
   subset, realizable/rejected split, constraining-SCC size, I-SCC
   size, and how often an I-SCC actually contains a constraining pair.
5. **Simulator counters** — simulator requests, structural-no-op vs
   structural-changed split, base rebuild count/time, and overlay
   rebuild count/time. Timing is collected only when
   `DEBUNDLE_TIMING=1`.
6. **Diagnostic translation counters** — verdict-to-`CycleEvidence`
   translation calls, active vs bypassed split, owner-module vector
   size, and unrealizable-SCC count.
7. **Base-graph snapshot rebuilds** — every time the committed base
   graphs change (`invalidate_cached_simulator` on any push/undo/
   commit), the _next_ gate query runs `tarjan_scc` once on each base
   graph (constraining + I) to emulate the per-push cost of a
   snapshot+clone incremental design. Records per-rebuild
   `nodes_count`, `distinct_edges_count`, `sccs_count`,
   `condensation_edges_count`, plus rebuild call count + cumulative
   time. This shadow work is collected only when `DEBUNDLE_TIMING=1`.

The counters live entirely in the tree as permanent diagnostics —
**not** "instrument, measure, strip". When `DEBUNDLE_TIMING` is unset,
normal runs still pay the cheap counter path: atomic increments plus
bounded integer histograms. They do not run `Instant` timing, print
reports, or execute shadow Tarjan traversals.

## How to run

```bash
# Build the local opt+debuginfo binary:
direnv exec . bash -lc 'bazelisk build //devinfra/js/debundle:debundle \
    -c opt --@rules_rust//:extra_rustc_flag=-Cdebuginfo=1 \
    --remote_download_outputs=toplevel'

GRAPH=/path/to/owner_graph.json
MODULES=/path/to/spec/modules

DEBUNDLE_TIMING=1 ./bazel-out/k8-opt/bin/devinfra/js/debundle/debundle \
    modules propose \
    --modules "$MODULES" --graph "$GRAPH" --format json \
    > /tmp/propose.json 2> /tmp/timing.txt
cat /tmp/timing.txt
```

## Example output (tana `78d928dca7`, 2026-05-27)

Representative run from the gaffer-private pinned-binary repin after
PR #1710 landed. `modules propose --format json` emitted 93 proposals;
stdout was the proposal JSON and this report was captured from stderr:

```
=== debundle gate perf counters (DEBUNDLE_TIMING=1) ===
scc_containing: 4380 calls (0 overlay-empty, 4380 overlay-nonempty)
  cumulative: 10.125s, per-call avg: 2311.617 µs
base tarjan_scc: 132 calls, cumulative 0.491s, per-call avg 3721.148 µs
verdict_touching: 2190 calls (2190 overlay), 0 realizable, 2190 rejected
  I-SCC with constraining pair: 2190
simulator requests: 2192 (2 structural-noop, 2190 structural-changed)
  base simulator rebuilds: 2, cumulative 0.076s, per-call avg 37959.328 µs
  overlay simulator rebuilds: 2190, cumulative 21.572s, per-call avg 9850.109 µs
diagnostic translation: 2191 calls (2191 active, 0 bypassed)
  overlay delta.len(): count=4380 min=2 median=7 p95=9 max=33 mean=8.27
  overlay additions: count=4380 min=1 median=3 p95=4 max=16 mean=3.64
  overlay removals: count=4380 min=1 median=4 p95=5 max=17 mean=4.63
  constraining SCC size: count=2190 min=2 median=3 p95=3 max=23 mean=3.16
  I-SCC size: count=2190 min=1524 median=1557 p95=1585 max=2711 mean=1557.43
  diagnostic owner_modules count: count=2191 min=9709 median=9709 p95=9709 max=9709 mean=9709.00
  diagnostic unrealizable SCC count: count=2191 min=0 median=2 p95=2 max=2 mean=2.00
  base nodes: count=132 min=175 median=2407 p95=2473 max=9107 mean=1507.65
  base edges (distinct): count=132 min=294 median=11204 p95=11416 max=23472 mean=6164.76
  base SCCs: count=132 min=175 median=879 p95=879 max=6385 mean=705.77
  base condensation edges: count=132 min=294 median=1234 p95=1234 max=9717 mean=1050.10
```

Reading the output:

- `scc_containing` ran 4380 times for 10.13s wall = ~22 % of the
  ~46 s proposer wall, matching the PR #1706 instrumented number
  exactly. **The hotspot is real.**
- The broader gate path is larger than SCC lookup alone:
  2190 overlay simulator rebuilds took 21.57s cumulative, about
  9.85ms each. A narrow SCC-only optimization can save the 10s slice,
  but the next best design should also avoid per-candidate simulator
  rebuilds where possible.
- Every candidate reaching `verdict_touching` rejected in this run
  (`0 realizable`, `2190 rejected`), yet diagnostic translation still
  ran 2191 times over a 9709-owner module vector. The fast path should
  answer boolean pass/reject first and materialize `CycleEvidence`
  lazily only for diagnostics.
- Every call has a non-empty overlay (`overlay-empty` = 0). That
  matches the verdict from PR #1706's dead-end note: the proposer
  always queries the move destination `to` and every overlay edge is
  by construction incident to `to`. **Any base-SCC short-circuit
  that depends on "overlay doesn't touch this SCC" will see 0/N hits.**
- Overlay shape is small (median delta.len()=7, p95=9, max=33). A
  snapshot+clone design's per-query work is bounded by base
  condensation + overlay edges — clone is cheap.
- Base condensation is small (median 879 SCCs, 1234 condensation
  edges). One `tarjan_scc` on the condensation clone is ~µs, not ms.
- A full `tarjan_scc` on the (uncondensed) base graph takes ~3.8 ms.
  With 132 invalidations per proposer run, the per-push cost of a
  snapshot-per-push design is ~0.5 s — small relative to the 10.13 s
  spent in `scc_containing`. (Tarjan over the _condensation_ clone is
  much cheaper than this; this number is the upper bound on the
  per-push amortization.)

## After quotient boolean split (source-built validation, 2026-05-27)

After splitting `QuotientGraph::merge_preserves_invariants` away from
`would_be_cycles_after_contract`, the same real-corpus proposer run
still emitted **93 proposals** and the captured `--format json` output
was byte-identical to the previous run.

Use an optimized binary when comparing wall time. A source `fastbuild`
binary measured `124.31s` wall on the same graph, which is not
release-comparable for this Rust workload. Rebuilding the same local
source binary with `-c opt` measured:

```
=== debundle gate perf counters (DEBUNDLE_TIMING=1) ===
scc_containing: 10 calls (0 overlay-empty, 10 overlay-nonempty)
  cumulative: 0.041s, per-call avg: 4099.902 µs
base tarjan_scc: 6 calls, cumulative 0.057s, per-call avg 9574.525 µs
verdict_touching: 5 calls (5 overlay), 0 realizable, 5 rejected
  I-SCC with constraining pair: 5
simulator requests: 7 (2 structural-noop, 5 structural-changed)
  base simulator rebuilds: 2, cumulative 0.083s, per-call avg 41338.510 µs
  overlay simulator rebuilds: 5, cumulative 0.148s, per-call avg 29628.586 µs
diagnostic translation: 6 calls (6 active, 0 bypassed)
  overlay delta.len(): count=10 min=2 median=4 p95=12 max=12 mean=5.60
  overlay additions: count=10 min=1 median=2 p95=6 max=6 mean=2.80
  overlay removals: count=10 min=1 median=2 p95=6 max=6 mean=2.80
  constraining SCC size: count=5 min=2 median=23 p95=23 max=23 mean=14.60
  I-SCC size: count=5 min=2360 median=2711 p95=2711 max=2711 mean=2570.80
  diagnostic owner_modules count: count=6 min=9709 median=9709 p95=9709 max=9709 mean=9709.00
  diagnostic unrealizable SCC count: count=6 min=0 median=2 p95=2 max=2 mean=1.67
  base nodes: count=6 min=2559 median=6872 p95=9107 max=9107 mean=5307.33
  base edges (distinct): count=6 min=3454 median=19826 p95=23472 max=23472 mean=12462.83
  base SCCs: count=6 min=2559 median=4502 p95=6385 max=6385 mean=4063.83
  base condensation edges: count=6 min=3454 median=7022 p95=9717 max=9717 mean=5902.67
```

Delta from the baseline:

| Metric                     | Before | After | Change  |
| -------------------------- | -----: | ----: | ------- |
| `scc_containing` calls     |   4380 |    10 | -99.8%  |
| `scc_containing` wall      | 10.13s | 0.04s | -10.08s |
| `verdict_touching` calls   |   2190 |     5 | -99.8%  |
| overlay simulator rebuilds |   2190 |     5 | -99.8%  |
| overlay simulator wall     | 21.57s | 0.15s | -21.42s |
| diagnostic translations    |   2191 |     6 | -99.7%  |
| proposer wall              |   ~46s | 3.54s | ~13x    |

Interpretation: most of the previous `RealizabilityIndex`/simulator
work was not intrinsically needed by the candidate-pop hot path; it was
an artifact of asking the diagnostics API for a boolean answer. The
remaining simulator calls are cold enough that the next optimization
should be driven by fresh wall-profile data, not by the old 2190-call
baseline.

## Counter design notes

- **`OnceLock<bool>` enabled-check.** First call to
  `gate_perf_counters::enabled()` resolves `std::env::var_os` once;
  every later call is an atomic load. No env-lookup overhead on the
  hot path.
- **Cheap always-on hot path.** Each `scc_containing` call adds two
  atomic increments (total + empty/nonempty bucket) plus three
  bounded histogram records. Histogram records do one lock acquire on
  a `Mutex<Vec<u32>>` — the proposer is single-threaded so contention
  is zero.
- **Timing is opt-in.** `Instant::now()` and cumulative nanosecond
  additions run only when `DEBUNDLE_TIMING=1`, because those values
  are only consumed by the stderr report.
- **Reservoir-sampled histograms.** Each histogram keeps at most
  `RESERVOIR_CAP=4096` samples (chosen so the tana ~4380-call stream
  stays ~93 % captured) and computes percentiles by sorting on
  shutdown. Cheap on the hot path; cheap to dump at exit.
- **Base snapshot is opt-in.** The shadow `tarjan_scc` only runs in
  the timing-enabled path. Without `DEBUNDLE_TIMING=1` the
  `base_snapshot_stale` flag costs one `Cell::set(true)` per
  invalidation — negligible.
- **Output is stderr.** Stdout is reserved for the proposer's JSON
  output. The RAII guard installs in `main` and prints on drop, after
  `real_main` returns.

## When to extend

Add new counters next to the existing ones in
`realizability::gate_perf_counters` when you need to validate a new
hot-path hypothesis. Keep cheap shape/count counters ungated; gate
only wall-clock timing, report output, or extra graph traversals behind
`gate_perf_counters::enabled()`. **Never strip a counter after one
measurement** — the cost of permanent diagnostic infrastructure is low
and the cost of re-instrumenting later is high.
