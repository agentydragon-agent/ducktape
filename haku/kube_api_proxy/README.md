# Haku Kubernetes API proxy

This is the first, deliberately narrow implementation of the inline authorization
proxy tracked by [#4428](https://github.com/agentydragon/ducktape/issues/4428).
It is a separate Go binary: Haku Console remains the temporary-grant authority,
while the proxy is the only Kubernetes request path available to an Agent.

```text
Agent --Haku bearer--> kube API proxy
                       |  classify Kubernetes API path and verb
                       |  POST bearer + attributes + minimal PolicyRule
                       v
                    Haku Console
                       |  allowed + lease expiry
                       v
                    kube-apiserver <-- proxy-held in-cluster credential
```

The structural property is fail-closed expiry. The proxy asks Console before
every request and bounds the forwarded request context by both the configured
request timeout and the returned lease expiry. If Console or the grant state is
unavailable, no request is sent to Kubernetes. Unlike a temporary RoleBinding,
there is no independent native-RBAC object which can remain usable because an
expiry reaper stopped.

## Implemented

- Kubernetes apiserver's `RequestInfoFactory` maps method/path/query to API
  group, resource, subresource, namespace, object name and verb. Depending on
  the real implementation avoids maintaining a security-sensitive parallel
  parser and keeps selector behavior aligned with kube-apiserver.
- The proxy derives the minimal equivalent resource or non-resource `PolicyRule`
  and sends it to Console with the original bearer in the `Authorization`
  header. The credential is never copied into JSON or logs.
- It requires HTTPS for the Console authorization hop unless an explicit
  development-only override is set, and never follows redirects with the bearer.
- If allowed, only ordinary representation/cache headers are forwarded. Caller
  authorization, cookies, API keys, proxy metadata and Kubernetes
  identity/impersonation headers are removed; the in-cluster transport supplies
  the upstream credential.
- Authority failures, malformed decisions, denials and already-expired grants
  all fail closed.
- Request bodies, authorization calls and Kubernetes requests are bounded.
- `watch`, log following, resource proxying, upgrades, pod `exec`, `attach` and
  `portforward` return `501` before authorization or forwarding.
- Console exposes the typed endpoint contract at
  `POST /api/internal/kubernetes/authorize`, but the current stub always returns
  `501`. The component therefore cannot authorize live traffic yet.

## Console authorization contract

Example request:

```json
{
  "attributes": {
    "resource_request": true,
    "verb": "get",
    "api_version": "v1",
    "namespace": "demo",
    "resource": "pods",
    "subresource": "log",
    "name": "web",
    "path": "/api/v1/namespaces/demo/pods/web/log"
  },
  "required_rules": [
    {
      "api_groups": [""],
      "resources": ["pods/log"],
      "verbs": ["get"],
      "resource_names": ["web"]
    }
  ]
}
```

The proxy forwards the Agent's original `Authorization: Bearer ...` header over
HTTPS. A successful response is:

```json
{
  "allowed": true,
  "lease_id": "opaque-audit-id",
  "expires_at": "2026-08-19T20:00:00Z"
}
```

Every allowed decision must contain a non-empty `lease_id` and `expires_at`;
the proxy fails closed on an incomplete response. Console should return
`allowed: false` for a valid identity without a covering lease, `401` for an
invalid identity, and a non-2xx response when grant state cannot be read.

## Configuration

| Environment                          |            Default | Meaning                                      |
| ------------------------------------ | -----------------: | -------------------------------------------- |
| `HAKU_KUBE_AUTHORIZATION_URL`        |           required | Absolute HTTPS Console authorization URL     |
| `HAKU_KUBE_ALLOW_INSECURE_AUTHORITY` |            `false` | Development/test-only plain-HTTP opt-in      |
| `HAKU_KUBE_LISTEN_ADDRESS`           |            `:8080` | Proxy listen address                         |
| `HAKU_KUBE_AUTHORIZATION_TIMEOUT`    |               `3s` | Maximum Console decision latency             |
| `HAKU_KUBE_REQUEST_TIMEOUT`          |              `30s` | Maximum ordinary Kubernetes request lifetime |
| `HAKU_KUBE_MAX_REQUEST_BYTES`        |         `10485760` | Maximum request body size                    |
| `HAKU_KUBE_SERVICEACCOUNT_DIRECTORY` | Kubernetes default | Projected CA and token directory             |
| `KUBERNETES_SERVICE_HOST`            |           required | In-cluster Kubernetes API host               |
| `KUBERNETES_SERVICE_PORT_HTTPS`      |           required | In-cluster API port (`..._PORT` fallback)    |

The Kubernetes API address, CA and rotating projected bearer are loaded from
Kubernetes' standard in-cluster environment and ServiceAccount files. This is
the narrow in-cluster information needed by the proxy. Environment variables
are decoded and validated together with `github.com/caarlos0/env/v11`; malformed
configured durations, booleans and sizes stop startup rather than silently
falling back to defaults.

## Deployment status and TODOs

The image is built and tested by `push-images.yml`, but **no Deployment, RBAC or
Agent routing is added yet**. Deploying a proxy with a broad upstream identity
before Console can authorize grants and before the direct API path is closed
would create authority without enforcement.

Before production deployment:

- TODO(#4428): implement Console Agent-token verification and temporary-grant
  rule matching; require and return the matching lease expiry.
- TODO(#4428): define the proxy ServiceAccount's reviewed maximum capability.
  Haku grants can only narrow that capability.
- TODO(#4428): force Agent Kubernetes traffic through the proxy with network
  policy/credential substitution and prove there is no direct API-server path.
- TODO(#4428): add per-agent/lease audit correlation and Prometheus metrics.
- TODO(#4428): decide whether to implement Kubernetes `watch` and following
  logs. Any implementation must terminate active streams at grant expiry.
- TODO(#4428): treat `exec`, `attach`, `portforward`, upgrades and resource
  proxying as separate, security-reviewed protocol increments rather than
  silently passing them through the ordinary HTTP handler.
- TODO(#4428): consider discovery-response caching only if it preserves the
  fail-closed authority model and never extends a grant lifetime.
