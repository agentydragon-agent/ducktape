# Plan: User-Facing Scenario Layer

## Purpose

Augur currently lets the browser submit a fairly low-level `ScenarioSet` shape.
That shape is already closer to the simulator than to the product UI: it
mentions actors, events, policies, balance sheets, property assumptions, tax
regimes, and similar details. This makes the frontend look like it owns facts
that should come from private config or catalogs, and it makes unsupported
simulator semantics easy to accidentally smuggle through the wire format.

The target is a healthier middle layer:

```
frontend controls
  -> user-facing scenario request
  -> product/scenario translator
  -> low-level augur.sim scenario + sampling request
  -> simulation run
  -> product read model
  -> frontend response
```

Keep the simulator input/output shape mostly fixed. Rationalize the higher-level
request and response shape around the product workflows.

## Ownership Boundaries

### Config-Owned Inputs

These are deployment/private facts. They should not be authored by the browser,
though the UI may display safe summaries.

- Primary household actors and default counterparty identities.
- Opening accounts, balances, assets, tax lots, basis, and liabilities.
- Portfolio/security series mappings and current as-of positions.
- Tax profile facts that are not scenario knobs.
- Default funding policies such as checking-floor behavior and sale preferences.
- Runtime limits and defaults: max rollouts, default rollout count, as-of date,
  model/provider selection, and private fixture paths.

### Catalog-Owned Inputs

These are selectable/reference facts. The browser should usually submit IDs, not
full denormalized catalog records.

- Locations and local regulations.
- Properties: listing/catalog id, price, HOA, rent estimate, beds/baths/sqft,
  property type, source metadata, and any checked public notes.
- Mortgage products or financing presets if they become catalogued products.
- Future series-source mappings, such as home-value series and rent series for
  a property/location.

### User-Owned Scenario Inputs

These are the intentionally small knobs the frontend should submit.

- Which catalog property/location to model.
- Whether the case is a purchase, hold/no-purchase, sale, or later another
  product-level scenario variant.
- Purchase timing, initially probably only month zero.
- Financing choice: cash, fixed 30-year, fixed 15-year, or custom rate/term
  where supported.
- Down payment or loan amount policy, if the UI exposes it.
- Occupancy/rental mode only after that mode has native translator + sim support.
- Explicit scenario label, color, enabled flag, and comparison metadata.
- Report request knobs: percentiles, monthly-table inclusion, selected view, and
  trajectory/detail options.

If a field is not truly user-owned, do not keep it in the frontend request just
because the simulator or old API can represent it.

## Proposed Module Boundary

Create a reusable product layer outside `augur/api`, tentatively:

```
augur/product/
  scenario_request.py      # user-facing request/read-model Pydantic types
  scenario_compose.py      # config + catalog + user request -> sim scenario
  response_model.py        # SimulationRun -> product response/read tables
  validation.py            # product-level unsupported/invalid combinations
```

`augur/api` should become mostly HTTP wiring:

- Parse/validate the product request.
- Load config/catalog/runtime services.
- Call product composition + model sampling + simulator.
- Serialize the product response.

`augur/sim` should not import this layer. It should keep receiving typed,
low-level simulation scenarios and materialized external series context.

## Parallel Product API Strategy

Build this as a parallel protocol instead of replacing the existing
`/api/scenario_sets/run` route in one jump. The server can expose a product
language endpoint while the current low-level `ScenarioSet` route remains as a
compatibility/debug path:

```
POST /api/projections/run          # product-facing request/response
POST /api/scenario_sets/run        # low-level compatibility route for now
```

Each spiral should add one product concept end-to-end:

- product request type
- product validation
- composition into `augur.sim.scenario.Scenario`
- simulation execution
- product response/read model
- parallel product frontend path or a narrow API test

This keeps the endpoint useful at every stage and prevents a giant rewrite
where we define a full product protocol before any of it is exercised.

## Parallel Product Frontend Strategy

Build a parallel frontend surface at the same time as the product endpoint:
a separate page, tab, or dev-only panel that speaks `ProjectionRequest` and
renders `ProjectionResponse`. The existing browser flow can remain on the
low-level route until the product flow covers enough behavior to replace it.

The product frontend should be intentionally thin:

