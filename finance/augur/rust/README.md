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
  and same-month suppression of property-tied cashflows and carrying costs, for
  fixtures without primary-residence / §121 state;
- property rented-fraction transitions, capital improvements, 27.5-year rental
  depreciation, rental/owner mortgage-interest splitting for uncapped
  acquisition debt, and sale-time §1250 recapture with federal capped-rate
  versus state ordinary-income treatment;
- fixed-payment mortgage origination, monthly interest/principal splitting,
  same-source funding-group settlement, and property-tax carrying costs;
- grouped scheduled and recurring obligations;
- insufficient-cash failure month and state freezing;
- federal and California ordinary-income year-end tax accruals;
- federal long-term-capital-gain stacking and tax accrual;
- quarterly estimated-tax payments, aggregate safe-harbor Q4 computation,
  January true-up, tax-liability settlement, and funded/unfunded tax-payment
  events;
- generated benchmark fixtures at 17 rollouts.

The Rust ledger also records tax expense/liability accrual entries, tax
prepayments and settlement, and preserves capital-loss carryforward between tax
years. Monthly and terminal output retain jurisdiction-level tax-liability
state; selected traces expose tax-payment and tax-settlement records.

Still missing before replacement is plausible:

- broader modeled tax facts, issuer-jurisdiction routing, and complete
  deduction policy;
- policy-driven purchases and taxable distribution character;
- mortgage contracts beyond the basic fixed-rate purchase mortgage;
- property-tax/SALT mixed-use splitting, mortgage principal-cap policies, and
  §121 primary-residence exclusion;
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
