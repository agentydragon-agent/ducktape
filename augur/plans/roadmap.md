# Augur Unified Plan

Last consolidated: 2026-05-25.

This plan consolidates the active Augur work from the public framework docs and
the private deployment notes. It is the priority ordering. `augur/TODO.md`
remains the detailed public backlog; private values, holdings, property data,
and deployment-specific composition stay in the downstream private repo.

## Sources

- `augur/SPEC.md`: product contract and simulator vocabulary.
- `augur/sim/README.md`: sim purpose, boundaries, invariants, and rollout
  failure semantics.
- `augur/sim/REQUIREMENTS.md` + `augur/sim/DESIGN.md`: simulator capability
  surface and structural decisions.
- `augur/sim/docs/tensorized_simulator.md`: rollout-axis tensorization design + invariants.
- `augur/sim/docs/tax_engine_evaluation.md`: tax engine build-vs-adopt evaluation.
- `augur/docs/prior_art_audit.md`: external architecture lessons for path
  identity, governance, policy projection, and accounting traces.
- `augur/sim/TODO.md`: forward-looking sim/product follow-ups.
- `augur/TODO.md`: public generic backlog.
- `gaffer-private/TODO.md`: private personal-finance modeling follow-ups.
- `gaffer-private/x/augur/SPEC.md`: private deployment boundary and image
  privacy contract.

## North Star

Augur simulates one (and, on the roadmap, a small set of) `ScenarioKey`s across
sampled exogenous paths and returns a distribution over trajectories. A
selected rollout is an inspection aid, not a separate deterministic product.
The UI, app state, and result APIs should make that distinction impossible to
miss.

The core model should stay structured around actors, accounts, assets,
liabilities, markets, policies, actions, ledgers, accounting detail, and
balance snapshots. The app may provide friendly controls, but it should not use
a flat browser-side "scenario row" as the source of truth and then expand it
back into typed backend objects.

The intended production backend path is `augur/model -> augur/sim -> augur/api`:
model providers sample exogenous levels/events with provenance, `augur/sim`
deterministically evaluates typed scenarios over those paths, and `augur/api`
serves compact projection/read models. The product metric-fan endpoint
already runs numpy-direct from `dense.buffers.*` (`monthly_metric_arrays`),
but the rollout-detail endpoint still calls `dense.decode()` to materialize
the long-form `SimulationRun` polars frames before the product layer
projects them. The next cutover is exposing `ProjectionRun` read models
(`augur/sim/projections.py`) over a `ScenarioKey` directly, instead of the
intermediate dataframe materialization. Tracked under "Architecture /
cutover" in `augur/sim/TODO.md`.

Standing guidance during continued cutover:

- **Ordinary income translation is deferred (low priority, 2026-05-24).**
  Today's scenarios are post-earning retirement projections rather than
  active W-2 income; the income knob is not on the near-term path.
  Promote when a scenario requires earning during the horizon.
- **Path-indexed recurring cashflows.** Outside rent indexes to the
  modeled rent-cost series from `augur/model` (configure current rent on
  the as-of date plus a model series key, scale future rent by the
  series ratio). Generalize this into a single path-indexed amount
  contract for other recurring cashflows rather than adding one-off
  inflation/rent flags. When native landlord rental cashflows land
  (`augur/sim/TODO.md` "Real-estate lifecycle"), tenant rent income for
  owned properties should use the same contract.
- **Nominal dollars through sim.** Backend/sim accounting stays in
  nominal dollars. Any inflation-adjusted display belongs in a
  postprocessing/read-model layer.
- **YAML-derived defaults.** Continue migrating bootstrap/UI defaults
  away from frontend literals and into deployment YAML; hide UI toggles
  for facts that should remain config-only (especially initial
  positions).

## Prior-Art Shape For Core Cleanup

The prior-art audit points to a conservative target shape:

- Exogenous path generation and household projection stay separate.
  `ExogenousSamplingRequest` plus `SampledExogenousBundle` is the durable economic
  scenario-generator boundary; the simulator is deterministic once it receives
  a typed scenario and sampled exogenous paths.
- Trajectory identity includes scenario input, exogenous model identity,
  evidence/calibration identity, generator implementation/version, seed, path
  index, and any non-exogenous event streams. `rollout_index` remains a convenient
  selector, not a reproducibility key by itself.
- Actor policy programs are ordered programs. Policy steps emit decisions and
  instructions; accounting/runtime code validates and applies effects. New
  policy families should not reintroduce per-class execution loops.
- Ledgers, balance snapshots, accounting detail, lots, liabilities, and typed
  cause IDs are the source of truth. Monthly arrays are chart/report views over
  that state, not a parallel semantic model.
- Model governance is part of the model output. Sampled bundles now carry first
  typed model/evidence/calibration/generator/path identities; the next cleanup
  is to persist real artifacts and validation results behind those IDs.

