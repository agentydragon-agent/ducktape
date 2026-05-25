# Plan: Landlord Rental Income + Mid-Horizon Lifecycle Events

Adds (a) realistic landlord rental income with vacancy + property
management agency + taxes, and (b) mid-horizon lifecycle events that
change property occupancy/rental status and the user's residence,
rendered as markers on the rollout graph.

## Goals

1. The user collects rent on an owned property they're renting out
   (whole or fractional), with realistic accounting and federal/CA tax
   treatment.
2. The user can describe events at month N that change the property's
   status (move in / move out / start renting / stop renting / change
   rented fraction / change collected rent) and where the user lives
   (which property, or outside rental).
3. The user can opt into a property management agency that takes
   management + leasing fees and absorbs marketing-time vacancy.
4. Every lifecycle transition shows up as a labeled event on the
   selected rollout's graph.

## What we have today

- `PropertyPurchase.is_primary_residence: bool` — gates the MID policy;
  no rental cashflow modeling.
- `ScenarioKey.monthly_rent_usd` + `rental_location_id` — the user's
  outside rent, indexed via `rent_series_id(rental_location_id)`.
  Flat assumption: user pays this rent for the entire horizon.
- `RentalUsePolicyId` enum in `augur/api/bootstrap.py` —
  `not_rented` / `rent_rooms_while_owner_lives_there` /
  `rent_whole_property`. Defined as a bootstrap option but the product
  surface does not use it yet.
- Property tax (with optional Prop-13 regime), HOA, insurance,
  maintenance, MID, SALT all wired as monthly obligations against the
  owner.
- Counterparty agents: explicit landlord/tenant/lender/tax_authority/
  hoa/insurer/maintenance_vendor/property_seller/spend_sink/
  property_management_agency-doesn't-exist-yet.
- Tax event frames: `tax_accruals`, `tax_breakdowns`, `tax_settlements`.
  `tax_breakdowns` already carries
  `mortgage_interest_deduction_usd`, federal SALT, itemized total.
- `RolloutEvent` discriminated union in `augur/product/wire.py` with
  precedents for `PropertyPurchaseEvent`, `MortgagePaymentEvent`, etc.
  No lifecycle-event variants yet.
- No engine concept of: depreciation, §1250 recapture, §121 exclusion,
  occupancy mode per month, user residence per month, rental status
  per month.

`augur/sim/REQUIREMENTS.md` already articulates the target capability
surface for §1250, §121, depreciation, and occupancy-mode-aware
deductions — but no code implements them. This plan delivers it.

## Out of scope (deferred)

- NIIT (3.8%) on net rental income — in `augur/sim/TODO.md` "Tax", out
  of scope until a scenario surfaces it.
- §469 passive-activity loss limitation — defer; assume rental income
  is the dominant case and losses, if any, deduct fully against
  ordinary income for now. Note the simplification in tests.
- §1031 like-kind exchange — out of scope.
- Real-estate-professional designation — out of scope.
- Tenant churn modeling at the individual-tenant level. Leasing fees
  fire on an average-tenancy cadence (`avg_tenancy_months`, default 24)
  while the property is in `RENTED_*` mode — captures lifetime cost
  without modeling specific tenants.
- Stochastic vacancy. Vacancy is a flat multiplier per
  `vacancy_pct`. Future stochastic vacancy would slot in as a
  modeled series.
- Lumpy HOA dues, location-specific insurance baseline, maintenance
  capex tax treatment — tracked separately in `augur/sim/TODO.md`
  "Real-estate lifecycle". This plan does add occupancy-aware
  insurance + maintenance multipliers (landlord vs owner-occupied);
  see "Occupancy-aware pricing models" below.
- §121 prorating for non-qualified-use periods (post-2008 rule
  attributing gain to non-qualified period). First implementation
  assumes the 2-of-5-years test passes or fails wholesale; we can
  refine later when a scenario surfaces the partial case.
- **Refinance** as a lifecycle event. Pairs naturally with the Next
  Lanes "Mortgage-rate path sampling" item; once that lands, a
  `RefinanceEvent` (new rate + new term + optional cash-out) slots in
  as another lifecycle variant.
- **Rent control / stabilization caps**. `SeriesIndexedAmount`
  escalates by the full rent series ratio. `augur/sim/TODO.md`
  "Exogenous sampling / VECM" already tracks adding a `rent_cap_pct`
  knob on the indexing primitive. Cross-applies to both outside-rent
  and landlord rental income once it lands.

## Engine model

### State buffers (per rollout, per property) — runtime-mutated

All lifecycle-affected state is **runtime-mutated per-month state**,
not precompiled per-month arrays. The same pattern as cash,
liability_balances, etc. today. This keeps the door open for
policy-driven lifecycle decisions (see "Lifecycle decision stream"
below).

| Buffer                                                         | Semantics                                                                  |
| -------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `property_occupancy_mode[rollout, property]`                   | current enum: `OFF` / `OWNER_OCCUPIED` / `RENTED_FULL` / `RENTED_PARTIAL`  |
| `property_rented_fraction[rollout, property]`                  | 0.0 in OFF/OWNER_OCCUPIED, in (0, 1] in RENTED_PARTIAL, 1.0 in RENTED_FULL |
| `property_cumulative_depreciation_usd[rollout, property]`      | monotone non-decreasing; only accrues while in RENTED\_\*                  |
| `property_owner_occupied_months_in_last_5y[rollout, property]` | rolling window count for §121                                              |
| `user_residence_property_id[rollout]`                          | which property the user lives in (or sentinel for outside rental)          |

State-history frames in the decoded result capture the full
`(month, rollout, property)` time series for diagnostic/reporting use.

`property_occupancy_mode` plus `user_residence_property_id` is the
joint state machine. Valid combinations are enforced by lifecycle
decision application; e.g. `OWNER_OCCUPIED` for property X requires
`user_residence_property_id == X`. `RENTED_PARTIAL` allows
`user_residence_property_id` to be either the same property or an
outside rental.

### Lifecycle decision stream

