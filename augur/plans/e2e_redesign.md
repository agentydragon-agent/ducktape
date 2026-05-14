# Plan: Redesign Augur Core Around Test-Driven E2e Scenarios

## Context

The augur core (`augur/core/`) has structural problems: closed `PropertyId`
enum, hardcoded `SF_TAX_RATE`, duplicated `MONTHS_PER_YEAR`,
`FINANCING_MODE_*` string constants vs `FinancingMode` enum, string-typed
legacy private-equity sale modes, monolithic `schemas.py`, two parallel
simulation paths (legacy scalar + vectorized), sparse reference validation,
and no standalone ergonomic API for tests or downstream callers.

We're iterating in spirals: write a test, see what hurts, fix the surface,
then expand the test. Refactoring emerges from making each e2e test readable.
Each spiral should leave the simulator easier to operate than it was before.

## Boundary Decisions

The simulator should have a small, stable, distribution-first contract:

- `augur/core/`: stochastic trajectory simulation. Given a typed `ScenarioSet`
  plus a `MarketBundleProvider` or already-sampled `MarketBundle`, it validates
  references, applies policies/events across rollouts, and returns typed
  distributions of trajectories. It should not know about React state, FastAPI
  request bodies, private catalogs, raw Manifold payloads, or model fitting.
- `augur/model/`: evidence ingestion, calibration, model fitting, and rollout
  providers. FRED/Yahoo/Zillow data already lives here through
  `MarketEvidence`; Manifold-derived probabilities belong in this evidence
  layer too. A `ManifoldMarketSnapshot` is not app state and should not move
  into `augur/app/`; it is evidence that feeds priors, calibration, or model
  fitting before producing a `MarketBundleProvider`.
- `augur/app/`: UX, bootstrap payload assembly, catalog defaults, request
  parsing, and app-specific validation. It adapts user-facing forms into core
  scenario objects and delegates simulation to core.

Core should be useful without the app, but its natural unit is a distribution
over trajectories, not a deterministic scenario runner. The app should be able
to compose private catalogs without patching simulator internals. Model fitting
should be replaceable without changing the simulator.

## Accounting Truth

The simulator should truthfully capture economic state transitions, including
taxes. Taxes are not just explanatory annotations on a chart; when an event or
policy creates taxable income, capital gains, depreciation recapture, property
tax, or estimated private-equity tax, the simulator should record the tax cash
flow, include it in net proceeds / cash / net worth, and expose enough detail
to explain the calculation.

## Policy Direction

A policy is an agent-control program: it looks at an agent's state, market
paths, and month, then emits actions for that specific agent. The current
pre-baked behaviors are useful pieces, but they should not imply "an agent is
exactly one of these behavior types."

Direction:

- Core should allow an agent to have multiple enabled policy rules/modules.
  Living expenses, liquidity reserve maintenance, private-equity sale-request
  handling, portfolio rebalancing, and partner-equity accrual can all apply to
  the same agent.
- Policy execution needs a stable, documented order so two enabled rules that
  touch the same asset or cash account have predictable results.
- The app should expose knobs, toggles, and select boxes that configure policy
  rules. "Checking floor", "sell into cash vs SP500", "sell fixed amount when
  a PE liquidity opportunity appears", and "manual sale requests only" are UI
  configuration choices, not mutually exclusive agent archetypes.
- Core should reject internally inconsistent policy configuration, but should
  not reject multiple policies of the same broad concern unless their effects
  are genuinely ambiguous.
- Reusable app presets are fine as presets that fill knobs. They should compile
  into explicit policy configuration before reaching core.

## Policy Runtime Design

The current engine is not truly policy-driven. It has hardcoded array
calculation blocks that reach into policies as configuration bags, parse random
chunks of their fields, and then synthesize actions after the fact. That shape
should be replaced by a runtime where policies are executable rules over
simulation state, and arrays are reporting output rather than the primary
execution mechanism.

Target architecture:

1. **Scenario configuration**
   Pydantic models remain the external schema. A scenario declares actors,
   initial assets/liabilities/accounts, scheduled events, market request, and
   each actor's ordered policy program. Policy models are configuration only:
   discriminated unions with explicit knobs, no opaque `parameters` bags.
2. **Runtime state**
   The engine initializes a per-rollout mutable state view from the scenario:
   cash/accounts, asset units/value/basis, liabilities, ownership ledgers,
   tax ledgers, property use, and any per-policy memory. It may remain
   vectorized internally, but the abstraction is "state of rollout(s)", not
   "arrays that policies patch indirectly."
3. **Policy context**
   For each month, policy rules receive a typed context: actor ID, month index,
   sampled market observation, scheduled events relevant to the actor/assets,
   available liquidity opportunities, and read access to current state.
4. **Policy evaluation**
   Each enabled policy rule evaluates in deterministic order and emits
   typed instructions. A policy should not mutate cash, holdings, basis,
   mortgage balance, ownership, or result arrays directly.
5. **Instruction application**
   A separate accounting/state-transition layer validates and applies
   instructions. It clips impossible sales, rejects unsupported transfers,
   computes taxes/basis effects, updates state, and records realized ledger
   entries with `rollout_index`, `month_index`, actor/account/asset/liability
   IDs, amount, category, and cause (`policy_id`, `event_id`, or market
   opportunity ID).
