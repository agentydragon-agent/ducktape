# Tofu-controller silent state divergence (2026-04-25)

## Incident

The `claude-jwt-rotation` CronJob failed with HTTP 400 `invalid_grant` when
requesting a JWT via `client_credentials` grant from Authentik. Investigation
revealed that the `authentik_application` objects for all three kubectl MCP
providers (`kubectl-passthrough-mcp`, `kubectl-sandbox-mcp`,
`kubectl-sandbox-client-credentials`) were missing from Authentik, despite the
corresponding OAuth2 **providers** existing. Without an application binding, Authentik
rejects token requests for the client_id.

The tofu-controller's `agent-machine-access` Terraform resource reported
"No drift" — its state file said the applications existed, and it never checked.

## Root cause

1. **Authentik DB data loss**: At some point after the April 11 bootstrap, the
   Authentik CNPG database lost the `authentik_application` rows created by
   Terraform. The most likely cause is a PVC wipe/recreate during a prior
   bootstrap cycle or maintenance operation. The OAuth2 providers survived
   (possibly recreated by a different mechanism or partially restored), but the
   applications did not.

2. **`refreshBeforeApply: false` (default)**: All 15 tofu-controller `Terraform`
   custom resources used the default setting, which skips `tofu refresh` before
   planning. The controller trusts the state file unconditionally — if state says
   a resource exists, the plan shows no drift, and no apply happens. This is a
   silent failure mode: reality can diverge from state indefinitely without any
   alert or corrective action.

## Detection

- The JWT rotation CronJob failed with `curl: (22) ... 400`.
- Loki logs (via `promtail`) preserved the pod output even after the
  `backoffLimit: 0` Job deleted the pod.
- Manual Authentik API query (`/api/v3/core/applications/`) confirmed the
  applications were missing while providers existed.

## Fix

1. **Enable `refreshBeforeApply: true`** on all 15 tofu-controller Terraform CRs.
   This adds a `tofu refresh` before each plan cycle, so the controller discovers
   state/reality divergence and triggers corrective applies automatically.

2. **Fix `TOKEN_URL` in `rotate.sh`**: The script used a per-application token
   endpoint (`/application/o/kubectl-sandbox-client-credentials/token/`) which
   returns HTTP 405. Authentik uses a shared token endpoint
   (`/application/o/token/`). This bug was masked by the missing application
   (which caused the earlier 400 error), but would have surfaced once the
   application was recreated.

## Lessons

- **Always enable `refreshBeforeApply: true`** for tofu-controller Terraform
  resources that manage external state (Authentik, DNS, Harbor, etc.). The cost
  is one extra API call per reconcile interval; the benefit is automatic
  detection and repair of state/reality divergence. The default `false` is only
  safe when the managed infrastructure is guaranteed immutable between applies
  (e.g., purely K8s-native resources that can't be modified outside TF).

- **Authentik token endpoints are shared**, not per-application. The OIDC
  discovery document (`.well-known/openid-configuration`) returns the correct
  `token_endpoint` — always use it rather than constructing URLs manually.

- **Partial data loss is harder to detect than total loss.** If all of Authentik
  had been wiped, everything would have broken visibly. Because only the
  applications were lost while providers survived, the failure was narrow
  (only `client_credentials` grants broke) and silent (TF saw no drift).
