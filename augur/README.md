# augur

Probabilistic simulator of a multi-agent economic system. Given a
**scenario** — a bundle of agents, assets, liabilities, markets, and
policies — augur produces a distribution over trajectories of state by
sampling many rollouts.

This package contains the generic framework: typed entity model, vectorized
engine, real-estate / ownership / private-equity / tax math, market models,
FastAPI scaffolding, and React shell. User-side configuration (specific
properties, holdings, agent identities, fitted models, deployment) is
composed in downstream user repos via the `Config` schema in
<api/config.py>.

See <SPEC.md> for the entity taxonomy + per-rollout evaluation loop.

## Planning boundary

Public, generic Augur work is tracked in this repo: simulator contracts,
policy/runtime/schema shape, tax/accounting behavior, market-provider
interfaces, public app framework, and generic catalog/storage contracts for
properties, locations, and property assets.

Downstream user repos track private composition: specific agent identities,
holdings, property shortlists, media, deployment manifests, and
company-/person-specific modeling assumptions.

## Layout

| Directory      | Purpose                                                                                                                                 |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `model/`       | Runtime market-provider configs, sim-facing market model APIs, simple fixture provider, and the active VECM provider.                   |
| `model/train/` | Offline market training, public-data loading, evaluation/metric tooling, and training config templates.                                 |
| `data/market/` | Public market-source blobs (FRED series, Yahoo SPY adjusted-close, Zillow ZHVI). Acquisition recipes in `source/SOURCES.md`.            |
| `api/`         | `Config` schema, wire request/response shapes, `Backend`, HTTP server, catalog/bootstrap assembly, OpenAPI schema export.               |
| `sim/`         | Deterministic trajectory evaluation over typed scenarios and sampled exogenous market/state bundles.                                    |
| `frontend/`    | React app + Tailwind bundle build, frontend helpers (casing conversion, columnar table marshaling, scenario-set state, backend client). |

## Deployment integration

The production server is API-only: `//augur/api:server` reads a `Config`
from `--config`, `$AUGUR_CONFIG_PATH`, or `/etc/augur/config.yaml`, then serves
the `/api/*` routes and `/healthz`. Downstream deployments should serve the
React bundle and private property assets separately, e.g. from an nginx
sidecar.

Property media stays outside the generic frontend bundle. Deployments publish
images through their own static host or CDN, then declare stable
`property_source.property_assets` entries in config. Each entry binds a
property ID to a deployment-owned asset ID and either an explicit public
`image_url` or the shared `property_source.asset_base_url/{asset_id}` URL.

For local public-fixture development, use the combined dev-only wrapper:

```bash
bazelisk run //augur:dev
```

The public fixture config uses the lightweight `simple` market provider. Fitted
macro models are selected in `Config.market_provider` YAML, e.g. `type:
vecm` with a trained blob path.
