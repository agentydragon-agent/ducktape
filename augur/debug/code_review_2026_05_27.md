# Augur Review Findings - 2026-05-27

Scope: reviewed the current `augur/` working tree with emphasis on simulator
correctness, vectorized numpy/dataflow, product-to-sim wiring, modularization,
and stale/dead documentation. The repository also has unrelated untracked files;
this file is the only intended output. I did not run tests.

Severity guide:

- P1: can produce materially wrong simulation output or hide an invalid scenario.
- P2: correctness risk, scaling bottleneck, or boundary problem that should be
  fixed before the area grows.
- P3: cleanup/stale documentation/idiom issue.

## Findings

### P1: Lifecycle event invariants are split between product wire and sim internals

Evidence:

- `Scenario._reject_out_of_horizon_scheduled_events` only validates
  `scheduled_asset_sales` and `scheduled_property_purchases`; it does not validate
  `property_lifecycle_events`, `scheduled_transfers`, or `scheduled_obligations`
  (`augur/sim/scenario.py:630-645`).
- `compile_lifecycle_events` checks only "known property" and "strictly after
  purchase"; it does not reject events outside the horizon, multiple sales for the
  same property, or events after a sale (`augur/sim/compiler/lifecycle.py:47-77`).
- Product wire rejects lifecycle events after the first sale
  (`augur/product/wire.py:155-170`), but callers can construct `Scenario`
  directly and bypass this guard.
- `_apply_lifecycle_events` marks an event as fired for every non-failed rollout
  before dispatching it, and passes only the rollout-active mask into sale handling
  (`augur/sim/engine/phases.py:352-378`). `_apply_property_sale` does not include
  `current.property_active[prop, :]` in its mask (`augur/sim/engine/phases.py:466-503`).

Impact:

- A lifecycle event at `month >= horizon` is silently unreachable because
  `month_starts` has only `horizon + 1` entries.
- Two `PropertySaleEvent`s for the same property can credit gross sale proceeds
  twice. The first sale freezes the property and pays off the mortgage; the second
  sale still computes market value from purchase price and home-value series, with
  mortgage payoff now zero, then credits cash again.
- A post-sale `SetRentedFractionEvent` or `CapitalImprovementEvent` can mutate an
  inactive property if the scenario is built at the sim layer.

Recommendation:

Move lifecycle invariants into the sim-owned schema/compiler: reject lifecycle
months outside `[0, horizon)`, enforce at most one sale per property, reject any
non-sale at or after the sale month, and have the engine mask lifecycle effects
by `active_rollout & current.property_active[prop, :]`. Set `fired` only after
the event actually applies.

### P1: Missing home-value series makes property sales look like zero-value events

Evidence:

- `CompiledSimulation.property_home_value_series_index` falls back to `NO_CODE`
  when the home-value series id is not present
  (`augur/sim/compiler/plan.py:226-231`).
- `_apply_lifecycle_events` sets `buffers.lifecycle.fired` before sale dispatch
  (`augur/sim/engine/phases.py:352-358`).
- `_apply_property_sale` returns early when the series index is missing, leaving
  all sale amount buffers at zero and leaving the property active
  (`augur/sim/engine/phases.py:429-433`).
- The decoder turns every fired sale event into a property-sale row and reads the
  zero-filled sale amount buffers (`augur/sim/codec/lifecycle.py:34-79`).

Impact:

A scenario can produce a sale marker with zero proceeds, zero payoff, zero gain,
and no frozen property state rather than failing fast. That is especially easy
for direct sim callers because generic series collection does not require
`home_value:<location>` for property purchases/sales the way the product layer
does (`augur/product/scenarios.py:128-138`).

Recommendation:

Make home-value series availability a compile-time requirement for every owned
property that can be valued or sold. Raise a clear `KeyError`/`ValueError` with
the expected series id instead of silently using `NO_CODE`. As a secondary guard,
do not mark sale events fired until sale application succeeds.

### P1: Section 121 occupancy uses rented fraction as a proxy for primary residence

Evidence:

- `ScheduledPropertyPurchase` has `rented_fraction` but no sim-side field for
  primary residence, owner occupancy, or actual use (`augur/sim/scenario.py:386-423`).
- The product API has `is_primary_residence`, but build wiring only uses it to add
  a mortgage-interest deduction policy (`augur/product/wire.py:131-146`,
  `augur/product/scenarios.py:252-255`).
- `_apply_owner_occupied_month` treats every active property with
  `rented_fraction < 1.0` as owner occupied (`augur/sim/engine/phases.py:513-529`).
- `_apply_property_sale` uses those months for the Section 121 exclusion
  (`augur/sim/engine/phases.py:450-464`).

Impact:

A second home, vacant investment property, or "off" property with
`rented_fraction=0.0` accrues owner-occupied months and can receive the Section
121 primary-residence exclusion on sale. This is a factual tax correctness bug,
not just an approximation.

Recommendation:

Add explicit sim-side occupancy/use state. At minimum, distinguish
`primary_residence`, `non_primary_owner_use`, `off/vacant`, and `rented`, then
make Section 121 count only qualifying primary-residence occupancy. Product
`is_primary_residence` should be lowered into that sim state rather than only
into MID policy wiring.

### P1: Product rental lifecycle events do not wire dynamic rent or management fees

Evidence:

- `SetRentedFractionEventWire` says it covers start/stop/change-rental-plan, but
  it only carries `month` and `rented_fraction` (`augur/product/wire.py:98-107`).
- Product required-series discovery adds rent series only when
  `property_purchase.initial_rental` exists, not when lifecycle events later start
  rental (`augur/product/scenarios.py:119-151`).
- `_wire_landlord_rental` runs once from the initial purchase state. It returns
  nothing when `initial_rental is None`, and otherwise wires tenant rent,
  management fee, and leasing fee from month 0 through horizon end
  (`augur/product/scenarios.py:502-600`).
- The translator appends lifecycle events separately after property purchase
  wiring (`augur/product/scenarios.py:261-264`, `augur/product/scenarios.py:369-378`).

Impact:

Starting rental mid-horizon changes tax/depreciation treatment in the sim but
does not create tenant rent income, management fees, or leasing fees. Stopping
rental mid-horizon changes tax/depreciation treatment but leaves month-0 rent and
management transfers active through the full horizon. Product-level scenarios can
therefore materially overstate or understate cash flow.

Recommendation:

Either lower lifecycle rental state into transfer schedules at compile time, or
move rent/management/leasing into a runtime property policy that reads
`current.property_rented_fraction`. Required-series discovery must inspect the
effective lifecycle rental timeline, not only `initial_rental`.

### P2: Out-of-horizon transfers and obligations are silently ignored

Evidence:

- Scheduled transfers are selected only by iterating `range(horizon)` and taking
  transfers whose `month == month`; out-of-horizon rows are never seen
  (`augur/sim/compiler/transfers.py:54-63`).
- Scheduled obligations are appended only when `0 <= scheduled.month < horizon`;
  otherwise the obligation is dropped (`augur/sim/compiler/obligations.py:88-94`).
- The only horizon validator covers asset sales and property purchases
  (`augur/sim/scenario.py:630-645`).

Impact:

Invalid user intent can disappear rather than fail. This is especially risky for
one-time expenses, taxes, or transfers that are expected to explain a cash-flow
cliff near the end of a scenario.

Recommendation:

Generalize the scenario-level horizon validator across every month-bearing
scheduled object, including transfers, obligations, and lifecycle events. For
recurring objects, validate `start_month <= end_month` and that the active window
intersects the horizon if silently empty recurrences are not intentional.

### P2: Independent exogenous models ignore required series/events

Evidence:

- `ProductService._simulate_missing` passes `required_level_series` and
  `required_event_series` into the exogenous sampler
  (`augur/product/service.py:193-201`).
- `IndependentSeriesModels.sample` ignores both required sets and samples every
  configured series/event instead (`augur/model/series_model.py:49-77`).
