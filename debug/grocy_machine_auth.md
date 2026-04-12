# Grocy Machine Auth Investigation

**Goal**: Agents (claude-sandbox, openclaw-sandbox) can call the Grocy API at
`grocy.allegedly.works` with a bearer token, alongside existing human OIDC SSO.

## Architecture

```
Human browser → grocy.allegedly.works → Authentik proxy outpost → grocy pod
                                         ↓ sets X-authentik-username header
Agent (bearer JWT) → grocy.allegedly.works → Authentik proxy outpost → grocy pod
```

Grocy uses `ReverseProxyAuthMiddleware` trusting `X-authentik-username` from the proxy
outpost. No second API key needed — any authenticated request through the proxy is trusted.

## What We Tried

### 1. Authentik API token as Bearer (failed)

The `agent-bearer-token` K8s secret contains an Authentik **API key** (intent=api). The
proxy outpost doesn't recognize API tokens — it expects either a browser session cookie or
a JWT issued by the provider.

### 2. Separate OAuth2 provider with client_credentials (failed)

Created `grocy-machine` OAuth2 provider in TF, successfully got a JWT via
`client_credentials` grant. But the proxy outpost **rejects JWTs from a different
provider** — it validates that the JWT's `azp` claim matches its own `client_id`.

Error: `"Due to 'Receive header authentication' being set, no redirect is performed."`

**Key learning**: Cross-provider JWTs don't work with proxy outposts. The outpost only
accepts JWTs from its own provider.

### 3. Move proxy provider to TF, use client_credentials on it (current — partial)

Since both human and machine auth must go through the same provider, moved the grocy proxy
provider from blueprint to the `agent-machine-access` TF module.

**Problem**: `authentik_provider_proxy` in the Authentik TF provider exports `client_id`
(computed) but **not** `client_secret`. The underlying Authentik API does return
`client_secret` on proxy providers (they inherit from OAuth2Provider), but the TF resource
schema doesn't expose it.

**Current state** (as of 2026-04-12):

- Blueprint `grocy-sso.yaml` removed, provider/app/bindings deleted from Authentik via API
- TF has `authentik_provider_proxy.grocy` but the plan fails on `.client_secret`
- Embedded outpost blueprint still references `!Find [authentik_providers_proxy.proxyprovider, [name, grocy]]`

## client_credentials Flow Details

- Token endpoint: `POST https://auth.allegedly.works/application/o/token/`
- Parameters: `grant_type=client_credentials&client_id=<id>&client_secret=<secret>&scope=openid`
- Authentik auto-creates a service account `ak-<provider-slug>-client_credentials`
- The auto-created user must pass the application's policy engine (needs a binding)
- Pre-creating the user in TF works — Authentik uses the existing user on first call

## Open Options

| #   | Approach                                                        | Pros                            | Cons                                              |
| --- | --------------------------------------------------------------- | ------------------------------- | ------------------------------------------------- |
| A   | `data "http"` to read client_secret from Authentik API          | Works, TF manages everything    | Hacky, fragile, token in state                    |
| B   | Blueprint for proxy provider, `client_secret: !Env` with SOPS   | Clean separation                | SOPS secret + env mount, dual management          |
| C   | PR the Authentik TF provider to export `client_secret`          | Clean, permanent                | Upstream dependency, time                         |
| D   | Skip proxy — direct network access to grocy pod + Grocy API key | Simple, no Authentik complexity | Two auth paths, CiliumNetworkPolicy, API key mgmt |
| E   | `random_password` in TF, share to blueprint via SOPS/env        | TF is source of truth           | Still need SOPS pipeline                          |

## Related Files

- `cluster/terraform/gitops/agent-machine-access/main.tf` — TF module (current owner)
- `cluster/k8s/grocy/settingoverrides.yaml` — Grocy reverse proxy auth config
- `cluster/k8s/authentik/app/blueprints/embedded-outpost.yaml` — outpost provider list
- `cluster/k8s/authentik/proxy-routes/grocy-httproute.yaml` — Gateway API route
