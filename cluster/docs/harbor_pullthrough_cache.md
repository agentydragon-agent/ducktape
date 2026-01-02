# Harbor Pull-Through Cache with Global Image Rewrite

## Executive Summary

This document explores strategies for deploying Harbor as a pull-through cache with **automatic global image
rewriting**, eliminating the need to manually reconfigure thousands of Helm charts and manifests.

**Key Question**: Can we transparently redirect all image pulls cluster-wide to Harbor without modifying
individual workload configurations?

**Answer**: **Yes**, using Talos containerd registry mirrors (infrastructure-level redirection) or Kubernetes
admission webhooks (application-level mutation).

**Recommended Approach**: **Talos Containerd Registry Mirrors** (already documented in
`harbor_pullthrough_cache.md` Phase 4) provides the cleanest, most transparent solution with zero
application-level changes required.

---

## Problem Statement

**Current Challenge**: Docker Hub rate limit (100 pulls/6hrs anonymous) blocks cluster bootstrap when Vault
statsD exporter repeatedly pulls `prom/statsd-exporter:latest`.

**Long-term Goal**: Use Harbor as primary image source to:

- Reduce upstream registry rate limit exposure
- Improve image pull performance (local cache)
- Enable offline capability
- Centralize vulnerability scanning

**Constraint**: Cluster has ~50+ workloads across 19 namespaces. Manually updating each
HelmRelease/Deployment to reference Harbor is labor-intensive and error-prone.

**Desired Solution**: Global "rewriter" that automatically redirects image pulls to Harbor without modifying individual manifests.

---

## Solution Options: Global Image Rewrite

### Option 1: Talos Containerd Registry Mirrors (RECOMMENDED ✅)

**Description**: Configure containerd at the Talos node level to transparently redirect image pulls to
Harbor. When any pod requests `docker.io/library/nginx:alpine`, containerd automatically translates to
`registry.test-cluster.agentydragon.com/docker-hub-proxy/library/nginx:alpine`.

**How It Works**:

```yaml
# terraform/01-infrastructure/talos.tf
machine:
  registries:
    mirrors:
      docker.io:
        endpoints:
          - https://registry.test-cluster.agentydragon.com/docker-hub-proxy
          - https://registry-1.docker.io  # Fallback
      ghcr.io:
        endpoints:
          - https://registry.test-cluster.agentydragon.com/ghcr-proxy
          - https://ghcr.io  # Fallback
      quay.io:
        endpoints:
          - https://registry.test-cluster.agentydragon.com/quay-proxy
          - https://quay.io  # Fallback
      registry.k8s.io:
        endpoints:
          - https://registry.test-cluster.agentydragon.com/registry-k8s-proxy
          - https://registry.k8s.io  # Fallback
```

**Behavior**:

1. Pod manifest: `image: docker.io/library/postgres:16`
2. Containerd intercepts pull request
3. Tries Harbor first: `registry.test-cluster.agentydragon.com/docker-hub-proxy/library/postgres:16`
4. If Harbor unavailable, falls back to `docker.io` upstream
5. Application is completely unaware of redirection

**Pros**:

- ✅ **Completely transparent** - No application-level changes required
- ✅ **Zero manifest modifications** - Works with all existing Helm charts unchanged
- ✅ **Automatic for entire cluster** - One configuration applies to all nodes
- ✅ **Built-in fallback** - Upstream registry used if Harbor down
- ✅ **Declarative infrastructure** - Configured via Terraform/Talos
- ✅ **No performance overhead** - Native containerd feature
- ✅ **Works pre-SSO** - No authentication required for pull-through proxy

**Cons**:

- ⚠️ **Requires node reboot** - Talos reconfiguration triggers node restart
- ⚠️ **Harbor must be operational** - Should only enable after Harbor is stable
- ⚠️ **Bootstrap chicken-and-egg** - Can't use for Harbor's own images (Harbor deployed first with public registries)

**Implementation Complexity**: Low - ~20 lines of HCL in existing Talos configuration

**Already Documented**: See `docs/harbor_pullthrough_cache.md` Phase 4 (lines 497-551)

**Verdict**: ✅ **RECOMMENDED** - This is the "sane cluster" approach. Industry-standard pattern used by
production Kubernetes deployments.

#### PRIMARY DIRECTIVE Compatibility: Turnkey Bootstrap with Talos Registry Mirrors

