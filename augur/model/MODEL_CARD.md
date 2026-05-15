# Augur Market Model Card And Provenance

Last updated: 2026-05-15.

This is the minimal `ModelCard` for the current Augur market-model layer. It is
documentation-only: the IDs named here are target vocabulary unless noted as
already persisted in code.

## Scope

Current governed surface:

- Registered macro market models in `augur.model.markets.registry`:
  `var1_gaussian`, `wilkie_cascade`, `vecm`, `dcc_gjr_garch`, and
  `stationary_bootstrap`.
- `MacroMarketBundleProvider`, which fits one registered model on public market
  evidence and emits a `MarketBundle` for projection.
- Fixture providers such as flat/noop or simple stochastic providers are test
  and smoke-test aids. They are not calibrated market models.

The models are intended to generate exogenous market paths for Augur household
scenario projection. They are not intended to make standalone investment
recommendations, price securities, optimize portfolios, or certify tax,
mortgage, or legal outcomes.

## Intended Use

Use the current market models to:

- sample distributions of SP500 total-return proxy, home-value, rent, CPI, and
  mortgage-rate paths for personal economic scenarios;
- compare scenario variants over shared sampled market paths;
- inspect one sampled rollout as a trajectory detail view inside a broader
  distribution;
- exercise model-comparison diagnostics such as held-out, rolling-origin, and
  multi-step predictive log-density.

Do not use them as:

- a deterministic forecast of any market factor;
- a source of authoritative financial, tax, or legal advice;
- a compliance-grade valuation or risk engine;
- a guarantee that liquidity, borrowing, tax timing, or default behavior is
  fully modeled.

## Provenance Boundary

The current boundary should remain:

```text
Raw evidence -> evidence set -> calibration/fitting -> market bundle/provider -> projection
```

Today that means:

- Raw evidence is checked-in public source data under `augur/model/config/source`
  and is documented in `SOURCES.md`. Current sources include FRED, Yahoo Finance
  SPY adjusted-close data, and trimmed Zillow ZHVI city rows.
- Evidence loading happens in `load_evidence()`, which returns
  `HistoricalSeries` plus `MarketEvidence`. `MarketEvidence` carries aligned
  monthly log returns, marginal return evidence, calibrated path priors, current
  mortgage-rate evidence, and latest-observation metadata.
- Calibration/fitting happens when `MacroMarketBundleProvider` calls
  `market_model.fit(historical)`.
- Market-bundle generation happens when the fitted model's `simulate(...)`
  output is adapted into `MarketBundle` arrays plus `MarketBundleMetadata`.
- Projection happens in core over the sampled `MarketBundle`; core should not
  receive source-specific objects such as FRED, Yahoo, Zillow, or Manifold
  shapes.

Current persisted provenance is partial. `MarketBundleMetadata` carries model
id, random seed, rollout count, horizon, event stream ids, notes, and source
metadata such as provider label and latest-observation ids. It does not yet
carry a stable `EvidenceSetId`, `CalibrationArtifactId`, or full
`RunProvenance`.

## Current Evidence And Artifacts

Current evidence set, informally:

- factor names: `sp500`, configured home-value factors, `rent`, `inflation`;
- aligned monthly returns built from SPY adjusted close, Zillow home values,
  rent CPI, and headline CPI;
- supporting latest observations for FRED SP500 price, FRED mortgage 30-year
  rate, Case-Shiller SF, FHFA SF-Oakland-Berkeley, and other source series;
- data-derived market-path priors for each factor.

Current calibration artifact, informally:

- in-memory fitted parameters on one `MarketModel` instance;
- per-factor market-path prior calibration stored in `MarketEvidence`;
- no durable calibration bundle, hash, or artifact id yet.

Current generator run, informally:

- registry model label;
- model implementation and config from `MacroModelSpec`;
- `MarketRequest` horizon, rollout count, seed, and market model id;
- provider-level source metadata embedded in `MarketBundleMetadata`.

## Known Limitations

`KnownLimitation` entries for the current model layer:

- Evidence-set identity is not stable. File paths and latest-observation
  metadata exist, but there is no hash or versioned `EvidenceSetId`.
- Calibration identity is not stable. Fitted parameters are not persisted behind
  a `CalibrationArtifactId`.
- `rollout_index` is only an array coordinate. Reproducible path identity needs
  model version, evidence id, calibration id, generator settings, seed, path
  index, factor set, and event-stream identity.
- Mortgage rates are current evidence adapted into bundle paths; the macro
  provider currently keeps them constant over the sampled horizon.
- Private-equity marks and yearly tender opportunities are provider/runtime
  bundle concerns in the current generic provider, not fitted idiosyncratic
  company models.
- Historical public market data is limited and location coverage is narrow.
  Zillow rows are trimmed to the currently configured cities.
- Source refresh recency is not enforced by this document or by model metadata.
- Market models do not model agent feedback, strategic behavior, market impact,
  tax-law changes, credit availability, or general equilibrium dynamics.
- Validation status is not attached to `MarketBundleMetadata` as a first-class
  `ValidationReport`.

## Validation Gaps

Current validation exists as model tests, provider shape tests, and the metric
battery in `metrics_report.py`. The metric battery can compare registered models
on held-out, rolling-origin, and multi-step predictive log-density.

Still missing:

- a durable `ValidationReport` artifact with report id, evidence id,
  calibration id, model implementation version, score summary, and date;
- documented stress scenarios and sensitivity checks;
- tests proving output provenance changes when evidence, calibration, model
  implementation, or generator settings change;
- calibration-data coverage and recency checks enforced at runtime;
- household-outcome validation that connects market-model differences to
  projection-level differences;
- typed limitations or warnings attached to every result instead of only
  generic strings and notes.

## Vocabulary To Standardize Later

Use these names for future governance and provenance work:

| Term                    | Meaning                                                                    |
| ----------------------- | -------------------------------------------------------------------------- |
| `ModelCard`             | Intended use, non-goals, assumptions, limitations, and validation state.   |
| `ValidationReport`      | Backtests, predictive scores, invariants, stress, and sensitivity checks.  |
| `EvidenceSetId`         | Stable id for the cleaned/aligned evidence used for fitting.               |
| `CalibrationArtifactId` | Stable id for fitted parameters and calibration metadata.                  |
| `RunProvenance`         | Result-level model, data, calibration, generator, seed, code, and path id. |
| `KnownLimitation`       | Typed limitation or warning carried with the result.                       |

Related runtime vocabulary direction:

- An actor policy emits an `Instruction`.
- Simulator/accounting code validates the instruction and records the resulting
  `Effect`.
- Obligations such as taxes, mortgage servicing, liabilities, and scheduled
  payments should be first-class domain/accounting concepts, not arbitrary
  extension hooks.
