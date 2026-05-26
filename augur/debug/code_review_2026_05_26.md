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

### B0. Unify rollout axis to R-last on state buffers — landed

`CurrentStateBuffers` (`579d7bdf5` + `77ab5bd1a`) and
`StateHistoryBuffers` (`8c3420303` + `135f6ecb0` + `7bbb89b0e`): every
rollout-dimensioned field is now `(…, R)`. `_snapshot_current_state`
copies directly with no per-field `.T`; the decode pass reads each state
arena through an `_r_first_view` helper that does a single
`np.moveaxis(state, -1, 1)` view so downstream row-major iteration
keeps working. `augur/product/decode.py` consumers updated to
`buffers.X_state[:, slot, _SINGLE_ROLLOUT_INDEX]`.
Manual fixups after the axis rotate covered ~12 derived ops (matmul
order, `sum(axis=…)`, `shape[1]` → `[0]`, fifo-seam transposes,
`slice_dense_result` axis, tax-liability settlement broadcasts).
All sim/api/product/visual tests numerically identical on RBE.

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

### X1. Drop `Property._collapse_list_notes` shim — **blocked externally**

`gaffer-private` properties.yaml migration is pushed
(`ecdaf9ae9` notes lists → string, `c64df0c27` drop flags). Ducktape
fix for `LocalRegulation.notes` (`82a62e419`) is on devel but
**GitHub Actions has suspended the `agentydragon` account** —
`push-images / Push augur` (and every other release/push-images job)
errors with `remote: Your account is suspended. Please visit
https://support.github.com for more information.` from `actions/checkout`.
No new augur image gets built; the cluster pod stays on the broken
pre-fix image (~70+ restarts as of 2026-05-26). The old pod still
serves. Unblock by contacting GitHub support; until then nothing
ducktape-side can move this forward.

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

| #   | Area                                                              | Impact     | Effort   |
| --- | ----------------------------------------------------------------- | ---------- | -------- |
| B5  | Bundle lifecycle/obligation discriminators into typed views       | DX         | medium   |
| B4  | Split compiler.py + engine.py                                     | DX         | large    |
| X1  | GitHub Actions blocked: account suspension blocks all push-images | cross-repo | external |