A `LifecycleDecision` is the unit the engine applies to mutate the
joint state machine:

```python
class LifecycleDecision(BaseModel):
    """One transition to apply at a specific (month, rollout)."""

    month: NonNegativeInt
    property_id: str   # property the transition targets
    kind: LifecycleTransitionKind
    params: LifecycleParams   # discriminated by kind: rental plan,
                              # residence target, sale closing costs, …
```

Per-month phase order (extending the existing engine step):

1. **Collect** lifecycle decisions targeting this month from all
   sources (today: scheduled lifecycle events only).
2. **Validate** decisions against current state (can't sell a property
   that's already sold; can't start renting if already renting unless
   the kind is `change_rental_plan`; …).
3. **Apply** decisions in deterministic order (sale before rental
   start, residence change after property-status change). Mutate the
   per-rollout state buffers in place.
4. **Emit** lifecycle marker events into the event log for reporting.
5. Continue with the existing month-step phases (obligation accrual,
   funding decisions, settlements, tax accrual).

For phase 1–4 of this plan, the **only source** of decisions is the
scenario's compiled scheduled events (`PropertyPurchase.lifecycle_events`

- `ScenarioKey.residence_timeline`). The compiler reduces these to a
  sparse `LifecycleDecision` table indexed by `(month, rollout)` —
  identical across rollouts since they're deterministic inputs.

### Future: policy-driven lifecycle (architectural placeholder)

The decision stream is deliberately pluggable. A future
`LifecyclePolicy` (ordered actor policy program, analogous to today's
`PrivateEquityTenderPolicy` / `FundingPolicy`) would slot in as a
second source of `LifecycleDecision` records:

- Reads current state vectorized across rollouts:
  `cash[rollout]`, `property_value[rollout, property]`,
  `mortgage_balance[rollout, property]`, `net_worth[rollout]`,
  `property_occupancy_mode[rollout, property]`, etc.
- Emits decisions targeting the **current** month based on observed
  state. Example: _"if house ≥80% of NW, sell"_ → boolean mask over
  rollouts → emit `PropertySaleEvent` for the masked subset.
- Runs in step 1 of the per-month phase, before validation/apply.

This plan does **not** ship a policy interface. It only commits to
the data shape (`LifecycleDecision`) and the per-month
collect-validate-apply loop, so that adding a second source later is
purely additive. No re-architecture needed.

### Occupancy-aware pricing models

Some costs scale with occupancy mode in real life — landlord insurance
runs 15–25% higher than owner-occupied (HO-3 vs DP-3), rental
maintenance runs 1.3–2× owner-occupied because tenants are harder on
the property and you can't defer fixes. The plan does **not** add a
proliferation of YAML knobs for these multipliers. Instead, both live
as **deterministic Python pricing functions** in `augur/sim/pricing.py`
(new module). The engine calls them each month given current state
(`occupancy_mode`, `location_id`, `base_annual_pct`) and gets back the
applied rate.

```python
# augur/sim/pricing.py
def insurance_rate(*, base_annual_pct: float, occupancy_mode: OccupancyMode) -> float:
    """Occupancy-aware homeowners/landlord insurance rate.

    Returns base_annual_pct scaled for landlord vs owner-occupied.
    """

def maintenance_rate(*, base_annual_pct: float, occupancy_mode: OccupancyMode) -> float:
    """Occupancy-aware maintenance rate (rentals run higher)."""
```

Each function is a pure Python computation, fully unit-tested, with
hard-coded constants for the multipliers (citable to industry
underwriting heuristics). Replacing the constants with a fitted model
later is internal.

**Why Python and not YAML**: these are pricing models (functions
of multiple state variables), not single deployment-configured rates.
A YAML approach would either need a lookup table per
`(location × occupancy)` pair or a separate scale factor field per
cost — both fragile and not extensible to richer state.

**Why `augur/sim` and not `augur/model`**: these are deterministic
state-conditional pricing functions, not stochastic exogenous paths.
`augur/model` is the home for evidence-driven path sampling
(`ExogenousSamplingRequest` → `SampledExogenousBundle`). A future
**stochastic** pricing model — e.g. the probabilistic mortgage-offer
model from `augur/TODO.md` "Exogenous Models & Evidence" (offered rate
distribution conditioned on term + credit score + LTV) — _would_
belong in `augur/model/` because it samples. The deterministic
multipliers here do not.

The split convention:

- **`augur/sim/pricing.py`**: deterministic, state-conditional pricing
  functions. Called inline in the engine. No randomness, no sampling.
  Examples: insurance occupancy multiplier, maintenance occupancy
  multiplier, future `closing_cost_pct(location, sale_price)`,
  `landlord_insurance_premium(base, vacancy_history)`.
- **`augur/model/pricing/`** (future, not in this plan): stochastic
  pricing models that sample a distribution. Examples: mortgage offer
  model (rate given term + credit), insurance claim frequency given
  region, vacancy duration given market.

### Land/building basis split

For depreciation, only the building basis depreciates over 27.5 years
straight-line. Add to deployment YAML on the property record (or
location default):

```yaml
land_value_pct: 0.30 # 30% of purchase price attributed to land
```

If absent, default to a configurable per-location value (start with
`0.30` for SF/Vallejo until tax-assessor data flows in). Document in
`augur/api/AGENTS.md` that this is a tax-assessor concept, not a
market-value concept.

### Depreciation accrual

While `property_occupancy_mode[t, r, p]` is `RENTED_FULL` or
`RENTED_PARTIAL`:

```
monthly_depreciation = (
    building_basis * property_rented_fraction[t, r, p] / (27.5 * 12)
)
property_cumulative_depreciation_usd[t, r, p] += monthly_depreciation
```

Building basis is adjusted basis at the start of the depreciation
period (= purchase price × (1 - land_value_pct) + capitalizable
closing costs). For partial-rental periods, the rented fraction of
basis is what depreciates; switching from RENTED_FULL to OWNER_OCCUPIED
pauses depreciation.

### §121 primary-residence exclusion (sale-time)

