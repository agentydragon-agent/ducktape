# Plan: Augur Simulator E2E Redesign

## Purpose

Augur's core simulator should be easier to operate and harder to misuse. We are
expanding e2e coverage in spirals: write a small core scenario, discover the
clunky/dead/weird API surface, fix that surface, then make the next spiral
larger.

The natural public unit is a `ScenarioSet` simulated over sampled market
trajectories. A selected one-rollout path is useful for UI inspection, but it is
one sampled trajectory from a distribution, not a separate deterministic product
API.

## Boundaries

- `augur/core/`: validates typed scenarios, applies policies/events over
  sampled rollouts, records accounting truth, and returns typed distribution
  results.
- `augur/model/`: evidence ingestion, calibration, fitting, and market-provider
  construction. Manifold/source-data shapes belong here as evidence that feeds
  fitting, not in app state or the simulator contract.
- `augur/app/`: UX, catalog/default composition, request parsing, and
  app-specific validation. It adapts user-facing forms into core scenarios and
  calls core.

## Target Runtime Shape

1. A scenario declares actors, initial accounts/assets/liabilities, scheduled
   events, market request, and each actor's ordered policy program.
2. The engine initializes vectorized rollout state: cash/accounts, asset
   units/value/basis, liabilities, ownership ledgers, tax state, property use,
   and policy memory.
3. Each month, policies receive typed context: actor, month, current state,
   relevant scheduled events, market observations, and available opportunities.
4. Policies emit typed decisions/instructions. They do not directly mutate
   cash, holdings, basis, liabilities, ownership, taxes, or result arrays.
5. Accounting appliers validate and apply instructions, update state, record
   ledger entries and balance snapshots, and record any shortfall/rejection.
6. Reporting arrays are derived from state/ledger or reconciled against them.
   Arrays can stay for chart performance, but they are not the source of truth.

## Invariants

- No `_enabled_policy_of()`-style singleton behavior execution. An actor policy
  program is an ordered sequence.
- Market paths and exogenous opportunities are observations, not policy
  decisions.
- Scheduled user events are explicit scenario transitions. The horizon itself
  is not an implicit property sale.
- Every cash/asset/liability/ownership/tax state change has a cause:
  `policy_id`, `event_id`, market opportunity, or system accounting process.
- Public result arrays reconcile to ledger/snapshot detail in e2e tests.

## Completed Snapshot

These are consolidated from the older spiral notes; detailed evidence lives in
`augur/core/test_e2e.py` and the focused core tests.

- Public API: `simulate_set(scenario_set, *, market_provider=None,
market_bundle=None)` returns a typed `SimulationRun`; callers can inspect a
  scenario, metric matrix/series/terminal value, and a selected rollout.
- Controlled market support: tests can plug deterministic/noop market bundles
  without creating a deterministic simulator API.
- Scenario validation: the public runner validates actor/property references,
  duplicate IDs, rental/property prerequisites, and market-bundle dimensions
  before entering the engine.
- Opaque property IDs: core scenarios use string property IDs with explicit
  location/tax-regime inputs instead of private catalog enums.
- Cash/SP500/monthly spend: e2e coverage verifies cash-only, SP500-only,
  combined net worth, monthly spend, per-rollout spend actions, and monthly
  spend ledger reconciliation.
- Mortgage/property purchase: e2e coverage verifies fixed-rate amortization,
  month-0 purchase cash outlay, ordinary owner mortgage actions, and mortgage
  cash/liability ledger reconciliation.
- Property sale/taxes: property sales are explicit `PropertySaleEvent`s, not
  horizon liquidation. Sale settlement records gross proceeds, selling costs,
  debt payoff, adjusted basis, gain/exclusion, depreciation recapture, tax, and
  net proceeds. Sale taxes now run through an annual federal + California pass
  for property, SP500, and PE sale gains.
- Rental: `RentalPlan` is a discriminated union keyed by `rental_mode`;
  whole-property and room-rental modes require their mode-specific rent fields.
  Rental income, vacancy, property tax, fees, and carrying costs reconcile to
  ledger detail.
- Checking-floor SP500 sales: fixed-tranche public-stock sell policies run in
  ordered policy-program order, can have multiple rules, emit policy-decision
  rows, realize actions, and reconcile sale/basis/tax/proceeds arrays.
- Private-equity sale requests: liquidity opportunities are market
  observations, sale requests are scheduled events, and PE sale policies decide
  requested sales. Tender-sale fractions and event-capacity helpers were
  deleted. PE sale/basis/tax/proceeds arrays reconcile to ledger detail.
- Partner equity: partner contribution policies can name property IDs, multiple
  partner policies run in actor order, contributions/accruals are split into
  transfer/action/ledger/snapshot detail, and property-sale partner claims
  settle against tax-adjusted sale net proceeds.
