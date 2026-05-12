# augur

Probabilistic simulator of a multi-agent economic system. Given a
**scenario** — a bundle of agents, assets, liabilities, markets, and
policies — augur produces a distribution over trajectories of state by
sampling many rollouts.

This package contains the generic core: typed entity model, vectorized
engine, real-estate / ownership / private-equity / tax math, scenario
schema. User-side configuration (specific properties, holdings,
agent identities, fitted models, deployment) is composed in downstream
user repos.

See <core/SPEC.md> in upstream consumers for the full entity taxonomy.

## Layout

| Directory | Purpose                                                                                                                              |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `core/`   | Engine, typed entity / asset / policy / action / event model, real-estate math, scenario serialization, location regulation registry |

## Status

Phase 2 of the augur split (see upstream gaffer-private:plans/augur_split.md).
`core/` extracted from gaffer; subsequent moves (`model/markets/`, app
framework, public market data) are planned but not yet here.
