# Augur code review — 2026-05-26

Thorough review of `augur/sim`, `augur/api`, `augur/product`, `augur/frontend`.
Three parallel passes synthesized below. Findings ranked by impact within each
section; file:line references throughout.

## A. Correctness issues (ship-blocking when triggered)

### A1. §121 primary-residence exclusion is single-filer-only

**engine.py:1424** hard-codes `SECTION_121_SINGLE_FILER_EXCLUSION_USD =
250_000.0`. The sale handler ignores the property owner's filing status and
always applies the single-filer cap. Married-filing-jointly is $500k. Filing
status is already on `TaxProfile`; engine just doesn't use it. Pro-rata
reduction for non-qualified-use periods (§121(c), post-2009) is also not
modeled — the 60-month occupancy-counter would need a parallel non-qualified-use
counter.

**Severity:** real tax delta for any MFJ scenario. Plumb filing status into
`_apply_property_sale`.

### A2. ProductService cache race

**augur/product/service.py:96,152-161** keeps an `OrderedDict` cache that
`_decoded_rollouts` mutates without locking. FastAPI + uvicorn runs request
handlers concurrently; two simultaneous metric-fan requests can hit `get` →
miss → both run the simulation → both call `cache[key] = …`, wasting CPU and
potentially producing inconsistent reads if either gets the LRU eviction
between get and put.

**Severity:** high if usage is parallel (e.g. while fan loads, user changes
seed). Fix is one `threading.Lock` around the cache ops.

### A3. React `key={index}` on the lifecycle event list

**augur/frontend/product_app.jsx:1505** maps `events.map((event, index) => …)`
with `key={index}`. Editing or reordering events will cause React to reuse the
wrong DOM node for the wrong row — `NumberInput` focus state and input value
can stick to the "previous" row after a row delete/insert. Same issue on
1029, 1069 (histogram bins, axis ticks; less harmful but still wrong-pattern).

**Severity:** real UX bug; user-facing once people start editing more than one
event at a time. Use a stable identity (kind + month, or assign a uuid at add
time).

### A4. §1250 simplification ≠ IRS rule

**engine.py:1411** routes recapture via `current.recapture_section_1250_ytd`
and **compiler.py:1271–1275** taxes it at flat 25% federal. Real §1250 caps
_unrecaptured_ depreciation at the **lower** of the marginal ordinary rate or
25%. For high-bracket taxpayers the cap binds, so our number is right; for
sub-25%-bracket taxpayers we overestimate. Personal-property and pre-1997
real-property recapture (the "ordinary" §1250 portion) is also not modeled.

**Severity:** real over-estimate at low marginal rates; documented v1 simplification.

### A5. MID lumps acquisition + home-equity debt

**compiler.py:1318–1387** computes one principal-cap ratio per (link, liability)
without distinguishing acquisition debt (where $750k/$1M caps apply) from
home-equity debt (TCJA disallows the interest deduction unless tied to
substantial improvements). All debt is treated as acquisition debt.

**Severity:** real over-estimate of MID when a scenario layers a HELOC.

## B. Function bloat / parameter density

### B1. `CompiledSimulation` is 170 fields (compiler.py:92–348)

Single flat dataclass. Unpacking patterns in `engine.py` ("`int(plan.property_owner_profile_index[prop])`") are everywhere. Group into nested dataclasses:

- `TaxArrays` (profile + link arrays, ~30 fields)
- `PropertyArrays` (property/lifecycle compile arrays, ~25 fields)
- `LiabilityArrays` (mortgage compile arrays, ~12 fields)
- `LiquidityPolicyArrays` (buffer + asset preference, ~17 fields)
- `TransferArrays` (recurring/scheduled transfer slot tables, ~15 fields)
- `ObligationArrays` (~20 fields)
- `LotArrays` / `CashArrays` (small clusters)
- `ExternalSeriesArrays` (string codes + cube)

Cuts the surface of the top-level dataclass by 6×; IDE navigation gets vastly
better; tests can construct partial fixtures from one nested arena instead of
"all 170 fields".