6. **Reporting**
   Monthly arrays and response columns are recorded from state and ledger after
   instruction application. They are derived/reporting surfaces, not the source
   of truth for economic effects.

Conceptual type split:

- `PolicyConfig`: external Pydantic config such as
  `CheckingFloorSellPublicStockPolicy`, `PrivateEquitySalePolicy`, or a future
  partner-equity agreement policy.
- `PolicyRule`: runtime adapter for one config object. It implements
  `evaluate(context, state) -> InstructionBatch`.
- `Instruction`: intended operation, e.g. `SellAssetInstruction`,
  `TransferCashInstruction`, `PayLiabilityInstruction`,
  `AccrueOwnershipInstruction`, `SetPropertyUseInstruction`, or
  `RequestPrivateEquitySaleInstruction`.
- `LedgerEntry`: realized accounting effect after validation/application.
- `SimulationAction`: user-visible audit/event view. It may be built from
  ledger entries and decisions, but should not be the only accounting truth.

Ordering and responsibility:

- Market paths and exogenous opportunities are observations, not policy
  decisions. A private-equity liquidity opportunity can exist without a sale;
  a policy decides whether to request one.
- Scheduled user events are explicit scenario transitions. A property sale is
  a scheduled event; the horizon itself is not a sale decision.
- System accruals such as mark-to-market value, mortgage interest accrual,
  property tax accrual, insurance, maintenance, depreciation, and taxable
  gain calculations are accounting processes. They can create ledger entries
  but should not masquerade as agent choice.
- Agent policies are decision programs: spend monthly cash, sell a fixed
  public-stock tranche to maintain liquidity, request a PE sale on an
  opportunity, transfer partner contributions, or service liabilities from a
  chosen account.

Vectorization requirement:

- The runtime can still be vectorized. `InstructionBatch` can be columnar over
  rollouts with masks and amount arrays, and the applier can update vectorized
  state. The design goal is not one Python object per rollout/month; it is
  making the execution boundary honest: policy evaluation emits instructions,
  accounting applies them, and reporting records the result.

Policy-runtime invariants:

- No `_enabled_policy_of()`-style singleton lookup for behavior execution.
  A policy program is an ordered sequence. If a domain only supports one
  agreement today, that should be represented by the runtime model or by
  explicit validation while we build the real ledgers, not by silently taking
  the first policy.
- No policy implementation writes result arrays directly.
- Every cash/asset/liability/ownership/tax state change has a ledger cause.
- Rejections and shortfalls are recorded explicitly instead of disappearing
  into clipped arrays.
- Public result arrays reconcile to ledger totals in e2e tests.

## E2e Spiral Rules

- Start each spiral with a small core e2e test in `augur/core/test_e2e.py`.
- Construct typed scenarios directly. Avoid frontend state, YAML, HTTP, or
  private config in these tests.
- Prefer the public scenario-set API once it exists; until then use
  `run_scenario_vectorized()` directly when a narrow core test needs internals.
- Assert on both state arrays and action/event logs when a behavior produces a
  visible action.
- Use controlled market paths in tests only to make expected values legible.
  They are fixtures for probing the stochastic engine, not a separate public
  deterministic mode.
- Preserve the ability to inspect a single sampled rollout from a distribution
  result. That is a UI/detail-view concern, not a separate deterministic input
  API.
- If constructing the test is clunky, fix the scenario/result surface or add
  narrow test support. Do not hide clunkiness with large one-off fixtures.
- Keep every behavioral cleanup covered by the e2e test that motivated it.

## Simulator API Cleanup Lane

These are not separate big-bang refactors. Pull them in as soon as a spiral
needs them.

1. **Distribution-first public entry point**: add `augur/core/api.py` only if it
   makes the scenario-set runner easier to use. The public function should be
   `simulate_set(scenario_set, *, market_provider=...)` or similar. A single
   scenario can be represented as a one-scenario set; do not add a special
   deterministic `simulate(scenario, market_bundle)` public mode.
2. **Controlled market test helpers**: move the ad hoc e2e `_flat_bundle()`
   shape into reusable test support, probably extending
   `augur/core/market_bundle_test_support.py`. Add simple path overrides for
   SP500, inflation, home value, rent, mortgage rate, private-equity value, and
   private-equity liquidity-event months so tests do not reconstruct frozen
   `MarketBundle` objects by hand. These helpers are test-only, even when they
   build a one-rollout flat path.
3. **Result ergonomics**: add small accessors on the returned run object, or a
   thin wrapper, for common assertions:
   `series("cash_usd", rollout=0)`, `final("net_worth_usd")`,
   `actions_of(MonthlySpendAction)`. Keep columnar export as a reporting
   boundary, not the only pleasant way to inspect results.
4. **Single-rollout inspection**: make sampled trajectory detail a first-class
   part of results. The UI should be able to select rollout `k` from the
   simulated distribution and show its curves, actions, liquidity events, taxes,
   and asset details. This is different from a public deterministic simulator:
   the selected rollout is one realized path from the sampled distribution.
5. **Reference validation**: validate scenario references before simulation:
   actor IDs on policies/accounts/assets/liabilities, property IDs on events
   and real-estate assets, one primary owner when owner-only logic is used,
   and unique IDs where the engine assumes uniqueness. Missing references
   should raise clear errors.
