# Talos Kubernetes Cluster

Small Talos k8s cluster with GitOps and HTTPS.

- Deploy: Single command `bazel run //cluster:bootstrap` (automated layered deployment)
- VMs:
  - Run Talos, configured and bootstrapped with Terraform.
  - Disks are pre-baked per-node from Image Factory with static IPs and Tailscale + QEMU guest agent
- VPS forwards traffic to cluster through Tailscale mesh.
- CNI: Cilium with Talos-specific security configuration
- Sealed-secrets: Automatic keypair persistence via terraform state for turnkey GitOps

## Prerequisites

- **Proxmox credentials**: Create Proxmox terraform + CSI users (tokens managed in terraform state)
- **SSH access**: `root@atlas` (Proxmox) and `root@agentydragon.com` (Headscale server) for credential generation
- See [docs/BOOTSTRAP.md](docs/BOOTSTRAP.md#credential-setup) for detailed setup instructions

## direnv

`.envrc` auto-exports `KUBECONFIG` and `TALOSCONFIG` and provides CLI tools (kubeseal, talosctl, etc.).
Execute tools like these with the direnv loaded, or use `direnv exec .`.

## Infrastructure

- Network: 10.2.0.0/16 (VLAN 4 on Proxmox vmbr4 bridge)
  - 10.2.0.1: Home router (gateway)
  - 10.2.0.2: Atlas (Proxmox host) - for CSI driver API access
  - 10.2.1.x: Control plane nodes (Proxmox)
  - 10.2.2.x: Worker nodes (Proxmox)
- Talos nodes:
  - Proxmox: talos-pve-cp-0 (10.2.1.1), talos-pve-worker-0 (10.2.2.1)
  - VPS: 2x Hetzner CPX31 (public IPs, hostNetwork for ingress/DNS)
- Domain: `*.allegedly.works`
  - PowerDNS in k8s has authority on this domain and handles Let's Encrypt DNS-01 challenges
  - cert-manager provisions Let's Encrypt certs
- HTTPS chain: Internet → VPS public IP:443 → ingress-nginx (hostNetwork) → backend pods

## Services

Deployed services accessible via `*.allegedly.works`:

- **Authentik (SSO)**: <https://auth.allegedly.works>
- **Gitea (Git)**: <https://git.allegedly.works>
- **Harbor (Registry)**: <https://registry.allegedly.works>
- **Vault (Secrets)**: <https://vault.allegedly.works>
- **Matrix (Chat)**: <https://chat.allegedly.works>
- **Grafana (Monitoring)**: <https://grafana.allegedly.works> (if exposed)
- **Nix Cache**: <https://cache.allegedly.works> (Harmonia binary cache)
- **Headscale**: <https://headscale.allegedly.works> (Tailscale coordination)
- **Website**: <https://www.allegedly.works> (placeholder)

All traffic routes: Internet → VPS public IP:443 → ingress-nginx (hostNetwork) → Services

### User Management

Users are declaratively provisioned via tofu-controller with ESO-generated passwords.

**Retrieve user password:**

```bash
kubectl get secret agentydragon-user-password -n flux-system -o jsonpath='{.data.user_password}' | base64 -d
```

**User Details:**

- Username: `agentydragon`
- Email: <agentydragon@gmail.com>
- Group: authentik Admins (admin permissions)
- Password: ESO-generated (32 chars, see command above)

## Secret Management Strategy

**Stable SealedSecret Keypair**: Keypair is generated and stored in terraform state (`terraform/00-persistent-auth/`)
to ensure SealedSecrets always decrypt correctly across cluster recreations.

**Setup**: Run `terraform apply` in `terraform/00-persistent-auth/` once per environment. The keypair
persists in terraform state and survives cluster destroy/recreate cycles.

**Sealing new secrets**:

```bash
# Get public cert from terraform state
cd terraform/00-persistent-auth
terraform output -raw sealed_secrets_cert_pem > /tmp/sealed-secrets.crt
kubeseal --cert /tmp/sealed-secrets.crt < secret.yaml > sealed-secret.yaml
```

**Bootstrap fail-fast**: Script requires persistent auth layer to exist, prevents keypair mismatches that break GitOps.

## CNI Architecture Decision

**Infrastructure vs GitOps Separation**: Based on circular dependency analysis and industry best practices
(AWS EKS Blueprints, etc.), CNI is managed at the infrastructure layer, not via GitOps.

**Architecture Layers:**

- **Talos**: CoreDNS
- **Terraform**: CNI (Cilium)
- **Flux**: Applications only

**Why CNI Cannot Be GitOps-Managed:**

- Circular dependency: GitOps tools need networking to function, but would be managing their own networking
- Network disruption during handoffs: When Flux tries to update Terraform-installed CNI, worker nodes become
  permanently NotReady due to container image pull failures during networking gaps
- Industry pattern: Major platforms (AWS EKS, GKE Autopilot) manage CNI at infrastructure layer

## Repository Structure

```text
cluster/
├── shell.nix, .envrc      # direnv (KUBECONFIG, TALOSCONFIG, kubeseal CLI, ...)
├── docs/
│   ├── BOOTSTRAP.md       # Bootstrap procedure from empty Proxmox
│   ├── OPERATIONS.md      # Management, troubleshooting commands
│   └── PLAN.md            # Future roadmap, strategic decisions
├── CLAUDE.md, AGENTS.md   # Instructions for AI agents
├── terraform/
│   ├── infrastructure/    # Provisioning from empty Proxmox; boots Talos, Kube, Cilium; hands off to Flux
│   │   ├── cilium/        # CNI configuration (Terraform-managed, not GitOps)
│   │   ├── talosconfig    # Creds for node Talos APIs (generated, gitignored)
│   │   ├── kubeconfig     # Kube config (generated, gitignored)
│   │   ├── modules/talos-node/ # Reusable Talos node module
│   │   └── tmp/           # Temporary files (e.g., per-node baked Talos disk images)
│   └── gitops/            # tofu-controller managed Terraform
│       ├── authentik/     # Authentik SSO provider configuration
│       ├── vault/         # Vault configuration
│       ├── secrets/       # Secret generation
│       ├── services/      # Service integration configs
│       └── users/         # User provisioning via Terraform
├── k8s/                   # Kubernetes manifests (Flux-managed applications only)
│   ├── core/              # CRDs and controllers (sealed-secrets, tofu-controller)
│   ├── cert-manager/
│   ├── ingress-nginx/     # HTTP(S) ingress
│   ├── powerdns/          # DNS server (external)
│   ├── vault/, external-secrets/  # Secret synchronization
│   ├── authentik/         # Identity and SSO provider
│   ├── sso/               # SSO integrations and user management
│   │   └── users/         # User provisioning manifests
│   ├── services-config/   # Authentik SSO config for services, via Terraform
│   └── applications/
│       ├── harbor/        # Container registry
│       └── gitea/, matrix/, headscale/, website/
└── flux-system/           # Flux controllers (auto-generated)
```

## How Things Are Wired Together

### Network Architecture

Internet → VPS public IP:443 → ingress-nginx (hostNetwork) → backend pods
Internet → VPS public IP:53 → PowerDNS (hostNetwork) → DNS responses

- DNS:
  - PowerDNS runs on VPS nodes with hostPort binding (public IPs)
  - Handles Let's Encrypt DNS-01 challenges to obtain SSL certs
  - CoreDNS forwards allegedly.works zone to PowerDNS ClusterIP for internal resolution
- Cilium: `kubeProxyReplacement: true` with privileged port protection enabled
- Cilium MTU: `MTU: 1370` (uppercase key required — Helm is case-sensitive).
  Accounts for double encapsulation: VXLAN (50 bytes) + WireGuard/KubeSpan (80 bytes).
  Without this, cross-node packets fragment and drop intermittently.
- KubeSpan: WireGuard mesh connects VPS and Proxmox nodes

- Terraform → Image Factory API → Custom QCOW2 with META key 10 → VMs with static IPs (no DHCP)
- GitOps flow: Git commit → Flux detects change → applies k8s manifests
- Deployment path: `k8s/` directory → Flux Kustomizations → HelmReleases → Running pods
- Secret management: local `kubeseal` → sealed-secrets controller → K8s Secret → Application pods

## Let's Encrypt Rate Limits

**IMPORTANT**: Let's Encrypt has strict rate limits that affect repeated testing:

**Duplicate Certificate Limit**: 5 certificates per week for the same exact domain name

- Applies per domain (e.g., `registry.allegedly.works`)
- Rolling 7-day window, refills at ~1 cert per 34 hours
- No overrides available
- **Problem**: Each `terraform destroy && bazel run //cluster:bootstrap` cycle requests fresh certificates

**For Development/Testing**: Use Let's Encrypt **staging environment**

- Staging limit: 30,000 certificates per week (vs production's 5)
- Certificates are untrusted (browser warnings) but functional
- Switch to production once deployment is stable

**If rate limited**: cert-manager will auto-retry on exponential backoff after the limit expires.
To force immediate retry after reset:

```bash
kubectl delete certificaterequest -A -l cert-manager.io/certificate-name
```

See: <https://letsencrypt.org/docs/rate-limits/>

## Prerequisites / external dependencies

- direnv configured in cluster directory
- VM hosting: Proxmox host `atlas` with SSH access
- GitHub for Flux
- VPS: nginx proxy and PowerDNS for external connectivity, configured in `~/code/ducktape` repo:
  - nginx: `ansible/nginx_sites/`
  - PowerDNS: `ansible/host_vars/vps/powerdns.yml`