At property sale, compute exclusion eligibility:

```
qualified  = property_owner_occupied_months_in_last_5y[sale_month] >= 24
exclusion  = qualified ? min(realized_gain, 250000) : 0   # single filer
```

(Joint filer / $500k cap deferred until filing-status support lands.)
After exclusion, remaining gain is taxed: long-term capital gains on
gain minus depreciation recapture; §1250 unrecaptured depreciation is
taxed @ 25% federal + CA ordinary.

### §1250 unrecaptured-depreciation recapture (sale-time)

At property sale:

```
recapture_amount = min(realized_gain, cumulative_depreciation)
federal_recapture_tax = recapture_amount * 0.25
ca_recapture_tax     = recapture_amount * ca_ordinary_marginal_rate
```

Recapture happens before §121 exclusion: §121 does NOT shelter the
recaptured portion.

### Schedule E expense routing

While the property is `RENTED_FULL` or `RENTED_PARTIAL`, expenses
attributable to the rented portion route to Schedule E (rental income
deduction) instead of Schedule A:

- Mortgage interest × rented fraction → Schedule E (not MID).
- Property tax × rented fraction → Schedule E (not SALT-capped).
- HOA × rented fraction → Schedule E.
- Insurance × rented fraction → Schedule E.
- Maintenance × rented fraction → Schedule E (treating routine
  maintenance as deductible; capex deferred to a later improvement
  basis pass).
- Management fees → Schedule E.
- Leasing fees → Schedule E.
- Depreciation → Schedule E.

`tax_breakdowns` schema gains:

- `net_rental_income_usd` — gross rent collected minus all Schedule E
  deductions. Can be negative; if negative, deducts against ordinary
  income for now (passive-loss limitation deferred).
- `schedule_e_deductions_usd` — sum of routed deductions.
- `depreciation_recapture_usd` — set only on the sale month.
- `section_121_exclusion_usd` — set only on the sale month.

### Owner-occupied vs not (MID + SALT-cap behavior)

MID applies only when the property is `OWNER_OCCUPIED` for some
fraction of the year (per §163(h)(3)). For mixed-use months
(`RENTED_PARTIAL` with user in the property), interest is split by
`(1 - rented_fraction)` to Schedule A (MID-eligible up to the cap) and
`rented_fraction` to Schedule E.

SALT cap applies only to the Schedule A portion of property tax; the
Schedule E portion is uncapped.

## Wire shape

### `PropertyPurchase` additions

```python
class RentalManagement(ApiModel):
    """Property management agency terms."""
    management_fee_pct: NonNegativeFloat        # of gross rent collected
    leasing_fee_months: NonNegativeFloat        # months of rent per leasing event
    avg_tenancy_months: PositiveInt = 24        # cadence for leasing-fee firing
    vacancy_pct: NonNegativeFloat = Field(le=1.0)  # 0..1 multiplier on collected rent

class PropertyPurchase(ApiModel):
    # existing fields …
    purchase_month: NonNegativeInt = 0  # was implicit 0; now configurable
    land_value_pct: NonNegativeFloat | None = None  # override location default
    initial_rental: RentalIncomePlan | None = None  # rent immediately at purchase
    rental_management: RentalManagement | None = None
    lifecycle_events: tuple[PropertyLifecycleEvent, ...] = ()

class RentalIncomePlan(ApiModel):
    monthly_rent_collected_usd: PositiveFloat   # base, will index by rent series
    fraction_rented: PositiveFloat = Field(le=1.0)  # 1.0 = whole property
```

Leasing fee fires every `avg_tenancy_months` while the property is in
`RENTED_*` mode (first fire at the month rental status activates).
This captures the lifetime cost of tenant turnover without modeling
specific tenant identities.

### Lifecycle events (discriminated union)

```python
class _PropertyLifecycleEventBase(ApiModel):
    month: PositiveInt  # 0 is purchase month; events fire at month >= 1

class StartRentingEvent(_PropertyLifecycleEventBase):
    kind: Literal["start_renting"] = "start_renting"
    plan: RentalIncomePlan

class StopRentingEvent(_PropertyLifecycleEventBase):
    kind: Literal["stop_renting"] = "stop_renting"

class ChangeRentalPlanEvent(_PropertyLifecycleEventBase):
    kind: Literal["change_rental_plan"] = "change_rental_plan"
    plan: RentalIncomePlan

class PropertySaleEvent(_PropertyLifecycleEventBase):
    kind: Literal["property_sale"] = "property_sale"
    closing_cost_pct: NonNegativeFloat = 5.0  # selling-side; typical broker + transfer

class CapitalImprovementEvent(_PropertyLifecycleEventBase):
    """Capital improvement: cash outflow, basis bump, new 27.5y depreciation track."""
    kind: Literal["capital_improvement"] = "capital_improvement"
    amount_usd: PositiveFloat
    description: str = ""   # human label for graph/ledger

PropertyLifecycleEvent = Annotated[
    StartRentingEvent | StopRentingEvent | ChangeRentalPlanEvent
    | PropertySaleEvent | CapitalImprovementEvent,
    Discriminator("kind"),
]
```

Repairs vs improvements per tax law: routine maintenance is expensed
Schedule E this year (current `maintenance_pct` flow); improvements
are capitalized — they add to adjusted basis and depreciate over
27.5y on their own clock (or amortize against the remaining building
life). `CapitalImprovementEvent` is the explicit improvement input.

### User-residence timeline

The user's outside-rent obligation is a function of where they live.
Replace today's flat `monthly_rent_usd` + `rental_location_id` with a
timeline:

```python
class OutsideRentSegment(ApiModel):
    start_month: NonNegativeInt
    monthly_rent_usd: PositiveFloat
    rental_location_id: str

class OwnerResidenceSegment(ApiModel):
    """User lives in an owned property; no outside rent obligation."""
    start_month: NonNegativeInt
    property_id: str  # must match a configured property purchase by then

class ScenarioKey(ApiModel):
    # existing fields …
    residence_timeline: tuple[OutsideRentSegment | OwnerResidenceSegment, ...] = ()
```