6. **Opaque catalog IDs**: replace closed core property enums with opaque
   `str` IDs. Location and tax-regime lookup belongs in app/catalog composition
   or explicit scenario data; core should not enumerate private properties.
7. **Clarify event vs scenario fields**: currently property purchase and
   mortgage origination are mostly static scenario fields, while sale and PE
   sale requests are scheduled events. The mortgage/sale spirals should decide
   and document the rule: either one-time economic changes are all events, or
   initial acquisition is static scenario state and events are future
   transitions. The API should not require callers to provide duplicated,
   conflicting sources of truth.
8. **Policy runtime, not singleton archetypes**: replace hardcoded engine
   branches that parse policy config with the policy runtime described above.
   `_enabled_policy_of()` is a symptom: it silently uses the first enabled
   policy of a type because the engine is shaped around bespoke arrays instead
   of an ordered policy program and instruction applier.
9. **Multi-agent accounting**: current scalar helpers aggregate checking,
   SP500, and PE holdings across all owners. Before the partner spiral, decide
   which result arrays are scenario-level aggregates and which are per-agent,
   then name them accordingly.
10. **Evidence/model boundary**: move source-data and Manifold fetch shapes out
    of `augur/core/schemas.py` when a model/evidence spiral touches them. A
    likely destination is `augur/model/evidence.py` or narrower
    source-specific modules under `augur/model/`.

## API Correctness / Ergonomics Follow-Ups

The public simulator API should make the correct thing easy without pretending
that a deterministic one-rollout runner is the main product. Use the e2e
spirals to pull these changes forward when the current surface gets in the way.

1. **Name the public runner after the product contract**:
   `simulate_set(scenario_set, *, market_provider=None, market_bundle=None)`.
   Do not expose `run_scenario_set_vectorized()` as the long-term public name;
   vectorization is an implementation detail. The public runner should own:
   reference validation, market sampling or bundle validation, execution,
   result wrapping, and serialization hooks.
2. **Separate core results from transport responses**:
   `ScenarioSetRunResponse` is useful for FastAPI/JSON, but core callers should
   get a `SimulationRun` or similar typed object first. That object can expose
   rich accessors and then serialize to the existing response shape. Echoing
   the request and report spec belongs at the app/transport boundary unless a
   core caller explicitly asks for it.
3. **Tighten the market-provider protocol**: the provider should receive a
   single `MarketRequest` and return a `MarketBundle` that is validated against
   that request. The current provider signature duplicates
   `rollout_count`/`horizon_months`/`seed` both as kwargs and inside
   `market_request`, which invites inconsistent inputs. Keep controlled/noop
   providers as provider implementations, not as a deterministic simulator API.
4. **Make shared-path semantics explicit**: `ScenarioSet.market_request` has
   `shared_market_paths`; the public runner should either honor it or remove
   it. For scenario comparison, shared paths across scenarios are usually the
   right default because they reduce noise. If independent paths are supported,
   the result metadata must record which scenario used which sampled bundle.
5. **Add ergonomic scenario builders for tests and app adapters**: e2e tests
   should not have to manually assemble ten nested Pydantic objects to express
   "one owner, $100k cash, monthly spend." Add small builders or factory
   helpers that still return normal `Scenario` / `ScenarioSet` objects and do
   not create a second schema language.
6. **Clarify initial state vs scheduled transitions**: purchase state,
   financing state, ownership, and future sale/liquidity/rental transitions
   should not be split across fields that can contradict each other. Prefer
   either: initial positions in `initial_balance_sheet` plus scheduled future
   events, or explicit month-0 events that create positions. Document the rule
   and validate duplicates. A property sale is a scheduled transition: do not
   implicitly liquidate real estate at the horizon just because the simulation
   ended.
7. **Make result inspection typed and local**: callers should not have to
   spelunk `monthly_columns["cash_usd"]`. Add accessors like
   `run.scenario("base").series("cash_usd", rollout=0)`,
   `run.scenario("base").terminal("net_worth_usd")`, and
   `run.scenario("base").actions(MonthlySpendAction)`. Keep columnar export as
   a reporting/JSON feature.
8. **Make rollout detail a first-class view**:
   `run.scenario("base").rollout(7)` should return one realized sampled path
   with curves, actions, asset details, liabilities, taxes, and ledger entries.
   This is for UI inspection of a selected sample; it is not a separate
   deterministic simulation mode.
   TODO: add a UI-oriented one-rollout evidence/detail API that returns the
   selected rollout's market observations, policy decisions/actions, ledger
   entries, balance snapshots, and curve values in one typed view.
9. **Introduce a ledger for economic truth**: arrays are good for charts, but
   correctness needs auditable cash-flow entries. Taxes, mortgage payments,
   property tax, rental income, sale proceeds, PE sale proceeds, and policy
   sells should produce ledger entries tagged with actor/account/asset IDs,
   month, rollout, amount, category, and cause. Summary arrays should be
   derivable from that truth or reconciled against it in tests.
10. **Separate policy decisions from accounting effects**: `SimulationAction`
    currently mixes "a policy decided to do something" with "money moved."
    Long-term, distinguish policy instructions from ledger entries/state
    transitions. A policy program emits intended operations; the accounting
    engine applies them, records realized effects, and records any shortfall or
    rejection.