**Question**: How does this work with `terraform destroy && ./bootstrap.sh` when Harbor doesn't exist yet?

**Answer**: **Fallback endpoints make this fully compatible with turnkey bootstrap.**

**The Magic of Fallback Endpoints**:

```yaml
mirrors:
  docker.io:
    endpoints:
      - https://registry.test-cluster.agentydragon.com/docker-hub-proxy  # Primary (Harbor)
      - https://registry-1.docker.io  # Fallback (upstream)
```

**Bootstrap Flow** (completely automatic, no manual intervention):

1. **Fresh Bootstrap Start**: Cluster has no Harbor yet
   - containerd tries Harbor first: `https://registry.test-cluster.agentydragon.com/docker-hub-proxy`
   - Connection refused (Harbor doesn't exist)
   - containerd **automatically falls back** to `https://registry-1.docker.io`
   - All images pulled from upstream (normal bootstrap)

2. **Harbor Deployed via Flux**: Harbor becomes operational during bootstrap
   - Harbor pods start (using upstream-pulled images)
   - Harbor ingress ready
   - Proxy cache projects configured

3. **Subsequent Image Pulls**: Harbor now responding
   - containerd tries Harbor first: Connection succeeds!
   - Image served from Harbor (cached or proxied)
   - **No cluster reconfiguration needed** - it just starts working

**Key Properties**:

- ✅ **Fully Declarative**: Mirror configuration in `talos.tf` (committed to git)
- ✅ **No Bootstrap Logic**: Script doesn't need to check if Harbor is ready
- ✅ **DAG-Compatible**: Works regardless of bootstrap order (Harbor can come later)
- ✅ **Transparent**: Applications unaware of fallback mechanism
- ✅ **Idempotent**: `terraform destroy && ./bootstrap.sh` works reliably every time

**Failure Modes Handled**:

- **Harbor not deployed yet**: Fallback to upstream ✅
- **Harbor temporarily down**: Fallback to upstream ✅
- **Harbor overloaded**: Fallback to upstream ✅
- **Harbor network issue**: Fallback to upstream ✅

**This is why Talos registry mirrors are PRIMARY DIRECTIVE compatible** - the fallback mechanism ensures
bootstrap never blocks on Harbor availability. Harbor becoming operational is just an optimization, not a
requirement.

**Comparison with Circular Dependencies**:

- ❌ **Gitea HelmRelease depending on secret that depends on Gitea**: Deadlock (we fixed this)
- ✅ **Talos mirrors referencing Harbor that doesn't exist yet**: Works (fallback handles it)

The difference: Talos containerd **gracefully degrades** to upstream when Harbor unavailable. Applications
don't have graceful degradation for missing secrets.

---

### Option 2: Kyverno Image Mutation Policy

**Description**: Deploy Kyverno policy engine and use mutation policies to rewrite image references at admission time.

**How It Works**:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: harbor-image-rewrite
spec:
  background: false
  rules:
    - name: rewrite-dockerhub
      match:
        any:
        - resources:
            kinds:
            - Pod
      mutate:
        patchStrategicMerge:
          spec:
            containers:
            - (name): "*"
              image: |-
                {{ regex_replace_all('^docker.io/(.*)$', '{{ image }}',
                   'registry.test-cluster.agentydragon.com/docker-hub-proxy/$1') }}
            initContainers:
            - (name): "*"
              image: |-
                {{ regex_replace_all('^docker.io/(.*)$', '{{ image }}',
                   'registry.test-cluster.agentydragon.com/docker-hub-proxy/$1') }}
```

**Behavior**:

1. Deployment submitted with `image: docker.io/postgres:16`
2. Kyverno admission webhook intercepts
3. Mutates image to `registry.test-cluster.agentydragon.com/docker-hub-proxy/postgres:16`
4. Pod created with rewritten image path

**Pros**:

- ✅ **Kubernetes-native** - Works with any Kubernetes distribution
- ✅ **No node reconfiguration** - Application-layer solution
- ✅ **Granular control** - Can apply different policies per namespace
- ✅ **Audit trail** - Policy changes tracked in git
- ✅ **Works pre-SSO** - No authentication required

**Cons**:

- ⚠️ **Additional dependency** - Requires Kyverno controller deployment
- ⚠️ **Policy complexity** - Need separate rules for each registry
- ⚠️ **Regex fragility** - Image path parsing can break edge cases
- ⚠️ **Performance overhead** - Every pod create goes through admission webhook
- ⚠️ **No fallback** - If Harbor down, rewritten images fail (unless policy injects fallback)
- ⚠️ **Observability gap** - Manifest shows original image, pod shows rewritten (confusing)

**Implementation Complexity**: Medium - Requires deploying Kyverno + writing mutation policies for each
registry

**Verdict**: ⚠️ Viable alternative if Talos registry mirrors not available (e.g., using different Kubernetes
distribution). Adds complexity for this cluster.

---

### Option 3: Custom Admission Webhook

**Description**: Write custom mutating admission webhook that rewrites image references.

**How It Works**:

1. Deploy custom webhook service
2. Register MutatingWebhookConfiguration for Pod resources
3. Webhook parses image field and rewrites to Harbor proxy path

**Pros**:

- ✅ **Full control** - Custom logic for complex rewrite scenarios
- ✅ **Works pre-SSO** - No authentication required

**Cons**:

- ❌ **High development effort** - Write webhook service from scratch
- ❌ **Maintenance burden** - Need to maintain custom code
- ❌ **Reinvents the wheel** - Kyverno/OPA Gatekeeper already solve this
- ❌ **Security risk** - Webhook has cluster-wide mutation privileges

**Verdict**: ❌ **NOT RECOMMENDED** - Over-engineered when better alternatives exist

---

### Option 4: ImagePolicyWebhook (Kubernetes Native)

**Description**: Kubernetes native admission controller for image policy enforcement. Can be extended to mutate images.

**How It Works**:

1. Configure kube-apiserver with `--admission-control-config-file`
2. Reference external webhook service
3. Webhook called on image pull decisions

**Pros**:

- ✅ **Kubernetes native** - No third-party dependencies

**Cons**:

- ❌ **Complex configuration** - Requires kube-apiserver reconfiguration
- ❌ **Talos limitation** - Cannot easily customize kube-apiserver flags in Talos
- ❌ **Limited mutation support** - Primarily designed for validation, not mutation
- ❌ **Rarely used** - Not common pattern in production clusters

**Verdict**: ❌ **NOT RECOMMENDED** - Too complex for this use case

---

## Harbor Pull-Through Cache: Pre-SSO Configuration

**Question**: Can we configure Harbor proxy cache before SSO/OIDC is set up?

**Answer**: **Yes, absolutely.**

### Why Harbor SSO is Independent from Proxy Cache

**Harbor Authentication Modes**:

1. **Admin Login** (Database auth) - Required for UI/API configuration
2. **OIDC SSO** (Authentik) - Optional, for end-user authentication
3. **Anonymous Pull** (Public projects) - Required for proxy cache

**Pull-Through Cache Projects**:

- Created as **public projects** with anonymous pull enabled
- No authentication required for `docker pull` operations
- Harbor authenticates to upstream registries (not cluster authenticates to Harbor)

**Configuration Flow**:

```text
1. Deploy Harbor with database auth (admin password)
   ↓
2. Login as admin via database credentials
   ↓
3. Create proxy cache projects (docker-hub-proxy, ghcr-proxy, etc.)
   ↓
4. Set projects as PUBLIC with anonymous pull
   ↓
5. Configure Talos registry mirrors → Harbor proxy URLs
   ↓
6. Cluster workloads pull from Harbor (no auth required)
   ↓
7. (Later) Configure Authentik OIDC for Harbor UI login
```

**Key Insight**: Harbor proxy cache **does not require SSO** for functionality. SSO only affects Harbor web UI
login and API authentication for management operations.

### Harbor Bootstrap Without SSO

**Phase 0: Harbor Deployment** (SSO not required)

- Deploy Harbor via Helm with database authentication
- Generate admin password via ESO
- Harbor operational, accessible via admin login

**Phase 1: Proxy Cache Setup** (SSO not required)

- Login to Harbor UI as admin
- Create registry endpoints (Docker Hub, GHCR, Quay, registry.k8s.io)
- Create proxy cache projects (public, anonymous pull enabled)
- Test: `docker pull registry.test-cluster.agentydragon.com/docker-hub-proxy/library/nginx:alpine`

**Phase 2: Cluster Integration** (SSO not required)

- Configure Talos containerd registry mirrors
- Apply Talos configuration (node reboot)
- Verify cluster pulls from Harbor
- Monitor cache hit rate

**Phase 3: SSO Configuration** (Optional, for UI convenience)

- Create Authentik OAuth provider
- Configure Harbor OIDC via Terraform provider
- Test SSO login
- End users can now login via Authentik

**Conclusion**: Harbor proxy cache can be fully operational **before SSO is configured**. SSO is a
nice-to-have for UI access, not a requirement for proxy cache functionality.

### Deployment Order: Harbor First, Then SSO (PRIMARY DIRECTIVE Compatible)

**Question**: Can I deploy fresh Harbor, configure pull-through cache, use it, then add Authentik SSO later?

**Answer**: **Yes, this is the recommended approach and fully PRIMARY DIRECTIVE compatible.**

**Why This Works**:

1. **Harbor has independent authentication modes**:
   - Database auth (built-in, always available)
   - OIDC SSO (optional, added later)
   - Anonymous pull for public projects (always available)

2. **Pull-through cache doesn't require SSO**:
   - Proxy cache projects are PUBLIC (anonymous pull enabled)
   - Image pulls never need authentication
   - Only UI/API management operations need auth

3. **Adding SSO later doesn't break anything**:
   - Existing proxy cache projects continue working
   - Image pulls still anonymous (unaffected by SSO config)
   - Database admin login still works (backup access)

**Turnkey Bootstrap Flow** (fully declarative, DAG-compatible):

```text
Phase 1: Harbor Deployment (No Authentik dependency)
  ├─ Harbor deployed via HelmRelease
  ├─ Admin password generated by ESO
  ├─ Database auth mode active
  └─ STATUS: Harbor operational, admin can login

Phase 2: Manual Proxy Cache Setup (One-time operation)
  ├─ Admin logs in via database auth
  ├─ Creates proxy cache projects (docker-hub-proxy, ghcr-proxy, etc.)
  ├─ Sets projects as PUBLIC (anonymous pull)
  └─ STATUS: Pull-through cache operational
      └─ Note: Projects persist in PostgreSQL PVC across cluster destroy/recreate

Phase 3: Talos Registry Mirrors (Infrastructure layer)
  ├─ Talos config includes registry mirrors with fallback
  ├─ Nodes configured at terraform apply time
  └─ STATUS: All cluster image pulls automatically use Harbor cache

Phase 4: Authentik SSO (Optional, added later)
  ├─ Authentik deployed independently
  ├─ terraform/authentik-blueprint/harbor creates OIDC app
  ├─ terraform/03-configuration/harbor-sso.tf configures Harbor OIDC
  └─ STATUS: Users can now login via SSO
      └─ Image pulls still work exactly the same (anonymous, unaffected)
```

**Key Ordering Properties**:

- ✅ **Harbor → Proxy Cache**: No dependencies, works immediately
- ✅ **Proxy Cache → Talos Mirrors**: Optional optimization (fallback ensures bootstrap works)
- ✅ **Talos Mirrors → Authentik**: No dependency (mirrors use fallback until Harbor ready)
- ✅ **Authentik → Harbor SSO**: One-way dependency (Harbor works without Authentik)

**DAG Compliance**:

```text
Harbor (database auth)
  ↓
Proxy Cache Config (manual, persists in PVC)
  ↓
Talos Mirrors (with fallback) ←─── No circular dependency!
  ↓                                  │
Cluster Image Pulls ←────────────────┘
  ↓
(Later, independently)
  ↓
Authentik Deployment
  ↓
Harbor SSO Config (optional enhancement)
```

**terraform destroy && ./bootstrap.sh Behavior**:

1. **First bootstrap**: Harbor deploys → Proxy cache projects created manually → Everything works
2. **Subsequent bootstraps**: Harbor deploys → Proxy cache projects **already exist** (PVC persisted) →
   Everything works automatically
3. **Adding Authentik later**: Deploy Authentik terraform → Harbor gets SSO → Image pulls unaffected

**Manual Steps Required** (one-time, not in bootstrap script):

- Create proxy cache projects via Harbor UI (one-time setup, persists forever)
- Alternative: Automate with Harbor Terraform provider (Phase 3 in roadmap)

**What Changes When SSO Added**:

- ✅ UI login: Can now use Authentik instead of database password
- ✅ API authentication: Can use OIDC tokens
- ❌ Image pulls: **No change** (still anonymous public projects)
- ❌ Proxy cache: **No change** (still works identically)

**This is PRIMARY DIRECTIVE compatible because**:

1. Harbor deployment is fully declarative (HelmRelease)
2. Proxy cache setup is one-time manual OR automated via Terraform
3. Talos mirrors are declarative with fallback (never blocks bootstrap)
4. SSO is optional enhancement that doesn't affect core functionality

---

## Declarative Configuration Methods

### Method 1: Talos Registry Mirrors (Infrastructure Layer)

**Configuration Location**: `terraform/01-infrastructure/talos.tf`

**Declarative?**: ✅ Yes - Terraform manages Talos machine configuration

**Example**:

```hcl
data "talos_machine_configuration" "worker" {
  cluster_name     = "talos-cluster"
  machine_type     = "worker"
  cluster_endpoint = "https://10.0.3.1:6443"
  machine_secrets  = talos_machine_secrets.main.machine_secrets

  config_patches = [
    yamlencode({
      machine = {
        registries = {
          mirrors = {
            "docker.io" = {
              endpoints = [
                "https://registry.test-cluster.agentydragon.com/docker-hub-proxy",
                "https://registry-1.docker.io"
              ]
            }
            "ghcr.io" = {
              endpoints = [
                "https://registry.test-cluster.agentydragon.com/ghcr-proxy",
                "https://ghcr.io"
              ]
            }
          }
        }
      }
    })
  ]
}
```

**GitOps Workflow**:

1. Edit `talos.tf` with registry mirror configuration
2. `git add -A && git commit -m "feat(harbor): enable Talos registry mirrors" && git push`
3. `cd terraform/01-infrastructure && terraform apply`
4. Talos applies configuration, nodes reboot with new containerd config
5. Verify: `talosctl -n <node-ip> get containerdconfig`

**Turnkey Bootstrap**: ✅ Changes preserved across `terraform destroy && ./bootstrap.sh` cycles

---

### Method 2: Harbor Proxy Projects (Manual UI Setup, Then Immutable)

**Current State**: Harbor proxy cache projects must be created via UI or API **after** Harbor deployment

**Problem**: Not fully declarative - requires post-deployment manual steps

**Solution Options**:

#### Option A: Harbor Terraform Provider (Recommended ✅)

**Tool**: [goharbor/harbor](https://registry.terraform.io/providers/goharbor/harbor/latest) Terraform provider

**Example**:

```hcl
# terraform/03-configuration/harbor-proxy-projects.tf

terraform {
  required_providers {
    harbor = {
      source  = "goharbor/harbor"
      version = "~> 3.11"
    }
  }
}

provider "harbor" {
  url      = "https://registry.test-cluster.agentydragon.com"
  username = "admin"
  password = var.harbor_admin_password
}

# Docker Hub proxy registry endpoint
resource "harbor_registry" "dockerhub" {
  provider_name = "docker-hub"
  name          = "dockerhub"
  endpoint_url  = "https://hub.docker.com"
}

# Docker Hub proxy cache project
resource "harbor_project" "dockerhub_proxy" {
  name        = "docker-hub-proxy"
  public      = true
  registry_id = harbor_registry.dockerhub.id
}

# Repeat for GHCR, Quay, registry.k8s.io
resource "harbor_registry" "ghcr" {
  provider_name = "github-ghcr"
  name          = "ghcr"
  endpoint_url  = "https://ghcr.io"
}

resource "harbor_project" "ghcr_proxy" {
  name        = "ghcr-proxy"
  public      = true
  registry_id = harbor_registry.ghcr.id
}
```

**Pros**:

- ✅ Fully declarative
- ✅ Version controlled in git
- ✅ Idempotent (safe to re-apply)
- ✅ Turnkey bootstrap (projects created automatically)

**Cons**:

- ⚠️ Requires Harbor to be operational first (chicken-and-egg solved by layered terraform)
- ⚠️ Harbor admin password must be available to Terraform (already solved via ESO + reflection)

**Implementation**:

1. Add Harbor provider to `terraform/03-configuration/` layer
2. Create registry endpoints and proxy projects as Terraform resources
3. Bootstrap flow: Layer 01 (Harbor deployed) → Layer 03 (Proxy projects created)

**Status**: **Not yet implemented** - Currently proxy projects must be created manually via Harbor UI

---

#### Option B: Kubernetes Job with Harbor CLI/API

**Alternative**: Run Kubernetes Job after Harbor deployment that calls Harbor API to create proxy projects

**Example**:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: harbor-proxy-setup
  namespace: harbor
spec:
  template:
    spec:
      containers:
      - name: setup
        image: curlimages/curl:latest
        command:
        - /bin/sh
        - -c
        - |
          # Create Docker Hub registry endpoint
          curl -X POST "https://registry.test-cluster.agentydragon.com/api/v2.0/registries" \
            -H "Authorization: Basic $(echo -n admin:$HARBOR_PASSWORD | base64)" \
            -d '{"name":"dockerhub","type":"docker-hub","url":"https://hub.docker.com"}'

          # Create proxy cache project
          curl -X POST "https://registry.test-cluster.agentydragon.com/api/v2.0/projects" \
            -H "Authorization: Basic $(echo -n admin:$HARBOR_PASSWORD | base64)" \
            -d '{"project_name":"docker-hub-proxy","public":true,"registry_id":1}'
        env:
        - name: HARBOR_PASSWORD
          valueFrom:
            secretKeyRef:
              name: harbor-admin-password
              key: password
      restartPolicy: OnFailure
```

**Pros**:

- ✅ Declarative (Job manifest in git)
- ✅ Automatic execution on Harbor deployment

**Cons**:

- ⚠️ Imperative API calls (not idempotent without additional logic)
- ⚠️ No drift detection
- ⚠️ More brittle than Terraform provider
- ⚠️ Harder to maintain

**Verdict**: Viable but **Terraform provider approach is superior**

---

## Implementation Roadmap

### Phase 0: Immediate Workaround (Current State)

**Goal**: Unblock bootstrap iteration 2

**Action**: Add `statsdDisabled: true` to Vault CR to avoid Docker Hub rate limit on `prom/statsd-exporter:latest`

**File**: `k8s/vault/instance.yaml`

```yaml
spec:
  statsdDisabled: true  # Disable statsD exporter sidecar
```

**Status**: Identified, not yet applied (waiting for user approval)

---

### Phase 1: Deploy Harbor Proxy Cache (No SSO Required)

**Prerequisites**: Harbor already deployed (✅ Complete)

**Tasks**:

1. **Manual Proxy Project Setup** (Temporary - until Terraform provider implemented)
   - Login to Harbor UI as admin
   - Create registry endpoints:
     - Docker Hub: `https://hub.docker.com`
     - GHCR: `https://ghcr.io`
     - Quay: `https://quay.io`
     - Kubernetes Registry: `https://registry.k8s.io`
   - Create proxy cache projects:
     - `docker-hub-proxy` → Docker Hub endpoint, public, anonymous pull
     - `ghcr-proxy` → GHCR endpoint, public, anonymous pull
     - `quay-proxy` → Quay endpoint, public, anonymous pull
     - `registry-k8s-proxy` → Kubernetes Registry endpoint, public, anonymous pull

2. **Test Proxy Cache**

   ```bash
   docker pull registry.test-cluster.agentydragon.com/docker-hub-proxy/library/nginx:alpine
   ```

3. **Verify Caching**
   - Harbor UI → Projects → docker-hub-proxy → Repositories
   - Should see `library/nginx` cached

**Deliverable**: Functional Harbor pull-through cache (no cluster integration yet)

---

### Phase 2: Enable Talos Registry Mirrors (Global Rewrite)

**Prerequisites**: Harbor proxy cache operational, tested manually

**Tasks**:

1. **Update Talos Configuration**
   - File: `terraform/01-infrastructure/talos.tf`
   - Add registry mirrors to controlplane and worker machine configs

2. **Apply Infrastructure Changes**

   ```bash
   cd terraform/01-infrastructure
   terraform apply
   ```

   - Talos nodes reboot with new containerd configuration

3. **Verify Mirrors Active**

   ```bash
   talosctl -n 10.0.1.1 get containerdconfig
   ```

   - Should show registry mirrors configured

4. **Test Cluster-Wide Redirection**

   ```bash
   kubectl run test-nginx --image=nginx:alpine --rm -it -- sh
   ```

   - Check containerd logs: `talosctl -n 10.0.1.1 logs containerd | grep registry.test-cluster`
   - Should show image pulled from Harbor proxy

5. **Monitor Cache Hit Rate**
   - Harbor UI → Projects → docker-hub-proxy → Statistics
   - Target: >80% cache hit rate after 1 week

**Deliverable**: All cluster image pulls automatically use Harbor (transparent to workloads)

**Expected Impact on Docker Hub Rate Limit**: ~95% reduction in upstream pulls (only uncached images hit Docker Hub)

---

### Phase 3: Automate Proxy Project Creation (Optional, for Turnkey Bootstrap)

**Goal**: Make Harbor proxy cache configuration fully declarative

**Tasks**:

1. **Add Harbor Terraform Provider**
   - File: `terraform/03-configuration/harbor-proxy.tf`
   - Provider configuration with admin credentials from Vault/ESO

2. **Define Registry Endpoints and Projects**
   - `harbor_registry` resources for Docker Hub, GHCR, Quay, registry.k8s.io
   - `harbor_project` resources for corresponding proxy cache projects

3. **Test Terraform Apply**

   ```bash
   cd terraform/03-configuration
   terraform apply
   ```

   - Should create/update proxy projects via Harbor API

4. **Verify Idempotency**
   - Run `terraform apply` multiple times
   - Should show "No changes" after initial apply

5. **Test Destroy → Bootstrap Cycle**

   ```bash
   cd terraform
   terraform destroy --auto-approve
   ./bootstrap.sh
   ```

   - Verify proxy projects recreated automatically
   - Verify cluster still pulls from Harbor after bootstrap

**Deliverable**: Harbor proxy cache configuration fully automated in bootstrap process

**Status**: **Optional** - Manual proxy project creation is one-time operation that persists across cluster
destroy/recreate (Harbor PostgreSQL data persists). Automating this provides cleaner bootstrap but not strictly
necessary.

---

### Phase 4: Harbor SSO (Independent from Proxy Cache)

**Prerequisites**: None (can happen before or after proxy cache setup)

**Tasks**: Already documented in `docs/harbor_sso_automation.md`

**Deliverable**: Harbor UI login via Authentik OIDC

**Note**: This phase is **completely independent** from proxy cache functionality. Proxy cache works without SSO.

---

## Benefits Analysis

### 1. Rate Limit Mitigation

**Before Harbor**:

- Vault pod: `prom/statsd-exporter:latest` pull (200 MB)
- Recreate cluster 5 times: 5 × 200 MB = 1 GB from Docker Hub
- Hit 100 pull limit: Bootstrap fails

**With Harbor (registry mirrors)**:

- First bootstrap: 1 × 200 MB from Docker Hub → cached in Harbor
- Subsequent bootstraps: 4 × 200 MB from Harbor cache (local, fast)
- Docker Hub sees only 1 pull
- **Result**: ~80% reduction in upstream pulls

### 2. Zero-Touch Application Changes

**Without Global Rewrite**:

- 50+ HelmReleases to modify
- Hundreds of image references to update
- Risk of typos/errors
- GitOps churn (many commits)

**With Talos Registry Mirrors**:

- 1 Terraform configuration change
- Zero application-level modifications
- All existing manifests work unchanged
- Single commit, single `terraform apply`

### 3. Bootstrap Speedup

**Baseline** (public registries):

- First image pull: 500ms-5s per layer (network latency)
- Total bootstrap time: ~10-15 minutes

**With Harbor Cache** (after first bootstrap):

- Cached image pull: 10-50ms per layer (local cluster network)
- Total bootstrap time: ~5-7 minutes
- **Result**: 2x faster bootstraps

### 4. Offline Capability

**Scenario**: Internet outage or Docker Hub maintenance

**Without Harbor**:

- Cannot pull images → Cannot recreate cluster
- Dependent on upstream registry availability

**With Harbor**:

- Cached images available → Cluster recreates normally
- Only new, uncached images affected
- **Result**: Resilient to upstream registry outages

---

## Risks and Mitigations

### Risk 1: Harbor Unavailability Blocks New Images

**Risk**: If Harbor down, new image pulls fail (even with fallback, first pull must succeed)

**Likelihood**: Low (Harbor deployed with monitoring, HA possible)

**Mitigation**:

- Containerd fallback endpoints configured (upstream registries)
- Harbor monitoring via Prometheus
- Pre-warm critical images via CronJob

**Residual Risk**: Minimal - fallback ensures service continuity

---

### Risk 2: Bootstrap Chicken-and-Egg

**Risk**: If Talos mirrors enabled before Harbor operational, bootstrap deadlocks

**Likelihood**: High if implemented incorrectly

**Mitigation**:

- **Phase ordering**: Deploy Harbor first (Phase 1), enable mirrors second (Phase 2)
- **Fallback endpoints**: Always configure upstream as secondary endpoint
- **Pre-flight check**: Bootstrap script verifies Harbor health before applying Talos mirrors
- **Git rollback**: Easy revert if mirrors break bootstrap

**Residual Risk**: Low - phased approach prevents deadlock

---

### Risk 3: Harbor Storage Exhaustion

**Risk**: Harbor cache fills up, cannot cache new images

**Likelihood**: Medium (depends on workload churn)

**Mitigation**:

- Prometheus alert on storage >80%
- Automated garbage collection (cron)
- Tag retention policies (keep last 10 versions)
- Proxmox CSI supports dynamic PVC expansion

**Residual Risk**: Low - proactive monitoring prevents exhaustion

---

## Comparison: "Sane Cluster" Best Practices

**Industry Standard Approach**: Containerd/CRI-O registry mirrors at node level

**Examples**:

- **AWS EKS**: Uses VPC endpoints + ECR proxy
- **GKE**: Artifact Registry with Container Analysis
- **Production Kubernetes**: Typically use containerd mirrors + private registry

**Why Talos Registry Mirrors Match Best Practices**:

1. ✅ **Infrastructure layer** - Configuration belongs with node setup, not application manifests
2. ✅ **Transparent to workloads** - Applications don't need to know about caching
3. ✅ **Centralized management** - One configuration point (Terraform), not scattered across manifests
4. ✅ **Fallback built-in** - Upstream registries still available if cache unavailable
5. ✅ **Performance** - Native containerd feature, no added latency

**Anti-Patterns to Avoid**:

- ❌ Modifying every Helm chart individually to reference private registry
- ❌ Using image pull policies to force local resolution (doesn't solve upstream dependency)
- ❌ Kubernetes admission webhooks for image rewriting (adds complexity, performance overhead)

**Conclusion**: Talos registry mirrors are the "sane cluster" approach. This is how production Kubernetes
clusters handle private registries at scale.

---

## References

- **Existing Documentation**:
  - `docs/harbor_pullthrough_cache.md` - Comprehensive Harbor pull-through cache strategy
  - `docs/harbor_sso_automation.md` - Harbor OIDC configuration with Terraform provider

- **Talos Documentation**:
  - [Registry Mirrors Configuration](https://www.talos.dev/latest/reference/configuration/#machineregistries)
  - [Containerd Registry Configuration](https://github.com/containerd/containerd/blob/main/docs/hosts.md)

- **Harbor Documentation**:
  - [Proxy Cache Documentation](https://goharbor.io/docs/latest/administration/configure-proxy-cache/)
  - [Harbor API Reference](https://goharbor.io/docs/latest/build-customize-contribute/configure-swagger/)

- **Kubernetes Image Policy**:
  - [Admission Webhooks](https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/)
  - [Kyverno Image Mutation](https://kyverno.io/docs/writing-policies/mutate/)

- **Harbor Terraform Provider**:
  - [Provider Documentation](https://registry.terraform.io/providers/goharbor/harbor/latest/docs)
  - [GitHub Repository](https://github.com/goharbor/terraform-provider-harbor)

---

## Appendix: Quick Start for Bootstrap Unblocking

**Immediate Action to Continue Bootstrap Iteration 2**:

1. **Add to `k8s/vault/instance.yaml` (line 14)**:

   ```yaml
   spec:
     statsdDisabled: true  # Disable Docker Hub rate-limited statsD exporter
   ```

2. **Commit and push**:

   ```bash
   git add k8s/vault/instance.yaml
   git commit -m "fix: disable Vault statsD exporter to avoid Docker Hub rate limit"
   git push
   ```

3. **Destroy and re-bootstrap**:

   ```bash
   cd terraform
   terraform destroy --auto-approve
   ./bootstrap.sh 2>&1 | tee /tmp/bootstrap-iteration3.log
   ```

4. **Monitor Vault pod startup**:

   ```bash
   kubectl get pods -n vault -w
   ```

   - Should show 3/3 containers ready (no ImagePullBackOff)

**This unblocks immediate development. Harbor proxy cache is a future enhancement for long-term resilience.**