Segments are interpreted as "at this month and after, until the next
segment, the user lives like this." Backward-compatible decoding for
the simple case: if `residence_timeline` is empty and
`monthly_rent_usd > 0`, decode as
`(OutsideRentSegment(start_month=0, monthly_rent_usd=…, rental_location_id=…),)`;
if `monthly_rent_usd == 0` and a `property_purchase` exists with
`is_primary_residence`, decode as
`(OwnerResidenceSegment(start_month=0, property_id=…),)`. We can drop
the legacy flat fields once the frontend is wired.

### Rollout-event additions

```python
class StartRentingMarkerEvent(_RolloutEventBase):
    kind: Literal["start_renting"] = "start_renting"
    property_id: str
    monthly_rent_collected_usd: float
    fraction_rented: float

class StopRentingMarkerEvent(_RolloutEventBase):
    kind: Literal["stop_renting"] = "stop_renting"
    property_id: str

class ChangeRentalPlanMarkerEvent(_RolloutEventBase):
    kind: Literal["change_rental_plan"] = "change_rental_plan"
    property_id: str
    monthly_rent_collected_usd: float
    fraction_rented: float

class ResidenceChangeEvent(_RolloutEventBase):
    kind: Literal["residence_change"] = "residence_change"
    from_property_id: str | None  # None = outside rental
    to_property_id: str | None    # None = outside rental

class PropertySaleMarkerEvent(_RolloutEventBase):
    kind: Literal["property_sale"] = "property_sale"
    property_id: str
    gross_proceeds_usd: float
    realized_gain_usd: float
    section_121_exclusion_usd: float
    depreciation_recapture_usd: float

class RentalIncomeEvent(_RolloutEventBase):
    """Per-month rent collected (after vacancy + management fees)."""
    kind: Literal["rental_income"] = "rental_income"
    property_id: str
    gross_rent_usd: float
    vacancy_loss_usd: float
    management_fee_usd: float
    leasing_fee_usd: float    # nonzero on leasing-fee firing months only
    net_to_owner_usd: float

class CapitalImprovementMarkerEvent(_RolloutEventBase):
    kind: Literal["capital_improvement"] = "capital_improvement"
    property_id: str
    description: str
```

`amount_usd` on the base class is fine for the "headline number"; the
extra fields give the ledger detail.

## Phase sequence

Each phase ends with a passing test slice and a meaningful product
demonstration.

### Phase 1: Static landlord rental + agency, no lifecycle, no taxes

Goal: scenarios can declare a property that's rented from month 0 for
the whole horizon, with rent + vacancy + management/leasing fees
flowing as real cashflows.

- Engine: `property_occupancy_mode` buffer initialized from
  `PropertyPurchase.initial_rental`; constant for the horizon.
  Modeled as runtime-mutated per-rollout state (see "State buffers"
  above), even though no transitions happen yet — sets the shape for
  later phases without retrofit.
- Engine: recurring inbound tenant→owner transfer, gross rent ×
  `(1 - vacancy_pct)` × `fraction_rented`, indexed by
  `rent_series_id(property.location_id)`.
- Engine: recurring outbound owner→management transfer for
  `management_fee_pct × net rent`.
- Engine: leasing-fee outbound owner→management transfer every
  `avg_tenancy_months` while the property is in `RENTED_*` mode,
  starting at the month rental status activates (month 0 in phase 1).
- Engine: invoke `pricing.insurance_rate` and
  `pricing.maintenance_rate` each month so landlord vs owner-occupied
  scaling lands together with the rest of the plumbing.
- Wire: `RentalIncomePlan` + `RentalManagement` on
  `PropertyPurchase`. New counterparty agents `tenant`,
  `property_management_agency`.
- Frontend: rental panel under the property purchase section. Form
  fields: monthly rent collected, fraction rented (slider or
  number 0.0–1.0), vacancy %, management fee %, leasing fee months,
  avg tenancy months.
- Tests: `RentalIncomeEvent` rows appear monthly with the expected
  amounts; leasing fee fires at months 0, `avg_tenancy_months`,
  `2 * avg_tenancy_months`, …; net cash flow matches the expected
  formula; rent indexes correctly via the rent series; insurance +
  maintenance are scaled by the occupancy-aware pricing functions.

**Acceptance**: a scenario with a $1M property, fully rented at
$5k/mo, 5% vacancy, 8% management, 1mo leasing fee every 24 months
produces ~$53.5k/yr net rental cash flow averaged over the lease
cycle, and grows with the location rent series.

### Phase 2: Rental taxes (depreciation + Schedule E routing)

Goal: rental income is taxed as ordinary income with Schedule E
deductions, and depreciation accrues against building basis.

- Engine: `property_cumulative_depreciation_usd` buffer; monthly
  accrual = `building_basis × fraction_rented / (27.5 × 12)`.
- Engine: when computing `tax_breakdowns` ordinary income, add net
  rental income (= gross rent − vacancy − management − leasing −
  rented-share of mortgage interest − rented-share of property tax −
  rented-share of HOA / insurance / maintenance − depreciation).
- Engine: when computing MID, multiply by `1 - rented_fraction`. When
  computing SALT-eligible property tax, multiply by
  `1 - rented_fraction`.
- Wire/product: extend `tax_breakdowns` projection with
  `net_rental_income_usd`, `schedule_e_deductions_usd`,
  `property_depreciation_usd`.
- Frontend: rental tab adds an info panel "Year-1 rental tax
  estimate: …".
- Tests: rental scenario with positive net rental income increases
  ordinary income; rental scenario with negative net rental income
  reduces ordinary income (passive-loss limitation deferred); MID is
  reduced when partial rental; depreciation accrues monthly and shows
  in the breakdown.

**Acceptance**: a fully-rented property with $5k/mo rent, $400k
mortgage at 6%, $15k/yr property tax pays roughly $3-4k/yr federal
income tax on net rental income (depending on basis and other
income); cumulative depreciation reaches ~$36k after 36 months on a
$700k building basis.

