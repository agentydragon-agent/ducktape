# Augur code review — 2026-05-26

Thorough review of `augur/sim`, `augur/api`, `augur/product`, `augur/frontend`.
Findings ranked by impact within each section; file:line references throughout.
Items checked off are **landed**; the rest remain open.

## A. Correctness issues

- **A1. §121 single-filer-only.** ✅ Landed in `ef0a8178b`. Introduced
  `FilingStatus(StrEnum)` (single only), per-profile
  `tax_profile_section_121_exclusion_usd` array; `_section_121_exclusion_for`
  raises `NotImplementedError` for any non-SINGLE filing status at compile
  time. Pro-rata reduction for non-qualified-use periods (§121(c)) still
  deferred — when adding a new filing-status variant, also wire that math.

- **A2. ProductService cache race.** ✅ Landed in `c6fc527b8`. Added
  `threading.Lock()` around `OrderedDict` get/put/move_to_end ops; simulations
  themselves run outside the lock.

- **A3. React `key={index}` on lifecycle event rows.** ✅ Landed in
  `41604bc4f`. Lifecycle rows use a stable `event._id` (assigned at
  `defaultLifecycleEvent` / `parseLifecycleEntry`). Histogram bins keyed on
  `bin.lo`; axis ticks keyed on value.

- **A4. §1250 marginal-rate floor.** ✅ Landed in `7e71857ba`.
  `_compute_tax_for_link` now applies the IRS Unrecaptured §1250 Gain
  Worksheet rule: the recapture is taxed at the LESSER of (a) the implied
  marginal ordinary rate (stack recapture on top of `ordinary_taxable` and
  diff against `ordinary_tax`) or (b) the flat federal cap. High-bracket
  taxpayers unchanged (25% cap binds); sub-25%-bracket taxpayers now pay
  the lower marginal walk. Personal-property and pre-1997 real-property
  recapture (the "ordinary" §1250 portion) is still not modeled — deferred.

### A5. MID lumps acquisition + home-equity debt (open)

`compiler.py` computes one principal-cap ratio per (link, liability) without
distinguishing acquisition debt (where $750k/$1M caps apply) from home-equity
debt (TCJA disallows the interest deduction unless tied to substantial
improvements). All debt is treated as acquisition debt.

**Severity:** real over-estimate of MID when a scenario layers a HELOC.

## B. Function bloat / parameter density (all open)

### B1. `CompiledSimulation` is ~170 fields (compiler.py)

Single flat dataclass. Unpacking patterns in `engine.py`
(`int(plan.property_owner_profile_index[prop])`) are everywhere. Group into
nested dataclasses:

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

### B2. `_compile_tax` returns a 17-tuple (now 18 after A1)

Replace tuple with a `TaxCompileOutput` dataclass. Same for
`_compile_properties_and_liabilities` (33-tuple) — split into
`_compile_properties` and `_compile_liabilities` returning small typed
objects.

### B3. `_wire_landlord_rental` mutates 4 lists in place (scenarios.py)

8 keyword-only params; threads `agents`/`initial_cash`/`recurring_transfers`/
`scheduled_transfers` lists through and appends to them. Return a dataclass
the caller merges instead.

### B4. `compiler.py` is ~2k lines, `engine.py` is ~3k lines

Monolithic. Both should split by domain:

- `compiler/{tax,properties_and_liabilities,transfers_and_obligations,
assets_and_sales,base}.py`
- `engine/{phase_transfers,phase_purchases,phase_obligations,phase_taxes,
phase_pe_tenders,phase_lifecycle,phase_settlement,buffers,decode}.py`

The orchestration (`_run_month_step`) stays in `engine/__init__.py` or
`engine/loop.py`.

## C. Dead code

### C1. STCG plumbing — false positive

The original review claimed STCG is dead; **incorrect**. `engine.py:2202–
2209` classifies each sold lot at sale time (LTCG if held ≥ 12 months,
else STCG) and routes gains to the right slot. The federal bracket walk
adds STCG into `ordinary_for_brackets` (engine.py:1098, 1117) so it's
taxed as ordinary income — the IRS rule. Decoders publish `stcg_usd` on
the tax-breakdown wire frame. The reason no current fixture triggers
STCG is that all lots in `testdata/config.yaml` start with
`holding_period_months_at_start ≥ 23`, so within a 60-month horizon no
sale lands inside the 12-month window. **No action.**

### C2. `OccupancyMode.OFF` / `RENTED_PARTIAL` — false positive

The original review flagged these as dead but `scenarios.py:459,463`
_does_ emit them (investment property not yet rented; partial rental). All
four variants are real states. **No action.**

- **C3.** `obligation_property_tax_owner_fraction` — ✅ Landed in
  `aca396f01`. The compile-time array was a fallback for the
  SALT/Schedule E split when a property-tax obligation wasn't tied to a
  property slot. In practice the kind==2 branch of
  `_compile_obligation_slots` is the only place that ever populates
  `obligation_property_tax_profile`, and it always sets
  `obligation_property_slot` for the same slot — so the engine's `else`
  fallback at the read site was unreachable. Removed the field from
  `CompiledSimulation`, its populate site, the tuple return + caller
  deconstruction, and the unreachable engine branch. Runtime
  `current.property_rented_fraction` is the single source of truth and
  already respects mid-horizon lifecycle events.

- **C4.** `tax_settlement_profile_index` — ✅ Landed in `eaf46b5bd`. Dropped
  from `CompiledSimulation`, `_compile_obligation_slots` return, and the
  populate site.

