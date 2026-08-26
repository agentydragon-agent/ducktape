# Augur Rust prototype benchmark

This benchmark fixture covers opening balances, scheduled and recurring
transfers, grouped recurring obligations, FIFO lots, and scheduled sales. It
does not exercise the prototype's tax-accrual, security-distribution, financed
property, or property-lifecycle paths. Those paths are differentially tested as
described in [README.md](README.md), but are intentionally outside this narrow
throughput baseline. Allocation, TLH, and private equity are also still absent.

The canonical generated fixture uses exact integer money and quantity values:

- 100,000 rollouts;
- 60 monthly transitions plus the month-zero snapshot;
- three cash accounts;
- one recurring transfer and one recurring obligation per month;
- two initial VTI lots and two scheduled FIFO sales;
- one row-major `100000 × 61` integer security-price series;
- 36,601,574 serialized bytes.

Fixture generation and JSON parsing happen outside timed regions. The optimized
Rust target also validates the fixture once before cold and warm timing.

## 2026-08-25 dense compatibility baseline

The current comparison retains the logical dense output contract on both
engines rather than comparing Rust summaries with JAX dense arrays:

- Rust uses `simulate_dense_validated(...)`: all 61 monthly snapshots and all
  native compatibility-event records are retained, while the Rust-only balanced
  journal is omitted because JAX has no matching channel.
- JAX retains its complete `DenseSimulationOutput` and materializes the lazy
  canonical `EventLog` inside the timed region.
- The fixture's Rust native records expand to exactly the same **2,420,000**
  canonical event rows reported by JAX. Existing differential tests establish
  row/state equality; benchmark checksums only prevent dead-code elimination.

The fixture remains the narrow workload described above. It is now an
apples-to-apples **dense-output** comparison, but not yet a representative
full-feature workload: taxes, bonds, property, allocation, private equity, and
TLH are still absent from this particular generated scenario.

Both commands used 10,000 rollouts × 60 transitions, five measured warm runs,
and the same seven-logical-CPU BuildBuddy runner class.

### Rust dense state and compatibility events

```text
bbr run -c opt //finance/augur/rust:benchmark_driver -- \
  --output-mode dense --rollouts 10000 --horizon-months 60 --repeats 5
```

- cold execution: **4.8413 s**;
- warm median: **0.5221 s**;
- warm runs: 0.5364, 0.5106, 0.5370, 0.5015, 0.5221 s;
- throughput: **19,153 rollouts/s**;
- throughput: **1,149,187 rollout-months/s**;
- peak child RSS: **2,020,068 KiB** (1.93 GiB);
- retained state snapshots: 610,000;
- retained native event records: 1,820,000;
- corresponding canonical event rows: 2,420,000;
- retained journal rows: 0;
- BuildBuddy invocation: `c92bde80-bbc5-49af-ba2b-3d25d887b87f`.

### JAX dense state and canonical events

```text
bbr run -c opt //finance/augur/rust:jax_benchmark_driver -- \
  --rollouts 10000 --horizon-months 60 --repeats 5
```

- cold compile/execution/event decode: **6.1061 s**;
- warm median: **1.9945 s**;
- warm runs: 1.9945, 2.0847, 2.0402, 1.8646, 1.9522 s;
- throughput: **5,014 rollouts/s**;
- throughput: **300,835 rollout-months/s**;
- peak process RSS: **2,109,856 KiB** (2.01 GiB);
- native dense arrays: 70 arrays, 56,180,000 elements, 360,680,000 bytes;
- canonical event frames: 2,420,000 rows, estimated 187,480,000 bytes;
- BuildBuddy invocation: `e0ba90d4-efce-406a-883f-76ba55059215`.

### Interpretation

On this dense-output workload, Rust's warm median is **3.82× faster** and its
measured peak RSS is **4.3% lower** than JAX's. The Rust output is nevertheless
not yet an ideal production layout: it stores rollout-major rich structs and
repeats static string metadata in snapshots/events, whereas JAX stores numeric
columnar arrays and canonical events in Polars columns. That Rust still has a
small measured memory advantage is encouraging, but factoring static metadata
once and retaining numeric state/event columns remains the likely route to a
larger memory win. Rerun this same dense benchmark after that output work rather
than falling back to compact-summary comparisons.

## 2026-08-24 baseline

The BuildBuddy runner exposed seven logical CPUs. These are measurements, not
performance gates.

### Rust compact population output

Command:

```text
bbr run -c opt //finance/augur/rust:benchmark_driver -- \
  --rollouts 100000 --horizon-months 60 --repeats 5
```

Result:

- median: **2.0530 s**;
- runs: 1.9930, 2.0530, 2.0604, 2.1628, 1.9760 s;
- throughput: **48,709 rollouts/s**;
- throughput: **2,922,559 rollout-months/s**;
- peak child RSS: **316,580 KiB**;
- counted journal entries: 12,500,000;
- counted dispositions: 200,000;
- counted tax accruals: 0;
- counted security distributions: 0;
- counted property purchases: 0;
- counted mortgage payments: 0;
- failed rollouts: 0;
- checksum: `13286037983044011749`;
- BuildBuddy invocation: `27f6c83e-8449-400e-b6f8-29c81380578d`.

This path retains fixed-size final summaries for every rollout and does not
allocate monthly snapshots, journals, or event traces. The same state-machine
code records full traces in `simulate(...)` for differential and forensic use.

### Existing JAX dense output

A single 100,000-rollout dense run did not complete on the runner (exit 255,
without a benchmark report). A 10,000-rollout run completed with:

- median: 1.9728 s;
- peak RSS: 1,769,936 KiB;
- BuildBuddy invocation: `7061383d-9f65-4cc8-9c75-363825dd99b3`.

The 100,000-rollout workload was then executed as ten 10,000-rollout batches,
which is an execution detail rather than a domain-model distinction:

```text
bbr run -c opt //finance/augur/rust:jax_benchmark_driver -- \
  --rollouts 100000 --batch-size 10000 --horizon-months 60 --repeats 5
```

Result:

- median: **16.5491 s**;
- runs: 19.2015, 15.8087, 16.4678, 16.5491, 16.6346 s;
- throughput: **6,043 rollouts/s**;
- throughput: **362,558 rollout-months/s**;
- one-batch cold/compile run: 4.0788 s;
- peak process RSS: **3,852,036 KiB**;
- failed rollouts: 0;
- batch checksum: `15196896690608004741`;
- BuildBuddy invocation: `8f6b5234-b79d-485d-ac52-bb397cbd5067`.

## Interpretation

The measured Rust summary path is about 8.1× the rollout-month throughput of
the batched JAX run on this narrow fixture. That is encouraging but not yet a
full-simulator result: Rust retains compact final summaries, while the JAX path
retains its complete dense monthly output for each 10,000-rollout batch. These
numbers and checksums predate the fixture-schema additions for private equity
and TLH; they remain historical evidence for the narrow workload, not a current
equivalent-output benchmark. Broader performance claims must wait for product
metrics, backend contracts, and an equivalent output policy.
