# Augur code review — 2026-05-26 (open items)

Trimmed to active work. Landed items recorded in `git log` — search for
`augur/sim:`, `augur/api`, `augur/frontend:` between `ef0a8178b` and
`1b6c46d47` to see them. Phases 1 (correctness), 2 (dead code), and 4
(frontend reorg) are closed.

## B. Structural refactor (Phase 3)

Listed in recommended execution order — each row sets up the next.

### B0. Unify rollout axis to R-last (medium; precursor to B1)

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

Land **before B1**: the nested-arena PR is much easier to read if axes
are already consistent. Two separate PRs.

Overall order within Phase 3: **B3 → B2 → B0 → B1 → B4**. B3 + B2 name
the seams first, then B0 transposes one field at a time, then B1 nests
the now-consistent arrays.

### B3. `_wire_landlord_rental` mutates 4 lists in place (small)

`scenarios.py` helper takes 8 keyword-only params and threads
`agents`/`initial_cash`/`recurring_transfers`/`scheduled_transfers`
lists through, appending to each. Return a dataclass the caller merges
instead. Good warmup that defines a typed return shape Phase 3 reuses.

### B2. Compile-helper tuple returns → dataclasses (medium)

`_compile_tax` returns an 18-tuple (was 17, +1 after A1's §121 array);
`_compile_properties_and_liabilities` returns a 33-tuple. Replace each
with a typed `*CompileOutput` dataclass; split the 33-tuple helper into
`_compile_properties` + `_compile_liabilities`. Names produced here are
the seams B1 will reuse.

### B1. `CompiledSimulation` ~170 fields → ~8 nested arenas (large; biggest lever)

Single flat dataclass. Unpacking patterns like
`int(plan.property_owner_profile_index[prop])` are everywhere in
`engine.py`. Group into:

- `TaxArrays` (profile + link arrays, ~30 fields)
- `PropertyArrays` (property/lifecycle compile arrays, ~25 fields)
- `LiabilityArrays` (mortgage compile arrays, ~12 fields)
- `LiquidityPolicyArrays` (buffer + asset preference, ~17 fields)
- `TransferArrays` (recurring/scheduled transfer slot tables, ~15 fields)
- `ObligationArrays` (~20 fields)
- `LotArrays` / `CashArrays` (small clusters)
- `ExternalSeriesArrays` (string codes + cube)

~6× reduction in top-level dataclass surface; IDE navigation gets vastly
better; tests can construct partial fixtures from one arena instead of
"all 170 fields".

### B4. Split monolithic `compiler.py` + `engine.py` (large; mostly mechanical after B1)

`compiler.py` is ~2k lines; `engine.py` is ~3k. Both should split by
domain:

- `compiler/{tax,properties_and_liabilities,transfers_and_obligations,assets_and_sales,base}.py`
- `engine/{phase_transfers,phase_purchases,phase_obligations,phase_taxes,phase_pe_tenders,phase_lifecycle,phase_settlement,buffers,decode}.py`

Orchestration (`_run_month_step`) stays in `engine/__init__.py` or
`engine/loop.py`.

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

| #   | Area                                                   | Impact     | Effort |
| --- | ------------------------------------------------------ | ---------- | ------ |
| B3  | `_wire_landlord_rental` return instead of mutate       | DX         | small  |
| B2  | Compile-helpers tuple→dataclass                        | DX         | medium |
| B0  | Unify rollout axis to R-last on `current` buffers      | DX         | medium |
| B1  | CompiledSimulation 170 → 8 nested arenas               | big DX win | large  |
| B4  | Split compiler.py + engine.py                          | DX         | large  |
| X1  | After Flux reconcile: drop `_collapse_list_notes` shim | cross-repo | small  |