### B2. `_compile_tax` returns a 17-tuple (compiler.py:1297–1315)

Replace tuple with a `TaxCompileOutput` dataclass. Same for
`_compile_properties_and_liabilities` (compiler.py:1515, **33-tuple**) — split into
`_compile_properties` and `_compile_liabilities` returning small typed objects.

### B3. `_wire_landlord_rental` mutates 4 lists in place (scenarios.py:465)

8 keyword-only params; threads `agents`/`initial_cash`/`recurring_transfers`/
`scheduled_transfers` lists through and appends to them. Return a dataclass
the caller merges instead.

### B4. `compiler.py` is 2018 lines, `engine.py` is 3168 lines

Monolithic. Both should split by domain:

- `compiler/{tax,properties_and_liabilities,transfers_and_obligations,assets_and_sales,base}.py`
- `engine/{phase_transfers,phase_purchases,phase_obligations,phase_taxes,phase_pe_tenders,phase_lifecycle,phase_settlement,buffers,decode}.py`

The orchestration (`_run_month_step`) stays in `engine/__init__.py` or
`engine/loop.py`.

## C. Dead code

### C1. STCG plumbing (engine.py:40)

`SHORT_TERM_CAPITAL_GAIN_CODE` is defined but nothing fires short-term gains.
`capital_gain_ytd[:, :, 2]` (rollout × profile × {LTCG, STCG}) wastes the
second dimension on a constant zero. Collapse to 1D when STCG is formally
deferred to a later phase; the bench savings are non-trivial.

### C2. `OccupancyMode.OFF` and `RENTED_PARTIAL` (pricing.py:25–29)

Defined but never written by any production path; the engine reads
`property_rented_fraction` directly as a float. The enum is a stale
abstraction from before the float-fraction refactor.

### C3. `obligation_property_tax_owner_fraction` (compiler.py:277)

Self-documented as deprecated; still read by engine.py:2022 as a fallback.
Either delete (and the fallback) or document the formal retention plan.

### C4. `tax_settlement_profile_index` (compiler.py:327)

Compiled (line 878) but no engine path reads it. Likely a stub for the planned
tax-settlement extension that was superseded.

### C5. Property metadata fields (api/bootstrap.py:48,50,51)

`Property.flags`, `Property.notes`, `Property.source_url` — never consumed in
frontend. Drop unless a planned UI surface exists.

### C6. Frontend dead helper (product_app.jsx:499–512)

`quantile()` is defined but never called; vestigial from earlier histogram work.

## D. Reorg / refactor

### D1. Extract `ProductScenarioForm` from `product_app.jsx`

`ProductProjectionWorkspace` is 360 lines (1939–2298). Most of the bulk is the
left sidebar form (lines 2059–2212). Pulling that into its own component
collapses `ProductProjectionWorkspace` to ~150 lines of layout + chart wiring.

### D2. Extract `useEventSelection` hook

`MetricFanChart` and `SelectedRolloutEventsPanel` each accept
`{selectedEventMonthIndex, hoveredEventMonthIndex, onSelectEventMonth,
onHoverEventMonth}` — 4-prop drilling from `ProductProjectionWorkspace`.
Encapsulate as one hook.

### D3. Lifecycle "is post-sale" predicate

product_app.jsx:1510 inlines
`event.month > saleMonth || (event.month === saleMonth && event.kind !==
"property_sale")` once for the list and once in `LifecycleEventsEditor`.
Extract to `isEventPostSale(event, saleMonth)`.

### D4. `MetricFanChart` is 193 lines (product_app.jsx:760–952)

Bands, axis ticks, and event-marker rendering inline. Extract `FanBands`,
`FanAxis`, `FanEventMarkers` subcomponents.

## E. Polish / UX

### E1. `eventMarkerYOffset` missing 8 of the 16 event kinds (product_app.jsx:593–607)

`outside_rent`, `closing_cost_payment`, `hoa_dues_payment`,
`homeowners_insurance_payment`, `property_maintenance_payment`, `tax_accrual`,
`capital_improvement`, `set_rented_fraction` fall through to 0. Markers stack
on the line — visible clutter when a month has 3+ events.

