# Augur code review — 2026-05-26 (open items)

Trimmed to active work. Landed items recorded in `git log` — search for
`augur/sim:`, `augur/api`, `augur/frontend:`. Phases 1 (correctness), 2
(dead code), and 4 (frontend reorg) are closed.

**B2 + B1 progress (in-flight on `augur-arena-refactor` worktree):**
Tax, TaxLiability, Transfer, Property, Liability, Sale, Obligation,
LiquidityPolicy, LifecycleEvent CompileOutput dataclasses landed and
embedded into `CompiledSimulation`. Remaining flat fields still hold
PE issuer + policy, MID + SALT, capital-gain agents, lot/cash arrays,
and lifecycle-state extras (`property_rented_fraction`, `property_building_basis`,
`property_owner_profile_index`, `property_home_value_series_index`,
`liability_owner_profile_index`).

## B. Structural refactor (Phase 3)

Listed in recommended execution order — each row sets up the next.

### B0. Unify rollout axis to R-last (medium; precursor to B1 nesting completion)

`CurrentStateBuffers` fields are shaped `(R, *)` (rollout-first);
`SimulationBuffers` fields are shaped `(*, R)` (rollout-last). Plan
arrays in `CompiledSimulation` have no R axis. Unify on **R-last** —
NumPy convention, trailing-axis-fastest broadcasting, contiguous
`state[..., r]` per-rollout views, and makes the per-step write
patterns `current.foo[profile, :] += amount` contiguous (currently
strided as `current.foo[:, profile]`).

Mechanical change:

- Transpose every `CurrentStateBuffers` field at allocation time.
- Swap index order at every engine read/write site.
- Sanity-check with `bbr test //augur/sim/...` (numerical results must
  be identical — this is a pure layout change).

### B1. Finish remaining `CompiledSimulation` arenas (medium remaining)

Already landed: tax / tax_liabilities / transfers / properties / liabilities /
sales / obligations / liquidity_policies / lifecycle_events.

Still flat:

- **PE arena**: `pe_issuer_codes` + `pe_issuer_*` (~5) + `pe_policy_*` (~12).
  Two natural sub-dataclasses (`PEIssuerCompileOutput`, `PEPolicyCompileOutput`)
  or one combined.
- **MID + SALT slice on TaxCompileOutput**: `tax_link_mid_principal_ratio`,
  `tax_link_mid_active`, `tax_link_salt_active`, `tax_link_salt_cap_by_year`,
  `tax_link_salt_contributing_mask`. These are outputs of
  `_compile_mortgage_interest_deductions` + `_compile_federal_salt_deductions`,
  not `_compile_tax` directly; need their own CompileOutputs or fold into
  TaxCompileOutput.
- **Capital-gain agents**: `capital_gain_agent_codes`,
  `tax_profile_capital_gain_index` — tiny (2 fields), small win.
- **Lifecycle state extras** computed in `compile_simulation` after the helpers
  run: `property_rented_fraction`, `property_building_basis`,
  `property_owner_profile_index`, `property_home_value_series_index`,
  `liability_owner_profile_index`. Could be on `PropertyCompileOutput` /
  `LiabilityCompileOutput` if the helper signature widens to receive
  `property_slot_by_id` + `profile_index_by_agent`.
- **Lot + cash + external-series leftovers**: small clusters; defer if not
  blocking other work.

### B4. Split monolithic `compiler.py` + `engine.py` (large; mostly mechanical after B1)

`compiler.py` is ~2k lines; `engine.py` is ~3k. Both should split by
domain:

- `compiler/{tax,properties_and_liabilities,transfers_and_obligations,assets_and_sales,base}.py`
- `engine/{phase_transfers,phase_purchases,phase_obligations,phase_taxes,phase_pe_tenders,phase_lifecycle,phase_settlement,buffers,decode}.py`

Orchestration (`_run_month_step`) stays in `engine/__init__.py` or
`engine/loop.py`.

### B5. Bundle lifecycle-event discriminators into per-event-kind dataclasses (small to medium; new)

`LifecycleEventCompileOutput` stores all kinds in a single dense table with
`kind ∈ {LIFECYCLE_KIND_FRACTION, LIFECYCLE_KIND_CAPITAL_IMPROVEMENT,
LIFECYCLE_KIND_SALE}` and reuses `amount` for both USD spend (kind 1) and
closing-cost % (kind 2). Same pattern exists in `ObligationCompileOutput`
(`source_kind` ∈ {0..5} with `source_index` re-purposed per kind) and in
the wire/scenario layer (`SetRentedFractionEvent` / `CapitalImprovementEvent`
/ `PropertySaleEvent` Pydantic discriminated union).

The numpy hot loop wants the dense table for vectorization; the engine's
slow path + decode pass would benefit from a typed view that maps each
row to its discriminated dataclass. Sketch: a `LifecycleEventView`
property on `LifecycleEventCompileOutput` that yields typed event rows
(or sub-array slices keyed by kind). Same idea for obligation source kinds.
This is the "discriminated union over a SoA layout" pattern — bundle the
discriminator + per-kind payload into the class system so callers don't
have to remember kind-specific field reuse.

## X. Cross-repo follow-ups

### X1. Drop `Property._collapse_list_notes` shim (small)

`gaffer-private` properties.yaml migration is pushed
(`ecdaf9ae9` notes lists → string, `c64df0c27` drop flags). Currently
blocked by an unrelated `LocalRegulation.notes` startup crash keeping
the new augur image in CrashLoopBackOff. Once that's resolved and the
new pod serves, the `CLEANUP(2026-05-25)` validator on
`augur.api.bootstrap.Property._collapse_list_notes` can go.

## F. Deferred modeling realism (Phase 5)

Tracked in `augur/sim/TODO.md`; documented v1 simplifications, no
current action:

- **NIIT** (3.8% on investment income above thresholds).
- **MFJ + HoH filing statuses** — needed before opening §121 to joint filers.
- **Property tax annual escalation** (Prop-13 2%/yr cap).
- **ARM, refinancing, prepayments** — straight 180/360 fixed only.
- **Wealthfront tax-loss harvesting** — flagged in gaffer-private TODO.
- **Stochastic vacancy + tenant model** — already noted in sim TODO.
- **No exception boundaries in compile/engine** — currently silent on misconfig.
- **Sentinel `NO_CODE = -1` without type-safety** — bounds checks absent.
- **§1250 personal-property + pre-1997 real-property recapture** (the
  "ordinary §1250 portion") — A4 only covered the unrecaptured-gain side.
- **§163(h)(3) substantial-improvement HELOC carve-out** — A5 leaves
  improvement-tied HELOCs to callers (tag as `acquisition`); a real
  carve-out would tie HELOC draws to `CapitalImprovement` events and
  re-classify automatically.

## Open items, ranked

| #  | Area                                                                | Impact     | Effort |
| -- | ------------------------------------------------------------------- | ---------- | ------ |
| B1 | Finish remaining `CompiledSimulation` arenas (PE, MID/SALT, lot/cash) | DX win    | medium |
| B0 | Unify rollout axis to R-last on `current` buffers                   | DX         | medium |
| B5 | Bundle lifecycle/obligation discriminators into typed views         | DX         | medium |
| B4 | Split compiler.py + engine.py                                       | DX         | large  |
| X1 | After Flux reconcile: drop `_collapse_list_notes` shim              | cross-repo | small  |