- The VECM sampler does honor required ids, so this behavior is inconsistent
  across providers.

Impact:

The product can request a required home-value, rent, inflation, or PE event
series and receive a bundle that omits it until a later KeyError, NaN, or zero-ish
fallback path. It can also sample irrelevant configured series, doing unnecessary
work for larger catalogs.

Recommendation:

Make `IndependentSeriesModels.sample` validate every required id and sample only
the requested ids, or explicitly document and implement "sample all configured
series" with an early missing-required error. Do the same for event ids.

### P2: External-series cubes use row-wise Python loops and weaker coverage validation than existing helpers

Evidence:

- `_validate_series_indexed_amounts` builds a Python dict via
  `external_series.series_values.iter_rows(named=True)` and checks required
  rollout/month cells with nested Python loops (`augur/sim/simulate.py:54-98`).
- `external_values_cube` and `external_event_values_cube` fill dense arrays by
  iterating long Polars rows (`augur/sim/compiler/series.py:52-93`).
- `SampledExogenousBundle.level_matrix` already has a stricter
  long-frame-to-matrix helper that validates exact rollout/month coverage for a
  series (`augur/model/exogenous.py:68-79`, `augur/model/exogenous.py:204-228`).

Impact:

This adds serial Python overhead in a path that should be batch-oriented, and it
does not uniformly fail on missing coverage for every series the sim consumes.
Some consumers validate only `SeriesIndexedAmount` inputs while asset prices,
home values, and event streams can still enter the dense plan with `NaN` or
default `False` cells.

Recommendation:

Use a shared matrix materialization path for all external level/event series:
filter or pivot by series id, validate exact `(rollout, month)` coverage, then
stack arrays into `(series, rollout, month)`. If `ExternalSeriesContext` remains
the sim boundary, give it the same coverage-checked matrix helpers as
`SampledExogenousBundle`.

### P2: Product fan path re-slices batched simulation into one-rollout cache entries

Evidence:

- `_simulate_missing` samples and simulates all missing seeds in one dense batch
  (`augur/product/service.py:185-209`), then immediately stores one sliced
  `DenseSimulationResult` per seed (`augur/product/service.py:211-216`).
- `_decoded_rollouts` loops over seeds and computes monthly arrays one rollout at
  a time (`augur/product/service.py:173-183`).
- `_metric_matrix` then loops those one-rollout arrays back into a 2-D matrix for
  percentile calculation (`augur/product/service.py:265-277`).

Impact:

The code gets the cost of batch simulation but loses much of the benefit at the
cache/API boundary. The fan path becomes "simulate in batch, split, decode
N times, restack", which is exactly the data shape the dense buffers were meant
to avoid.

Recommendation:

Separate distribution/fan caching from selected-rollout detail caching. Keep a
batch-shaped dense result or batch-shaped metric matrix for the fan, and slice
only when serving the selected rollout endpoint. This matches the existing
direction in `augur/sim/TODO.md:9-17`.

### P2: Direct cash mutations bypass obligation/failure semantics

Evidence:

- Scheduled transfers directly debit and credit cash without checking available
  funds (`augur/sim/engine/phases.py:19-51`).
- Property purchases directly debit buyer cash for down payment plus closing cost
  (`augur/sim/engine/phases.py:733-757`).
- Capital improvements directly debit owner cash and increase basis
  (`augur/sim/engine/phases.py:362-367`).
- Obligation settlement does have explicit funded/failed handling
  (`augur/sim/engine/phases.py:1043-1095`).

Impact:

An unaffordable property purchase or capital improvement can continue as a
negative-cash rollout rather than an obligation shortfall/failure. That may be
intentional for some transfers, but today the distinction is encoded by which
phase happens to implement the cash movement, not by a scenario-visible contract.

Recommendation:

Make the cash-demand taxonomy explicit. If purchases/capex/transfers are allowed
to overdraft, expose a warning/diagnostic and document it. If they are not,
lower them into obligation-like demands or add a common funding/failure policy.

### P2: Obligation funding recomputes the same account group for every slot

