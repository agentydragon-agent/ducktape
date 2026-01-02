# Talos Cluster Bootstrap Playbook

Step-by-step instructions for cold-starting the Talos cluster from layered terraform architecture.

## Cold-Start Cluster Deployment

### Prerequisites

- SSH access to `root@atlas.agentydragon.com` (Proxmox) and `root@agentydragon.com` (Headscale) for auto-provisioning
- `direnv` configured in cluster directory
- VPS with nginx and PowerDNS configured via Ansible
- Access to AWS Route 53 for `agentydragon.com`
- **Stable SealedSecret keypair** stored in libsecret (one-time setup, see below)

### Step 0: One-Time SealedSecret Keypair Setup

**IMPORTANT**: Generate stable keypair ONCE and store in libsecret. Required before first bootstrap:

```bash
# Generate stable keypair (run ONCE per development machine)
openssl genrsa 4096 | secret-tool store service sealed-secrets key private_key
openssl req -new -x509 -key <(secret-tool lookup service sealed-secrets key private_key) \
  -out /tmp/sealed-secrets.crt -days 365 -subj '/CN=sealed-secrets'
secret-tool store service sealed-secrets key public_key < /tmp/sealed-secrets.crt
rm /tmp/sealed-secrets.crt

# Only Proxmox CSI uses sealed secrets now - Authentik uses ESO
# Regenerate CSI sealed secret if needed
kubeseal --cert <(secret-tool lookup service sealed-secrets key public_key) \
  < /tmp/proxmox-csi-secret.yaml > k8s/storage/proxmox-csi-sealed.yaml
```

### Step 1: Layered Terraform Deployment

**NEW**: 3-layer terraform architecture with proper API dependency management.

```bash
./bootstrap.sh

# Layered bootstrap handles all components in proper dependency order
```

**Prerequisites:**

- `gh auth login` completed for GitHub access
- Stable SealedSecret keypair in libsecret (Step 0)

#### Bootstrap Layer Architecture

The bootstrap process is organized into distinct layers, each providing essential infrastructure for subsequent layers:

**Layer 0: Persistent Authentication** (`terraform/00-persistent-auth/`)

- Proxmox API credentials for VM provisioning
- Proxmox CSI tokens for persistent storage
- Sealed secrets cluster keypair (persists across cluster rebuilds)
- Exists independently of cluster lifecycle - survives `terraform destroy` of VMs

**Layer 1: Infrastructure** (`terraform/01-infrastructure/`)

- VM provisioning via Proxmox (5 nodes: 3 controllers, 2 workers)
- Disk images with baked Talos configuration
- Tailscale machine keys and VPN registration
- Cilium CNI deployment with kube-proxy replacement
- Kubernetes cluster bootstrap and kubeconfig generation

**Layer 2: Services** (`terraform/02-services/`)

- Flux GitOps engine initialization
- Core Kubernetes services (MetalLB, cert-manager, ingress-nginx)
- Storage providers (Proxmox CSI)
- Secret management (Vault, External Secrets Operator)
- Identity provider (Authentik)
- Platform services (Harbor, Gitea, Matrix, PowerDNS)

**Layer 3: Configuration** (`terraform/03-configuration/`)

- DNS zone and record provisioning (PowerDNS API)
- SSO provider configuration (Authentik, Harbor, Gitea)
- Application integration and service wiring

This **single command** executes a **3-phase layered deployment**:

#### Phase 0: Preflight Validation

- ✅ Git working tree clean check (Flux requirement)
- ✅ Pre-commit validation (security, linting, format)
- ✅ Terraform configuration validation for all 3 layers

#### Phase 1: Infrastructure (`terraform/01-infrastructure`)

- **Proxmox API** → Creates VMs with Talos images
- **Talos API** → Bootstraps cluster, generates kubeconfig
- **Kubernetes API** → Installs Cilium CNI, applies sealed secrets key
- **Storage** → Generates Proxmox CSI sealed secrets

#### Phase 2: Services (`terraform/02-services`)

- **Flux Bootstrap** → Initializes GitOps engine with GitHub
- **GitOps Module** → Deploys service manifests via Flux

#### Phase 3: Configuration (`terraform/03-configuration`)

- **PowerDNS API** → Creates DNS zones and records
- **Service APIs** → Configures SSO providers (Authentik, Harbor, Gitea)

**Architecture Benefits**:

- **Proper API dependency chain**: Each layer depends on APIs from previous layers
- **No circular dependencies**: PowerDNS provider only used after PowerDNS service is deployed
- **Provider separation**: Infrastructure providers (Proxmox, Talos) separate from service APIs
- **Fail-fast validation**: All layers validated before any deployment begins

#### Key Features

- **🔍 Comprehensive validation** before any infrastructure changes
- **⚡ Proper dependency management** - respects actual API availability
- **🛡️ Stable sealed secrets** - Keypairs persist across destroy/apply cycles
- **📊 Clear progress reporting** - Phase-by-phase status updates
- **❌ Fail-fast behavior** - Stops immediately on validation failures

#### Test

```bash
kubectl get nodes -o wide  # Nodes should be Ready with Cilium CNI
flux get all               # Check GitOps status - should show healthy reconciliations
kubectl get pods -A        # All system pods should be running
# Note: kubectl automatically uses VIP (10.2.3.1) for HA - no manual --server needed
```

### Step 2: Verification

**NEW**: All components deploy automatically via layered terraform. No manual steps needed.

