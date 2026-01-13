# Talos Cluster Bootstrap Playbook

Step-by-step instructions for cold-starting the hybrid Talos cluster (2x Hetzner VPS + 2x Proxmox home).

## Architecture Overview

```text
Internet → VPS (2x Hetzner CPX31, Hillsboro OR)
              ├── talos-vps-cp-0 (controlplane, schedulable)
              ├── talos-vps-cp-1 (controlplane, schedulable)
              └── KubeSpan mesh (WireGuard) → Home Proxmox (atlas)
                                                   ├── talos-pve-cp-0 (controlplane)
                                                   └── talos-pve-worker-0 (worker)
```

**Node Topology** (4 nodes total):

| Node               | Location        | Role         | IP/Access                 |
| ------------------ | --------------- | ------------ | ------------------------- |
| talos-vps-cp-0     | Hetzner (hil)   | controlplane | Dynamic (Hetzner assigns) |
| talos-vps-cp-1     | Hetzner (hil)   | controlplane | Dynamic (Hetzner assigns) |
| talos-pve-cp-0     | Proxmox (atlas) | controlplane | 10.2.1.1                  |
| talos-pve-worker-0 | Proxmox (atlas) | worker       | 10.2.2.1                  |

**etcd Quorum**: 3 controllers (2 VPS + 1 Proxmox) - cluster survives home outage.

## Prerequisites

### Required Credentials

1. **Hetzner Cloud API Token** (`HCLOUD_TOKEN` env var)
   - Create at: Hetzner Cloud Console → Security → API Tokens
   - Permissions: Read/Write

2. **Proxmox API Token** (managed in 00-persistent-auth layer)
   - User: `terraform@pve`
   - Created automatically by persistent auth terraform

3. **GitHub CLI** (`gh auth login`)
   - Required for Flux GitOps bootstrap

### Required Access

- SSH to `root@atlas.agentydragon.com` (Proxmox host)
- `direnv` configured in cluster directory

### Persistent Auth Layer

Run once per environment (survives cluster destroy/recreate):

```bash
cd terraform/00-persistent-auth
terraform init && terraform apply
```

This creates:

- Talos machine secrets (shared across all nodes)
- Proxmox API tokens (terraform + CSI)
- Sealed secrets keypair

## Cold-Start Deployment

### Single Command Bootstrap

```bash
export HCLOUD_TOKEN="your-hetzner-api-token"
./bootstrap.sh
```

The bootstrap script executes a 3-phase layered deployment:

#### Phase 0: Preflight Validation

- Git working tree clean (Flux requirement)
- Pre-commit validation (security, linting)
- Terraform configuration validation

#### Phase 1: Infrastructure (`terraform/01-infrastructure`)

- **Hetzner API** → Creates 2x VPS with Talos ISO
- **Proxmox API** → Creates 2x VMs with baked Talos images
- **Talos API** → Bootstraps cluster from first VPS, generates kubeconfig
- **Kubernetes API** → Installs Cilium CNI, deploys sealed secrets keypair

#### Phase 2: Services (`terraform/02-services`)

- **Flux Bootstrap** → Initializes GitOps engine with GitHub
- **Core Services** → MetalLB, cert-manager, ingress-nginx
- **Storage** → Hetzner CSI (VPS), Proxmox CSI (home)
- **Platform** → Vault, ESO, Authentik

#### Phase 3: Configuration (`terraform/03-configuration`)

- **PowerDNS API** → DNS zones and records
- **Service APIs** → SSO providers (Authentik, Harbor, Gitea)

### Verification

```bash
# Check nodes (all 4 should be Ready)
kubectl get nodes -o wide

# Check Flux status
flux get all

# Check pods
kubectl get pods -A | grep -v Running

# Check storage classes
kubectl get storageclass
# Should show: hcloud-volumes (VPS), proxmox-csi (home)
```

## Bootstrap Layer Architecture

**Layer 0: Persistent Auth** (`terraform/00-persistent-auth/`)

- Talos machine secrets
- Proxmox API tokens
- Sealed secrets keypair
- Survives cluster destroy/recreate

**Layer 1: Infrastructure** (`terraform/01-infrastructure/`)

- Hetzner VPS nodes (2x CPX31)
- Proxmox VMs (1x controlplane, 1x worker)
- Cilium CNI with VXLAN tunnel mode
- KubeSpan mesh (WireGuard between all nodes)

**Layer 2: Services** (`terraform/02-services/`)

- Flux GitOps
- Core services (MetalLB, cert-manager, ingress)
- Storage (Hetzner CSI, Proxmox CSI)
- Platform (Vault, Authentik, Harbor)

**Layer 3: Configuration** (`terraform/03-configuration/`)

- DNS provisioning
- SSO configuration

## Networking

### KubeSpan (Node-to-Node)

WireGuard mesh connecting VPS ↔ home nodes.

- Port: UDP 51820
- Automatic peer discovery via Talos cluster discovery
- Handles NAT traversal for home nodes

### Cilium CNI (Pod Networking)

- Mode: VXLAN tunnel (required for cross-VPS connectivity)
- Port: UDP 8472
- kube-proxy replacement enabled

### Cluster Endpoint

Uses KubePrism (`localhost:7445`) during bootstrap to avoid circular dependency.
Kubeconfig is patched post-bootstrap with real VPS IP for external access.

## Storage

| Location | CSI Driver  | StorageClass   | Use Cases                  |
| -------- | ----------- | -------------- | -------------------------- |
| VPS      | hcloud-csi  | hcloud-volumes | Vault, Authentik, DNS      |
| Home     | proxmox-csi | proxmox-csi    | Harbor, Gitea, Loki, media |

## Sealed Secrets Keypair

The keypair persists in terraform state (`00-persistent-auth`):

- Generated once, reused across cluster rebuilds
- All SealedSecrets in git decrypt correctly after recreate
- No manual re-sealing needed

## External Connectivity

### DNS Delegation

1. Route 53 delegates `test-cluster.agentydragon.com` → VPS PowerDNS
2. PowerDNS runs on VPS nodes (public IPs)
3. cert-manager uses DNS-01 challenges

### Ingress

- ingress-nginx on VPS nodes (hostNetwork or NodePort)
- VPS public IPs receive HTTPS traffic directly
- No nginx proxy layer needed (VPS nodes are in the cluster)

## Troubleshooting

See `docs/troubleshooting.md` for:

- KubeSpan connectivity issues
- Storage (Hetzner CSI, Proxmox CSI)
- Sealed secrets keypair mismatches