11. **Use actor policy programs**: each actor should have an ordered sequence
    of enabled rules with explicit knobs. Multiple monthly-spend or sell-down
    rules should be legal when their order and target accounts are unambiguous.
    Ambiguity should be modeled directly in the instruction applier, not hidden
    behind first-enabled lookup.
12. **Give validation errors stable paths**: Pydantic should handle type/shape
    validation; core should add domain validation with errors like
    `scenarios[0].events[2].property_id references unknown property`. Do not
    let missing references become late `KeyError`/`ValueError` failures inside
    the vectorized engine.
13. **Make IDs uniformly opaque but typed by role**: keep `PropertyId` as an
    opaque catalog key, but use distinct aliases or lightweight wrappers for
    actor/account/asset/liability/property IDs so APIs cannot silently accept
    the wrong ID role. The JSON representation should remain plain strings.
14. **Publish stable metric names**: expose metric IDs through constants or a
    small enum-like registry so app/tests use the same names as core. Preserve
    explicit units in names (`cash_usd`, `sp500_value_usd`) and avoid leaking
    implementation words such as `generic_` into public paths.
15. **Define aggregate vs per-agent result semantics**: scenario-level
    aggregate arrays should have names like `net_worth_usd`; per-agent results
    should be nested or explicitly keyed by `actor_id`. Do this before the
    partner-equity spiral makes aggregate and individual claims diverge.

## Spiral 1: DONE

Cash-only + SP500 + monthly spend. 5 tests in `augur/core/test_e2e.py`:

- `test_cash_only_no_activity_preserves_balance` - $100k checking, flat market
- `test_sp500_only_grows_with_market` - $50k SP500, multipliers
  `[1.0, 1.1, 1.2, 1.3]`
- `test_cash_and_sp500_combined_net_worth` - $30k cash + $70k SP500, flat
- `test_monthly_spend_drains_cash` - $100k cash, $5k/month spend -> $40k at
  month 12
- `test_monthly_spend_records_each_rollout_and_month` - every sampled rollout
  gets its own spend action entries

**Added to engine**: `MonthlySpendPolicy`, `MonthlySpendAction`,
`monthly_spend_usd` array in `ScenarioRunArrays`.

**Learned**:

- No generic "agent spends $X/month" existed -> fixed.
- `MarketBundle` is a frozen dataclass; overriding one multiplier array
  requires full reconstruction -> fix with controlled market test helpers.
- `factor_ids` on `MarketBundleMetadata` appears to have real usage in
  adapters for organizing multiplier paths -> keep for now, but make tests
  able to ignore it.
- Monthly spend action recording created one action for rollout 0 even though
  cash changed across all rollouts -> fixed by recording per-rollout actions.

## Spiral 2: Mortgage Amortization + API Cleanup

### Step 1: Refactor `PropertyId` to opaque `str`

`PropertyId` is a closed `StrEnum` with specific properties
(`SF_ASHTON`, `VALLEJO_CALHOUN`, ...). Properties should be opaque IDs resolved
from a catalog. Before writing the mortgage test, make this change:

- In `scenario_set.py`: replace `class PropertyId(StrEnum)` with
  `PropertyId = str` or a stronger `NewType` only if it remains JSON-friendly.
- Update all references in `scenario_engine.py`, `market_bundle.py`,
  `property_sale.py`, `property_tax.py`, `property_depreciation.py`,
  `local_regulation.py`, app catalog/default injection, and tests.
- Remove `_PROPERTY_LOCATION_DEFAULTS` from core. App/catalog code should fill
  `location_id` and purchase price before simulation, or tests should provide
  them explicitly.
- Keep `location_id` separate. A property ID is a catalog key; a location ID is
  simulation input.

### Step 2: Dedup `MONTHS_PER_YEAR`

Create `augur/core/_constants.py` with `MONTHS_PER_YEAR = 12`. Replace the
duplicated definitions in `augur_accounting.py`, `scenario_engine.py`,
`property_tax.py`, `property_depreciation.py`, `personal_wealth.py`,
`outcome_view.py`, and `augur/model/market_data.py`.

If model code should not import from core, put the constant somewhere neutral
or keep a local model constant deliberately. Do not leave accidental duplicate
definitions.

### Step 3: Distribution-First API + Controlled Market Test Helpers

**DONE**: Added `augur/core/api.py` and updated e2e tests to use the
distribution-first shape:

- `simulate_set(scenario_set, *, market_provider=...)` as the public core
  entry point.
- Result support for selecting one sampled rollout for detail inspection in the
  UI.
- Optional explicit `market_bundle` injection can remain internal/test-facing
  if it is needed for precise e2e assertions.
- Reusable controlled market helpers for e2e tests.

This step should make the next tests short enough that their financial intent
is visible without implying that deterministic simulation is a product API.

**Learned**:

- A thin `SimulationRun` / `ScenarioRun` wrapper is enough to hide columnar
  internals for tests: `series(...)`, `matrix(...)`, `terminal(...)`,
  `actions(...)`, and `rollout(...)` cover the first e2e assertions.
- The app backend can route through `simulate_set(...).to_response()` without
  changing its HTTP response shape.
- The public runner is the right place for pre-engine domain validation. The
  first pass catches unknown actor references with stable paths such as
  `scenarios[0].policies[0].actor_id`.
- Follow-up still needed: turn the initial validation helper into a fuller
  domain validator, decide how independent market paths should work, and move
  more app/model callers off implementation-named vectorized entry points.