```bash
# Verify cluster health
kubectl get nodes -o wide                    # All nodes Ready with Talos/Cilium
kubectl get pods -A | grep -v Running        # Should be empty (all pods running)

# Verify GitOps
flux get all                                 # All Flux resources should be healthy

# Verify storage
kubectl get storageclass                     # Should show proxmox-csi-retain
kubectl get pods -n csi-proxmox              # CSI controller/node pods running

# Verify Vault (Stage 1)
kubectl get pods -n vault                    # Bank-Vaults instance running
kubectl get secret -n vault instance-unseal-keys  # Root token available

# Verify ESO
kubectl get pods -n external-secrets-system  # ESO controller running
kubectl get clustersecretstore vault-backend # Should be valid/ready

# Verify Authentik bootstrap
kubectl get secret -n authentik authentik-bootstrap  # ESO-generated token
flux reconcile ks infrastructure-storage --wait
```

#### Storage Verification

```bash
kubectl get storageclass                    # Should show proxmox-csi (default)
kubectl get pods -n csi-proxmox            # CSI controller and node pods running
kubectl get csinode                        # Verify CSI driver registered
```

### Sealed-Secrets Keypair Persistence (Optional Optimization)

The cluster automatically manages sealed-secrets keypair persistence for turnkey GitOps workflows:

- **First deployment**: Sealed-secrets controller generates new keypair, terraform stores it in system keyring
- **Subsequent deployments**: Terraform restores keypair from keyring, all existing sealed secrets work immediately
- **Without persistence**: Each deployment generates new keypair, requiring manual sealed secret regeneration

**No action needed** - this happens automatically during `terraform apply`.

### Step 3: Platform Services Automatic Deployment

**NEW**: All platform services deploy automatically via layered terraform with ESO secret generation.

Platform services (Vault, Authentik, Harbor, Gitea, Matrix) deploy automatically through the layered bootstrap process:

- **Vault**: Bank-Vaults operator deploys with initial root token
- **ESO**: Connects to Vault and provides password generation
- **Authentik**: Bootstrap token auto-generated by ESO Password generator
- **SSO Services**: OAuth2 providers configured automatically in terraform

#### Verification

```bash
# Check all platform services
flux get ks infrastructure-platform         # Platform services status
kubectl get pods -n vault -n authentik     # Core platform pods
kubectl get externalsecret -n authentik    # ESO-generated secrets
kubectl get secret -n authentik authentik-bootstrap  # Auto-generated token
```

### Step 4: External Connectivity via DNS Delegation

#### Step 4.1: DNS Delegation Setup

Create NS delegation in Route 53 for `test-cluster.agentydragon.com` to VPS PowerDNS, then delegate to cluster.

#### Step 4.2: VPS Configuration Updates

Update `~/code/ducktape` repository configurations:

- **PowerDNS**: Add delegation in `ansible/host_vars/vps/powerdns.yml` to cluster PowerDNS VIP (10.2.3.3)
- **NGINX**: Update `ansible/nginx-sites/test-cluster.agentydragon.com.j2` for SNI passthrough to cluster ingress VIP (10.2.3.2:443)

#### Step 4.3: Deploy VPS Configuration

```bash
cd ~/code/ducktape/ansible
ansible-playbook vps.yaml -t powerdns,nginx-sites
```

#### Step 4.4: Wait for In-Cluster PowerDNS

Monitor Flux deployment of platform services:

```bash
flux get ks infrastructure-platform  # Wait for platform services
kubectl get pods -n dns-system       # Verify PowerDNS pod running
kubectl get svc powerdns-external    # Should show LoadBalancer IP 10.2.3.3
```

#### Step 4.5: Test DNS Delegation Chain

```bash
# Test VPS → cluster DNS delegation
dig @ns1.agentydragon.com test-cluster.agentydragon.com NS
# Test cluster PowerDNS directly
dig @10.2.3.3 test.test-cluster.agentydragon.com
# Test SNI passthrough via VPS to cluster ingress (standard HTTPS port 443)
curl -I https://auth.test-cluster.agentydragon.com/
```

Cluster should now be operational with GitOps and external HTTPS connectivity.

## Architecture Overview

### Layered Terraform Structure

The cluster uses a **3-layer terraform architecture** that properly models API dependencies:

```text
Layer 1: Infrastructure (terraform/01-infrastructure/)
├── Proxmox API → VMs created
├── Talos API → Cluster bootstrapped, kubeconfig generated
├── Kubernetes API → CNI installed, nodes Ready, sealed secrets applied
└── Storage → CSI secrets sealed and ready

Layer 2: Services (terraform/02-services/)
├── Flux Bootstrap → GitOps engine initialized
└── Service Manifests → Deployed via GitOps

Layer 3: Configuration (terraform/03-configuration/)
├── PowerDNS API → DNS zones and records created
└── Service APIs → SSO providers configured
```

### VIP Bootstrap Solution

The cluster solves the VIP chicken-and-egg problem (can't bootstrap with VIP that doesn't exist yet) through terraform:

1. Bootstrap uses direct controller IP (`10.2.1.1:6443`)
2. Generated kubeconfig uses VIP (`10.2.3.1:6443`) for operations

Users only see the final VIP-based kubeconfig - the bootstrap complexity is internal to terraform.

### Provider Configuration

Each layer uses providers appropriate to its API dependencies:

- **Layer 1**: Proxmox, Talos, Kubernetes, Helm, Vault
- **Layer 2**: Kubernetes, Helm, Flux, Vault
- **Layer 3**: PowerDNS, Authentik, Harbor, Gitea

The Kubernetes and Helm providers in Layer 1 use kubeconfig data directly from Talos outputs, avoiding file-based
configuration issues.