### Phase 3 sub-phases (current best plan after Phase 2 landed)

Phase 2 left the engine with **compile-time-baked** rented_fraction:
`plan.property_rented_fraction[prop]`, `plan.liability_rented_fraction[lia]`, plus
compile-time scaling of MID (`tax_link_mid_principal_ratio` ×= `(1 - rented_fraction)`)
and per-obligation `property_tax_owner_fraction`. To support mid-horizon
lifecycle events, all of these must become runtime-state-driven.

- **3.0**: Sim scenario types (`PropertyLifecycleEvent` union of
  `StartRentingEvent` / `StopRentingEvent` / `ChangeRentalPlanEvent`).
  Runtime state buffer `CurrentStateBuffers.property_rented_fraction[R, P]`
  initialized from `plan.property_rented_fraction[P]`. Per-month
  `_apply_lifecycle_events` mutates the state buffer. Depreciation accrual
  reads runtime state. Sim-layer tests for: rented_fraction transitions
  mid-horizon → depreciation rate changes accordingly. (MID/SALT/property-tax
  still use initial rented_fraction in this sub-phase — limitation documented.)
- **3.1**: Refactor MID + property-tax obligations to use runtime state.
  - Mortgage interest: split each month's paid interest into
    `current.liability_owner_interest_ytd[R, L]` (× `1 - rented_fraction`) and
    `current.liability_rental_interest_ytd[R, L]` (× `rented_fraction`). MID at
    year-end multiplies the owner buffer by `tax_link_mid_principal_ratio`
    (now unscaled at compile time); rental buffer deducts as Schedule E.
  - Property tax: scale obligation_property_tax_owner_fraction at settle time
    by `current.property_rented_fraction[r, prop]` instead of the compile-time
    array. Same for the deductible_fraction → Schedule E.
- **3.2**: Residence timeline. `ScenarioKey.residence_timeline` with
  `OutsideRentSegment | OwnerResidenceSegment`. Engine gates outside-rent
  obligation on `current.user_residence_property_id[R]`. Wire-layer
  backward-compat decoding from flat `monthly_rent_usd`.
- **3.3**: `CapitalImprovementEvent` — debits cash, bumps `building_basis`
  by amount_usd, depreciation continues on the new (higher) basis.
- **3.4**: Wire layer + product translator for PropertyLifecycleEvent +
  ResidenceTimeline. Translator pushes them through to sim scenario.
- **3.5**: Frontend lifecycle editor + residence timeline editor.

Each sub-phase ships independently with its own e2e tests.

### Phase 3 (original plan — superseded by sub-phases above)

Goal: scenarios can declare events that change rental status or
fraction mid-horizon, and the engine applies them via the
`LifecycleDecision` stream defined above.

- Wire: `PropertyPurchase.lifecycle_events` with `StartRentingEvent`,
  `StopRentingEvent`, `ChangeRentalPlanEvent`, `CapitalImprovementEvent`
  (no `PropertySaleEvent` yet — phase 4).
- Wire: `ScenarioKey.residence_timeline` with `OutsideRentSegment` +
  `OwnerResidenceSegment`. Backward-compat decoding from flat
  `monthly_rent_usd` until frontend ships the editor.
- Compiler: validate scheduled lifecycle events at scenario load and
  reduce them to a sparse `LifecycleDecision` table indexed by
  `(month, rollout)` — identical across rollouts since they're
  deterministic inputs at this phase.
- Engine: in the per-month phase, collect decisions targeting this
  month from the precompiled table, validate against current state,
  apply in deterministic order (sale > rental start/stop/change >
  residence change > capital improvement), mutate state buffers,
  emit marker events into the event log.
- Engine: outside-rent obligation enabled/disabled per month based on
  `user_residence_property_id`. Leasing-fee cadence resets each
  `StartRentingEvent`.
- Engine: `CapitalImprovementEvent` debits cash, increases
  `building_basis` by `amount_usd`, and adds the improvement to the
  cumulative depreciation track (treating it as a 27.5y SL bucket on
  its own clock for simplicity; if the property is currently rented,
  depreciation on the new basis accrues from the improvement month).
- Frontend: per-property lifecycle editor (compact list-of-events
  table with "+ Add event" button). Residence-timeline editor as a
  separate accordion section.
- Tests: scheduled events produce `LifecycleDecision` records and
  apply as expected; end-to-end scenario "buy, owner-occupy 24mo,
  start renting whole property at month 24, user moves to outside
  rental at month 24, capital improvement of $30k at month 36"
  produces the expected cashflows, depreciation accrual starting at
  month 24, MID flipping off at month 24, SALT cap freeing up at
  month 24, outside rent obligation kicking in at month 24, and
  basis bump + accelerated depreciation from month 36.

**Acceptance**: a 5-year "live in then rent out" scenario produces
the right cashflow shape and tax treatment at each phase boundary.

### Phase 4: Property sale + §1250 recapture + §121 exclusion

Goal: scenarios can sell the property mid-horizon or at end-of-horizon
with realistic tax treatment.

- Wire: `PropertySaleEvent` lifecycle variant with closing-cost %.
- Engine: at sale month, compute:
  - Gross proceeds = market value at sale month (from home-value
    series) × (1 - closing_cost_pct).
  - Realized gain = gross proceeds - adjusted basis (where adjusted
    basis = purchase price + capitalizable closing costs -
    cumulative depreciation).
  - Depreciation recapture (§1250 unrecaptured) = min(realized gain,
    cumulative depreciation), taxed @ 25% federal + CA ordinary
    marginal.
  - §121 exclusion: if owner-occupied ≥ 24 of the prior 60 months,
    exclude up to $250k of the post-recapture gain (single filer).
  - Long-term capital gains tax on the remaining gain.
  - Mortgage payoff at sale month (existing flow).
