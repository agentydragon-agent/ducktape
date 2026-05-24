# Augur Exogenous Model Card And Provenance

Last updated: 2026-05-20.

This is the minimal `ModelCard` for the current Augur exogenous-model layer.
The active trained `vecm` provider attaches typed model-version, evidence,
calibration, scenario-generator, and exogenous-path-set identity metadata to
`SampledExogenousBundle.metadata`. Those identities are stable for the same
checked-in public evidence and model inputs, but evidence and calibration are
still runtime-derived metadata rather than durable persisted artifacts.

## Scope

Current governed surface:

- Active trained exogenous model: `vecm`.
- `VecmModel` (NumPyro), which loads a trained VECM blob and samples native
  `SampledExogenousBundle` levels/events.
- Simple stochastic providers are runtime placeholders. Deterministic flat
  exogenous paths are test-only fixtures. Neither is a calibrated exogenous model.

The models are intended to generate exogenous paths for Augur household
scenario projection. They are not intended to make standalone investment
recommendations, price securities, optimize portfolios, or certify tax,
mortgage, or legal outcomes.

## Intended Use

Use the current exogenous models to:

- sample distributions of SP500 total-return proxy, home-value, rent, CPI, and
  mortgage-rate paths for personal economic scenarios;
- compare scenario variants over shared sampled exogenous paths;
- inspect one sampled rollout as a trajectory detail view inside a broader
  distribution;
- exercise model-comparison diagnostics such as held-out, rolling-origin, and
  multi-step predictive log-density.

Do not use them as:

- a deterministic forecast of any exogenous factor;
- a source of authoritative financial, tax, or legal advice;
- a compliance-grade valuation or risk engine;
- a guarantee that liquidity, borrowing, tax timing, or default behavior is
  fully modeled.

## Provenance Boundary

The current boundary should remain:

```text
Raw evidence -> evidence set -> calibration/fitting -> sampled exogenous bundle -> projection
```

Today that means:

- Raw evidence is checked-in public source data under `augur/data`
  and is documented in `augur/data/SOURCES.md`. Current sources
  include FRED, Yahoo Finance SPY adjusted-close data, and trimmed Zillow ZHVI
  city rows.
- Evidence loading happens in `load_evidence()`, which returns
  `HistoricalSeries` plus `ExogenousEvidence`. `ExogenousEvidence` carries aligned
  monthly log returns, marginal return evidence, calibrated path priors, current
  mortgage-rate evidence, and latest-observation metadata.
- Calibration/fitting happens offline through `augur.fit`; runtime
  config points at the persisted trained VECM blob.
- Sampled-bundle generation happens when `VecmModel.sample(request)` rolls
  the fitted recurrence forward and emits native sampled levels/events.
- Projection happens in `augur/sim`; the simulator should not receive
  source-specific objects such as FRED, Yahoo, Zillow, or Manifold shapes.

Current persisted provenance is partial. `SampledExogenousBundle.metadata` carries
model-version, evidence-set, calibration-artifact, scenario-generator,
event-stream, and provider-label ids. It does not yet persist typed
evidence/calibration artifacts outside the run payload, so these identities are
not archival proof on their own.

## Current Evidence And Artifacts

Current evidence set, informally:

- factor names: `sp500`, configured home-value factors, `rent`, `inflation`;
- aligned monthly returns built from SPY adjusted close, Zillow home values,
  rent CPI, and headline CPI;
- supporting latest observations for FRED SP500 price, FRED mortgage 30-year
  rate, Case-Shiller SF, FHFA SF-Oakland-Berkeley, and other source series;
- data-derived exogenous-path priors for each factor.

Current calibration artifact, informally:

- in-memory fitted parameters on one `VecmModel` instance;
- per-factor exogenous-path prior calibration stored in `ExogenousEvidence`;
- a runtime-derived calibration run/artifact identity in
  `SampledExogenousBundle.metadata`;
- no durable calibration bundle or persisted fitted-parameter artifact yet.

Current generator run, informally:

- model label;
- model implementation and config from `VecmModel(VecmConfig(k_ar_diff=1, coint_rank=1))`;
- `SamplingRequest` horizon, rollout count, seed, and exogenous model id;
- model-version, evidence, calibration, and scenario-generator identity in
  `SampledExogenousBundle.metadata`;
- provider-level label metadata embedded in `SampledExogenousBundle.metadata`.

## Known Limitations

- Evidence-set identity is runtime-derived from the loaded public market
  evidence metadata. It is stable for the same checked-in inputs, but there is
  no persisted evidence artifact yet.
- Calibration identity is runtime-derived from model/evidence/factor identity.
  Fitted parameters are not persisted behind a durable
  `CalibrationArtifactId`.
- `rollout_index` is only an array coordinate. Reproducible path identity needs
  model version, evidence id, calibration id, generator settings, seed, path
  index, factor set, and event-stream identity.
- Mortgage rates are current evidence adapted into sampled paths; they are
  currently kept constant over the sampled horizon.
- Private-equity marks and yearly tender opportunities are current model/runtime
  bundle concerns in the VECM wrapper, not fitted idiosyncratic company models.
- Historical public market data is limited and location coverage is narrow.
  Zillow rows are trimmed to the currently configured cities.
- Source refresh recency is not enforced by this document or by model metadata.
- Exogenous models do not model agent feedback, strategic behavior, market impact,
  tax-law changes, credit availability, or general equilibrium dynamics.

## Validation Gaps

Current validation exists as model tests, provider shape tests, and the metric
battery in `augur/fit/metrics_report.py`. The metric battery scores
the active trained model on held-out, rolling-origin, and multi-step predictive
log-density.

Still missing:

- a durable `ValidationReport` artifact with score summary, report date,
  validation window, and acceptance criteria;
- documented stress scenarios and sensitivity checks;
- broader tests proving output provenance changes when persisted evidence,
  calibration, model implementation, or generator settings change;
- calibration-data coverage and recency checks enforced at runtime;
- household-outcome validation that connects exogenous-model differences to
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

Related runtime vocabulary direction:

- An actor policy emits an `Instruction`.
- Simulator/accounting code validates the instruction and records the resulting
  `Effect`.
- Obligations such as taxes, mortgage servicing, liabilities, and scheduled
  payments should be first-class domain/accounting concepts, not arbitrary
  extension hooks.
