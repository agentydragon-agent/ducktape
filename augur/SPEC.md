# Augur — Specification

Augur is a probabilistic simulator of a multi-agent economic system. Given a
**scenario** — a bundle of agents, assets, liabilities, external series, and policies —
it produces a distribution over trajectories of state (net worth, cash,
ownership shares, taxes, liquidity events, …) by sampling many rollouts.

This document specifies the entity model, the per-rollout evaluation loop, and
the user-visible guarantees. Implementation details live in code; SPEC.md only
records what an outside observer can rely on.

## Architecture Boundary

Augur separates exogenous path generation from path evaluation. `augur/model` owns
evidence ingestion, calibration, fitted-model identity, stochastic sampling,
and exogenous-model provenance. `augur/sim` evaluates scenario sets over already
materialized exogenous trajectories. `augur/api` adapts product requests into
model + simulation inputs and shapes responses for the frontend.

Compatibility adapters may exist during migration, but the durable contract is
the `model -> sim -> api -> frontend` boundary rather than the legacy wire
shapes.

The current product-language API surface is intentionally narrow. A
`ScenarioKey` describes one cash-spend scenario without randomness, and product
view requests add explicit rollout seeds. The product route also includes
deployment-configured public-security lots as passive mark-to-market holdings;
those holdings are config facts, not frontend knobs. The product funding policy
can list supported sellable buckets in order, currently `public_securities`,
and can request the simulator's cash-buffer rule: when post-obligation cash is
below a dollar trigger, sell a fixed dollar amount from that order. The
product portfolio route returns the configured initial cash and public-security
positions, including tax lots, as a read-only product surface. The metric-fan
route returns compact requested percentiles; the rollout route returns one full
per-seed table plus product-readable event rows for that selected rollout, such
as public-security sales, monthly expense settlements, and rollout failures.
Missing rollouts are transparently sampled and simulated into an in-memory
server cache. Product concepts that are neither in the request type nor
deployment config are not supported by the product endpoint yet.

## Model

### Entities

| Entity           | What it is                                                                                                                                                                                                    | Examples                                                                                                                             |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `Agent`          | An economic actor with state (cash, holdings, liabilities, ownership shares) and a set of policies.                                                                                                           | a primary owner, a lender, a tenant                                                                                                  |
| `Asset`          | Something an agent owns that has value. Discriminated subtype determines valuation and liquidity model.                                                                                                       | a `LiquidSecurity` tracking SP500, a `PrivateEquity` holding, a `RealEstate` property                                                |
| `Liability`      | A debt an agent owes, with an amortization schedule.                                                                                                                                                          | a mortgage on a property                                                                                                             |
| `ExternalSeries` | An exogenous trajectory source generated outside the simulator and consumed as per-rollout paths.                                                                                                             | SP500 total return, local home-price paths, local rent paths, CPI, mortgage rate, per-`PrivateEquity` price + liquidity-event stream |
| `Policy`         | A typed rule attached to an agent: `(state, external_series, time) → list[Instruction]`. Composable; an agent can hold any number.                                                                            | liquidity-reserve maintenance, max-concentration rebalancing, mortgage payment, rental management                                    |
| `Instruction`    | A policy-emitted intent (e.g. "sell N units of asset X"). Validated and applied by the engine into an `Effect`.                                                                                               | `SellInstruction`, `BorrowInstruction`                                                                                               |
| `Effect`         | A realized state mutation after validation. The trace records effects, not the raw instructions.                                                                                                              | `SellSp500Effect`, `SellCryptoEffect`, `SellPrivateEquityEffect`, `SettlePropertySaleEffect`                                         |
| `Obligation`     | A first-class cash demand on an actor (tax, mortgage, property tax, HOA, insurance, maintenance, outside rent, special assessment, estimated tax). Settled via the funding-policy chain or fails the rollout. | annual tax due at year-end, monthly property tax                                                                                     |
| `Scenario`       | A bundle: agents + assets + liabilities + initial state + policies + required external series + horizon.                                                                                                      | "primary buys property X and rents rooms while living there"                                                                         |