- **C5.** `Property.{notes, source_url, flags}` — ✅ fully resolved. Notes
  - source_url surfaced in `a8e6aee5a` (PropertyPurchasePanel renders a
    "Source listing ↗" link and a `whitespace-pre-line` notes block;
    `notes` is now `str`, transitional list→str validator with CLEANUP
    tombstone). `flags` dropped from the schema + fixture in `c3d662a34`,
    with a transitional `model_validator` that strips the legacy key
    during the gaffer-private migration window.

### C6. Frontend `quantile()` — false positive

The original review flagged this as dead but it has two real callers (lines
543, 1003) for percentile labels in the fan + histogram. **No action.**

## D. Reorg / refactor

- **D1. Extract `ProductScenarioForm` from `product_app.jsx`.** ✅ Landed
  in `3272713b8`. Pulled the entire sidebar form (Scenario, Funding,
  Sampling) out of `ProductProjectionWorkspace` into its own component
  receiving `{input, bootstrap, portfolio, portfolioError, onChange,
onReset}`. Workspace shrank by ~145 lines.

- **D2. `useEventSelection` hook.** ✅ Landed in the same commit. Wraps
  `selected/hovered month + toggle + clear`; consumers spread
  `eventSelection.*` instead of 4-prop drilling.

- **D3. Lifecycle "is post-sale" predicate.** ✅ Landed in `e89b88ede`.
  Pulled the inline check at `LifecycleEventsEditor` into a documented
  helper `isEventPostSale(event, saleMonth)` that mirrors the wire
  validator's rule (event strictly after sale, or same-month non-sale).

- **D4. MetricFanChart subcomponents.** ✅ Landed in the same commit. Pulled
  the y-axis + x-tick loops into `FanAxes`, and the per-event SVG group into
  `FanEventMarker`. `MetricFanChart` body now mostly composes those plus the
  band/line polylines, which stayed inline because they're a handful of
  lines each.

- **D5. RolloutResultsPanel extraction.** ✅ Landed in `440baec90`.
  Pulled the chart + per-rollout details block (metric picker, terminal
  histogram, fan chart, event legend/panel, terminal metric table) out
  of `ProductProjectionWorkspace` into its own component receiving the
  state slices it renders. The workspace render shrank by ~50 lines and
  the panel is now navigable in isolation.

## E. Polish / UX

- **E1. Event legend + per-kind visibility + per-month marker stacking.** ✅
  Landed in `7ed53e6d5`. Replaced the static `eventMarkerYOffset` table
  with a `useVisibleEventKinds` hook + `EventKindLegend` chip strip
  under the chart. Each chip toggles its kind on/off (shift-click = "only
  this kind"); top-right gives bulk Show all / Hide all. The chart
  buckets visible events by month and stacks them upward using
  `EVENT_MARKER_STACK_PITCH_PX`, so markers no longer overlap when a
  month has 3+ events.

- **E2. Escape clears event selection.** ✅ Landed in `e89b88ede`.
  `useEventSelection` registers a global `keydown` listener while a
  marker is selected; pressing Escape calls `clear()` and detaches the
  listener. The effect short-circuits when nothing is selected so other
  Escape consumers (modals, menus) keep priority.

## F. Modeling realism limitations (acceptable v1; deferred)

Tracked in `augur/sim/TODO.md`; gaps noted:

- **§163(h)(3) acquisition vs home-equity debt distinction** — not modeled.
- **NIIT (3.8% on investment income above thresholds)** — already noted.
- **MFJ + HoH filing statuses** — needed before opening §121 to joint filers.
- **Property tax annual escalation (Prop-13 2%/yr cap)** — already noted.
- **ARM, refinancing, prepayments** — straight 180/360 fixed only.
- **Wealthfront tax-loss harvesting** — flagged in gaffer-private TODO.
- **Stochastic vacancy + tenant model** — already noted in sim TODO.
- **No exception boundaries in compile/engine** — currently silent on misconfig.
- **Sentinel `NO_CODE = -1` without type-safety** — bounds checks absent.

## Phase plan

- **Phase 1 (correctness)** — ✅ A1, A2, A3, A4 landed. **A5 still open.**
- **Phase 2 (dead-code sweep)** — ✅ all closed. C3, C4, C5 landed;
  C1/C2/C6 were false positives.
- **Phase 3 (structural refactor)** — open. B1 grouping
  `CompiledSimulation` into nested arenas is the biggest lever; B2, B3, B4
  follow naturally.
- **Phase 4 (frontend reorg)** — ✅ all closed. D1, D2, D3, D4, D5, E1, E2
  landed.
- **Phase 5 (modeling realism)** — deferred, tracked in
  `augur/sim/TODO.md`.

## Cross-repo follow-ups

- **`gaffer-private` properties.yaml migration** — pushed (`ecdaf9ae9`
  notes lists → string, `c64df0c27` drop flags). Once Flux reconciles
  the next augur image, drop the last transitional shim
  `Property._collapse_list_notes` (`CLEANUP(2026-05-25)`).

## Remaining open items, ranked

| #   | Area                                                   | Impact                 | Effort |
| --- | ------------------------------------------------------ | ---------------------- | ------ |
| A5  | MID acquisition-vs-HELOC                               | over-estimate w/ HELOC | medium |
| B1  | CompiledSimulation 170 → 8 nested arenas               | big DX win             | large  |
| B2  | Compile-helpers tuple→dataclass                        | DX                     | medium |
| B3  | `_wire_landlord_rental` return instead of mutate       | DX                     | small  |
| B4  | Split compiler.py + engine.py                          | DX                     | large  |
| X1  | After Flux reconcile: drop `_collapse_list_notes` shim | cross-repo             | small  |