- Engine: state buffers freeze post-sale (property "disappears").
- Frontend: sale event in the lifecycle editor.
- Tests: sale of a never-rented owner-occupied property gets full
  §121 exclusion; sale of a fully-rented investment property gets no
  §121 and full §1250 recapture on depreciation; sale after
  owner-occupied + rented mixed history gets the right
  proration of qualifying months.

**Acceptance**: "buy month 0, owner-occupy 36mo, rent 36mo, sell
month 72" produces correct §121 (qualifies; 24-of-60 satisfied) and
§1250 recapture on the 36mo of depreciation.

### Phase 5: Rollout-graph annotation

Goal: every lifecycle event renders as a labeled marker on the
selected rollout's chart, with hover text describing the transition.

- Wire: new `RolloutEvent` variants
  (`StartRentingMarkerEvent`, `StopRentingMarkerEvent`,
  `ChangeRentalPlanMarkerEvent`, `ResidenceChangeEvent`,
  `PropertySaleMarkerEvent`, `RentalIncomeEvent`).
- Product decoder: emit these events alongside the existing
  `PropertyPurchaseEvent` / `MortgagePaymentEvent` / etc.
- Frontend: chart annotation layer. Markers grouped by month; the
  hover surfaces all events at that month. Distinct icon/color per
  event kind.
- Tests: visual goldens for a multi-phase scenario.

**Acceptance**: a "buy, live, rent, sell" rollout shows markers at
months 0 (purchase), 24 (move out + start renting + residence change
to outside rental), and 72 (sale).

## Open design questions

- **Building basis split source**: deployment YAML default per
  location vs explicit `land_value_pct` on each `PropertyPurchase` vs
  hardcoded 30%? Start with **explicit override on PropertyPurchase
  falling back to a location-level default in deployment YAML**; both
  can be optional and default to `0.30`. Document the simplification.
- **Vacancy granularity**: flat % multiplier (current plan) vs a
  discrete "vacant month" event stream sampled from the exogenous
  bundle. The user asked for "realistic" — the multiplier is the
  industry-standard approximation for long-horizon investor
  underwriting. Stochastic vacancy belongs in `augur/sim/TODO.md`
  "Exogenous sampling / VECM" as a follow-up.
- **Leasing fee firing**: once at rent-start (current plan) vs once
  per N-year lease cycle. Industry: typically 1mo new tenant, 0.5mo
  renewal, average tenancy ~2y. Modeling tenant turnover is real
  scope creep; pick the single-firing model and document the
  simplification.
- **Mid-horizon property purchase**: `purchase_month` field on
  `PropertyPurchase` could go from "configurable" all the way to
  "stochastic offer model" (already in `augur/TODO.md`). For this
  plan, `purchase_month=0` stays the only tested case; field exists
  for future use but the engine asserts month 0 in phase 1, relaxes
  in a follow-up.
- **Closing costs at sale**: typical SF is ~6% (broker 5% + transfer
  tax 0.68% + escrow + title). Default to 5% with the broker fee
  split out? Or a single `closing_cost_pct` on the sale event?
  Single number for the plan; future split when needed.
- **Residence timeline + multi-property**: the timeline assumes the
  user is in exactly one place at a time. Multi-residence (e.g.
  primary + vacation home) defers to whenever a scenario surfaces it.
- **§121 prorating**: phase 4 plan implements the wholesale
  qualifies/doesn't-qualify test (24 of last 60 months). The
  post-2008 non-qualified-use proration is real tax law but adds
  fiddly state. Defer to a follow-up bullet in `augur/sim/TODO.md`.

## Verification

After each phase:

```bash
bbr test //augur/sim:simulate_test //augur/api:server_test //augur/product:service_test
```

After phase 5:

```bash
bbr test //augur:visual_test
```

A new visual golden covers the multi-phase rollout chart with all
lifecycle markers.

## Sim-layer e2e test coverage

Every phase adds sim-layer e2e tests in
`augur/sim/test_rental_lifecycle_e2e.py` (or extends the existing
`augur/sim/test_e2e.py`). These tests build a `Scenario` directly,
call `simulate_with_external_series_dense(...)`, decode the result,
and assert against:

- the **event frames** (`transfers`, `obligation_settlements`,
  `tax_accruals`, `tax_breakdowns`, `tax_settlements`,
  `lot_dispositions`, `mortgage_payments`, lifecycle event frames),
- the **state history** (cash, property_occupancy_mode,
  cumulative_depreciation, liabilities, ownership stakes), and
- the **rollout status** (FAILED on shortfall; healthy otherwise).

Sim-layer tests use deterministic exogenous series (constant rent
series, constant home-value series) so cashflows are exact-math
predictable. Stochastic tests use the existing `simple` provider with
a fixed seed and assert ranges.

### Coverage matrix

Each cell is one named test. Phase column = when the test is added.