### Step 4: Write Mortgage Amortization Test

**DONE**: Agent buys a property at $500k with 20% down, fixed-30 at 6%.
Verify:

- Month-1 interest ~= $2,000, principal ~= $398 for a $400k 30-year loan at
  6%.
- Balance paydown over time.
- Cash starts at $100k, drops by down payment plus buy-side closing costs at
  month 0.
- Location and local regulation are explicit scenario inputs, not inferred
  from a hardcoded core property table.

This exercises property selection, financing, mortgage amortization, and
initial cash outlay. It should also force the event-vs-static-purchase rule to
be documented.

**Learned**:

- A normal owner mortgage amortizes and affects cash, but only partner-equity
  scenarios currently emit `PayMortgageAction`. Decide in the policy-program
  cleanup whether mortgage payment should become an always-on liability-payment
  rule/action.

## Spiral 3: Property Appreciation + Sale + Tax Cleanup

### Step 1: Remove `SF_TAX_RATE` from `augur_accounting.py`

`effective_tax_rate()` in `augur_accounting.py` falls back to
`SF_TAX_RATE = 0.0118268325` when `tax_rate_override` is `None`. Tax rates
should come from `LocalRegulation` or explicit scenario input. Remove the
constant and fallback; callers must pass a rate or look it up deliberately.

### Step 2: Write Property Sale Test

**DONE**: Property sale test with controlled appreciation. Sell at month 60.
Verify:

- Gross proceeds.
- Closing costs including local transfer tax.
- Debt payoff.
- Capital gains tax after exclusion and depreciation recapture when applicable.
- Net proceeds added to cash.

This exercises `PropertySaleEvent` and `property_sale.py`. It should validate
that tax calculation uses `LocalRegulation` instead of hidden defaults.

**Learned**:

- Sale tax and net proceeds are part of simulator truth and now have e2e
  coverage for capital-gains tax after the primary-residence exclusion.
- Depreciation recapture remains covered in focused property-sale tests; bring
  it into an e2e spiral when rental income and depreciation are widened.
- Spiral 7 exposed that no-sale property scenarios were implicitly liquidating
  at the horizon. That is now fixed: only an explicit `PropertySaleEvent`
  produces property-sale cash flow, while no-sale terminal results keep home
  equity in net worth.

## Spiral 4: Rental Income

**DONE**: Property rented at $3k/month with 5% vacancy and 8% management fee.
Verified gross rent, vacancy loss, management fee, net rent, property tax, and
the owner cash-flow impact through `simulate_set()`.

**Cleanup completed**:

- `RentalPlan` is now a Pydantic discriminated union on `rental_mode`, backed
  by the `RentalMode` enum rather than loose strings.
- Mode-specific required fields live in the schema shape: whole-property modes
  require `monthly_rent_usd`; room-rental mode requires
  `room_rent_monthly_usd`.
- Core domain validation still handles cross-object requirements, such as
  rented scenarios needing an explicit property, instead of duplicating
  Pydantic's shape validation.

**Learned / follow-up**:

- `RentalMode` and `OccupancyMode` still overlap conceptually. Keep pressure on
  this in later property/event spirals: occupancy should describe who lives in
  the property, while rental configuration should describe income-producing
  use.
- Room-rental configuration likely needs a positive `rooms_rented`
  requirement.
- Decide whether `TRANSITION_TO_WHOLE_PROPERTY_RENTAL` remains a rental state
  or becomes a scheduled event/policy transition.
- Rental income is currently exposed as arrays, but no rental ledger/action is
  emitted yet. The accounting ledger cleanup should make rental income,
  vacancy, management fees, and property tax auditable entries.

## Spiral 5: SP500 + Checking Floor Policy

**DONE**: Agent holds $50k SP500, cash drains through monthly spend, and a
checking-floor policy sells SP500 to maintain a $10k floor. Verified sell
action recording, basis reduction, realized gain, cash restoration, and no
shortfall when holdings are sufficient.

**Cleanup completed**:

- Checking-floor rules now use ordered enabled-policy execution instead of
  `_enabled_policy_of()` first-match behavior.
- Multiple checking-floor rules can run in policy tuple order, with each rule
  recording its own `SellSp500Action`.

Remaining cleanup:

- Replace `FINANCING_MODE_*` constants in `augur_accounting.py` with
  `FinancingMode`.

**Learned / follow-up**:

- The current checking-floor rule sells a fixed `sale_amount_usd` when cash is
  below the floor. That is the right default behavioral model: a human policy
  is more likely to sell a configured tranche than to solve for exactly enough
  cash to touch the floor. The UI/API should make sale sizing explicit, with
  fixed-tranche sizing as the normal setting.
- `checking_floor_shortfall_usd` is still a summary array. Actions now carry
  per-policy shortfall, but a ledger/result cleanup should define whether the
  summary means max unmet reserve after all rules or per-rule unmet reserve.

## Spiral 6: Private Equity Sale Requests and Liquidity Opportunities

**DONE**: Agent holds PE units worth $200k. A manual `private_equity_sale_request`
asks to sell a configured amount, but the sale only executes when the sampled
market path has a private-equity liquidity opportunity in that month. Verified
after-tax proceeds, destination account/asset, remaining units, remaining
basis, and action log.

Cleanup completed:

- Removed old PE sale-fraction fields from market bundles and rollout adapter output.
  PE liquidity events are binary; the simulator no longer tracks what fraction
  of a PE position can be sold at an event.
- Removed per-event fraction fields from rollout-side `PrivateEquityEvent`.
- Removed the old event-capacity helper. An event/opportunity exposes liquidity;
  sale sizing belongs to policy or explicit sale request, not to the market
  event itself.
- Replaced the old private-equity rebalance policy shape with
  `PrivateEquitySalePolicy`, whose `sale_rule` is a discriminated union. The
  first two rules are `manual_requests_only` and
  `fixed_amount_on_opportunity`.
- Renamed the public manual event to `private_equity_sale_request`.
- Renamed the result metric to
  `private_equity_liquidity_available_value_usd` so result columns describe
  market opportunity rather than policy decision.
- Updated the app scenario-set adapter to emit typed policy/event fields
  directly instead of legacy `parameters` bags.
- Removed stale deployment config fields that implied unused PE sale modes or
  concentration targets.

Remaining cleanup:

- Decide whether automatic PE sale rules should be a single `sale_rule` union
  or an ordered list of PE sale rules, once we have a second real automatic
  behavior.
- Add ledger entries for PE sale gross proceeds, basis, tax, and after-tax
  destination so action logs are not the only audit trail.
- Thread per-holding tax/basis semantics into the scenario API instead of
  using deployment config placeholders.

## Spiral 7: Partner Equity Accrual

**DONE**: Two agents. Partner contributes $1k/month toward a $100k property
with a 0% fixed-30 mortgage. After 60 months, verify partner contribution
arrays, unallocated excess, mortgage paydown, partner ownership percentage,
partner equity claim, owner claim, owner cash, and action logs for partner
cash transfer, mortgage payment, and equity accrual.

This is the first multi-agent e2e test. It should force clarity on aggregate
vs per-agent result arrays and on how actor IDs flow through accounts, assets,
policies, and actions.

Cleanup completed:

- `PartnerEquityAccrualPolicy` can now name its `property_id`; omitting it
  keeps the current single-selected-property shorthand.
- Core validation rejects partner-equity policies that reference a property
  other than the selected scenario property.
- Property disposition no longer treats absence of a sale event as an implicit
  horizon sale. Sale cash flow now requires `PropertySaleEvent`.
- Partner equity no longer uses first-enabled singleton lookup. Multiple
  partner policies execute through actor policy programs, and public arrays
  aggregate agreement results.
- Partner-equity mortgage actions now use the ordinary mortgage servicing
  applier instead of a partner-specific action path.

Remaining cleanup:

- Split `TransferPartnerContributionAction` into actual cash movement and
  applied-to-house-cost accounting. The model now records unallocated excess,
  but a ledger needs to say where that excess lives.

## Policy Runtime Migration Plan

Do this incrementally. Each step should leave `bbr test //augur/...` green and
should preserve the public `simulate_set()` shape.

### Step 1: Add Runtime Types Without Changing Behavior

**DONE (first slice)**: Introduced internal runtime dataclasses/protocols:

- `ActorPolicyProgram`: enabled policy rules grouped by actor in scenario actor
  order, preserving per-actor rule order.
- `PolicyContext`: month and actor context placeholder for policy evaluation.
- `SellAssetInstructionBatch`: columnar intended asset-sale operation.
- `GenericSp500SaleApplication`: realized sale result after accounting applies
  a sell instruction.
- `LedgerEntryBatch`: placeholder for realized accounting entries.

**DONE (schema cleanup slice)**: Policy configuration is now consistently
shaped as explicit typed config. Core policies remain a Pydantic
discriminated union on `policy_type`; private-equity sale rules and liquidity
reserve rules are nested discriminated unions; private-equity sale proceeds use
a typed destination enum instead of a raw literal; rental modes remain a
`RentalMode` enum plus a `RentalPlan` discriminated union.

Still to add as the runtime expands:

- `SimulationState`: vectorized state for accounts, holdings, liabilities,
  basis, ownership, property use, tax state, and per-policy memory.
- `PolicyRuntime`: compiles Pydantic `PolicyConfig` objects into ordered
  runtime rules.
- Legacy `ScenarioKnobs` string literals live on the older scalar/vectorized
  path and should disappear with the remaining `simulate_arrangement()` /
  `simulate_property_vectorized()` cleanup rather than being promoted as the
  public scenario API.

Covered by `//augur/core:policy_runtime_test`, including policy order and
disabled-policy exclusion.

### Step 2: Move Checking-Floor Selling First

**DONE**: Checking-floor is the first migrated policy path.

- `CheckingFloorSellPublicStockPolicy` evaluates current cash and SP500 state.
- It emits `SellAssetInstruction(asset_type=generic_sp500_stock, amount_usd=...)`.
- The instruction applier updates cash, units/value, remaining basis, realized
  gain, and shortfall state.
- Existing checking-floor e2e tests assert arrays and actions still match.

Acceptance met: checking-floor policy evaluation no longer directly mutates
`current_cash`, `remaining_sp500_units`, remaining basis, or result arrays
inside the monthly loop.

Remaining before this slice is fully ledger-backed:

- Add ledger entries from the SP500 sale applier and reconcile sale arrays to
  ledger totals.
- Generalize `SellAssetInstructionBatch` beyond SP500 so PE sales can reuse the
  same instruction family.