- expose only product-owned knobs
- use generated product wire types
- call `/api/projections/run`
- render the product read model, not simulator internals
- link to trace/detail views only when debugging needs them

Each spiral should land with just enough UI to exercise the new product
concept. For Spiral 1, that can be a monthly spend input, spend-index selector,
rollout/horizon controls, and a cash/net-worth fan view. Later spirals can add
catalog selectors and richer comparison views without forcing the old page to
move prematurely.

## Frontend-Driven Milestones

Drive the rollout by what the new product frontend allows a user to do. Each
milestone should add one coherent UI capability and the smallest backend slice
needed to support it: product request type, validation, composition,
simulation, product response model, and tests.

### Stage 0: Product Sandbox

Create the parallel product page/tab/dev panel.

The frontend can:

- call `/api/projections/run`
- use generated product wire types
- show request/response debug panels
- render an empty or placeholder chart shell

This stage proves routing, generated types, dev-server wiring, and the product
endpoint skeleton without replacing the existing scenario-set UI.

### Stage 1: Cash Runway

Model the smallest useful product scenario: configured cash plus recurring
spend.

The frontend can:

- set monthly spend
- choose inflation indexing on/off
- set horizon, rollout count, and seed
- run the projection and view cash/net-worth percentile bands

This stage proves `CashSpendCase`, product composition into a low-level
spending scenario, loud rejection for unsupported inflation behavior, and the
first product read model.

### Stage 2: Liquid Portfolio Runway

Add configured public-security lots and simple liquidation behavior.

The frontend can:

- keep the Stage 1 spend controls
- set or view a minimum cash buffer
- enable supported taxable-sale behavior when it exists
- view liquid net worth, holdings value, sales, realized gains/taxes if
  supported, and shortfall probability

This stage proves that the product UI can stay simple while config supplies the
opening portfolio, tax lots, security-series mapping, and default funding
policy.

### Stage 3: Simple Scenario Comparison

Let users compare multiple product scenarios side by side before introducing
houses.

The frontend can:

- create multiple named scenarios
- vary spend, buffer, horizon, or other already-supported product knobs
- enable/disable scenarios
- view comparison tables, terminal metrics, and metric deltas

This stage proves multi-scenario product requests and response summaries
without adding new domain complexity.

### Stage 4: Catalog House Purchase

Add the first product-level house-purchase flow.

The frontend can:

- select a catalog property/location by id
- choose purchase timing, initially probably month zero
- choose a financing preset or supported custom financing input
- view home equity, mortgage balance, carrying costs, cash, and liquid net
  worth impact

Catalog/config should supply property facts, local assumptions, opening
portfolio, and default funding policy. Unsupported property-tax, HOA,
insurance, maintenance, or financing semantics must fail loudly rather than be
fabricated.

### Stage 5: House Scenario Comparison

Make the product UI useful for the first real housing decision.

The frontend can:

- compare do-nothing/hold against one or more buy scenarios
- compare properties, down payments, purchase timing, or financing choices
- show scenario deltas for cash, liquid net worth, home equity, carrying costs,
  and failure/shortfall rates

This is the first milestone where the product flow should have equivalence or
regression tests against overlapping old browser-shaped requests.

### Stage 6: Income, Taxes, And Occupancy

Add richer household and property modes only when the simulator has native
semantics for them.

The frontend can:

- select supported income/tax profile variants
- select owner occupancy or supported rental mode
- view tax, rental income, and occupancy-sensitive metrics that are actually
  backed by sim/read-model behavior

Depreciation, recapture, jurisdiction-specific tax behavior, and rental expense
details should stay out of the product request until their ledger/read-model
semantics are explicit.

### Stage 7: Stock Sales And Liquidity Planning

Expose funding policies in product language.

The frontend can:

- choose supported sale/funding strategies for down payments or cash buffers
- compare sale timing and concentration-reduction policies
- view taxes, cash, liquid net worth, shortfall risk, and concentration metrics

The UI should describe goals and policies, not raw simulator transactions.

### Stage 8: Private And Illiquid Assets

Add private/illiquid positions only after the product layer can clearly state
the liquidity regime being modeled.

The frontend can:

- choose supported private-asset assumptions such as liquidity event, tender,
  lockup, or acquisition regimes