Evidence:

- `_obligation_group_funded` loops every obligation slot, rebuilds the
  `(agent, from_slot)` group mask, sums that group's due amounts, and recomputes
  available cash for each slot (`augur/sim/engine/phases.py:1107-1121`).

Impact:

This is correct-looking but unnecessarily serial and repeated in the monthly hot
loop. The grouped semantics are useful; the implementation just does the same
group aggregation once per member.

Recommendation:

Precompute per-month group ids for `(agent, from_slot)` at compile time, or derive
them once per month. Then compute group due as a vectorized scatter/add or a
small loop over unique groups and broadcast the funded result back to slots.

### P3: Sale-event documentation is stale and contradicts the engine

Evidence:

- `PropertySaleEvent` docs say gross proceeds use
  `market_value * (1 - closing_cost_pct)` even though the field is `0..100` and
  the engine divides by 100 (`augur/sim/scenario.py:338-361`,
  `augur/sim/engine/phases.py:402-438`).
- The same docs say Section 1250 recapture is added to ordinary income for both
  federal and CA, and that Section 121 is a phase-4 follow-up
  (`augur/sim/scenario.py:347-355`).
- Engine/tax code now routes Section 1250 through federal cap handling and
  applies Section 121 exclusion logic (`augur/sim/engine/phases.py:84-150`,
  `augur/sim/engine/phases.py:406-413`, `augur/sim/engine/phases.py:450-464`).

Impact:

The schema-level comments are now misleading enough to cause future scenario
authors or reviewers to misunderstand the implemented tax behavior.

Recommendation:

Update `PropertySaleEvent` docs to match current behavior: `closing_cost_pct` is
a percent, federal Section 1250 uses the lesser-of marginal/cap rule, CA-style
links can treat recapture as ordinary, and Section 121 is implemented with the
current occupancy caveat from the P1 finding above.

### P3: Product rental comments and sim TODO still describe shipped or contradicted work

Evidence:

- `_wire_landlord_rental` comments say Schedule E deductions and MID/SALT scaling
  are deferred follow-ups (`augur/product/scenarios.py:526-543`).
- The sim TODO says rental tax Phase 2 has landed, including Schedule E,
  MID/SALT scaling, depreciation accrual, and year-end rental-interest deduction
  (`augur/sim/TODO.md:95-98`).
- The same TODO still lists broad real-estate lifecycle support, including
  mid-horizon lifecycle events and sale, as missing (`augur/sim/TODO.md:99-127`),
  even though typed lifecycle events and sale machinery now exist.

Impact:

The stale notes make it harder to distinguish real remaining work from completed
work. That matters in Augur because future changes are likely to be staged by
agents reading these trackers.

Recommendation:

Trim the TODO to the actual remaining gaps: dynamic rent/management cash-flow
wiring, explicit occupancy state, product-controlled purchase month, and any
still-missing lifecycle semantics. Remove comments that claim Schedule E/MID/SALT
scaling is not wired, or narrow them to the specific dynamic-rental gap.

### P3: Rollout detail still materializes dense results through the older Polars/Pydantic path

Evidence:

- `augur/sim/TODO.md` already calls out replacing
  `dense.decode() -> SimulationRun` on the rollout-detail endpoint with
  `ProjectionRun` read models (`augur/sim/TODO.md:9-17`).
- Product event projection still iterates Polars rows into Pydantic event markers
  (`augur/product/decode.py:520-548`).
- Product lot valuation loops every lot even when the dense arrays already carry
  lot state and external value cubes (`augur/product/decode.py:180-195`).

Impact:

This is not the primary correctness risk, but it keeps the selected-rollout path
on a different dataflow than the fan path and makes future vectorized/result
boundary work harder. It is also the place where product code still knows too
much about decoded sim frames.

Recommendation:

Finish the `ProjectionRun` cutover for rollout detail and keep product conversion
at the API/product boundary. Use dense-buffer/projection helpers for lot/property
valuation rather than reimplementing per-lot loops in product decode.
