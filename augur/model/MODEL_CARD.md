# Augur Market Model Card And Provenance

Last updated: 2026-05-15.

This is the minimal `ModelCard` for the current Augur market-model layer.
`MacroMarketBundleProvider` attaches typed model-card, model-version, evidence,
calibration, scenario-generator, exogenous-path-set, validation-report, and
known-limitation identity metadata to `MarketBundleMetadata`. Those identities
are stable for the same checked-in public evidence and model inputs, but
evidence, calibration, and validation are still runtime-derived metadata rather
than durable persisted artifacts.

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
id, model-card id, model-version id, typed `EvidenceSet`, `CalibrationRun`,
`CalibrationArtifact`, `ScenarioGeneratorRun`, `ExogenousPathSet`,
`ValidationReport`, and `KnownLimitation` payloads, plus seed, rollout count,
horizon, event stream ids, notes, provider label, and latest-observation ids.
It does not yet persist evidence/calibration/validation artifacts outside the
run payload, so these identities are not archival proof on their own.

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
- a runtime-derived calibration run/artifact identity in
  `MarketBundleMetadata`;
- no durable calibration bundle or persisted fitted-parameter artifact yet.

Current generator run, informally:

- registry model label;
- model implementation and config from `MacroModelSpec`;
- `MarketRequest` horizon, rollout count, seed, and market model id;
- model-card/version, evidence, calibration, scenario-generator,
  validation-report, and known-limitation identity in `MarketBundleMetadata`;
- provider-level source metadata embedded in `MarketBundleMetadata`.

## Known Limitations

`KnownLimitation` entries for the current model layer:

- Evidence-set identity is runtime-derived from the loaded public market
  evidence metadata. It is stable for the same checked-in inputs, but there is
  no persisted evidence artifact yet.
- Calibration identity is runtime-derived from model/evidence/factor identity.
  Fitted parameters are not persisted behind a durable
  `CalibrationArtifactId`.
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
- Validation status is attached as a placeholder `ValidationReport`, not a
  decision-grade report artifact.

## Validation Gaps

Current validation exists as model tests, provider shape tests, and the metric
battery in `metrics_report.py`. The metric battery can compare registered models
on held-out, rolling-origin, and multi-step predictive log-density.

Still missing:

- a durable `ValidationReport` artifact with score summary, report date,
  validation window, and acceptance criteria instead of the current
  `not_available` placeholder;
- documented stress scenarios and sensitivity checks;
- broader tests proving output provenance changes when persisted evidence,
  calibration, model implementation, or generator settings change;
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