- Legacy cleanup: the old `ownership.py` / `real_estate.py` side path was
  deleted; scenario-set simulation is the current partner-equity path.
- Result detail: public scenario results now include actions, policy decisions,
  market observations, ledger entries, and balance snapshots. Selected rollouts
  can filter these details locally.
- E2E serialization: response payload coverage includes SP500 sale, PE sale,
  property sale settlement, tax fields, ledger rows, policy-decision rows, and
  market-observation rows.

## Active Step 7: Arrays Reconcile To Ledger

Current status: first-pass reconciliation coverage exists, public row-level
detail is available, and the first recurring cash-flow arrays now derive from
ledger rows. The remaining work is to keep shrinking bespoke array math without
changing monthly-column semantics.

Next slices:

1. Generalize the ledger-derived matrix helper if the next array families need
   multiple categories, actor filters, property filters, or balance snapshots.
2. Move sale-related reporting arrays toward ledger/state derivation once tax
   timing and basis semantics are explicit enough.
3. Keep the existing monthly columns stable, and keep reconciliation tests in
   place as guardrails.
4. Add any missing causes/IDs needed by derivation. Do not add ad hoc string
   parsing to recover meaning from categories.
5. Separate arrays that are true state snapshots, such as asset value and
   remaining liability balance, from transaction-flow arrays that should derive
   from ledger entries.

Done for Step 7:

- Actor-keyed ledger entries and balance snapshots are public result detail.
- Monthly spend, mortgage interest/principal/payment, rental income/fees,
  property carrying costs, and net property cash flow derive from ledger rows
  before being exposed as monthly result arrays.
- E2E tests reconstruct matrices from ledger/snapshot rows for monthly spend,
  SP500 sales/taxes, PE sales/taxes, mortgage payments, rental/property
  operating cash flows, property sale settlement/taxes, and partner-equity
  ledgers/claims.
- Selected-rollout detail includes market paths, PE liquidity opportunities,
  monthly-spend decisions, checking-floor sell decisions, PE sale decisions,
  partner contribution decisions, actions, ledger entries, snapshots, and curve
  values.

## Open Design Follow-Ups

These are tracked more granularly in `augur/TODO.md`.

- Derive more arrays from ledger/state instead of only reconciling after the
  fact.
- Convert taxes into a ledger/liability workflow with estimated-payment timing.
- Expand annual tax modeling: qualified dividends, short-term gains, losses,
  rental income, deductible expenses, passive-loss release, SALT/property-tax
  treatment, California conformity/non-conformity, and ordinary-income
  schedules beyond a single `TaxProfile` value.
- Replace remaining class-filtered policy execution with actual ordered actor
  policy programs and runtime rules.
- Split private-equity liquidity opportunity, user sale request, policy
  decision, accounting application, and public action with explicit cause IDs.
- Remove or implement schema-only policy types:
  `LiquidityReservePolicy`, `PortfolioTargetRebalancePolicy`, and
  `ManualEventSchedulePolicy`.
- Clarify initial state vs scheduled transitions for purchase, financing,
  ownership, sale, rental transition, and liquidity events.
- Reduce single-property/global scenario assumptions. Over time,
  `property_selection`, `financing`, `rental_plan`, and `tax_profile` should
  become initial positions, per-property settings, or per-actor/accounting
  inputs.
- Collapse the old/new schema surfaces. `augur/core/scenario_set.py` is the
  scenario-set simulator schema; legacy shapes in `augur/core/schemas.py`
  should be deleted, moved, or wrapped at an explicit compatibility boundary.
- Publish stable metric IDs and define aggregate vs per-agent result semantics.
- Refresh `augur/SPEC.md` once policy execution, sale taxes, and one-rollout
  detail stabilize.

## Next 7 Days

Day 1: Finish the first direct array-from-ledger derivation for low-risk
recurring cash-flow arrays.

Day 2: Extend derivation to mortgage/property operating cash-flow arrays and
remove duplicated bespoke assignments where possible.

Day 3: Tighten policy-decision/opportunity cause IDs, especially around
private-equity sale requests and market liquidity opportunities.

Day 4: Start tax ledger/liability shape: annual assessment, source allocation,
and payment timing as separate concepts.

Day 5: Clarify initial state vs event transitions and add validation for
duplicated/conflicting purchase, financing, rental, and sale sources of truth.

Day 6: Prune or implement schema-only policy types and remove stale legacy
schema paths that no current caller should use.

Day 7: Update `augur/SPEC.md` and app-facing detail expectations once the new
core result contract is stable enough to promise.

## Verification

After each behavioral slice:

```bash
bbr test //augur/core:test_e2e
```

Before handing off a finished spiral:

```bash
bbr test //augur/core:all
bbr build //augur/...
```

If app-facing request or state conversion changed, also run the relevant
`augur/app` JavaScript and backend tests.
