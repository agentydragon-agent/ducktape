# Secret Synchronization Analysis

## Problem Statement

The cluster has a systemic issue where different components become desynchronized on password/secret values,
leading to authentication failures. This violates the PRIMARY DIRECTIVE of achieving reliable turnkey bootstrap.

## Root Cause

**ESO Password Generator Volatility**: ExternalSecrets Operator (ESO) Password generators regenerate values on
every `refreshInterval`, but applications that have already consumed and persisted those values don't
automatically update.

## Affected Systems

### 1. PowerDNS API Key

**Current Configuration:**

- Password generator: `powerdns-api-key-generator` (dns-system namespace)
- Refresh interval: **1 hour**
- Secret: `powerdns-api-key` (dns-system, reflected to cert-manager/external-dns/powerdns-operator)

**Synchronization Points:**

1. ESO generates password → Kubernetes Secret (`PDNS_API_KEY`)
2. PowerDNS pod reads secret via environment variable → `PDNS_api_key` env var
3. PowerDNS **writes to PostgreSQL DB on init** (first boot with empty PVC)
4. External consumers (webhook, external-dns, operator) read from reflected secret

**Failure Mode:**

- PowerDNS pod starts: 05:49 UTC (reads password: `NDPEfQ44KYK8FE3Yj3x7Rv7MW8RR93mp`)
- PostgreSQL DB initialized with this password
- ESO refreshes secret: 08:52 UTC (regenerates NEW password)
- Secret updated with new value
- PowerDNS still running with old env var (no restart)
- **But DB has old password, new password in env var won't work for DB connection**
- Webhook reads NEW password from secret → authentication fails (401 Unauthorized)

**Critical Issue**: PowerDNS only applies password to DB on init (empty PVC). After that, the DB password is
immutable unless you manually ALTER USER or destroy the PVC.

### 2. Authentik Bootstrap Token

**Current Configuration:**

- Password generator: `authentik-bootstrap-password` (authentik namespace)
- Refresh interval: **24 hours**
- Secret: `authentik-bootstrap` → consumed by Job and Authentik pods

**Synchronization Points:**

1. ESO generates token → Secret `authentik-bootstrap`
2. Authentik pods read secret → Bootstrap token in application DB
3. Kubernetes Job reads secret → Posts token to `/api/v3/core/tokens/`
4. Terraform reads secret → Uses token for Authentik provider authentication

**Failure Mode:**

- Bootstrap Job runs at cluster creation → writes token A to Authentik DB
- 24 hours later: ESO refreshes → secret now has token B
- Authentik pods still running with token A loaded
- Terraform reads token B from secret → 403 "Token invalid/expired"
- **Job immutability**: Can't update Job to re-run with new token

### 3. Authentik PostgreSQL Password

**Current Configuration:**

- Password generator: `authentik-postgres-password-generator`
- Refresh interval: **1 hour** (most volatile!)
- Secret: `authentik-postgres` → consumed by Authentik and PostgreSQL

**Synchronization Points:**

1. ESO generates password → Secret
2. PostgreSQL init: Sets postgres user password on first boot (empty PVC)
3. Authentik connection string reads from secret

**Failure Mode:**

- PostgreSQL initializes with password at 10:00
- ESO refreshes at 11:00 → new password in secret
- Authentik pods restart → connection string uses NEW password
- PostgreSQL DB still has OLD password
- **Result**: Authentik can't connect to database (FATAL: password authentication failed)

## Dependency Chain Analysis

```text
┌─────────────────────────────────────────────────────────────────────┐
│ ESO Password Generator (volatile, regenerates every refresh)       │
└──────────────────┬──────────────────────────────────────────────────┘
                   │
                   ▼
         ┌─────────────────────┐
         │ Kubernetes Secret   │
         │  (mutable, changes) │
         └──────┬──────────────┘
                │
        ┌───────┴───────────────────────┐
        │                               │
        ▼                               ▼
┌──────────────────┐          ┌────────────────────┐
│ Application Pod  │          │ Init Script/Job    │
│ (reads at start) │          │ (writes to DB)     │
└────────┬─────────┘          └─────────┬──────────┘
         │                              │
         │ No auto-restart              │ Runs once, immutable
         │                              │
         ▼                              ▼
┌──────────────────┐          ┌────────────────────┐
│ Environment Var  │          │ PostgreSQL Database│
│ (stale)          │          │ (persisted, stable)│
└──────────────────┘          └────────────────────┘
         │                              │
         └──────────┬───────────────────┘
                    │
                    ▼
             Desynchronized!
     Pod env var ≠ DB password ≠ Secret value
```

