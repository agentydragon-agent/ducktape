# Augur TODO

Last design scan: 2026-05-14.

## Next

- [ ] Continue `plans/e2e_redesign.md` Step 7 by moving sale-related transaction arrays toward ledger/state derivation once tax timing and basis semantics are explicit enough.

## Step 7 Scope

- [x] Persist actor-keyed ledger entries and balance snapshots into scenario result detail. Public `ScenarioResult`, `ScenarioRun`, and selected-rollout detail now expose row-level ledger/snapshot records.
- [x] Add reconciliation e2e tests for current policy arrays: monthly spend, SP500 sales and taxes, private-equity sales and taxes, mortgage payments, rental/property operating cash flows, property sale settlement/taxes, and partner-equity ledgers/claims.
- [x] Derive recurring cash-flow arrays from ledger rows: monthly spend, mortgage interest/principal/payment, rental income/fees, property carrying costs, and net property cash flow.
- [ ] Make arrays derive from state/ledger where practical. Where an array remains bespoke for performance or UI compatibility, assert that it reconciles to the ledger total and document any intentional difference.
- [x] Expand one-rollout detail beyond curves/actions/ledger/snapshots to include market observations and explicit policy decisions.

## API / Runtime Design Debt

- [ ] Replace class-filtered policy execution with ordered actor policy programs. `actor_policy_programs()` exists, but the engine still flattens policies with `enabled_rules_of_type()` and runs hardcoded branches in `run_scenario_vectorized()`.
- [ ] Split private-equity liquidity opportunity, user sale request, policy decision, accounting application, and public action into separate concepts with explicit cause IDs.
- [ ] Remove or implement schema-only policy types: `LiquidityReservePolicy`, `PortfolioTargetRebalancePolicy`, and `ManualEventSchedulePolicy`.
- [ ] Make result inspection typed and local. String metric names via `series("cash_usd")` are acceptable as a compatibility layer, but primary callers should get discoverable typed metric/rollout/detail helpers.
- [ ] Honor or remove `ReportSpec.include_monthly_columns`, `include_sample_paths`, and unsupported `MarketRequest.shared_market_paths=false`.
- [ ] Collapse the old and new schema surfaces. `augur/core/scenario_set.py` is the scenario-set simulator schema; legacy shapes in `augur/core/schemas.py` should be deleted, moved, or wrapped at an explicit compatibility boundary.
- [ ] Clarify initial state vs scheduled transitions. Property purchase, financing, ownership, future sale, rental transition, and PE liquidity should not be split across fields/events that can contradict each other.
- [ ] Reduce single-property/global assumptions. Scenario-level `property_selection`, `financing`, `rental_plan`, and `tax_profile` should eventually become initial positions, per-property settings, or per-actor/accounting inputs as the simulator grows.
- [ ] Move evidence/model-fetching shapes out of core simulator API when touched. Core should consume calibrated market/provider inputs, not source-specific evidence objects.

## Tax Follow-Ups

- [ ] Continue the annual federal + California tax model beyond sale taxes: qualified dividends, short-term gains, capital losses, rental income, deductible expenses, passive-loss release, SALT/property-tax treatment, California conformity/non-conformity, and ordinary income schedules beyond one annual `TaxProfile` value.
- [ ] Convert taxes into a ledger/liability workflow with payment timing instead of only allocating annual incremental tax back to sale months.
- [ ] Keep stock-sale, PE-sale, and property-sale tax reconciliation in the Step 7 test set.

## Reporting / UI Follow-Ups

- [ ] Key partner-equity reporting by partner actor or make it derivable from actor-keyed ledger entries. Aggregate scenario arrays are fine for charts but should not be the only public detail.
- [ ] Reconsider whether to reintroduce per-component partner contribution reporting for interest, property tax, insurance, HOA, and maintenance.
- [ ] Refresh `augur/SPEC.md` once policy execution, sale taxes, and one-rollout detail have stabilized.