- compare liquidity cases against public/liquid baselines
- view product summaries without exposing internal ledgers by default

This stage should come after the simpler public-asset and housing flows are
healthy.

## Proposed Request Shape

Names are provisional; the important part is the ownership split.

```py
class ProjectionRequest(ApiModel):
    request_id: str
    title: str
    sampling: SamplingRunRequest
    report: ProductReportSpec = ProductReportSpec()
    scenarios: tuple[UserScenario, ...]


class SamplingRunRequest(ApiModel):
    exogenous_model_id: str = "current_exogenous_model"
    rollout_count: int
    horizon_months: int
    seed: int


class UserScenario(ApiModel):
    scenario_id: str
    label: str
    enabled: bool = True
    color: str | None = None
    case: ScenarioCase


ScenarioCase = Annotated[
    CashSpendCase | HousePurchaseCase | HoldCurrentPortfolioCase | SellPropertyCase,
    Field(discriminator="case_type"),
]


class CashSpendCase(ApiModel):
    case_type: Literal["cash_spend"] = "cash_spend"
    monthly_spend_usd: float
    spend_index: Literal["none", "inflation"] = "inflation"
    initial_cash_source: Literal["config_default"] = "config_default"


class HousePurchaseCase(ApiModel):
    case_type: Literal["house_purchase"] = "house_purchase"
    property_id: str
    purchase_month: int = 0
    financing: FinancingChoice
    occupancy: OccupancyChoice = OccupancyChoice(mode="owner_occupied")
```

`FinancingChoice` should be a small product union:

```py
FinancingChoice = Annotated[
    CashPurchase | FixedRateMortgage | CustomMortgage,
    Field(discriminator="financing_type"),
]

class FixedRateMortgage(ApiModel):
    financing_type: Literal["fixed_rate_mortgage"] = "fixed_rate_mortgage"
    term_years: Literal[15, 30]
    down_payment_pct: float
    rate_pct: float | None = None  # None means catalog/model default.
```

Open question: whether `rate_pct` belongs in the user request or a catalog/model
assumption. For initial local development it can stay user-settable, but the
type should make that explicit.

## Composition Contract

The product translator takes:

- `ProjectionRequest`
- private `Config`
- property/location catalog
- portfolio/opening-position config
- runtime/model provider configuration

and returns:

- one low-level `augur.sim.scenario.Scenario` per enabled user scenario
- required external level/event series
- `ExogenousSamplingRequest`
- a mapping from user scenario id to composed low-level scenario identity
- structured acceptance/rejection diagnostics

Composition is where product defaults become explicit sim objects:

- User selects `property_id`.
- Catalog supplies price, HOA, location, rent estimate, local regulation.
- Config supplies the primary actor, initial cash/accounts/assets/tax lots.
- Financing choice creates scheduled purchase/mortgage objects.
- Local regulation creates property tax and tax profile hooks where supported.
- Funding config creates liquidity policies.
- Unsupported product choices fail before sim input is produced.

The translator must not silently drop a user-owned field. A field is either:

- accepted and translated,
- rejected with a structured diagnostic, or
- not present in the product request type yet.

## Proposed Response Shape

The frontend should not need full simulator ledgers for normal comparison views.
The response should be a product/read model derived from `SimulationRun`.

```py
class ProjectionResponse(ApiModel):
    request_id: str
    projection_run_id: str
    sampling_metadata: SamplingMetadataView
    scenarios: tuple[ScenarioRunView, ...]
    warnings: tuple[str, ...] = ()


class ScenarioRunView(ApiModel):
    scenario_id: str
    label: str
    accepted: AcceptedScenarioSummary
    rollout_health: RolloutHealthSummary
    distribution: DistributionView
    trajectory: TrajectoryView | None = None
    diagnostics: tuple[ScenarioDiagnostic, ...] = ()
```

Distribution views should stay compact:

- terminal metric table
- metric fan tables by scenario and metric
- percentile bands requested by `ProductReportSpec`
- scenario comparison summaries

Trajectory/detail views should be opt-in:

- selected rollout monthly ledger/read model
- selected accounting detail rows
- selected event summaries
- trace IDs to link back to sim output when debugging

The simulator can keep returning `SimulationRun` with full dataframes. The
product response model decides which views are serialized for the browser.

