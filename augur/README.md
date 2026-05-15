# augur

Probabilistic simulator of a multi-agent economic system. Given a
**scenario** — a bundle of agents, assets, liabilities, markets, and
policies — augur produces a distribution over trajectories of state by
sampling many rollouts.

This package contains the generic framework: typed entity model, vectorized
engine, real-estate / ownership / private-equity / tax math, market models,
FastAPI scaffolding, and React shell. User-side configuration (specific
properties, holdings, agent identities, fitted models, deployment) is
composed in downstream user repos via the `AugurConfig` schema in
<app/config.py>.

See <SPEC.md> for the entity taxonomy + per-rollout evaluation loop.

## Layout

| Directory       | Purpose                                                                                                                                                       |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `core/`         | Engine, typed entity / asset / policy / action / event model, real-estate math, scenario serialization, location regulation registry.                         |
| `model/`        | Market models (Wilkie, VAR, VECM, DCC-GARCH, bootstrap) + macro market-bundle provider + loaders for FRED/Yahoo/Zillow public-data CSVs.                      |
| `model/config/` | Public market-source CSVs (FRED series, Yahoo SPY adjusted-close, Zillow ZHVI) and market model config templates. Acquisition recipes in `source/SOURCES.md`. |
| `app/`          | `AugurConfig` schema, `AugurBackend`, `rollout_server`, catalog/bootstrap-payload assembly, React app + Tailwind bundle build.                                |
| `app/lib/`      | Frontend helpers: casing conversion, columnar table marshaling, scenario-set state, backend client.                                                           |

## Deployment integration

A user-side composer (e.g. gaffer-private's `serve.py`) builds an `AugurConfig`
from its private values, then either passes it directly to `run_server()` or
materializes it as YAML at `$AUGUR_CONFIG_PATH` for a ConfigMap-mounted
deployment. The framework's only contract with the deployment is the
`AugurConfig` Pydantic shape (see <app/config.py>).

For local public-fixture runs:

```bash
bazelisk run //augur/app:server -- \
  --config augur/app/testdata/config.yaml \
  --provider noop
```

`--provider noop` uses deterministic flat market paths for browser and API
smoke tests. Fitted macro models remain selectable with `--provider vecm`,
`--provider var`, etc.