| Test                                                                                | Phase | What it locks down                                                                                                                   |
| ----------------------------------------------------------------------------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `test_rental_income_flows_monthly_at_constant_rent`                                 | 1     | Tenant→owner transfer fires every month; amount = base × (1 - vacancy) × fraction_rented after rent_series scaling.                  |
| `test_rental_income_indexed_by_rent_series`                                         | 1     | Doubling the rent series doubles the monthly transfer.                                                                               |
| `test_vacancy_pct_zero_collects_full_rent`                                          | 1     | Edge case: vacancy_pct=0 means no reduction.                                                                                         |
| `test_vacancy_pct_one_collects_no_rent`                                             | 1     | Edge case: vacancy_pct=1 means zero rent.                                                                                            |
| `test_fraction_rented_half_collects_half_rent`                                      | 1     | Partial rental.                                                                                                                      |
| `test_management_fee_paid_monthly_against_net_rent`                                 | 1     | Owner→management transfer = management_fee_pct × net rent each month.                                                                |
| `test_leasing_fee_fires_at_rent_start_and_every_avg_tenancy_months`                 | 1     | Leasing fee at months 0, `avg_tenancy_months`, `2 * avg_tenancy_months`, … while in `RENTED_*`. Amount = leasing_fee_months × base.  |
| `test_no_rental_management_means_no_agency_fees`                                    | 1     | Optional management; absent → no fees.                                                                                               |
| `test_insurance_rate_scales_for_landlord_vs_owner_occupied`                         | 1     | `pricing.insurance_rate` returns higher value for `RENTED_*` than `OWNER_OCCUPIED`.                                                  |
| `test_maintenance_rate_scales_for_landlord_vs_owner_occupied`                       | 1     | Same shape for `pricing.maintenance_rate`.                                                                                           |
| `test_rental_income_obligation_settles_against_cash_buffer`                         | 1     | Rental income is an inbound obligation; ledger reconciles.                                                                           |
| `test_depreciation_accrues_monthly_against_building_basis`                          | 2     | cumulative_depreciation monotone; rate matches building_basis × fraction_rented / 330.                                               |
| `test_depreciation_zero_when_not_renting`                                           | 2     | OWNER_OCCUPIED → no accrual.                                                                                                         |
| `test_depreciation_resumes_when_rental_resumes`                                     | 2     | Stop renting → pause; restart → resume.                                                                                              |
| `test_full_rental_routes_mortgage_interest_to_schedule_e_not_mid`                   | 2     | RENTED_FULL: MID = 0; full interest is rental deduction.                                                                             |
| `test_partial_rental_splits_mortgage_interest_by_fraction`                          | 2     | RENTED_PARTIAL: MID × (1 - fraction); Schedule E × fraction.                                                                         |
| `test_full_rental_property_tax_uncapped_by_salt`                                    | 2     | RENTED_FULL: SALT-applicable property tax = 0; rental deduction takes the whole thing.                                               |
| `test_partial_rental_property_tax_splits_by_fraction`                               | 2     | Same split logic.                                                                                                                    |
| `test_net_rental_income_taxed_as_ordinary`                                          | 2     | Positive net rental income → ordinary tax bracket; verify federal + CA together.                                                     |
| `test_net_rental_loss_reduces_ordinary_income`                                      | 2     | Negative net → reduces taxable income (passive-loss limitation deferred — assert the simplification).                                |
| `test_rental_management_fees_deductible_against_rental_income`                      | 2     | Schedule E sum includes management + leasing fees.                                                                                   |
| `test_owner_occupied_to_rented_transition_at_month_n`                               | 3     | StartRentingEvent: depreciation begins, MID flips off, SALT freed up, outside rent obligation starts iff residence_timeline says so. |
| `test_rented_to_owner_occupied_transition_at_month_n`                               | 3     | StopRentingEvent: depreciation pauses, MID resumes, outside rent ends if residence_timeline says so.                                 |
| `test_change_rental_plan_event_updates_fraction_and_rent`                           | 3     | ChangeRentalPlanEvent at month N flips fraction_rented + rent amount without restart of all derived state.                           |
| `test_outside_rent_obligation_gated_by_residence_segment`                           | 3     | OwnerResidenceSegment at month N drops the outside rent obligation; OutsideRentSegment at month M reinstates it.                     |
| `test_residence_change_to_property_starts_section_121_clock`                        | 3     | property_owner_occupied_months_in_last_5y increments while user lives there.                                                         |
| `test_residence_change_away_freezes_section_121_clock`                              | 3     | Counter doesn't increment while user is elsewhere.                                                                                   |
| `test_leasing_fee_cadence_resets_on_each_start_renting_event`                       | 3     | Stop renting at month M and start again at month M+12 → leasing fee at M+12, and the avg_tenancy_months cadence resets from there.   |
| `test_lifecycle_events_must_be_chronological`                                       | 3     | Scenario validator rejects out-of-order events.                                                                                      |
| `test_lifecycle_event_after_horizon_is_rejected`                                    | 3     | Validator rejects events with month >= horizon.                                                                                      |
| `test_lifecycle_decisions_compile_into_sparse_per_month_table`                      | 3     | Compiled `LifecycleDecision` table has exactly len(lifecycle_events) + len(residence_timeline) rows; runtime collect+apply matches.  |
| `test_capital_improvement_event_debits_cash_and_bumps_basis`                        | 3     | CapitalImprovementEvent: cash -= amount_usd, building_basis += amount_usd, fires marker event into log.                              |
| `test_capital_improvement_during_rental_accelerates_depreciation`                   | 3     | If RENTED\_\* at the improvement month, the improvement basis depreciates from that month on a 27.5y SL clock alongside existing.    |
| `test_capital_improvement_during_owner_occupied_does_not_depreciate`                | 3     | If OWNER_OCCUPIED at the improvement month, basis bumps but no depreciation accrual.                                                 |
| `test_capital_improvement_basis_carries_into_sale_gain_calc`                        | 4     | Improvements added before sale reduce realized gain by amount_usd (less any depreciation taken on them).                             |
| `test_sale_realizes_gain_over_adjusted_basis`                                       | 4     | Realized gain = proceeds × (1 - closing_cost_pct) − (purchase + cap closing costs − cumulative_dep).                                 |
| `test_sale_of_never_rented_owner_occupied_gets_full_section_121`                    | 4     | 24-of-60 months satisfied → exclusion up to $250k single filer.                                                                      |
| `test_sale_of_pure_investment_gets_no_section_121`                                  | 4     | 0 owner-occupied months → no exclusion.                                                                                              |
| `test_sale_after_owner_then_rented_gets_section_121_if_qualifying_months_satisfied` | 4     | 36 months owner-occupied then 24 months rented then sale (month 60): qualifies (24-of-60).                                           |
| `test_sale_after_owner_then_rented_gets_no_section_121_if_window_lapsed`            | 4     | 24 months owner-occupied then 60 months rented then sale (month 84): does not qualify.                                               |
| `test_sale_recaptures_depreciation_at_25_pct_federal`                               | 4     | Federal 25% × cumulative_dep (capped at realized gain).                                                                              |
| `test_sale_recaptures_depreciation_at_ca_ordinary_rate`                             | 4     | CA recapture = cumulative_dep × CA ordinary marginal.                                                                                |
| `test_recapture_does_not_shelter_under_section_121`                                 | 4     | §121 applies only to the post-recapture LTCG portion.                                                                                |
| `test_sale_pays_off_mortgage_at_sale_month`                                         | 4     | Mortgage balance zeroed; liability state freezes.                                                                                    |
| `test_sale_freezes_property_state_after_sale_month`                                 | 4     | property_occupancy_mode, cumulative_depreciation, ownership stake all freeze.                                                        |
| `test_sale_at_horizon_end_works_same_as_mid_horizon_sale`                           | 4     | No special-case at horizon-1 sale.                                                                                                   |
| `test_cannot_rent_after_sale`                                                       | 4     | Validator rejects StartRentingEvent after PropertySaleEvent.                                                                         |
| `test_rental_event_frames_decode_into_rollout_events`                               | 5     | Decoder emits RentalIncomeEvent / StartRentingMarkerEvent / etc. at the right months.                                                |
| `test_lifecycle_marker_events_match_lifecycle_event_months`                         | 5     | One marker per lifecycle event in the input.                                                                                         |

