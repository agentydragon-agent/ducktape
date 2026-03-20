# Nebula Mesh Migration Plan

**Status**: Completed (2026-03). KubeSpan disabled on all Talos nodes, Nebula deployed on
all nodes, kubespand decommissioned. See
<../lessons_learned/kubespand-tombstone.md> for the full post-mortem.

## Motivation

KubeSpan (Talos's built-in WireGuard mesh) doesn't reliably support the target
topology: k8s workers running on random laptops behind arbitrary NATs. The core
problem is that KubeSpan has **no relay capability** — when two NAT'd nodes can't
hole-punch (symmetric NAT, double NAT with bad timing), they simply can't communicate.
The endpoint cycling algorithm makes direct NAT-to-NAT connections probabilistically
slow (~240s average) even when hole-punching is theoretically possible.

See `cluster/kubespand/debug/doublenat-test-timeout.md` for the detailed root cause
analysis.

**Nebula** (MIT-licensed, created by Slack) solves this with:

- **Lighthouse nodes** on VPS with public IPs for peer discovery
- **Relay support** (v1.6.0+) through lighthouse/relay nodes when hole-punching fails
- **Certificate-based identity** — no online coordination server needed
- **Talos system extension** available (contrib tier in `siderolabs/extensions`)

## Current Architecture

```text
┌─────────────────────────────────────────────────┐
│  Hetzner VPS (public IPs)                       │
│  ├─ talos-vps-cp-0 (control plane + worker)     │
│  └─ talos-vps-cp-1 (control plane + worker)     │
└─────────────────┬───────────────────────────────┘
                  │ KubeSpan (WireGuard UDP 51820)
                  │ Cilium VXLAN (UDP 8472)
┌─────────────────┴───────────────────────────────┐
│  Proxmox (atlas, VLAN 4, 10.2.0.0/16)          │
│  ├─ talos-pve-cp-0 (10.2.1.1, control plane)   │
│  └─ wyrm2 (NixOS GPU worker via kubespand)      │
└─────────────────────────────────────────────────┘
```

**Networking stack**: KubeSpan WireGuard → Cilium VXLAN on top. MTU: 1370 (1500 - 80
WireGuard - 50 VXLAN).

## Target Architecture

```text
┌─────────────────────────────────────────────────┐
│  Hetzner VPS (public IPs)                       │
│  ├─ talos-vps-cp-0 (lighthouse + relay + CP)    │
│  └─ talos-vps-cp-1 (lighthouse + relay + CP)    │
└─────────────────┬───────────────────────────────┘
                  │ Nebula (UDP 4242)
                  │ Cilium VXLAN (UDP 8472)
┌─────────────────┴───────────────────────────────┐
│  Proxmox (atlas)                                │
│  ├─ talos-pve-cp-0 (nebula node)                │
│  └─ wyrm2 (NixOS, nebula node)                  │
├─────────────────────────────────────────────────┤
│  Roaming laptops (behind arbitrary NATs)        │
│  ├─ rugged (NixOS, nebula node)                 │
│  └─ future laptops...                           │
└─────────────────────────────────────────────────┘
```

**Key changes**: KubeSpan disabled on all nodes. Nebula provides the encrypted overlay.
VPS nodes act as lighthouses + relays. Roaming laptops get guaranteed connectivity
through relay even behind symmetric/double NAT.

## Nebula Concepts (Quick Reference)

- **CA**: Offline certificate authority. Generate once, sign node certs with it.
  The CA private key never touches any node — only the public cert is distributed.
- **Lighthouse**: Node with public IP that maintains a peer registry. Responds to
  "where is node X?" queries and coordinates hole-punching.
- **Relay**: Node that forwards encrypted traffic when direct connections fail.
  End-to-end encrypted — relay can't read payloads. Any node with a public IP
  can be both lighthouse and relay.
- **Certificates**: Each node gets a signed cert embedding its Nebula IP, name,
  and group memberships. Nodes verify each other via CA cert — no coordination
  server needed.
- **Protocol**: Noise_IX (identity exchange during handshake, unlike WireGuard's
  Noise_IK which requires pre-shared keys). Default encryption: AES-256-GCM.
- **Relay runs over UDP** — unlike Tailscale DERP (TCP 443). May be blocked by
  restrictive corporate firewalls.

## Migration Steps

### Phase 1: Generate Nebula CA and Node Certificates

```bash
# Install nebula-cert (or use nix)
# Generate CA (do this on a trusted machine, keep ca.key safe)
nebula-cert ca -name "allegedly.works" -duration 87600h  # 10 years

# Sign node certificates
# VPS lighthouses
nebula-cert sign -name "talos-vps-cp-0" -ip "10.42.0.1/16" \
  -groups "lighthouse,controlplane,vps"
nebula-cert sign -name "talos-vps-cp-1" -ip "10.42.0.2/16" \
  -groups "lighthouse,controlplane,vps"

# Proxmox nodes
nebula-cert sign -name "talos-pve-cp-0" -ip "10.42.0.10/16" \
  -groups "controlplane,proxmox"
nebula-cert sign -name "wyrm2" -ip "10.42.0.20/16" \
  -groups "worker,proxmox,gpu"

# Roaming nodes
nebula-cert sign -name "rugged" -ip "10.42.0.30/16" \
  -groups "worker,roaming"
```

The `10.42.0.0/16` overlay subnet must not conflict with:

- Pod CIDR (check `cluster.network.podSubnets` in Talos config)
- Service CIDR (check `cluster.network.serviceSubnets`)
- Proxmox VLAN (10.2.0.0/16) — **conflict!** Use `10.42.0.0/16` or `172.30.0.0/16`

### Phase 2: Store Nebula Secrets

Nebula CA + node certs should be managed similarly to the existing sealed secrets
flow. Options:

#### Option A: Sealed Secrets (recommended for bootstrap)

Store in `persistent-auth` Terraform state alongside sealed secrets keypair:

```hcl
# terraform/bootstrap/persistent-auth/nebula.tf

resource "tls_private_key" "nebula_ca" {
  algorithm = "ED25519"
}

# Or: use null_resource + local-exec to run nebula-cert
# and store outputs in local_sensitive_file
```

Seal the per-node cert+key into SealedSecrets for in-cluster access.

#### Option B: Vault

Store CA cert + per-node cert/key pairs in Vault KV:

- `kv/nebula/ca` → `ca.crt`
- `kv/nebula/nodes/talos-vps-cp-0` → `host.crt`, `host.key`

ESO creates K8s secrets from Vault. Talos/NixOS nodes get certs via cloud-init
or Terraform provisioning.

**Recommendation**: Use Vault (Option B) for runtime, with CA key stored _only_
in `persistent-auth` TF state (never in Vault — only the public CA cert goes to
Vault). This follows the existing secret flow pattern.

### Phase 3: Talos Configuration Changes

#### 3a. Add Nebula Extension to Talos Schematics

In `cluster/terraform/bootstrap/infrastructure/hetzner-nodes.tf` and
`proxmox-nodes.tf`, add the Nebula extension:

```hcl
resource "talos_image_factory_schematic" "hetzner" {
  schematic = yamlencode({
    customization = {
      systemExtensions = {
        officialExtensions = [
          # existing extensions...
          "siderolabs/nebula",  # ADD THIS
        ]
      }
    }
  })
}
```

Same for `proxmox` schematic.

#### 3b. Disable KubeSpan

In `cluster/terraform/bootstrap/infrastructure/main.tf`, remove or disable
KubeSpan:

```hcl
# BEFORE
common_machine_base = {
  network = {
    kubespan = {
      enabled             = true
      allowDownPeerBypass = true
    }
  }
  # ...
}

# AFTER
common_machine_base = {
  network = {
    kubespan = {
      enabled = false
    }
  }
  # ...
}
```

#### 3c. Add Nebula Extension Service Config

Add Nebula config as a Talos machine config patch. Each node needs its own
`ExtensionServiceConfig` with its cert/key:

```hcl
# Per-node Nebula config patch
yamlencode({
  machine = {
    files = [
      {
        path    = "/etc/nebula/ca.crt"
        op      = "create"
        content = file("${path.module}/nebula/ca.crt")
      },
      {
        path    = "/etc/nebula/host.crt"
        op      = "create"
        content = local.nebula_certs[each.key].cert
      },
      {
        path        = "/etc/nebula/host.key"
        op          = "create"
        content     = local.nebula_certs[each.key].key
        permissions = 384  # 0600
      },
      {
        path    = "/etc/nebula/config.yaml"
        op      = "create"
        content = yamlencode(local.nebula_configs[each.key])
      },
    ]
  }
})
```

#### 3d. Nebula Config Templates

**Lighthouse (VPS nodes)**:

```yaml
pki:
  ca: /etc/nebula/ca.crt
  cert: /etc/nebula/host.crt
  key: /etc/nebula/host.key

static_host_map:
  "10.42.0.1": ["<vps-cp-0-public-ip>:4242"]
  "10.42.0.2": ["<vps-cp-1-public-ip>:4242"]

lighthouse:
  am_lighthouse: true
  interval: 10

listen:
  host: "0.0.0.0"
  port: 4242

relay:
  am_relay: true

punchy:
  punch: true
  respond: true

tun:
  dev: nebula1
  drop_local_broadcast: false
  drop_multicast: false

firewall:
  outbound:
    - port: any
      proto: any
      host: any
  inbound:
    - port: any
      proto: any
      host: any
```

**Regular node (Proxmox, roaming laptops)**:

```yaml
pki:
  ca: /etc/nebula/ca.crt
  cert: /etc/nebula/host.crt
  key: /etc/nebula/host.key

static_host_map:
  "10.42.0.1": ["<vps-cp-0-public-ip>:4242"]
  "10.42.0.2": ["<vps-cp-1-public-ip>:4242"]

lighthouse:
  am_lighthouse: false
  interval: 10
  hosts:
    - "10.42.0.1"
    - "10.42.0.2"

listen:
  host: "0.0.0.0"
  port: 4242

relay:
  relays:
    - "10.42.0.1"
    - "10.42.0.2"
  use_relays: true

punchy:
  punch: true
  respond: true

tun:
  dev: nebula1
  drop_local_broadcast: false
  drop_multicast: false

firewall:
  outbound:
    - port: any
      proto: any
      host: any
  inbound:
    - port: any
      proto: any
      host: any
```

#### 3e. Update Firewall Rules

In `main.tf`, replace KubeSpan firewall rule:

```hcl
# BEFORE
# KubeSpan (WireGuard)
rule {
  direction  = "in"
  protocol   = "udp"
  port       = "51820"
  source_ips = ["0.0.0.0/0", "::/0"]
}

# AFTER
# Nebula mesh
rule {
  direction  = "in"
  protocol   = "udp"
  port       = "4242"
  source_ips = ["0.0.0.0/0", "::/0"]
}
```

#### 3f. Update Cilium MTU

Nebula overhead differs from WireGuard. Nebula adds ~38 bytes of overhead
(UDP header + Nebula header) vs WireGuard's 80 bytes.

New MTU: 1500 - 50 (VXLAN) - 38 (Nebula) = **1412**

Update `cilium-values.yaml`:

```yaml
MTU: 1412 # 1500 - VXLAN(50) - Nebula(38)
```

**TODO**: Verify exact Nebula overhead — it depends on cipher (AES-256-GCM vs
ChaCha20-Poly1305) and whether relay adds extra framing.

### Phase 4: NixOS Worker Changes (wyrm2, rugged)

#### 4a. Replace kubespand with Nebula

In `nix/nixos/modules/k8s-worker.nix`:

```nix
# BEFORE
imports = [ ./kubespand.nix ];
# ...
ducktape.kubespand.enable = true;

# AFTER
imports = [ ./nebula-mesh.nix ];
# ...
ducktape.nebulaMesh.enable = true;
```

#### 4b. New NixOS Module: `nebula-mesh.nix`

Create `nix/nixos/modules/nebula-mesh.nix`:

```nix
{ config, pkgs, lib, ... }:
let
  cfg = config.ducktape.nebulaMesh;
in
{
  options.ducktape.nebulaMesh = {
    enable = lib.mkEnableOption "Nebula mesh network";
    configPath = lib.mkOption {
      type = lib.types.str;
      default = "/etc/nebula/config.yaml";
      description = "Path to Nebula config (placed by cloud-init)";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ pkgs.nebula ];

    # Firewall: allow Nebula UDP
    networking.firewall.allowedUDPPorts = [ 4242 ];

    systemd.services.nebula = {
      description = "Nebula mesh network";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        Type = "simple";
        ExecStart = "${pkgs.nebula}/bin/nebula -config ${cfg.configPath}";
        Restart = "on-failure";
        RestartSec = "5";

        # Nebula needs to create TUN device
        AmbientCapabilities = "CAP_NET_ADMIN";
      };
    };
  };
}
```

#### 4c. Update Cloud-Init Provisioning

In `cluster/terraform/bootstrap/k8s-worker-proxmox/main.tf`, the `k8s_cluster_join`
block currently passes `cluster_id` and `cluster_secret` (KubeSpan discovery).
Replace with Nebula credentials:

```hcl
# BEFORE
k8s_cluster_join = {
  bootstrap_kubeconfig = local.bootstrap_kubeconfig
  ca_cert              = local.k8s_ca_cert_pem
  cluster_id           = local.infra.kubespan_cluster_id
  cluster_secret       = local.infra.kubespan_cluster_secret
  node_name            = "k8s-worker-test"
}

# AFTER
k8s_cluster_join = {
  bootstrap_kubeconfig = local.bootstrap_kubeconfig
  ca_cert              = local.k8s_ca_cert_pem
  node_name            = "k8s-worker-test"
  nebula_ca_cert       = file("${path.module}/nebula/ca.crt")
  nebula_host_cert     = file("${path.module}/nebula/wyrm2.crt")
  nebula_host_key      = file("${path.module}/nebula/wyrm2.key")
  nebula_config        = local.nebula_configs["wyrm2"]
}
```

The `proxmox-vm` module's cloud-init needs updating to write Nebula config
files instead of kubespand agent.yaml.

#### 4d. Update k8s-worker.nix Dependencies

In `nix/nixos/modules/k8s-worker.nix`:

```nix
# BEFORE
systemd.services.kubelet = {
  after = [ ... "kubespand.service" ];
  requires = [ "kubespand.service" ];
};

# AFTER
systemd.services.kubelet = {
  after = [ ... "nebula.service" ];
  requires = [ "nebula.service" ];
};
```

Also update:

- Remove `wireguard-tools` from `kubeletDeps` (Nebula doesn't use kernel WireGuard)
- Remove WireGuard-specific sysctl (`rp_filter = 0` may still be needed — test)
- Remove `networking.firewall.checkReversePath = "loose"` if not needed
- Remove `boot.kernelModules = [ "wireguard" ]` from kubespand.nix

#### 4e. KubePrism / Control Plane Endpoint

kubespand currently provides **KubePrism** (localhost:7445 → control plane LB).
With Nebula, we need an alternative:

- **Option A**: Use Nebula IPs directly in kubeconfig
  (`https://10.42.0.1:6443`). Simple but single-point-of-failure.
- **Option B**: Run a lightweight TCP proxy (e.g., HAProxy, socat) on each NixOS
  worker that load-balances across all control plane Nebula IPs. This replicates
  what KubePrism does.
- **Option C**: DNS round-robin — `api.allegedly.works` resolves to all CP Nebula
  IPs. Requires DNS to work before k8s (chicken-and-egg if DNS is in-cluster).

**Recommendation**: Option B — a small systemd service running socat/HAProxy on
`localhost:7445` that proxies to the 3 control plane Nebula IPs. Keeps the
existing kubeconfig pattern unchanged.

### Phase 5: Remove kubespand

After Nebula is working:

1. Remove `cluster/kubespand/` (the entire Go project)
2. Remove `nix/nixos/modules/kubespand.nix`
3. Remove `nix/nixos/packages/kubespand.nix`
4. Clean up kubespand references from BUILD.bazel files
5. Update `cluster/AGENTS.md`, `cluster/README.md`

## Storing Nebula Secrets as Sealed Secrets

The Nebula CA cert and per-node credentials can be stored as SealedSecrets in
the cluster, following the existing pattern for other bootstrap secrets.

### What to Store

| Secret                           | Where                           | Why                            |
| -------------------------------- | ------------------------------- | ------------------------------ |
| `ca.key` (CA private key)        | `persistent-auth` TF state ONLY | Crown jewel — never in cluster |
| `ca.crt` (CA public cert)        | SealedSecret or Vault           | All nodes need it              |
| Per-node `host.crt` + `host.key` | SealedSecret per node           | Node identity                  |

### SealedSecret Structure

```yaml
# k8s/nebula/nebula-ca-sealed.yaml
apiVersion: bitnami.com/v1alpha1
kind: SealedSecret
metadata:
  name: nebula-ca
  namespace: kube-system
spec:
  encryptedData:
    ca.crt: <encrypted>

# k8s/nebula/nebula-node-<name>-sealed.yaml (one per node)
apiVersion: bitnami.com/v1alpha1
kind: SealedSecret
metadata:
  name: nebula-node-talos-vps-cp-0
  namespace: kube-system
spec:
  encryptedData:
    host.crt: <encrypted>
    host.key: <encrypted>
```

### Talosconfig in Cluster

Storing `talosconfig` (Talos API client credentials) as a SealedSecret is
useful for:

- Agent tooling that needs `talosctl` access from within pods
- Automated node management / monitoring

```yaml
# k8s/talos/talosconfig-reader-sealed.yaml
apiVersion: bitnami.com/v1alpha1
kind: SealedSecret
metadata:
  name: talosconfig-reader
  namespace: claude-sandbox # or wherever agents run
spec:
  encryptedData:
    talosconfig: <encrypted os:reader talosconfig>
```

This is already planned — see `cluster/docs/plan.md`:

> "Deploy readonly Talos credentials into cluster"

**Recommendation**: Use Vault + ESO rather than raw SealedSecrets for the Nebula
node secrets. This follows the existing pattern where Terraform generates secrets
→ stores in Vault → ESO reads stable values. The CA public cert can go in either
SealedSecret or Vault. The CA private key stays in `persistent-auth` TF state
(offline, never in cluster).

For talosconfig: the `os:reader` config is already generated by
`talos-reader-config.tf`. Store it in Vault and use ESO to project it into
the namespaces that need it.

## Risks and Considerations

1. **Nebula extension is "contrib" tier** — best-effort support from Sidero Labs.
   May lag behind Talos releases.
2. **UDP-only relay** — if a laptop is on a network that blocks arbitrary outbound
   UDP (e.g., strict corporate firewall), Nebula relay won't work. Tailscale DERP
   over TCP 443 handles this better. Mitigation: try port 443 for Nebula listeners.
3. **No dynamic node enrollment** — adding a new laptop requires signing a cert
   offline and distributing it. Could automate with a small enrollment service,
   but that adds complexity.
4. **MTU needs verification** — Nebula overhead may differ from the 38-byte
   estimate. Must measure actual MTU after deployment.
5. **Cluster rebuild required** — changing from KubeSpan to Nebula is a networking
   layer swap. Safest to do via full `tofu destroy` → `bazel run //cluster:bootstrap`.
6. **kubespand removal** — wyrm2 and rugged currently depend on kubespand for mesh
   networking. Must coordinate the NixOS config change with the cluster rebuild.
7. **KubePrism replacement** — kubespand currently provides the localhost:7445
   control plane proxy. Need an alternative on NixOS nodes (see Phase 4e).

## Open Questions

- [ ] Exact Nebula overhead for MTU calculation (test with `ping -s` across overlay)
- [ ] Can Nebula listen on port 443/UDP to evade restrictive firewalls?
- [ ] Does the Talos Nebula extension support relay mode or only basic connectivity?
- [ ] How does Nebula interact with Cilium's VXLAN — does it need special routing?
- [ ] Certificate rotation strategy (Nebula certs have fixed expiry, no ACME)
- [ ] Should we keep KubeSpan between VPS nodes (they can reach each other directly)
      and only use Nebula for NAT'd nodes? Or full replacement?
