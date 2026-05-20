# Augur Sim TODO

Current tracker for gaps in `augur/sim` before treating it as the
primary simulation backend for the Augur frontend/API.

## Frontend/API Integration Blockers

- [ ] Define the durable API projection over `SimulationRun`: per
      rollout/per agent net worth, account balances, transaction log,
      tax breakdowns, obligation lifecycle rows, failure rows, and compact
      scenario metadata. Prefer a clean `model -> sim -> api` contract
      over matching legacy `ScenarioRunArrays` names.
- [ ] Add frontend-shaped e2e fixtures that pin output rows for the
      representative scenarios the UI needs. These should sit on top of
      the existing pinned numerics tests rather than replacing them.
- [ ] Decide how failed rollouts are surfaced in API summaries:
      all-rollout metrics, surviving-rollout metrics, and explicit
      failure-count/failure-month distributions.
- [ ] Remove or hide legacy partner-equity contribution inputs from
      frontend/backend integration until a generic, tested property-stake
      model exists. Do not add a bespoke partner-contribution pathway to
      `sim`.

## Sim Capability Gaps

- [ ] Finish the real-estate lifecycle: property sale, closing costs,
      mortgage payoff, sale proceeds split, occupancy changes,
      depreciation, §121 exclusion, §1250 recapture, itemized deductions,
      SALT cap, and qualified-residence mortgage-interest deduction.
- [ ] Add net-worth and audit projections from state/event frames.
      The raw frames exist; frontend integration needs stable projection
      helpers and tests.
- [ ] Move production stochastic market generation to `augur/model`.
      `GeometricBrownianPath` in `augur/sim/market.py` remains acceptable
      as test/bench scaffolding until the model package supplies sampled
      exogenous path bundles.
- [ ] Add variable spending/obligation amounts sourced from exogenous
      model paths.
- [ ] Exercise constrained sellability masks end to end.

## Explicitly Deferred

- [ ] HIFO, specific-id, and average-cost lot selection.
- [ ] Withholding, underpayment penalties, partial obligation
      payments, delinquency balances, grace periods, and failure recovery.
- [ ] NIIT and filing statuses beyond single.
- [ ] Consider globally unique account ids to remove repeated
      `agent_id` join boilerplate.