### Step 3: Move Monthly Spend to Debit Instructions

**DONE (first slice)**: `MonthlySpendPolicy` now evaluates through the policy
runtime and emits a `DebitAccountInstructionBatch` against the actor's checking
account. The debit applier records a cash ledger entry and updates cash.

Acceptance met for the current checking-account model: multiple monthly-spend
policies remain legal and run in actor program order; spend arrays are derived
from the cash ledger entry emitted by the debit applier.

Remaining before this is a complete account model:

- Replace the single scenario cash array with named cash/account state so a
  policy can choose a specific funding account.
- Persist ledger entries into public result detail once the result API exposes
  a ledger view.

### Step 4: Move Private-Equity Sales to Opportunity + Instruction

**DONE (first slice)**: Market liquidity is now represented as a
`PrivateEquitySaleOpportunityBatch`, and `PrivateEquitySalePolicy` emits a
`PrivateEquitySaleInstructionBatch` before accounting applies the sale.

- Scheduled `PrivateEquitySaleRequestEvent` creates a request observation.
- `PrivateEquitySalePolicy` decides whether to emit a
  `SellAssetInstruction` for a given opportunity/request.
- The applier enforces liquidity availability, computes sold units, basis,
  taxable gain, estimated tax, destination account/asset, remaining holdings,
  and ledger entries.

Acceptance met for the current PE sale shape: market opportunity, explicit sale
request, policy decision, and sale application are distinct runtime objects;
the engine no longer uses first-enabled PE policy lookup for sale execution;
`SellPrivateEquityAction` is recorded from the realized instruction
application.

Remaining before this is a complete PE/account model:

- Reconcile public PE sale arrays directly to persisted ledger entries once the
  result API exposes ledger detail.
- Decide whether `PrivateEquitySalePolicy.sale_rule` should become an ordered
  list of rules once there is a second real automatic PE behavior.
- Thread per-holding tax/basis semantics into the scenario API instead of
  relying on aggregate PE holdings.

### Step 5: Move Liability Servicing and Property Cash Flows

**DONE (first slice)**: Ordinary owner mortgage payments now flow through a
`MortgagePaymentApplication` with cash and liability ledger entries, and normal
mortgage scenarios emit `PayMortgageAction` for each payment month. This makes
the recurring owner mortgage visible in result actions instead of only in
arrays.

**DONE (second slice)**: Property operating cash flow now flows through a
`PropertyOperatingCashFlowApplication`. The applier records rental gross,
vacancy, collected rent, property tax, HOA, insurance, maintenance, management
fee, and leasing fee ledger entries, and the existing result arrays are derived
from that application. The ledger is still internal until the result API grows
a first-class ledger view.

Make recurring property economics explicit accounting entries:

- Optional liability-servicing policy that decides which account pays due
  liabilities if there is more than one plausible source.
- Partner-equity mortgage payments should reuse the same liability-servicing
  applier once partner contracts move to instructions.

Acceptance met for ordinary single-owner mortgages: ordinary mortgage scenarios
produce mortgage payment ledger/action truth, not only partner-equity scenarios.
Acceptance met for internal property operating accounting: recurring rental and
carrying-cost arrays are produced by an applier with ledger entries.

### Step 6: Move Partner Equity to Contract Instructions

**DONE (first slice)**: Partner contributions now compile into a
`TransferCashInstructionBatch`, and house-cost allocation runs through
`apply_partner_house_cost_contribution()`. That applier records contribution
transfer, used house-cost funding, unallocated escrow, and partner principal
credit ledger entries while preserving the existing aggregate result arrays and
actions.

**DONE (second slice)**: Partner ownership accrual now runs through
`apply_partner_ownership_accrual()` instead of bespoke scenario-engine math.
The applier credits partner and owner principal into separate equity ledgers,
applies the optional ownership freeze, computes owner/partner home-equity
claims, and records ownership ledger entries. Public monthly/terminal/fan
results now expose the first ledger-shaped reconciliation metrics:
`partner_principal_credit_usd`, `owner_principal_credit_usd`,
`partner_equity_ledger_usd`, `owner_equity_ledger_usd`,
`partner_house_costs_usd`, and `partner_house_cost_share`.

**DONE (third slice)**: Partner policies now run through actor policy
programs instead of `_enabled_policy_of()` singleton lookup. Multiple
partner-equity policies execute in actor order, each records its own transfer
and equity accrual actions, and scenario-level partner arrays aggregate the
agreements. Mortgage payment actions now come from the shared mortgage
servicing applier even in partner-equity scenarios.

**DONE (fourth slice)**: Runtime ownership output now separates realized
transaction ledger entries from balance snapshots. Principal credits remain
ledger entries; cumulative equity ledgers and owner/partner home-equity claims
are balance snapshots.

**DONE (legacy cleanup)**: Deleted the old `ownership.py` / `real_estate.py`
side path and its tests. The current scenario-set simulator is the only
partner-equity path under `augur/core`.

**DONE (sale-settlement slice)**: Property sales now produce an explicit
settlement shape and a typed `settle_property_sale` action per rollout. The
settlement records gross sale value, selling costs, debt payoff, adjusted
basis, realized gain, depreciation recapture, capital gain/exclusion, taxable
gain, tax, and net proceeds. Public arrays still exist for chart compatibility,
but the one-rollout detail API can now show a truthful sale settlement object.