## Policy Runtime And Result Typing

The simulator executes ordered actor policy programs and writes typed event
frames (`transfers`, `lot_dispositions`, `tax_accruals`, `tax_settlements`,
`obligation_accruals`, `obligation_settlements`, …) as the trace surface.
Ledger/snapshot/accounting-detail rows are the canonical source of truth.

Remaining work:

- Trace rows for **decisions that produced no event** — today the event
  frames record what actually happened, but a policy that decided "no
  sale because no opportunity" / "rejected because below floor" produces
  no row. Trajectory inspection needs those decisions visible.
- Keep exogenous paths and opportunities as observations, not policy
  decisions.

Private downstream work:

- Populate real cost bases for private holdings and taxable brokerage
  positions in the private repo.
- Model managed direct-index/tax-loss-harvesting behavior as a private
  deployment input once the generic position/tax hooks exist.

Acceptance criteria:

- Policy order is explicit and testable.
- No policy family bypasses the ordered actor program dispatcher.
- Policy decisions (including no-op / rejected) are visible in
  trajectory inspection.

## Property-Asset Storage Contract

`PropertySourceConfig` + `PropertyAssetConfig` cover the YAML side
(`properties_path` for the shortlist, `property_assets` for stable image
URLs). What's missing is a durable backing store:

- Durable property-asset storage backed by object storage or a
  database-like asset table — not just YAML + nginx sidecar.
- Keep large private media out of ConfigMaps. The current private nginx
  image is the expedient until the generic asset contract exists.
- Keep the generic Augur OCI image free of private config, property
  records, and private media.

Acceptance criteria:

- Public image layers contain only generic Augur code and public-safe
  inputs.
- Private deployments can supply config, property records, and media
  through runtime inputs without forking app logic.

## UI Cleanup

These should follow the result-shape and state-shape work so they don't
polish the wrong structure.

- Continue the Mantine migration. `MantineProvider` wraps the product
  shell; controls are mixed Tailwind + Mantine. Standard controls
  (selects, number inputs, buttons, prefix/suffix adornments) should
  move to Mantine unless there's a documented reason not to.
- Continue renaming private-equity result columns/panels away from
  generic liquidity language where they mean tender eligibility or sale
  opportunities.
- Rework mortgage controls around standard mortgage products and
  explicit custom override mode.
- Refresh `augur/SPEC.md` after policy execution, tax timing, and
  result-view contracts stabilize.

## Next Lanes (parallelism + sequencing)

- **Tax surface beyond sale tax** — qualified dividends, short-term gains,
  capital losses + carryforward, rental income tax, passive-loss release.
  (~~SALT/property-tax federal deduction~~ done — `FederalSaltDeductionPolicy`
  with year-keyed cap; AGI phase-out + sales-tax election still deferred.)
- **`RegimeChange` mid-rollout events** — IPO converts
  `LiquidityEventOnly` → `PublicMarket`. The discriminated-union shape
  already supports it; runtime needs to sample the event month and flip
  the variant. Companion to PE acquisition events.
- **Mortgage-rate path sampling** — today the mortgage rate is a single
  PMMS survey number at scenario time; required-series introspection
  doesn't cover a `mortgage30:*` path. Adding it would let "what if
  rates fall to 5% in 18 months" scenarios work.
- **Underpayment penalty on quarterly estimates** — IRS interest rate +
  3% on shortfalls. Layers on the year-end true-up already in place.
- **Borrowing facilities** — overdraft, margin, credit line as explicit
  funding sources in the obligation pipeline. Today negative cash is a
  silent warning; with explicit borrowing it becomes an
  accounting-tracked liability paired with a funding source.
- **Persist model-governance artifacts** — durable evidence / calibration
  / validation-report storage for market providers. `augur/model/`.
  Self-contained, can run in parallel with anything.
- **Reintroduce partner/co-owner agreements** after sim has a tested
  agreement model. "Agent X pays agent Y this amount over this period
  for this share/claim" should come back as a tested agreement model
  in `augur/sim`, not as a scenario-wide enum.

## Guardrail: Evidence Configuration Stays Typed At The Boundary

Keep the exogenous evidence config Pydantic-parsed at load time
(`augur/fit/evidence_config.py`), with `evidence_config_test` as the
review point when adding new source-data fields or deployment-supplied
config. Reject stale simulation knobs at the file boundary —
`ExogenousSamplingRequest` owns rollout count, horizon, and seed; the
market config should not keep a second inert copy.

## Verification Loop

For each public framework slice:

```bash
bbr test //augur:browser_shell_test
bbr test //augur:visual_test
bbr test //augur/api:server_test
```

Before handing off a broader spiral:

```bash
bbr test //augur/...
bbr build //augur/...
```

For private deployment slices, also run the private Augur browser/backend tests
and verify the live deployment only after the public framework commit is
repinned downstream.