## Why This Is Critical

**Violates PRIMARY DIRECTIVE**: The turnkey bootstrap requirement means `terraform destroy && bootstrap.sh` must
result in working cluster. But with volatile passwords:

1. First bootstrap: Works (everything uses same initial password)
2. Wait 1-24 hours
3. ESO refreshes → passwords change
4. Services break → authentication failures
5. `terraform destroy && bootstrap.sh` again → Works temporarily
6. Cycle repeats

**This is not acceptable for production** - services should not spontaneously break after 1-24 hours of uptime.

## Solution Options

### Option 1: Make Passwords Immutable (Simplest)

**Change refresh intervals from `1h`/`24h` to `never` or very long (1 year)**

Pros:

- Simple declarative fix
- No architectural changes
- Passwords stable across cluster lifetime

Cons:

- No automatic password rotation
- If secret deleted, new password generated (desync risk on secret recreation)

### Option 2: Use Vault Backing for ESO (Best)

#### Configure Password generators to store values in Vault

ESO should pull from Vault instead of regenerating values.

Currently:

```yaml
spec:
  dataFrom:
    - sourceRef:
        generatorRef:
          kind: Password  # Regenerates every refresh!
```

Change to:

```yaml
spec:
  data:
    - secretKey: password
      remoteRef:
        key: secret/powerdns-api-key  # Stable value in Vault
```

With initial generation via Terraform:

```hcl
resource "vault_kv_secret_v2" "powerdns_api_key" {
  mount = "secret"
  name  = "powerdns-api-key"
  data_json = jsonencode({
    password = random_password.powerdns_api_key.result
  })
}

resource "random_password" "powerdns_api_key" {
  length  = 32
  special = false
}
```

Pros:

- Passwords persist in Vault across cluster destroy/recreate
- ESO syncs stable values (no regeneration)
- Enables password rotation when needed (update Vault value → ESO syncs → restart pods)
- Single source of truth for secrets

Cons:

- Requires Vault Terraform resources for each secret
- More complex than Option 1

### Option 3: Stakater Reloader (Proper Pod Restart Automation)

#### Use Reloader to automatically restart pods when secrets change

**Stakater Reloader** is the industry-standard Kubernetes controller that watches Secrets/ConfigMaps and triggers
rolling restarts of Deployments/StatefulSets/DaemonSets when values change.

Installation:

```yaml
# k8s/core/reloader.yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: stakater
  namespace: flux-system
spec:
  interval: 24h
  url: https://stakater.github.io/stakater-charts
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: reloader
  namespace: kube-system
spec:
  chart:
    spec:
      chart: reloader
      sourceRef:
        kind: HelmRepository
        name: stakater
  values:
    reloader:
      watchGlobally: true
```

Usage - add annotation to deployments:

```yaml
metadata:
  annotations:
    reloader.stakater.com/auto: "true"  # Watch all referenced secrets
    # OR
    secret.reloader.stakater.com/reload: "powerdns-api-key"  # Watch specific secret
```

**What This Solves:**

- ✅ Pod-level secret consumption (environment variables, volume mounts)
- ✅ Applications that reload config dynamically
- ✅ Most service-to-service authentication

**What This DOESN'T Solve:**

- ❌ **Init-time persistence**: Applications that write secrets to DB on first boot
- ❌ **Immutable Jobs**: Kubernetes Jobs that can't be updated after creation
- ❌ **Database passwords**: PostgreSQL sets password on init, restart doesn't help

**Examples of Layer 2 Problems:**

1. **PowerDNS API Key**: Written to PostgreSQL on DB init → restarting pod doesn't update DB
2. **Authentik Bootstrap Token**: Job writes to Authentik DB once → Job is immutable
3. **PostgreSQL Password**: Set on DB creation → restart doesn't ALTER USER password

Pros:

- Industry-standard solution (10k+ GitHub stars)
- Handles 90% of rotation cases
- Zero-downtime rolling restarts
- Works with GitOps (doesn't modify manifests)

Cons:

- Doesn't solve init-time persistence pattern (requires architectural changes)

### Option 4: Remove Init-Time Password Applications

#### Make applications reload passwords dynamically

Applications should accept password changes without restart.

Pros:

- True dynamic secret rotation

Cons:

- Requires application support (PostgreSQL doesn't support this)
- Not viable for third-party applications
- Complex to implement

## Recommended Solution

**Three-Phase Approach:**

### Phase 0: Immediate Stabilization (Current)

#### Change refresh intervals to 8760h (1 year)

- Stops ongoing authentication failures
- Achieves stable turnkey bootstrap
- Buys time for proper architecture

**Status**: ✅ Implemented in commit eaaf4b1

### Phase 1: Proper Pod Restart Automation (Medium-term)

#### Deploy Stakater Reloader + reasonable refresh intervals

1. Deploy Reloader controller to cluster
2. Add `reloader.stakater.com/auto: "true"` annotations to all deployments
3. Change refresh intervals back to reasonable values (24h-168h)
4. Test rotation: ESO updates secret → Reloader restarts pod → pod uses new value

**This solves**: 90% of rotation cases (service-to-service auth, API keys consumed by pods)

**Doesn't solve**: Init-time persistence patterns (requires Phase 2)

### Phase 2: Fix Init-Time Persistence Patterns (Long-term)

**Architecture changes for applications that persist secrets:**

#### PowerDNS API Key

**Current**: API key written to PostgreSQL on init, never updated

**Solution Options**:

1. **Multiple valid keys**: Support array of API keys in DB, rotate by adding new + pruning old
2. **Dynamic update**: Add sidecar/cronjob that runs `UPDATE pdns_config SET api_key = $NEW_KEY`
3. **Overlapping validity**: Keep old key valid while new key rolls out

#### Authentik Bootstrap Token

**Current**: Immutable Job writes token to DB once

**Solution Options**:

1. **Overlapping tokens**: Support multiple valid tokens, prune after rotation window
2. **Token refresh endpoint**: API to add new tokens without Job restart
3. **CronJob pattern**: Replace immutable Job with CronJob that runs periodically

#### PostgreSQL Passwords

**Current**: Password set on DB init via env var, never changed

**Solution Options**:

1. **Accept manual rotation**: Destroy/recreate for password changes (acceptable for infrequent rotation)
2. **ALTER USER automation**: Sidecar that detects secret change and runs `ALTER USER ... PASSWORD`
3. **Vault Database Secrets Engine**: Dynamic credentials with automatic rotation

### Phase 3: Vault-Backed Persistence (Future)

#### Migrate from ESO Password generators to Vault KV storage

**Why**: ESO Password generators are stateless (regenerate on sync). Vault KV persists values.

**Implementation**:

1. Terraform generates passwords and stores in Vault KV (one-time)
2. ESO reads from Vault KV (stable values across syncs)
3. Rotation: Update Vault value → ESO syncs → Reloader restarts pods

**Benefit**: Enables controlled rotation while maintaining stability

## Implementation Plan

### Implementation Roadmap

#### Stage 0: Stabilization (DONE ✅)

Changed refresh intervals to 8760h to prevent spontaneous auth failures.

Files updated:

- `charts/powerdns/templates/external-secret.yaml`
- `k8s/authentik/bootstrap-external-secret.yaml`
- `k8s/authentik/postgres-external-secret.yaml`
- `k8s/authentik/admin-password-external-secret.yaml`

#### Stage 1: Reloader Deployment (TODO)

1. Add Reloader HelmRelease to `k8s/core/reloader.yaml`

2. Add annotations to deployments:

   ```yaml
   # Example: k8s/powerdns/helmrelease.yaml
   values:
     podAnnotations:
       reloader.stakater.com/auto: "true"
   ```

3. Change refresh intervals to reasonable values (24h-168h)

4. Test rotation workflow

#### Stage 2: Vault KV Migration (TODO)

1. Create Terraform module for secret generation:

   ```text
   terraform/gitops/secrets/
   ├── main.tf           # Vault KV secrets
   ├── passwords.tf      # random_password resources
   └── outputs.tf        # Secret paths
   ```

2. Update ExternalSecret resources to use Vault remoteRef instead of generators

3. Remove Password generator resources

#### Stage 3: Fix Init-Time Patterns (TODO)

Address PowerDNS, Authentik, PostgreSQL persistence patterns per Phase 2 solutions above.

## Webhook Namespace Issue (Separate Problem)

**Issue**: ClusterIssuer `apiKeySecretRef` without explicit namespace causes cert-manager to look in Certificate
namespace (e.g., `monitoring`) instead of where secret exists (`cert-manager`).

**Fix**: Always specify namespace in `apiKeySecretRef`:

```yaml
apiKeySecretRef:
  name: powerdns-api-key
  key: PDNS_API_KEY
  namespace: cert-manager  # Explicit namespace required!
```

**Why**: Secrets are created in `dns-system` and reflected to `cert-manager`. If namespace not specified,
cert-manager defaults to the Certificate resource's namespace, causing "secret not found" errors.

**Resolution stored in**: Will add to CLAUDE.md troubleshooting section.