### End-to-end multi-phase scenarios

The "headliner" tests stitch the whole pipeline together with realistic
numbers:

- **`test_e2e_buy_live_rent_sell`**: 5-year scenario. Buy $1M property
  month 0 (15% down, 30y fixed at 6%, 30% land). Live in for 36
  months. Start renting whole property month 36 at $5k/mo (5%
  vacancy, 8% management, 1mo leasing). Sell month 60 at home-value
  series × $1M. Assert: full §121 qualifies (36 of last 60 months
  owner-occupied), §1250 recapture on 24 months × monthly_dep,
  mortgage paid off, terminal cash matches a hand-computed expected
  value within rounding tolerance.
- **`test_e2e_buy_rent_immediately_sell`**: 5-year pure investment.
  Buy month 0, rent month 0, sell month 60. Assert: no §121, full
  §1250 recapture on 60 months, expected terminal cash.
- **`test_e2e_partial_rental_for_three_years`**: Buy + live for full
  60 months but rent 50% (rooms / ADU) months 12-48. Assert:
  depreciation accrues on 50% of building basis for 36 months; MID
  applies at 50% during the partial-rental window and full outside
  it; partial-rental property tax split correctly.
- **`test_e2e_move_to_outside_rental_when_renting_out`**: User lives
  in property month 0-23, then moves to outside rental month 24 and
  rents out the whole property. Assert: outside-rent obligation
  fires from month 24; rental income fires from month 24; both rates
  index via their respective series; tax treatment switches.
- **`test_e2e_failure_when_management_fees_exceed_cash`**: Engineered
  scenario where rental + management fees produce a shortfall.
  Rollout status flips to FAILED on the expected month.

### State-vs-ledger reconciliation

Per the `augur/sim/TODO.md` "Arrays reconcile to ledger" invariant,
every new monthly metric introduced by this work
(`net_rental_income_usd`, `property_depreciation_usd`,
`property_sale_*_usd`, `schedule_e_deductions_usd`) gets a
reconciliation test that confirms the monthly array sums match the
corresponding ledger/event-frame totals. Example shape:

```python
def test_rental_income_metric_reconciles_to_transfer_ledger():
    run = simulate_with_external_series_dense(scenario, …)
    monthly_rental_income = monthly_metric_arrays(run.decode(), …)["net_rental_income_usd"]
    transfers = run.events_log.transfers.filter(
        pl.col("cause_id").str.starts_with("rental_income:")
    )
    assert pytest.approx(monthly_rental_income.sum()) == transfers["amount_usd"].sum()
```

### Why this matters

Rental + lifecycle is the most accounting-dense feature in augur to
date. A bug in depreciation accrual or §1250 recapture is invisible
in headline numbers but materially distorts after-tax IRR. The
coverage matrix above is the contract: each row is a behavior we want
to be able to refactor freely without breaking. Tests use exact-math
deterministic fixtures so they stay precise; the stochastic
production scenarios are covered by the existing visual + smoke
tests.

## Touchpoints

- `augur/sim/scenario.py`: `ScheduledPropertyPurchase` gains rental +
  lifecycle fields; new `RentalIncomePlan`, `RentalManagement`,
  `LifecycleDecision`, lifecycle event types.
- `augur/sim/compiler.py`: validate scheduled lifecycle events and
  reduce them to a sparse `LifecycleDecision` table indexed by
  (month, rollout). Land/building basis split.
- `augur/sim/engine.py`: per-month decision collect+apply phase;
  state buffers as runtime-mutated state (not precompiled arrays);
  depreciation accrual; §1250 recapture math; §121 eligibility check;
  residence-segment outside-rent gating; leasing-fee cadence;
  capital-improvement application.
- `augur/sim/pricing.py` (new): deterministic occupancy-aware pricing
  functions (`insurance_rate`, `maintenance_rate`, others as needed).
  Pure Python, unit-tested with explicit constants.
- `augur/sim/events.py`: depreciation accrual event frame (or fold
  into `tax_breakdowns`), rental income event frame, lifecycle event
  frame.
- `augur/sim/state.py`: new state-history frames for
  `property_occupancy_history`, `property_depreciation_history`.
- `augur/product/wire.py`: lifecycle event union, residence timeline,
  rental income plan, new rollout event variants.
- `augur/product/scenarios.py`: translator from wire shape to sim
  scenario; new counterparty constants `TENANT_AGENT_ID`,
  `PROPERTY_MANAGEMENT_AGENT_ID`.
- `augur/product/decode.py`: emit new `RolloutEvent` variants.
- `augur/product/service.py`: thread the new event types through.
- `augur/frontend/product_app.jsx`: rental panel + lifecycle editor +
  residence timeline + chart annotations.
- `augur/api/testdata/config.yaml`: extend testdata with `land_value_pct`
  per location (or a single default).
- `augur/sim/TODO.md`: drop the "Real-estate lifecycle" /
  "Landlord rental income" / "Mid-horizon lifecycle" bullets as each
  phase lands; tombstone in the commit message.
