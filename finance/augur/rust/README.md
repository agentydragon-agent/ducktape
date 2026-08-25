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
- scalar, tagged-fixed, and inflation/rent-series-indexed amounts across
  transfers, property cashflows, and obligations, including rollout-specific
  monthly or periodic reset boundaries and exact half-up ratio scaling;
- initial tax lots and FIFO scheduled sales;
- monthly security distributions based on currently held units, including
  independently rounded issuer tax-character slices for Treasury, municipal,
  corporate, and mixed funds;
- par-only held-to-maturity nominal bonds and TIPS, including finite coupon
  schedules, par redemption, CPI-indexed principal, deflation-floor redemption,
  phantom accretion income, and federal/state/own-issue interest exemptions;
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
- target-allocation cash-band raises before obligation funding, including
  projected end-of-month demand, exact integer water-filling, source-account
  order, FIFO lot dispositions, immutable sleeve weights, realized gains,
  attempted-funding attribution, and canonical obligation-failure metadata;
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
state and held bond principal; selected traces expose tax-payment,
tax-settlement, and issuer-attributed bond cashflow/accretion records.

The strict fixture stores monetary series (security prices, distributions, and
home values) as currency quanta. Inflation and rent index levels instead use a
dimensionless parts-per-billion scale. Referenced index levels must be positive
and must round-trip exactly through the Python/JAX `float64` external-series
boundary; the Rust validator and Python adapter reject fixtures that would lose
an integer level during that conversion. Series coverage is deliberately dense:
every series supplies every rollout and snapshot in the fixture.

Initial lots store total basis, but that total must imply an exact
integer-currency-quantum basis per whole unit:
`basis × quantity_scale` must divide evenly by `units`. Both the Rust validator
and Python adapter reject an inexact lot rather than letting the legacy adapter
floor a different basis.

Bond coupon rates use the same parts-per-billion contract and must round-trip
exactly through the legacy Python/JAX `float64` boundary. Nominal coupons round
the full `face × annual rate × period / 12` rational once; TIPS preserve the
legacy engine's indexed-principal and fixed-point period-rate path. Government
issuer levels come from one scenario-level jurisdiction identity registry,
rather than duplicated caller-supplied metadata on each bond.

Distribution tax-character fractions use exact PPB weights that must be
positive, sum to one, and preserve the same issuer identity contract as bond
interest. Each slice is paid, journaled, attributed, and routed through the
jurisdiction's interest-exemption policy independently; the slice sum is the
fund's cash payout.

The current target-allocation boundary deliberately accepts sell-only policies:
`purchase_slots_per_sleeve` must be zero and drift-triggered rebalancing must be
unset; each unsupported field has a specific validation error. It evaluates the
band after all monthly obligations have accrued, sells before the grouped
funding check, and therefore makes an unpaid obligation mean the configured
portfolio genuinely could not fund it. Selected traces expose the source and
proceeds accounts on every lot disposition and the ordered sleeve identities
attempted for every matching obligation. Buy slots and the post-settlement
purchase leg are the next slice rather than silently ignored.

Still missing before replacement is plausible:

- broader modeled tax facts and complete deduction policy;
- policy-driven purchases;
- mortgage contracts beyond the basic fixed-rate purchase mortgage;
- property-tax/SALT mixed-use splitting, mortgage principal-cap policies, and
  §121 primary-residence exclusion;
- target-allocation purchases/rebalancing, broader liquidity policy, TLH, and
  private equity;
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
