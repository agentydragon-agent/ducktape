# Augur Rust simulator prototype

This directory contains a clean-sheet deterministic simulator that is being
built in parallel with `finance/augur/sim`. It is not yet a replacement for the
existing engine.

## Invariants

- Money is always a checked `i64` count of the fixture's declared currency
  quantum. Products use `i128` intermediates and explicit half-away-from-zero
  rounding.
- Every monetary change is a balanced compound journal entry. Entries are
  validated and applied atomically; signed debits sum to zero.
- Exogenous paths are materialized once into a strict integer fixture. Rust and
  Python/JAX consume the same fixture bytes; Rust does not resample paths.
- Independent rollouts execute in parallel with Rayon and are collected by
  deterministic rollout index.
- Obligations sharing one payer/source account settle all-or-none, matching the
  existing simulator's hard-demand grouping.
- Failed rollouts stop executing future actions and expose zero value-bearing
  snapshots while retaining the preceding causal trace.
- Full forensic output and compact population output use the same state-machine
  implementation. The compact path does not allocate every monthly snapshot or
  journal and is suitable for 100,000-rollout workloads.

## Covered behavior

The differential suite currently proves exact integer agreement for:

- opening balances and opening equity;
- scheduled and recurring transfers;
- initial tax lots and FIFO scheduled sales;
- monthly security distributions based on currently held units;
- financed or cash property purchases with explicit property, mortgage,
  receivable, and counterparty ledger postings;
- property-gated scheduled and recurring cashflows, including ordinary-income
  and deductible-expense tax tagging;
- property sales driven by rollout-scoped home-value paths, including seller
  closing costs, mortgage payoff, realized long-term gain, lifecycle ordering,
  and same-month suppression of property-tied cashflows and carrying costs;
- fixed-payment mortgage origination, monthly interest/principal splitting,
  same-source funding-group settlement, and property-tax carrying costs;
- grouped scheduled and recurring obligations;
- insufficient-cash failure month and state freezing;
- federal and California ordinary-income year-end tax accruals;
- federal long-term-capital-gain stacking and tax accrual;
- generated benchmark fixtures at 17 rollouts.

The Rust ledger also records tax expense/liability accrual entries and preserves
capital-loss carryforward between tax years.

Still missing before replacement is plausible:

- tax payment/safe-harbor/true-up scheduling and broader modeled tax facts;
- policy-driven purchases and taxable distribution character;
- mortgage-interest deduction and contracts beyond the basic fixed-rate
  purchase mortgage;
- property occupancy, improvements, depreciation, §1250 recapture, and §121
  primary-residence exclusion;
- target allocation, liquidity funding, TLH, and private equity;
- complete selected-rollout causal trace parity for those domains;
- Python extension/Arrow output integration.

## Targets

```text
//finance/augur/rust:simulator_cli
//finance/augur/rust:simulator_test
//finance/augur/rust:differential_test
//finance/augur/rust:benchmark_fixture
//finance/augur/rust:benchmark_driver
//finance/augur/rust:jax_benchmark_driver
```

`simulator_cli FIXTURE.json OUTPUT.json` retains full traces. The benchmark
uses `simulate_summaries_validated(...)`, which validates once and then retains
fixed-size final summaries for every rollout. See [BENCHMARK.md](BENCHMARK.md)
for the measured 100,000-rollout baseline and its output-contract caveats.