**DONE (annual sale-tax slice)**: The scenario engine now computes simulated
sale taxes with an annual federal + California pass instead of relying on
point-in-time `cap_gains_rate` shortcuts. The first implementation uses 2026
federal ordinary brackets, standard deductions, long-term capital-gains
thresholds, unrecaptured Section 1250 treatment, 2025 California brackets and
standard deductions, and California Behavioral Health Services Tax over $1M.
It aggregates property depreciation recapture, taxable property capital gains,
public-stock sale gains, and private-equity sale gains by tax year, then
allocates the incremental federal/CA tax back to the sale months and sale
sources. Monthly and terminal result columns now expose federal, California,
total income tax, SP500 sale tax, PE sale tax, and property-sale tax.

**DONE (response serialization coverage)**: The public `simulate_set()`
response payload now has e2e coverage for one-rollout sale action detail across
SP500 sales, private-equity sales, and `settle_property_sale` actions with tax
fields.

**DONE (partner sale-claim slice)**: Partner sale claims now settle against the
tax-adjusted property sale net proceeds instead of mark-to-market home equity.
From the sale month onward, partner and owner claim arrays allocate the
`SettlePropertySaleAction` / property settlement net proceeds after transaction
costs, debt payoff, depreciation recapture tax, and capital-gains tax.

Refactor partner equity as a policy/contract rule:

- Unallocated contribution excess is recorded as cash, escrow, refund, or an
  explicit liability according to the modeled agreement.
- Continue the tax settlement model beyond the first sale-tax slice. TODO:
  aggregate qualified dividends, short-term gains, capital losses, rental
  income, deductible expenses, passive-loss release, SALT/property-tax
  treatment, California conformity/non-conformity, and ordinary income
  schedules beyond a single annual `TaxProfile` input. TODO: make taxes a
  ledger/liability workflow with estimated-payment timing instead of only
  allocating the annual incremental tax back to source sale months.
- Reconsider whether to reintroduce per-component partner contribution
  reporting for interest, tax, insurance, HOA, and maintenance. The deleted
  side path reported those slices; the current core exposes total house costs,
  contribution used, house-cost share, and principal credit.
- Refresh `augur/SPEC.md` once the scenario-set simulator's public promises
  around policies, sale taxes, and one-rollout action detail stabilize.
- Clean up private-equity event vocabulary. TODO: make liquidity opportunities,
  IPO/acquisition events, and user sale requests distinct domain concepts with
  names that do not imply the market opportunity is the agent decision.

Remaining acceptance: persist actor-keyed ledger entries into result detail
instead of exposing only scenario-level arrays; partner-equity outputs should
be keyed by partner actor or derivable from those ledger entries; multiple
partner agreements are no longer silently collapsed in reporting.

### Step 7: Make Arrays Reconcile to Ledger

For every public metric array touched by these policies, add reconciliation
tests that compare array totals to ledger totals. The arrays can stay for chart
performance and API compatibility, but their meaning should be derived from
state/ledger, not bespoke policy-specific math.

## Spiral N+: Structural Cleanup

Once the spirals validate the surface:

1. Split `schemas.py` into focused modules:
   `http_types.py`, `scenario_types.py`, `simulation_types.py`, and model-side
   evidence/source-data modules.
2. Consolidate legacy + vectorized paths. The dedicated ownership/real-estate
   side path is gone; remaining cleanup should focus on deleting or wrapping
   `simulate_arrangement()` and `simulate_property_vectorized()` once all
   callers move to `simulate_set()`.
3. Move `ManifoldMarketSnapshot` and related source fetch shapes to the
   model/evidence layer, then have fitting code consume them to produce
   calibrated priors or provider inputs.
4. Make `augur/core/api.py` the only public core simulation entry point used by
   app/model/tests, with first-class support for inspecting individual sampled
   rollouts from a distribution result.
5. Update `augur/SPEC.md` when the public behavior changes, especially around
   event semantics, multi-agent result semantics, and evidence/model
   boundaries.

## Seven-Day Strategy

Day 1: stabilize Spiral 1. Run the new e2e target, fix immediate issues in
monthly spend action recording, and extract controlled market test support.

Day 2: make property IDs opaque. Update app/catalog default injection and core
tests so core no longer knows specific private property IDs or locations.

Day 3: add `augur/core/api.py`, move e2e tests onto it, and add result accessors
or a thin result wrapper if assertions are still array spelunking. Include a
single-rollout detail accessor so the UI can select one sampled trajectory
without treating it as a deterministic simulation mode.

Day 4: implement the mortgage amortization e2e. Fix purchase/financing
validation and document whether initial acquisition is static scenario input or
a scheduled event.

Day 5: implement property sale/appreciation e2e. Remove hidden SF tax fallback
and make sale/tax/local-regulation dependencies explicit.

Day 6: implement rental income and checking-floor e2e coverage. Start the
policy-program cleanup by making checking-floor behavior an ordered rule with
knobs instead of treating policy types as singleton archetypes.

Day 7: implement the partner-equity e2e now that private-equity sale requests
are split from market liquidity opportunities. End the week with a short
SPEC/update pass and a backlog of only evidence-backed cleanups.

Every day should end with the relevant core e2e target green and a brief note
on newly discovered clunky/dead/weird APIs.

## Verification

After each spiral:

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
