# Scenario-set → product surface gap

Inventory of features the legacy scenario-set surface
(`augur/api/scenario_set*.py`, frontend `augur/frontend/app.jsx`) has
that the product surface (`augur/product/*`, frontend
`augur/frontend/product_app.jsx`) does not yet have, organized around the
goal: **port product close enough to scenario-set to delete scenario-set**.

Excludes things product already has via recent work: property purchase
with closing costs, mortgage origination, property tax, HOA dues,
homeowners insurance, property maintenance, mortgage-interest deduction
with `is_primary_residence`, URL state encoding, inflation-indexed
monthly spend.

Effort tags are coarse: **low** = wire/UI only, no new sim primitive;
**medium** = new fields + translator changes, sim already supports;
**high** = new sim primitive (state machine, event stream, tax math)
plus wire + UI.

## Scenario-set also doesn't really do these

Things that appear in scenario-set's schema/types but the bridge to sim
rejects or hardcodes — so deleting scenario-set is not a regression and
these are out of scope for the porting effort. Either keep on the
roadmap for genuine new modeling work, or delete from scenario-set
schema as cleanup.

| Gap                                 | Where rejected / unsupported                                                                 |
| ----------------------------------- | -------------------------------------------------------------------------------------------- |
| **Mid-horizon purchase month**      | `bridge.py:506,737` — both surfaces require `month_index == 0`                               |
| **Property sale**                   | schema-only at `scenario_set.py:287`; no bridge translation; sim has no sale machinery       |
| **Rental income / occupancy modes** | `bridge.py:670,683` — requires `OWNER_LIVES_IN_PROPERTY` + `NotRentedRentalPlan`             |
| **Depreciation / §1250 recapture**  | gated on rental; nothing in sim                                                              |
| **Multi-property**                  | bridge loops over a single selection                                                         |
| **Multi-actor semantics**           | `bridge.py:351` — requires exactly one primary owner; other actors are ownership labels only |
| **Crypto positions**                | `bridge.py:603` — rejects with "crypto positions" unsupported                                |
| **PE marks + sale policies**        | `bridge.py:606,611,615` — rejects non-`LiquidityEventOnly` regimes and sale policies         |
| **Special-assessment richness**     | flat-amount in both; Prop 13 escalation + CFD term unimplemented in either                   |
| **SALT cap math**                   | not in either                                                                                |

## Tier 1 — port to enable deleting scenario-set

These are real scenario-set features the user uses today. Port these,
then delete scenario-set + bridge + legacy frontend route.

### Multi-scenario comparison (scenario list + per-scenario fan)

- **Scenario-set location**: `augur/frontend/app.jsx:930`–`1020` `ScenarioList`, `:401`–`406` `scenarioFanRows` rendering one fan band per enabled scenario; per-scenario color, label, enable toggle, duplicate/delete; URL state preserves the full list
- **Why missing from product**: product is single-scenario end-to-end (wire `ScenarioKey` → response). No scenario list, no cross-scenario aggregation in UI.
- **Effort**: medium. Shareable scenario-comparison permalink comes for free.

### ~~Terminal distribution histogram (replaces today's terminal strip)~~ — done

Landed in `augur/frontend/product_app.jsx` as `TerminalDistributionHistogram` and
follow-up refinements (failed cells colored red inline with the rest of the
distribution, metric-aware binning that tracks the chart's selected metric,
nice currency tick steps, gap-aware container sizing so cells don't get clipped).
The terminal-metrics table also got a SELECTED column whose position floats to
the correct slot among the percentiles based on the chart's selected metric.

## Tier 2 — genuine new modeling (post-deletion)

User-driven feature work that's not a scenario-set port (scenario-set
doesn't really support these either) but real future capability.
Listed in approximate user priority.

### Crypto (BTC, ETH) — high priority

- **What**: sampled BTC/ETH price series in `augur/model`, crypto holdings in `ScenarioKey`, crypto-aware liquidity policy preference, LTCG routing on sale
- **Effort**: high (new sampled series + new asset class)

### Private equity — critical

- **What**: PE position with cost basis + sampled marks, tender-window sample events, sale policy with regime variants (acquisition / IPO / secondary)
- **Effort**: high (new sampled-event primitive)

### Multi-actor for partner mortgage contribution — medium priority

- **What**: contribution agreement between two actors, shared mortgage liability with per-actor split, per-actor tax accounting
- **Effort**: high (sim primitive currently single-primary-owner)

### Occupancy modeling + tax interaction — eventually

- **What**: distinguish primary residence from rental property; needed for §121 (sale exclusion), §1250 recapture, and rental-income event stream
- **Effort**: high. Gated on property-sale lifecycle.

### ~~SALT cap (federal Schedule A)~~ — done

Landed as `FederalSaltDeductionPolicy` with a year-keyed `cap_schedule`. Default
schedule encodes the TCJA + OBBBA timeline ($40k for years 0-3, $10k from year 4);
empty schedule models the post-OBBBA TCJA sunset (no cap). State income tax for
the profile's non-federal jurisdictions plus property tax paid this calendar year
flow into the federal itemized deduction, capped per schedule. Engine processes
state links before federal SALT links so the cap math has all the inputs.

Modeling gaps explicitly deferred (documented in `scenario.py`):

- AGI-based phase-out of the $40k cap for high earners (treated as flat ceiling).
- Sales-tax election in lieu of state income tax (for no-state-income-tax states).
- Payment-vs-accrual timing nuance (we deduct state tax accrued in the calendar
  year, equivalent to assuming withholding equals accrual).

## Skip entirely

Gaps that won't be ported and shouldn't pull resources. Where the
scenario-set schema carries the corresponding type, the cleanup at
scenario-set deletion time should also drop the schema.

- **Mid-horizon purchase month** — both surfaces require month-0 today; delete `PropertyPurchaseEvent.month_index` from scenario-set on deletion. Decisions we want to evaluate now are "buy at T=0 vs. don't buy," not "buy at T=5".
- **Multi-property** — one home is enough.
- **Custom (non-catalog) property entry** + UI form — catalog covers what we model.
- **Initial balance sheet overrides per scenario** + UI edit form — portfolio config in YAML is the right contract; per-scenario overrides muddy "this scenario."
- **Monthly-flow tables per asset class** — delete; not in active use.
- **Accounting / journal-entry drilldown** — product event table covers this sufficiently already.
- **Tax-profile / regime toggles** — diagnostic value (flip MID off, etc.) is small; jurisdiction what-ifs need real new jurisdictions wired, not toggles; TCJA sunset is better modeled as a date-keyed cap change inside MID itself.
- **Actor management UI without multi-agent sim** — wait until multi-actor (Tier 2) is real.
- **Occupancy / rental UI without rental sim** — wait for rental income (Tier 2).
- **Liquidity-policy asset preference chain UI** — empty without crypto + PE; revisit when those land.
- **Ordinary income / W-2** — `augur/sim/TODO.md:237` defers; current scenarios are post-earning.

## Suggested sequence

1. ~~**Terminal distribution histogram**~~ — done.
2. **Multi-scenario comparison** (Tier 1) — the only remaining deletion blocker.
3. **Delete scenario-set** + bridge + legacy frontend route + the rejected/aspirational schema (`PropertyPurchaseEvent.month_index`, crypto/PE schema types, occupancy/rental enums, etc.).
4. **Tier 2 features** in user-priority order — likely crypto → PE → multi-actor → occupancy. ~~SALT cap~~ done.