### Asset subtypes

| Subtype          | Valuation                                                                                                             | Liquidity                                                                                 |
| ---------------- | --------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `Cash`           | Face value.                                                                                                           | Always liquid.                                                                            |
| `LiquidSecurity` | Tracks an external-series multiplier (e.g. SP500 total-return proxy).                                                 | Always sellable.                                                                          |
| `RealEstate`     | Tracks location-bound home-value and rent paths; has property tax / insurance / HOA / maintenance / depreciation.     | Sellable on demand; sale incurs closing costs, capital-gains tax, depreciation recapture. |
| `PrivateEquity`  | Tracks an idiosyncratic per-asset price path and protocol control series supplied by the exogenous trajectory bundle. | Saleability is driven by exogenous PE protocol series plus the owner's PE tender policy.  |

### Private-Equity Protocol

The model layer must emit a complete per-issuer protocol bundle whenever a
scenario holds `private_equity:<issuer>`:

| Series / Event                                        | Meaning                                                                                                                                                                                                                          |
| ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `private_equity:<issuer>`                             | Per-unit mark / sale price path.                                                                                                                                                                                                 |
| `private_equity_sale_opportunity:<issuer>`            | Discrete voluntary tender event stream. Public-market saleability is represented by the `public_market` regime.                                                                                                                  |
| Typed PE protocol frame                               | Integer-coded sim-facing issuer regime and event marker: private operating, public market, acquired, collapsed; tender, admin mark update, public-market open, acquisition cashout, legal impairment, forced recovery, collapse. |
| `private_equity_sale_capacity_fraction:<issuer>`      | Fraction of currently held units sellable through a voluntary tender/public-market opportunity.                                                                                                                                  |
| `private_equity_eligible_fraction:<issuer>`           | Fraction of currently held units eligible for voluntary sale.                                                                                                                                                                    |
| `private_equity_forced_sale_fraction:<issuer>`        | Fraction of currently held units forcibly sold in that month.                                                                                                                                                                    |
| `private_equity_liquidity_blocked:<issuer>`           | Boolean-ish level; values `>= 0.5` block voluntary tender/public-market sales.                                                                                                                                                   |
| `private_equity_forced_recovery_cashout_usd:<issuer>` | Dollar recovery paid for the remaining position in that month.                                                                                                                                                                   |

The simulator hard-fails if any required PE protocol series is absent. It
validates integer code series, finite marks, and fraction bounds before applying
sales. Voluntary sales are policy-mediated: the owner's PE tender policy sets a
liquid-net-worth floor, while the exogenous protocol determines whether a tender
or public-market sale is possible and how much is sellable. Forced sale and
forced-recovery cashout series bypass the voluntary floor and apply directly to
the remaining position.

### Policy types

Policies are first-class typed objects. The current policy vocabulary:

| Policy                    | Inputs                                                       | Action(s) emitted                                                                                          |
| ------------------------- | ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| `PrivateEquitySalePolicy` | Sale-rule configuration for voluntary PE sale opportunities. | Sell `PrivateEquity` when an automatic rule intersects with an exogenous tender/public-market opportunity. |
| `MortgagePaymentPolicy`   | Mortgage liability, payer agent, cash source.                | `PayLiability` from owner cash flow.                                                                       |
| `RentalUsePolicy`         | Property, mode (occupied / rented / partial), tenant pool.   | `OccupyProperty` / `RentProperty`.                                                                         |
| `OccupancyDecisionPolicy` | Property, move-out month, alternative housing config.        | Transitions occupation phase; potentially triggers `RentProperty`.                                         |

Policies do not encode actor identities in their type names — actor IDs are
data in scenario configuration, not type-system distinctions.

Partner/co-owner contribution agreements are intentionally not part of the
current product contract. The previous frontend/backend actor-policy path was
removed until the simulator has a tested, explicit agreement model.

### Obligation Lifecycle

