# Augur Sim TODO

Current tracker for gaps in `augur/sim` before treating it as the
primary simulation backend for the Augur frontend/API.

## Switchover Definition

The replacement is done when the production API path is:

```text
current API / catalog config
  -> typed sim scenario + market sampling request with explicit rollout seeds
  -> augur/model JointMarketModel.sample(...)
  -> SampledMarketBundle levels/events
  -> augur/sim deterministic evaluation
  -> augur/api ProjectionRun/read models
```

`augur/core` may keep a compatibility runner while parity is being checked, but
it should not be the production owner of market sampling, path evaluation, or
response semantics after cutover.

## Replacement Checklist

- [ ] Replace the API backend's direct `augur.core.api.ScenarioEngine`
      execution path with a `model -> sim -> api` path. Keep the legacy
      path available as a shadow/parity baseline until the sim path has
      browser and fixture coverage.
- [ ] Replace the legacy `ScenarioSet` request boundary with either a
      native sim request schema or an explicit translator from the current
      browser/API payload into `augur.sim.scenario.Scenario`.
- [ ] Replace legacy `ScenarioRunArrays` response shaping with serialized
      `ProjectionRun` read models. The API should expose compact scenario
      metadata plus distribution-first projections instead of preserving
      legacy field names by default.
- [ ] Replace production use of `augur.core.market_bundle.MarketBundle`
      in the Augur run path with model-owned exogenous bundles supplied by
      `augur/model` and consumed by `augur/sim`. The production `simple`
      provider config now samples a sim-native joint model and adapts it to
      the legacy core bundle; the backend still executes through core.
- [ ] Make `noop` and any other runtime-selectable provider produce the same
      `SampledMarketBundle` levels/events shape directly. The core bundle
      adapter should be a legacy compatibility shim, not a requirement for a
      provider to participate in production.
- [ ] Replace core-side required-market-key discovery with sim scenario
      introspection so model providers know which public markets, private
      equity paths, locations, currencies, and other exogenous series must
      be sampled.
- [ ] Add the sim-side market consumption adapter: sampled levels/events should
      drive mark-to-market asset values, rent/home-value paths, private-equity
      marks, private-equity sale opportunities, mortgage/rate paths when they
      exist, and any future exogenous streams. `augur/sim` must not sample
      production market paths internally.
- [ ] Replace bespoke partner-equity contribution handling with the generic
      property-stake model once property stakes are covered by sim tests.
- [ ] Replace ad hoc catalog/default expansion in the legacy backend with
      an `AugurConfig`/catalog-to-sim scenario builder that remains
      compatible with `gaffer-private` deployment YAML.
- [ ] Replace the current all-or-nothing backend switch with a staged
      rollout: shadow endpoint, parity fixtures against overlapping legacy
      outputs, browser smoke coverage, then frontend cutover.
- [ ] After cutover, keep the core adapter only for explicit legacy fixtures or
      remove it once no API, browser, or private deployment path depends on
      core-shaped market bundles.

## Frontend/API Integration Blockers

- [ ] Add API serialization, compact scenario metadata, and a frontend
      adapter over `ProjectionRun`. Prefer a clean `model -> sim -> api`
      contract over matching legacy `ScenarioRunArrays` names.
- [ ] Add a backend shadow-run/parity harness that can run the current
      `ScenarioSet` through both paths. Feed both paths from the same
      model-owned sampled bundle wherever possible, so parity failures isolate
      simulator behavior rather than differences in market draws.
- [ ] Preserve legacy scalar-seed behavior only at the API compatibility edge.
      The request translator or core shim should expand scalar seed + rollout
      count into explicit rollout seeds; model implementations and sim should
      never rely on an omitted/default seed.
- [ ] Define the minimal compatibility response for existing frontend routes:
      scenario metadata, distribution summaries, selected-rollout trajectory
      series, accounting/detail drilldowns, warnings, and model provenance.
      Anything else should move behind sliced read-model endpoints instead of
      being preserved as legacy top-level fields.
- [ ] Remove or hide legacy partner-equity contribution inputs from
      frontend/backend integration until a generic, tested property-stake
      model exists. Do not add a bespoke partner-contribution pathway to
      `sim`.

## Sim Capability Gaps

- [ ] Finish the real-estate lifecycle: property sale, closing costs,
      mortgage payoff, sale proceeds split, occupancy changes,
      depreciation, §121 exclusion, §1250 recapture, itemized deductions,
      SALT cap, and qualified-residence mortgage-interest deduction.
- [ ] Move production stochastic market generation to `augur/model`.
      Static/GBM fixture path specs, the production `simple` model, and the
      representative calibrated VECM model now emit the model-owned sampled
      levels/events bundle shape. Unported exploratory models were moved to
      `augur/model/x/legacy_market_models/` for later porting or deletion.
- [ ] Align every market-provider/model implementation with the
      `augur/sim` consumption API. Simple and VECM now implement the
      `JointMarketModel` contract and are shimmed for core; `noop` still needs
      to produce or adapt to the sampled levels/events bundle before the
      backend switches away from core.
- [ ] Treat `augur/model/x/legacy_market_models/` as non-runtime code. Port
      only models selected by production or used as representative joint-model
      coverage; delete or keep the rest quarantined until a fresh design pass.
- [ ] Replace the VECM wrapper's ad hoc latest-observation lookup with a
      typed evidence artifact/runtime state boundary. The model should receive
      factor-keyed current levels and provenance metadata directly, not infer
      `sp500`, home-value, rent, and inflation values from source-specific
      `latest_observations` maps.
- [ ] Add variable spending/obligation amounts sourced from exogenous
      model paths.
- [ ] Exercise constrained sellability masks end to end.

## Refactor Follow-Ups

- [ ] Revisit whether policy should emit all agent actions, including
      obligation-payment transfers. Potential future shape: hard
      demands are inputs to the agent policy, the policy emits both
      liquidation orders and checking-cash payment transfers, and
      settlement only validates that every hard demand was satisfied.
      Current split is narrower: policy emits sales; settlement emits
      required payments.
- [ ] Consider whether `EventLog` should expose only catalog-keyed
      access (`log.frame(EVENT_FRAMES.transfers)`) or keep the current
      convenience properties (`log.transfers`, etc.). The catalog now
      owns schema/normalization, but the property layer still repeats
      event names for caller ergonomics.

## Explicitly Deferred

- [ ] HIFO, specific-id, and average-cost lot selection.
- [ ] Withholding, underpayment penalties, partial obligation
      payments, delinquency balances, grace periods, and failure recovery.
- [ ] NIIT and filing statuses beyond single.
- [ ] Consider globally unique account ids to remove repeated
      `agent_id` join boilerplate.
