# Gate-path perf counters and timing report

Permanent diagnostic counters for the proposer's realizability gate.
Cheap shape/count counters are always recorded. `DEBUNDLE_TIMING=1`
enables stderr reporting, wall-clock timing, and expensive shadow
base-Tarjan measurement.

The implementation lives in
`devinfra/js/debundle/realizability.rs::gate_perf_counters`, exposed
through the `SccTimingReporter` RAII guard.

## What's instrumented

The counters cover the path through
`IncrementalQuotient::verdict_with_overlay_touching` plus its
no-overlay cousin `IncrementalQuotient::verdict_touching`:

1. `OverlayGraphView::scc_containing` calls, split into overlay-empty
   and overlay-non-empty.
2. `scc_containing` cumulative wall time, only when
   `DEBUNDLE_TIMING=1`.
3. Overlay shape histograms: `delta.len()`, additions, removals.
4. Verdict counters: `verdict_touching` calls, overlay-call subset,
   realizable/rejected split, SCC sizes, and constraining-pair hits.
5. Simulator counters: requests, structural-no-op vs structural-changed
   split, base rebuild count/time, overlay rebuild count/time.
6. Diagnostic translation counters: translation calls, active vs
   bypassed split, owner-module vector size, unrealizable-SCC count.
7. Base-graph snapshot rebuilds: opt-in shadow `tarjan_scc` over each
   stale base graph to estimate snapshot+clone designs.

When `DEBUNDLE_TIMING` is unset, normal runs still pay only the cheap
counter path: atomic increments plus bounded integer histograms. They do
not call `Instant::now()`, print reports, or run shadow Tarjan
traversals.

## How to run

```bash
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

Use an optimized binary for wall comparisons. Rust `fastbuild` binaries
are not release-comparable for this workload.

## Current representative output

tana `78d928dca7`, source-built `-c opt`, 2026-05-27:

```text
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

Interpretation for current head:

- The proposer emits 93 proposals and currently spends 3.54s wall on
  the representative optimized run.
- Gate diagnostics are not the active wall problem: SCC lookup,
  simulator rebuild, and diagnostic translation counts are single
  digits.
- The next proposer optimization should start from a fresh profile, not
  from pre-fix gate counters.

## Counter design notes

- **`OnceLock<bool>` enabled-check.** First call resolves
  `std::env::var_os`; later calls are atomic loads.
- **Cheap always-on hot path.** Count and shape counters stay ungated.
  The proposer is single-threaded, so the bounded histogram mutex has no
  contention in the expected path.
- **Timing is opt-in.** `Instant::now()`, cumulative nanosecond
  additions, report output, and shadow graph traversals run only when
  `DEBUNDLE_TIMING=1`.
- **Reservoir-sampled histograms.** Each histogram keeps at most
  `RESERVOIR_CAP=4096` samples and computes percentiles on report.
- **Output is stderr.** Stdout is reserved for the proposer's JSON
  output.

## When to extend

Add new counters next to the existing ones in
`realizability::gate_perf_counters` when validating a new hot-path
hypothesis. Keep cheap `O(1)` integer/shape counters ungated; gate only
wall-clock timing, report output, or extra graph traversals behind
`gate_perf_counters::enabled()`.