Current required obligations are due immediately in the month they fire. The
engine debits the configured cash account, uses the agent's configured
liquidation policy to sell assets if the cash account goes negative, and marks
the rollout failed if the account cannot be brought back to non-negative cash.
After failure, state-backed value metrics for that rollout are frozen at zero
for the rest of the simulation; the failed status and first failure month remain
machine-readable. It does not model partial payments, grace periods,
delinquency balances, recovery/cure, or underpayment penalties.

### Effect types

`Effect` rows are the user-visible trace surface for realized sales. System-emitted accounting moves (mortgage settlement, monthly spend, property-cost obligations) are derivable from ledger postings, balance snapshots, and accounting details — the canonical detail surface — and are not separate effect rows.

| Effect                     | What it records                                                                             |
| -------------------------- | ------------------------------------------------------------------------------------------- |
| `SellSp500Effect`          | Sale of generic SP500 stock: units, basis, realized gain, tax allocation.                   |
| `SellCryptoEffect`         | Sale of crypto holding: units, basis, realized gain, tax allocation.                        |
| `SellPrivateEquityEffect`  | Sale of private-equity holding (tender, public-market post-lockup, or forced acquisition).  |
| `SettlePropertySaleEffect` | Property disposition: gross proceeds, debt payoff, closing costs, capital-gains allocation. |

Discrete one-time events the engine also records (not produced by policies but
by exogenous trajectory inputs / scenario configuration):

| Event            | Source                                     | Effect                                                                                           |
| ---------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| `LiquidityEvent` | Exogenous opportunity for `PrivateEquity`. | Window during which `SellAsset` on that equity is permitted at the event's `price_usd_per_unit`. |
| `RegimeChange`   | Exogenous regime transition (future).      | Mutates the asset's `LiquidityRegime` variant.                                                   |

## Per-rollout evaluation loop

For one rollout, given a `Scenario` and an exogenous trajectory bundle:

1. The selected exogenous trajectory provides shared macro paths plus
   per-asset price paths, sellability masks, and opportunity streams.
2. State is initialized from the scenario: each agent's cash, holdings,
   liabilities, ownership shares.
3. For each month `t` in `[0, horizon_months]`:
   a. Apply scheduled events for the month (regime changes, lockup expiry,
   liquidity events open).
   b. Mark-to-market: update asset values using external series.
   c. Accrue: rent income, expenses, depreciation, mortgage interest,
   property tax, insurance.
   d. Each agent's policies produce actions in deterministic order.
   e. Engine validates + applies actions; ledger records them.
   f. Record the per-month row (one row per agent + portfolio-wide aggregates).
4. At horizon, record the terminal row. A property is sold only if the
   scenario includes a `PropertySaleEvent`; otherwise it remains owned and
   contributes home equity rather than sale cash.

## Outputs

The product API exposes two response shapes against a `ScenarioKey`:

- `MetricFanResponse` — one user-selected metric over the horizon as a
  percentile fan across the requested rollout seeds, plus per-rollout
  summaries (terminal metrics, sort rank, pass/fail) keyed by seed.
- `RolloutResponse` — full per-month metric frame and typed event log for
  one selected rollout seed.

Both carry an `exogenous_model_id` so the caller can identify which
trajectory bundle the response was sampled against. Failed rollouts zero
their downstream metrics from the failure month onward.

## What augur does not do (non-goals)

- It is not a tax compliance engine. Tax computations are approximations
  parameterized at the scenario level (marginal rates, cap-gains rates,
  depreciation rules). They are not authoritative.
- It is not a real-time pricing engine. Exogenous paths are trajectories
  generated outside the simulator; intra-month dynamics are not modeled.
- It is not a portfolio optimizer. Policies are user-specified rules; augur
  reports their consequences, not what optimal policies would be.
- It does not model agent learning or strategic interaction (game-theoretic
  best response). Each agent's policy is fixed by scenario configuration.
- It currently assumes FIFO lot selection for sale-basis accounting where a
  simulator slice needs concrete cost-basis math. HIFO, specific-identification,
  and average-cost lot selection are future extensions.
