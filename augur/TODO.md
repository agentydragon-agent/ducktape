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
- [ ] Separate rollout stochastic inputs in the API/data model. Today a rollout
      is effectively a sampled market environment plus deterministic policy. Make
      that explicit, and consider separate structures/identifiers for market
      nondeterminism, policy nondeterminism, and any future non-market random
      events so trajectory IDs do not conflate different sources of randomness.
- [ ] Decide how failed or insolvent rollouts should be represented. Consider a
      programmatic guard that treats `cash_usd <= 0` as a failure unless an
      enabled sale/financing policy can cover the shortfall, and define whether
      actual cash is ever allowed to go below zero or instead produces a
      first-class failed-rollout state.
- [ ] Clarify initial state vs scheduled transitions. Property purchase,
      financing, ownership, future sale, rental transition, and private-stock
      sale opportunities should not be split across fields/events that can
      contradict each other.
- [ ] Reduce single-property/global assumptions. Scenario-level `property_selection`, `financing`, `rental_plan`, and `tax_profile` should eventually become initial positions, per-property settings, or per-actor/accounting inputs as the simulator grows.
- [ ] Replace built-in `LocationId` enum with database-like location entities, parallel to properties. A location should carry regulation/tax/modeling knobs that downstream regulation and tax code interprets, not require hardcoded enum extension.
- [ ] Move local-regulation definitions toward config-driven data, likely YAML
      or another reviewed structured format. The config should cover generic
      knobs where possible while still being able to select location-specific
      code paths for tax, regulation, or other behaviors that cannot be modeled
      cleanly as data alone.
- [ ] Move pure-data model inputs out of Python modules and into dumb parsed
      configuration resources, such as Pydantic-parsed YAML loaded via runfiles
      or `importlib.resources`. Tables/constants like those currently embedded
      in `annual_tax.py` should be data unless the Python code is doing real
      behavior.
- [ ] Prefer Pydantic for serde and validation at API/config boundaries. Avoid
      custom `to_json_dict()`-style conversion helpers except at narrow
      compatibility seams.
- [ ] Move evidence/model-fetching shapes out of core simulator API when touched. Core should consume calibrated market/provider inputs, not source-specific evidence objects.
- [ ] Remove redundant `augur_` prefixes from internal module names such as
      `augur.core.augur_accounting`; inside the `augur` package they add noise
      without clarifying ownership.

## Tax Follow-Ups

- [ ] Continue the annual federal + California tax model beyond sale taxes: qualified dividends, short-term gains, capital losses, rental income, deductible expenses, passive-loss release, SALT/property-tax treatment, California conformity/non-conformity, and ordinary income schedules beyond one annual `TaxProfile` value.
- [ ] Convert taxes into a ledger/liability workflow with payment timing instead of only allocating annual incremental tax back to sale months.
- [ ] Prefer yearly income/tax-lot ledgers with explicit tax settlement near
      realistic payment dates over trying to account for every tax effect at
      the moment income or a gain occurs. The settlement workflow should also
      model cash management: pay from cash when possible, otherwise invoke an
      explicit sale/financing policy to raise cash for the tax bill.
- [ ] Draft taxes and mortgages as first-class obligations/cash demands rather
      than arbitrary policy hooks. The accounting layer should emit obligations
      with due dates and causes; actor policy should decide how to fund them;
      simulator instructions should sell/borrow/use cash and resulting effects
      should settle or fail the obligation.
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
- [ ] Move property/location details out of result views. The property and
      location card describes scenario input, not a distribution or a selected
      trajectory. It should become part of shared scenario context, the left input
      pane, or a dedicated property/details view rather than living under
      distribution/trajectory results.
- [ ] Add explicit comparison views for deltas between two scenario
      distributions. The simulator should not bake a baseline/counterfactual
      into each rollout; a delta view should compare two real scenarios, either
      as the distribution of differences between samples from both
      distributions or as paired differences conditioned on the same underlying
      exogenous path.
- [ ] Continue migrating Augur UI controls to Mantine. Mantine is the chosen
      boring React component kit and now backs the app provider, result tabs, and
      result disclosure behavior. Migrate form controls, tables, buttons, input
      groups, and remaining disclosure widgets incrementally instead of adding
      more one-off local primitives.
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
- [ ] Add a top-level reporting toggle for nominal vs inflation-adjusted USD.
      Amounts, charts, tables, and summary metrics should make clear whether
      they are shown in nominal future dollars or real/inflation-adjusted
      dollars.
- [ ] Clean up redundant result-mode chips. Once a page-level header clearly
      says the user is looking at a distribution or a trajectory, individual
      child cards should not keep repeating `DISTRIBUTION`/`TRAJECTORY` badges
      unless the badge disambiguates mixed content.
- [ ] Normalize result table labels. Headers like `P50 net worth` next to
      `liquid worth` are inconsistent because the second value is also a
      percentile, and "liquid worth" is unclear wording. Prefer explicit,
      consistent labels such as `P50 liquid net worth` or whatever term the model
      settles on.
- [ ] Add hover-driven trajectory inspection to distribution charts. The fan
      chart should keep showing distribution envelopes and the central
      median/mean line by default, but hovering should reveal the selected
      rollout trajectory line without permanently rendering every rollout. While
      hovered, distribution-page summary numbers should switch where meaningful
      from aggregate values to that rollout's values, and time-sensitive values
      should use the hovered x-coordinate/month. The hover detail should also
      show the hovered trajectory's percentile at that point and, if practical,
      lightly highlight the complementary percentile trajectory/range.
- [ ] Restore richer distribution fan rendering. The current chart shows one
      envelope range plus one middle line, but the earlier private prototype had
      a fuller continuous-color fan showing more of the distribution. Consider
      bringing that back after the distribution/trajectory structure settles.
- [ ] Rework selected-path ledger detail toggles. The current chips above the
      ledger table are clunky UI sugar; a better shape would make aggregate
      columns expandable in place, similar to hidden columns in a spreadsheet:
      e.g. `House costs total` expands in place into tax, insurance, HOA, and
      maintenance subcolumns under the same table header.
- [ ] Key partner-equity reporting by partner actor or make it derivable from actor-keyed ledger entries. Aggregate scenario arrays are fine for charts but should not be the only public detail.
- [ ] Reconsider whether to reintroduce per-component partner contribution reporting for interest, property tax, insurance, HOA, and maintenance.
- [ ] Refresh `augur/SPEC.md` once policy execution, sale taxes, and one-rollout detail have stabilized.
