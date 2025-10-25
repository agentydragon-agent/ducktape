# rspcache proxy & admin

`rspcache` uses PostgreSQL to store responses, streaming frames, and client API keys.
The proxy continues to expose an OpenAI-compatible `/v1/responses` endpoint, while a separate admin server provides a live UI and key management.

## Environment

* `ADGN_RESP_DB_URL` – required PostgreSQL DSN (e.g. `postgresql+asyncpg://user:pass@localhost/rspcache`).
* `OPENAI_API_KEY` – default upstream key. Additional keys can be provided via `ADGN_OPENAI_KEYS` (`alias=key,...`) or `ADGN_OPENAI_KEY_<ALIAS>` env vars.
* `RSPCACHE_REQUIRE_API_KEY` – set to `true`/`1` to enforce client API tokens. When disabled, clients may still identify themselves with `sk-rsp_…` keys and requests will be attributed to them.

## Running

```bash
# Proxy (OpenAI-compatible endpoint)
rspcache --app proxy --host 127.0.0.1 --port 8000

# Admin surface (UI + management API)
rspcache --app admin --host 127.0.0.1 --port 8100
```

The admin server listens for PostgreSQL `LISTEN/NOTIFY` events to drive live updates. If the database role cannot use `LISTEN`, the UI falls back to manual refresh.

## Admin UI

The Vite/React dashboard lives in `adgn/rspcache_admin_ui`. Build assets into the Python package before deploying the admin server:

```bash
cd adgn/rspcache_admin_ui
npm install
# Allow direnv when prompted to expose the project PYTHONPATH
direnv allow
npm run build
# Optional: regenerate API types after backend changes.
# This also pulls the latest public OpenAI OpenAPI spec and emits TS types.
npm run typegen
```

Build output is written to `adgn/src/adgn/rspcache/admin_ui_dist/`. When that directory is absent, the admin server serves a placeholder message instead of the UI.

## Client API keys

Use the admin UI (or `POST /api/keys`) to mint tokens. Tokens are formatted like `sk-rsp_<random>`, hashed with per-key salt, and associated with an optional upstream key alias. Requests authenticated with these tokens appear in the timeline with their key name.

### Upstream key aliases

Each client key can target a named upstream OpenAI credential. The alias must match one of the entries loaded by the proxy:

- the default `OPENAI_API_KEY` becomes alias `default`
- `ADGN_OPENAI_KEYS="primary=sk-...,fallback=sk-..."` registers `primary` and `fallback`
- any `ADGN_OPENAI_KEY_<ALIAS>` environment variable is mapped after lowercasing `<ALIAS>`

When a request arrives with a client token, the proxy resolves the alias attached to that token, fetches the corresponding upstream key, and forwards the OpenAI call with those credentials. Rotating upstream keys is therefore a matter of updating the environment, while per-client aliases remain stable.

## Container build

A dedicated runtime image lives at `adgn/docker/rspcache/Dockerfile`. Build/push it after running the UI build:

```bash
cd adgn/rspcache_admin_ui
npm install
npm run build

cd ../../
docker build -t registry.k3s.agentydragon.com/rspcache:<tag> -f adgn/docker/rspcache/Dockerfile .
docker push registry.k3s.agentydragon.com/rspcache:<tag>
```

Deployments reference the image via the in-cluster registry; override the tag through Helm values if needed (`appImage.tag`).

## Kubernetes deployment (k3s)

The Helm chart under `k8s/helm/rspcache/` provisions:

- `rspcache-postgres` StatefulSet (10 Gi PVC) + Service
- `rspcache-proxy` Deployment/Service (load balanced `/v1/responses`)
- `rspcache-admin` Deployment/Service with Authentik-protected Ingress (`rspcache-admin.k3s.agentydragon.com`)

Before deploying, ensure the following secrets exist/are updated:

- Postgres credentials + `ADGN_RESP_DB_URL` (via the sealed secret data under `sealedSecrets.db` in `values.yaml`)
- Upstream OpenAI API key(s) (manually manage the `rspcache-openai` secret so live keys stay out of git)

Apply the stack:

```bash
cd k8s/helm/rspcache
helm dependency build
helm upgrade --install rspcache . --namespace rspcache --create-namespace --wait
```

Once the pods are healthy, port-forward or visit the Authentik-protected admin host to mint client tokens and monitor traffic.

## Key provisioning CLI

The `rspcache` Typer CLI now includes helper commands:

- `rspcache run --app proxy|admin` – launch the proxy/admin ASGI apps (used inside the container images).
- `rspcache keys mint --name ember` – create a client token via the admin API (supports `--alias`, `--notes`, `--admin-url`, `--bearer-token`).
- `rspcache keys list` / `rspcache keys revoke --name ember` – inspect or retire tokens.

Typical bootstrap flow:

1. Build/push the container and apply the k8s manifests.
2. `kubectl port-forward svc/rspcache-admin -n rspcache 8100:8100`
3. `python -m adgn.rspcache.cli keys mint --name ember`
4. Store the returned `sk-rsp_…` secret (SealedSecret) and point Ember at `http://rspcache.rspcache.svc.cluster.local:8000`.

Update the Ember chart values (`k8s/helm/ember/values.yaml`) with the new `api_base` config value and keep the `ember-rspcache-client` secret current so the agent authenticates through the proxy.
