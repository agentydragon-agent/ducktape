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
- Optional saved-scenario label/comparison metadata once the product API owns
  persisted comparisons. Color, enabled flags, and selected trajectory remain
  frontend state.
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
POST /api/product/projections/metric_fan  # compact product distribution view
POST /api/product/projections/rollout     # one full product rollout detail
POST /api/scenario_sets/run               # low-level compatibility route for now
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
a separate page, tab, or dev-only panel that speaks `ScenarioKey` plus view
requests. The existing browser flow can remain on the low-level route until the
product flow covers enough behavior to replace it.

The product frontend should be intentionally thin:

- expose only product-owned knobs
- use generated product wire types
- call `/api/product/projections/metric_fan` for aggregate charts
- call `/api/product/projections/rollout` only for single-rollout detail
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

Current status: Stage 0, Stage 1, and the passive mark-to-market part of Stage 2
are implemented in the current tree. The `/product` frontend calls cache-backed
product routes through generated Zod types, the backend composes a cash-spend
`ScenarioKey` plus configured public-security lots into `augur/sim`, and the
product page renders a server-side metric fan with compact rollout summaries.
The metric-fan response does not include every rollout's monthly table; selecting
a ranked rollout sliver calls `/api/product/projections/rollout` on demand,
overlays that rollout on the graph, shows product event markers and an event
table, and shows its terminal metrics beside the distribution percentiles.
Initial public-security positions are exposed through the read-only
`/api/product/portfolio` route. The existing `ScenarioSet` route and frontend
remain the compatibility/debug path.

### Stage 0: Product Sandbox

Create the parallel product page/tab/dev panel.

The frontend can:

- call the product metric-fan route
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

This stage proves product composition into a low-level spending scenario, loud
rejection for unsupported choices, and the first product read model. The request
shape stays flat until a named case union is needed.

### Stage 2: Liquid Portfolio Runway

Add configured public-security lots and simple liquidation behavior.

The frontend can:

- keep the Stage 1 spend controls
- set or view a minimum cash buffer
- enable supported public-security sale behavior
- view liquid net worth, holdings value, sales, realized gains/taxes if
  supported, and shortfall probability

This stage proves that the product UI can stay simple while config supplies the
opening portfolio, tax lots, security-series mapping, and default funding
policy. The passive opening-lot/price-path portion and the first sale-order /
cash-buffer controls are implemented; realized gains, tax behavior, and richer
shortfall summaries remain.

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

## Current Stage 1 Wire Shape

The first product protocol is intentionally narrower than the eventual product
scenario protocol. `ScenarioKey` contains the deterministic product scenario
parts: exogenous model id, horizon months, monthly spend, spend index, and the
funding policy. The funding policy is intentionally still small: an ordered
sell bucket list plus the simulator's cash-buffer trigger and fixed sale
amount. Metric-fan and rollout-detail requests add the seed set or single seed.

The metric-fan response returns sampled exogenous model id, diagnostics, failed
rollout count, a requested-percentile monthly metric table, requested terminal
percentiles, and compact rollout summaries with seed, failure state, terminal
metrics, and rank. It does not echo request fields like horizon months and does
not include per-rollout monthly tables. The rollout-detail response returns one
full rollout table plus a discriminated union of selected-rollout product events
for a requested seed. Current event variants are public-security sales, monthly
expense settlements, and rollout failures. The product portfolio route returns
configured opening cash and public-security positions with lots; it is a
read-only product surface, not part of scenario identity.

This shape deliberately omits request IDs, labels, scenario IDs, selected
rollout state, colors, disabled scenarios, user-selected individual securities,
and gains. Those are either frontend state, config-owned facts, later product
concepts, or not yet supported.

The server owns an in-memory bounded LRU cache keyed by `(ScenarioKey, seed)`.
Requests are deterministic without public run IDs: if a rollout is missing from
cache, the server transparently samples and simulates it from the scenario key
and seed.

Deployment/config owns rollout defaults and limits. The bootstrap payload
publishes `default_rollout_samples`, `max_rollout_samples`, and
`max_horizon_months`; request fields remain explicit.

## Later Product Scenario Shape

Once Stage 1 is healthy, the product protocol can grow back toward named
scenario cases. Names are still provisional; the important part is the ownership
split.

Financing should eventually be a small product union, likely covering cash
purchase, fixed-rate mortgage, and custom mortgage. Fixed-rate mortgage should
carry term, down payment policy, and possibly an explicit rate when the rate is
not supplied by catalog/model assumptions.

Open question: whether `rate_pct` belongs in the user request or a catalog/model
assumption. For initial local development it can stay user-settable, but the
type should make that explicit.

## Composition Contract

The product translator takes:

- `ScenarioKey`
- private `Config`
- property/location catalog
- portfolio/opening-position config
- runtime/model provider configuration

and returns:

- one low-level `augur.sim.scenario.Scenario` for the current Stage 1 request
- required external level/event series
- `ExogenousSamplingRequest`
- structured acceptance/rejection diagnostics

Composition is where product/config/catalog facts become explicit sim objects.
In Stage 1, config supplies the primary actor and initial cash account, and the
request creates one recurring cash-spend obligation. Later house and portfolio
flows should follow the same boundary:

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

## Later Response Shape

The frontend should not need full simulator ledgers for normal comparison views.
The current Stage 1 response is rollout-oriented and compact. A richer
multi-scenario response can be introduced once the product protocol actually
supports scenario comparison. That later shape should carry sampling metadata,
warnings, per-scenario accepted summaries, rollout health, compact distribution
views, optional trajectory/detail views, and diagnostics.

Distribution views should stay compact:

- terminal metric table
- metric fan tables by scenario and metric
- percentile bands requested by whatever report/view controls exist then
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

- one cash-spend projection per request
- `monthly_spend_usd`
- `spend_index = "inflation" | "none"`
- `horizon_months`
- explicit `rollout_seeds`

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

Add configured public-security lots and product funding-policy liquidation.

- config supplies public lots, basis, and external series mapping
- product case can keep the same spend knobs and expose sell-order / cash-buffer knobs
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

Completed:

- Defined the first product request/response Pydantic types in `augur/product`
  and exported them through the schema/Zod pipeline.
- Added cache-backed product metric-fan and rollout-detail routes for Spiral 1
  cash-spend projections with explicit rollout seeds.
- Composed the product request into a low-level sim scenario using configured
  primary cash and recurring spend, including the supported path-indexed
  inflation spend shape.
- Added a parallel `/product` frontend surface in the shared shell. It calls the
  product routes through the shared client, validates request/response payloads
  with generated Zod types, and renders a metric fan plus ranked rollout slivers.
  Selecting a sliver fetches that rollout's detail on demand, overlays it on the
  chart, and shows terminal metrics beside the distribution percentiles without
  downloading full rollout tables in the aggregate metric-fan response.
- Added focused coverage through the product route and browser golden:
  `//augur/api:server_test` and `//augur:product_visual_golden_test`.
- Added passive configured public-security lots to the product projection
  translator, including anchored sampled price paths and product metrics for
  public-security value and liquid net worth.
- Added product funding policy controls and request fields. The product
  translator now maps `sell_order=["public_securities"]` plus the simulator's
  cash-buffer trigger/fixed-sale knobs into low-level liquidity policies.
- Added `/api/product/portfolio` for read-only configured opening cash and
  public-security positions, and rendered those positions in the product
  frontend sidebar.
- Added selected-rollout event rows to `/api/product/projections/rollout`,
  using a discriminated union keyed by `kind`, and rendered those events as
  graph markers plus a table in the product frontend.

Remaining:

1. Add more direct product composer/read-model unit tests around rejection cases
   and edge cases that the e2e route test does not isolate.
2. Keep the current `ScenarioSet` route and current frontend flow as the
   compatibility/debug path while the product flow grows.
3. Add equivalence tests as later spirals overlap existing browser-shaped
   requests. For the house slice, prove the current browser-shaped request and
   new product request produce equivalent low-level sim scenarios and matching
   comparison metrics.
4. Finish Stage 2 liquid portfolio behavior: taxable-sale policy, realized
   gains/taxes, and shortfall summaries.
5. Move the main frontend request construction from low-level `ScenarioSet` to
   product `ScenarioKey` plus view requests once house-purchase parity is good
   enough.
6. Move response materialization/read-model code into the product layer. Keep
   `SimulationRun` as the source, but stop exposing simulator-shaped details by
   default.
7. Remove low-level API fields from the frontend wire once no caller depends on
   them. Keep old URLs invalid if the cleanup requires it.

## Initial Test Targets

- Product model unit tests for request validation and rejected unsupported
  combinations.
- Composer/read-model tests against public fixture config/catalog, starting with
  the flat cash-spend projection request.
- Equivalence tests against the current `//augur:browser_shell_test` scenario
  slice once a spiral overlaps it.
- Browser/API smoke test on the parallel product frontend route. The current
  route-level cash-spend e2e is in `//augur/api:server_test`.
- Visual goldens for visible product frontend changes. The current product
  golden is `//augur:product_visual_golden_test`.

## Open Questions

- Should this layer be named `augur/product`, `augur/app`, or
  `augur/usecases`? `product` currently communicates the boundary best.
- How much of financing belongs in catalog/model assumptions versus user input?
- Once persisted product runs exist, should selected-trajectory detail keep the
  product route's follow-up fetch shape or move behind run-handle slice URLs?
- Should private config define one canonical primary actor or a named household
  template that the product request references?
- How should saved user scenarios be versioned as the product request type
  evolves?
