# Augur TODO

Last design scan: 2026-05-14.

## Next

- [ ] Continue `plans/e2e_redesign.md` Step 7 by replacing `allocated_to_source_month` tax timing with realistic annual/estimated-payment liability timing.
- [x] Add public Augur app/server e2e tests backed by non-private fixtures: fixture `AugurConfig`, deterministic/noop market provider path, representative property fixtures, and Playwright coverage for the generic UI.
- [x] Add a public Bazel-runnable Augur server binary that accepts `--config`, `--dist-dir`, and `--market-config` so private deployments do not need their own `serve.py` wrapper.
- [ ] Make the generic Augur OCI image public-safe: no private Python config, property records, or media in image layers; deployments supply private config and assets through mounted runtime inputs.

## Step 7 Scope

- [x] Persist actor-keyed ledger entries and balance snapshots into scenario result detail. Public `ScenarioResult`, `ScenarioRun`, and selected-rollout detail now expose row-level ledger/snapshot records.
- [x] Add reconciliation e2e tests for current policy arrays: monthly spend, SP500 sales and taxes, private-equity sales and taxes, mortgage payments, rental/property operating cash flows, property sale settlement/taxes, and partner-equity ledgers/claims.
- [x] Derive recurring cash-flow arrays from ledger rows: monthly spend, mortgage interest/principal/payment, rental income/fees, property carrying costs, and net property cash flow.
- [x] Derive sale transaction arrays from ledger rows: SP500 sale/basis/gain/tax, checking-floor sale action, private-equity sale/basis/tax, property sale gross/closing cost/debt payoff/tax/net proceeds, and net property sale cash flow.
- [x] Derive partner contribution transaction arrays from actor-keyed ledger rows: contribution transfer, contribution used for house costs, unallocated contribution excess, and partner principal credit.
- [x] Classify current monthly result arrays in `plans/e2e_redesign.md` as state snapshots, transaction flows, explanatory calculations, or compatibility aliases.
- [x] Add typed accounting-detail rows for property-sale basis/gain calculations and sale-tax payment allocation. Federal/California/total tax arrays and property-sale basis/gain arrays now derive from those rows.
- [ ] Make arrays derive from state/ledger where practical. Where an array remains bespoke for performance or UI compatibility, assert that it reconciles to the ledger total and document any intentional difference.
- [x] Expand one-rollout detail beyond curves/actions/ledger/snapshots to include market observations and explicit policy decisions.

## API / Runtime Design Debt

- [ ] Replace class-filtered policy execution with ordered actor policy programs. `actor_policy_programs()` exists, but the engine still flattens policies with `enabled_rules_of_type()` and runs hardcoded branches in `run_scenario_vectorized()`.
- [ ] Split private-equity liquidity opportunity, user sale request, policy decision, accounting application, and public action into separate concepts with explicit cause IDs.
- [ ] Remove or implement schema-only policy types: `LiquidityReservePolicy`, `PortfolioTargetRebalancePolicy`, and `ManualEventSchedulePolicy`.
- [ ] Make result inspection typed and local. String metric names via `series("cash_usd")` are acceptable as a compatibility layer, but primary callers should get discoverable typed metric/rollout/detail helpers.
- [ ] Honor or remove `ReportSpec.include_monthly_columns`, `include_sample_paths`, and unsupported `MarketRequest.shared_market_paths=false`.
- [ ] Decide whether counterfactual rent belongs in the scenario-set backend API. The app currently persists the counterfactual rent controls in URL state, but the public scenario-set schema does not consume them.
- [x] Collapse the old and new schema surfaces. `augur/core/scenario_set.py` is the scenario-set simulator schema; the legacy joint-rollout and stochastic-outcome schemas have been deleted instead of kept behind compatibility wrappers.
- [ ] Clarify initial state vs scheduled transitions. Property purchase, financing, ownership, future sale, rental transition, and PE liquidity should not be split across fields/events that can contradict each other.
- [ ] Reduce single-property/global assumptions. Scenario-level `property_selection`, `financing`, `rental_plan`, and `tax_profile` should eventually become initial positions, per-property settings, or per-actor/accounting inputs as the simulator grows.
- [ ] Replace built-in `LocationId` enum with database-like location entities, parallel to properties. A location should carry regulation/tax/modeling knobs that downstream regulation and tax code interprets, not require hardcoded enum extension.
- [ ] Move evidence/model-fetching shapes out of core simulator API when touched. Core should consume calibrated market/provider inputs, not source-specific evidence objects.

## Tax Follow-Ups

- [ ] Continue the annual federal + California tax model beyond sale taxes: qualified dividends, short-term gains, capital losses, rental income, deductible expenses, passive-loss release, SALT/property-tax treatment, California conformity/non-conformity, and ordinary income schedules beyond one annual `TaxProfile` value.
- [ ] Convert taxes into a ledger/liability workflow with payment timing instead of only allocating annual incremental tax back to sale months.
- [ ] Keep stock-sale, PE-sale, and property-sale tax reconciliation in the Step 7 test set.

## Reporting / UI Follow-Ups

- [ ] Key partner-equity reporting by partner actor or make it derivable from actor-keyed ledger entries. Aggregate scenario arrays are fine for charts but should not be the only public detail.
- [ ] Reconsider whether to reintroduce per-component partner contribution reporting for interest, property tax, insurance, HOA, and maintenance.
- [x] Replace deployment-private app e2e tests as the main confidence signal. Public Augur behavior now has a ducktape browser smoke backed by non-private fixtures; gaffer can keep only private-config/assets coverage.
- [ ] Refresh `augur/SPEC.md` once policy execution, sale taxes, and one-rollout detail have stabilized.
