# Augur Rust prototype benchmark

This benchmark fixture covers opening balances, scheduled and recurring
transfers, grouped recurring obligations, FIFO lots, and scheduled sales. It
does not exercise the prototype's tax-accrual path, and the prototype does not
exercise its basic financed-property path. Property lifecycle behavior beyond
purchase, mortgage carrying cost, and property tax is not implemented;
allocation, TLH, and private equity are also still absent.

The canonical generated fixture uses exact integer money and quantity values:

- 100,000 rollouts;
- 60 monthly transitions plus the month-zero snapshot;
- three cash accounts;
- one recurring transfer and one recurring obligation per month;
- two initial VTI lots and two scheduled FIFO sales;
- one row-major `100000 × 61` integer security-price series;
- 36,601,574 serialized bytes.

Fixture generation and JSON parsing happen outside timed regions. The optimized
Rust target also validates the fixture once before warmup and timing.

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
retains its complete dense monthly output for each 10,000-rollout batch. The
differential tests establish exact agreement for the covered behavior; broader
performance claims must wait until the broader property lifecycle, tax payment,
allocation/TLH, private-equity, and failure-trace behavior is implemented and
compared under an equivalent output policy.