### E2. Escape key doesn't clear event selection (product_app.jsx:892–908)

Mouse leave clears hover; keyboard has Enter/Space to select but no Escape to
deselect.

### E3. Inline-index `key={index}` on the histogram bins / axis ticks

(product_app.jsx:1029, 1069)

Same React-key issue as A3 but in less critical lists. Use immutable identity.

## F. Modeling realism limitations (acceptable v1; deferred)

Track in `augur/sim/TODO.md` — most already are; gaps noted:

- **§163(h)(3) acquisition vs home-equity debt distinction** — not modeled.
- **NIIT (3.8% on investment income above thresholds)** — already noted.
- **MFJ + HoH filing statuses** — needed to fix A1.
- **Property tax annual escalation (Prop-13 2%/yr cap)** — already noted.
- **ARM, refinancing, prepayments** — straight 180/360 fixed only.
- **Wealthfront tax-loss harvesting** — flagged in gaffer-private TODO.
- **Stochastic vacancy + tenant model** — already noted in sim TODO.
- **No exception boundaries in compile/engine** — currently silent on misconfig.
- **Sentinel `NO_CODE = -1` without type-safety** — bounds checks are absent.

## Top-of-list summary

| #   | Area                                      | Impact                          | Effort    | File                    |
| --- | ----------------------------------------- | ------------------------------- | --------- | ----------------------- |
| A1  | §121 filing-status                        | tax error on every MFJ sale     | small     | engine.py:1424          |
| A2  | ProductService cache race                 | latency + occasional wasted CPU | small     | service.py:96           |
| A3  | React `key={index}` on event list         | UX bug on edit/reorder          | small     | product_app.jsx:1505    |
| C1  | Collapse STCG dim                         | clearer + cheaper               | small-med | engine.py + state       |
| C2  | OccupancyMode dead variants               | tiny                            | small     | pricing.py:25           |
| C3  | `obligation_property_tax_owner_fraction`  | tiny                            | small     | compiler.py:277         |
| C5  | `Property.flags/notes/source_url`         | tiny                            | small     | bootstrap.py:48         |
| B1  | CompiledSimulation 170 → 8 grouped arenas | big DX win                      | large     | compiler.py:92          |
| B2  | `_compile_tax` 17-tuple → dataclass       | DX                              | medium    | compiler.py:1222        |
| B4  | Split `compiler.py` + `engine.py`         | DX                              | large     | compiler.py / engine.py |
| D1  | Extract ProductScenarioForm               | DX                              | medium    | product_app.jsx         |
| E1  | Missing event Y-offsets                   | minor UX                        | small     | product_app.jsx:593     |
| A4  | §1250 marginal-rate floor                 | over-estimate for low brackets  | small     | engine.py:1411          |
| A5  | MID home-equity-debt distinction          | over-estimate w/ HELOC          | medium    | compiler.py:1318        |

## Suggested phased plan

**Phase 1 — Correctness sweep (~half session):**
A1 (§121 MFJ + use filing_status), A2 (cache lock), A3 (React key fix).

**Phase 2 — Dead-code sweep (~one session):**
C1 (STCG dim collapse), C2 (OccupancyMode pruning), C3, C4, C5, C6.

**Phase 3 — Structural refactor (~two sessions, one PR each):**
B1 (group CompiledSimulation into 8 nested arenas) → B2 (tuple→dataclass for
compile helpers) → B4 (split compiler.py + engine.py).

**Phase 4 — Frontend reorg (~one session):**
D1 (extract ProductScenarioForm), D2 (useEventSelection hook), D4
(MetricFanChart subcomponents), E1 + E2 polish.

**Phase 5 — Modeling realism (deferred, track in `augur/sim/TODO.md`):**
A4 (§1250 marginal floor), A5 (acquisition vs HELOC MID), F items.

Each phase is independently shippable. Phases 1 and 2 should land first; they
unblock the structural work in 3 by removing distractions from the rename
diff.