## Spiral Roadmap

### Spiral 1: Cash Spend

Start with the smallest useful product scenario:

> The configured primary agent starts with configured cash and spends
> `$X/month`, optionally indexed to inflation. Return the distribution of cash
> and net worth over time.

This exercises the new product endpoint without catalog properties, mortgages,
tax lots, property ledgers, or stock sales.

Product request:

- one `CashSpendCase`
- `monthly_spend_usd`
- `spend_index = "inflation" | "none"`
- sampling request with rollout count, horizon, seed

Composition:

- config supplies primary agent and opening cash account
- product case creates one monthly spend obligation/policy
- inflation indexing either maps to the existing supported sim path or fails
  loudly until that support is explicit

Response:

- rollout health summary
- cash/net-worth metric fan
- optional selected-rollout monthly cash table

### Spiral 2: Cash Plus Liquid Portfolio

Add configured public-security lots and checking-floor liquidation.

- config supplies public lots, basis, and external series mapping
- product case can keep the same spend knobs
- response adds liquid net worth, public security value, sales, and shortfalls

### Spiral 3: Catalog Property Purchase

Add the first house purchase product case.

- browser submits property id and financing choice
- catalog supplies property/location/local-regulation facts
- config supplies opening portfolio and default funding policy
- composer creates month-zero purchase, mortgage, property tax, HOA,
  insurance, and maintenance objects
- response adds property value, mortgage balance, home equity, and property
  carrying costs

### Spiral 4: Rental/Occupancy And Taxes

Only add these once their simulator semantics are native enough to avoid
papering over gaps.

- owner occupancy versus rental modes
- rent income/management/leasing fees
- tax profile and jurisdiction handling
- depreciation/recapture only when read-model and ledger semantics exist

### Spiral 5: Private Equity And Rich Liquidity

Add PE cases after the product layer can express why a position is being
modeled and the simulator supports the required liquidity regime.

- liquidity-event-only holdings
- public-market/lockup/acquisition regimes
- sale policies and tender opportunities
- response summaries that do not expose raw internal ledgers by default

## Migration Plan

1. Define the product request/response Pydantic types without changing the
   existing low-level endpoint. Add schema-export and Zod generation coverage.
2. Add a new parallel endpoint that accepts `ProjectionRequest` and implement
   only Spiral 1.
3. Add product composer tests for Spiral 1 against public fixture config.
4. Add response/read-model tests for the cash/net-worth distribution view.
5. Add a parallel frontend page/tab/dev panel that calls the product route for
   Spiral 1 and renders only the product response model.
6. Keep the current `ScenarioSet` route and current frontend flow as the
   compatibility/debug path while the product flow grows.
7. Add equivalence tests as later spirals overlap existing browser-shaped
   requests. For the house slice, prove the current browser-shaped request and
   new product request produce equivalent low-level sim scenarios and matching
   comparison metrics.
8. Grow the product protocol through the spiral roadmap.
9. Move the main frontend request construction from low-level `ScenarioSet` to
   `ProjectionRequest` once house-purchase parity is good enough.
10. Move response materialization/read-model code into the product layer. Keep
    `SimulationRun` as the source, but stop exposing simulator-shaped details by
    default.
11. Remove low-level API fields from the frontend wire once no caller depends on
    them. Keep old URLs invalid if the cleanup requires it.

## Initial Test Targets

- Product model unit tests for request validation and rejected unsupported
  combinations.
- Composer tests against public fixture config/catalog, starting with
  `CashSpendCase`.
- Equivalence tests against the current `//augur:browser_shell_test` scenario
  slice once a spiral overlaps it.
- Browser/API smoke test on the parallel product frontend route.
- Visual goldens only after the response shape or visible metrics change.

## Open Questions

- Should this layer be named `augur/product`, `augur/app`, or
  `augur/usecases`? `product` currently communicates the boundary best.
- How much of financing belongs in catalog/model assumptions versus user input?
- Should selected-trajectory detail be returned with the main run or fetched by
  a follow-up endpoint keyed by `projection_run_id`, `scenario_id`, and
  `rollout_index`?
- Should private config define one canonical primary actor or a named household
  template that the product request references?
- How should saved user scenarios be versioned as the product request type
  evolves?
