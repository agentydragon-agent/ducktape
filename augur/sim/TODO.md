# Augur Sim TODO

Current tracker for gaps in `augur/sim` before treating it as the
primary simulation backend for the Augur frontend/API.

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
- [ ] Replace core-side required-market-key discovery with sim scenario
      introspection so model providers know which public markets, private
      equity paths, locations, currencies, and other exogenous series must
      be sampled.
- [ ] Replace bespoke partner-equity contribution handling with the generic
      property-stake model once property stakes are covered by sim tests.
- [ ] Replace ad hoc catalog/default expansion in the legacy backend with
      an `AugurConfig`/catalog-to-sim scenario builder that remains
      compatible with `gaffer-private` deployment YAML.
- [ ] Replace the current all-or-nothing backend switch with a staged
      rollout: shadow endpoint, parity fixtures against overlapping legacy
      outputs, browser smoke coverage, then frontend cutover.

## Frontend/API Integration Blockers

- [ ] Add API serialization, compact scenario metadata, and a frontend
      adapter over `ProjectionRun`. Prefer a clean `model -> sim -> api`
      contract over matching legacy `ScenarioRunArrays` names.
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
      Static/GBM fixture path specs and the production `simple` model now
      live in `augur/model`; the remaining production gap is moving the
      calibrated macro providers to emit the same sim-facing sampled
      levels/events bundle shape.
- [ ] Align every market-provider/model implementation with the
      `augur/sim` consumption API. Simple now implements the
      `JointMarketModel` contract and is shimmed for core; `noop`, VECM,
      VAR, Wilkie, DCC/GARCH, bootstrap, and future calibrated joint models
      still need to produce or adapt to the sampled levels/events bundle
      before the backend switches away from core.
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
