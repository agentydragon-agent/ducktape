# Augur TODO

Last design scan: 2026-05-15.

This file tracks public, generic Augur backlog. Downstream repos should keep
private composition, deployment, and user-/company-specific modeling assumptions
in their own trackers.

Priority ordering and cross-repo consolidation live in
`plans/roadmap.md`. Keep this file as the public generic backlog rather than a
second ordered roadmap.

## Next

- [ ] Continue `plans/e2e_redesign.md` Step 7 by replacing `allocated_to_source_month` tax timing with realistic annual/estimated-payment liability timing.
- [ ] Make the generic Augur OCI image public-safe: no private Python config, property records, or media in image layers; deployments supply private config and assets through mounted runtime inputs.
- [ ] Add a durable property-asset storage contract: stable property asset IDs/URLs backed by object storage or a database-like asset table, so deployments do not need to bake private media into frontend images.

## Step 7 Scope

- [ ] Make arrays derive from state/ledger where practical. Where an array remains bespoke for performance or UI compatibility, assert that it reconciles to the ledger total and document any intentional difference.

## API / Runtime Design Debt

- [ ] Replace class-filtered policy execution with ordered actor policy programs. `actor_policy_programs()` exists, but the engine still flattens policies with `enabled_rules_of_type()` and runs hardcoded branches in `run_scenario_vectorized()`.
- [ ] Split private-equity sale opportunity, user participation preference,
      policy decision, accounting application, and public action into separate
      concepts with explicit cause IDs. Tender-eligible private marks are not
      liquid assets and must stay out of `liquid_net_worth`.
- [ ] Extend policy schema/programs enough for downstream deployments to express concentrated-holding limits, liquidity-sale preferences, tender/acquisition/IPO preferences, and tax preferences without ad-hoc `AugurConfig` fields.
- [ ] Replace `scenario.actorPolicy`-style enums with explicit actor
      agreements/contracts. For example, "agent X pays agent Y this amount over
      this period and receives this equity/share/claim in return" should be a
      modeled agreement between agents, not a scenario-level enum that activates a
      hardcoded partner-ownership hack. The exact representation still needs design.
- [ ] Remove or implement schema-only policy types: `LiquidityReservePolicy`, `PortfolioTargetRebalancePolicy`, and `ManualEventSchedulePolicy`.
- [ ] Make result inspection typed and local. String metric names via `series("cash_usd")` are acceptable as a compatibility layer, but primary callers should get discoverable typed metric/rollout/detail helpers.
- [ ] Honor or remove `ReportSpec.include_monthly_columns`, `include_sample_paths`, and unsupported `MarketRequest.shared_market_paths=false`.
- [ ] Clarify initial state vs scheduled transitions. Property purchase,
      financing, ownership, future sale, rental transition, and private-stock
      sale opportunities should not be split across fields/events that can
      contradict each other.
- [ ] Reduce single-property/global assumptions. Scenario-level `property_selection`, `financing`, `rental_plan`, and `tax_profile` should eventually become initial positions, per-property settings, or per-actor/accounting inputs as the simulator grows.
- [ ] Replace built-in `LocationId` enum with database-like location entities, parallel to properties. A location should carry regulation/tax/modeling knobs that downstream regulation and tax code interprets, not require hardcoded enum extension.
- [ ] Move evidence/model-fetching shapes out of core simulator API when touched. Core should consume calibrated market/provider inputs, not source-specific evidence objects.

## Tax Follow-Ups

- [ ] Continue the annual federal + California tax model beyond sale taxes: qualified dividends, short-term gains, capital losses, rental income, deductible expenses, passive-loss release, SALT/property-tax treatment, California conformity/non-conformity, and ordinary income schedules beyond one annual `TaxProfile` value.
- [ ] Convert taxes into a ledger/liability workflow with payment timing instead of only allocating annual incremental tax back to sale months.
- [ ] Keep stock-sale, PE-sale, and property-sale tax reconciliation in the Step 7 test set.
- [ ] Replace user-entered flat marginal tax rates with bracket-aware tax
      accounting. Asking for a single "marginal tax rate" is a symptom that the
      model probably is not consistently computing which portions of income,
      gains, deductions, and losses fall into which federal/state brackets.

## Reporting / UI Follow-Ups

- [ ] Reframe the Augur UI around the user's conceptual model instead of the
      simulator's current implementation seams. The present sidebar mixes initial
      holdings, policy knobs, exogenous market events, tax constants, financing
      assumptions, actor participation, and result summaries in ways that make the
      product feel internally confused. Start with an information architecture pass:
      define scenario identity, actors/ownership, initial balance sheet, market
      assumptions, policy choices, tax assumptions, and output diagnostics as
      separate concepts before continuing local control tweaks. Do not keep using a
      flat browser-side "scenario row" as the source of truth and then expand it
      into typed backend objects; that shape recreates the spreadsheet-style
      coupling the simulator is supposed to avoid.
- [ ] Audit remaining result panels for distribution-vs-trajectory mixing. The
      first split moved the liquidity/stock-sales panel into the trajectory view so
      "Final SP500" is sourced from the selected rollout instead of a terminal P50
      next to a path table; keep applying that rule as result helpers become typed.
- [ ] Add explicit comparison views for deltas between two scenario
      distributions. The simulator should not bake a baseline/counterfactual
      into each rollout; a delta view should compare two real scenarios, either
      as the distribution of differences between samples from both
      distributions or, when `shared_market_paths=true`, as paired differences
      conditioned on the same underlying market rollout.
- [ ] Adopt a boring standard React UI component framework, or explicitly
      document why Augur is not doing so. The current app uses Tailwind utilities
      without a component kit, and details like input prefixes/suffixes/adornments
      already do not visually mesh with the inputs. Basic form controls,
      disclosure widgets, tables, buttons, tabs, and input groups should come from
      a well-tested component surface instead of being locally reinvented.
- [ ] Finish financing-control cleanup around mortgage terms. The browser now
      hides custom term/rate fields outside custom override mode, but the broader
      domain model still needs a pass over which mortgage products and override
      fields should exist at all.
- [ ] Give room-rental vacancy a realistic default in fixtures and deployment
      config. The visible/default value appears to be `0%`, which is not a
      credible modeling default.
- [ ] Reorganize tax controls so capital-gains rates, exclusions, and other tax
      constants live together and apply consistently to stock, private-equity, and
      property-sale gains. Verify the current math before moving controls.
- [ ] Finish the private-equity tender/opportunity redesign. The browser no
      longer exposes arbitrary USD sale controls, core no longer has a manual
      sale-request path, `liquid_net_worth` no longer counts tender-eligible
      private marks, and a first liquid-net-worth-floor sale policy records
      explicit sale/non-sale reasons. The model still needs richer exogenous
      tender/acquisition/IPO opportunity settings, participation policies beyond
      the first floor rule, and clearer private-stock sale/tax vocabulary.
- [ ] Make charts choose human-sensible axis ticks. Use a smart step heuristic
      so labels land on natural values like `$1,000`, `$2,000`, `$3,000` instead of
      awkward computed values such as `$1,247.20` or `$9,231.10`.
- [ ] Key partner-equity reporting by partner actor or make it derivable from actor-keyed ledger entries. Aggregate scenario arrays are fine for charts but should not be the only public detail.
- [ ] Reconsider whether to reintroduce per-component partner contribution reporting for interest, property tax, insurance, HOA, and maintenance.
- [ ] Refresh `augur/SPEC.md` once policy execution, sale taxes, and one-rollout detail have stabilized.
