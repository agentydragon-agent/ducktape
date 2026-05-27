# Gate-path perf counters (`DEBUNDLE_TIMING=1`)

Permanent diagnostic counters for the proposer's realizability gate
hot path, gated entirely behind the `DEBUNDLE_TIMING` environment
variable. Lives in
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
   reported as `cumulative / count`.
3. **Overlay shape histograms** — `delta.len()`, `additions` (overlay
   entries whose effective edge count > 0 after combining with the
   base), `removals` (effective count ≤ 0). Each histogram tracks
   `count`, `min`, `median`, `p95`, `max`, `mean` via a 4096-entry
   reservoir.
4. **Base-graph snapshot rebuilds** — every time the committed base
   graphs change (`invalidate_cached_simulator` on any push/undo/
   commit), the _next_ gate query runs `tarjan_scc` once on each base
   graph (constraining + I) to emulate the per-push cost of a
   snapshot+clone incremental design. Records per-rebuild
   `nodes_count`, `distinct_edges_count`, `sccs_count`,
   `condensation_edges_count`, plus rebuild call count + cumulative
   time.

The counters live entirely in the tree as permanent diagnostics —
**not** "instrument, measure, strip". They're free when
`DEBUNDLE_TIMING` is unset: a single `OnceLock<bool>` load (~ns), no
atomic increments, no allocations, no shadow Tarjan.

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

```
=== debundle gate perf counters (DEBUNDLE_TIMING=1) ===
scc_containing: 4380 calls (0 overlay-empty, 4380 overlay-nonempty)
  cumulative: 10.251s, per-call avg: 2340.456 µs
base tarjan_scc: 132 calls, cumulative 0.503s, per-call avg 3810.785 µs
  overlay delta.len(): count=4380 min=2 median=7 p95=9 max=33 mean=8.27
  overlay additions: count=4380 min=1 median=3 p95=4 max=16 mean=3.64
  overlay removals: count=4380 min=1 median=4 p95=5 max=17 mean=4.63
  base nodes: count=132 min=175 median=2407 p95=2473 max=9107 mean=1507.65
  base edges (distinct): count=132 min=294 median=11204 p95=11416 max=23472 mean=6164.76
  base SCCs: count=132 min=175 median=879 p95=879 max=6385 mean=705.77
  base condensation edges: count=132 min=294 median=1234 p95=1234 max=9717 mean=1050.10
```

Reading the output:

- `scc_containing` ran 4380 times for 10.25s wall = ~22 % of the
  ~46 s proposer wall, matching the PR #1706 instrumented number
  exactly. **The hotspot is real.**
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
  snapshot-per-push design is ~0.5 s — small relative to the 10.25 s
  spent in `scc_containing`. (Tarjan over the _condensation_ clone is
  much cheaper than this; this number is the upper bound on the
  per-push amortization.)

## Counter design notes

- **`OnceLock<bool>` enabled-check.** First call to
  `gate_perf_counters::enabled()` resolves `std::env::var_os` once;
  every later call is an atomic load. No env-lookup overhead on the
  hot path.
- **Atomic-only hot path.** Each `scc_containing` call adds three
  atomic increments (`SCC_CALLS_TOTAL`, the empty/nonempty bucket,
  one timer add) plus three histogram records. Histogram records do
  one lock acquire on a `Mutex<Vec<u32>>` — the proposer is single-
  threaded so contention is zero.
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
hot-path hypothesis. Keep them gated behind
`gate_perf_counters::enabled()` and follow the atomic-increment +
optional-`Instant` pattern. **Never strip a counter after one
measurement** — the cost of permanent diagnostic infrastructure is
low and the cost of re-instrumenting later is high.
