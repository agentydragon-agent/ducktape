# Augur Sim TODO

Current tracker for gaps in `augur/sim` before treating it as the
primary simulation backend for the Augur frontend/API.

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
      `GeometricBrownianPath` in `augur/sim/market.py` remains acceptable
      as test/bench scaffolding until the model package supplies sampled
      exogenous path bundles.
- [ ] Add variable spending/obligation amounts sourced from exogenous
      model paths.
- [ ] Exercise constrained sellability masks end to end.

## Refactor Follow-Ups

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
