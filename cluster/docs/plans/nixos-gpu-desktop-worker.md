# NixOS GPU Desktop + K8s Worker (Unified VM)

Replace the separate Talos GPU worker VM and wyrm desktop VM with a single NixOS VM
that serves both roles: a K8s worker with GPU access and a daily-driver Linux desktop.

## Motivation

Proxmox doesn't support elastic RAM allocation across VMs (balloon is unreliable,
virtio-mem not yet available — Bugzilla #2949). Any static RAM split between a GPU
worker and a desktop VM is constraining: the worker is over-provisioned when idle,
the desktop starves during heavy use, or vice versa.

A single VM eliminates the split entirely — one VM gets ~28GB (leaving ~4GB for
Proxmox host + lightweight Talos CP VM).

## Current State

| VM                       | Role           | RAM  | GPUs    | OS     |
| ------------------------ | -------------- | ---- | ------- | ------ |
| `talos-pve-gpu-worker-0` | K8s GPU worker | 32GB | 2x 5090 | Talos  |
| `wyrm`                   | Desktop        | ?    | None    | Pop OS |

## Target State

| VM          | Role                     | RAM   | GPUs    | OS    |
| ----------- | ------------------------ | ----- | ------- | ----- |
| (single VM) | K8s GPU worker + desktop | ~28GB | 2x 5090 | NixOS |

The Talos control plane VM on Proxmox stays unchanged (lightweight, ~4GB).

## Architecture

```text
┌─────────────────────────────────────────────────┐
│  NixOS VM (Proxmox, ~28GB RAM, 2x RTX 5090)    │
│                                                 │
│  ┌─── Desktop ──────────────────────────────┐   │
│  │  GNOME/KDE, Steam, browser, dev tools    │   │
│  └──────────────────────────────────────────┘   │
│                                                 │
│  ┌─── K8s Worker ───────────────────────────┐   │
│  │  containerd + kubelet (systemd service)  │   │
│  │  NVIDIA device plugin (DaemonSet)        │   │
│  │  Cilium agent (DaemonSet)                │   │
│  │  Ollama, ML workloads (scheduled pods)   │   │
│  └──────────────────────────────────────────┘   │
│                                                 │
│  ┌─── Networking ───────────────────────────┐   │
│  │  Tailscale → Headscale (mesh)            │   │
│  │  HAProxy localhost:7445 → control plane  │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

## GPU Mode Switching

The GPUs are always passed through to the single VM via VFIO. The question is whether
kubelet is claiming them for cluster workloads or they're free for desktop/gaming use.

### Light switch: taint toggle (no kubelet restart)

Keeps the node in the cluster. DaemonSets (Cilium, Promtail, etc.) keep running.
Only GPU-consuming pods are affected.

```bash
# "Gaming mode" — evict GPU workloads
kubectl taint nodes gpu-node nvidia.com/gpu=true:NoExecute --overwrite

# "Cluster mode" — allow GPU workloads
kubectl taint nodes gpu-node nvidia.com/gpu=true:PreferNoSchedule --overwrite
```

GPU-consuming pods (Ollama) must tolerate `PreferNoSchedule` but not `NoExecute`.
When the taint flips to `NoExecute`, the scheduler evicts them. When it flips back,
they reschedule.

### Heavy switch: drain + stop kubelet

For full GPU release (no device plugin, no container runtime holding GPU contexts):

```bash
# Enter gaming mode
kubectl drain gpu-node --ignore-daemonsets --delete-emptydir-data
sudo systemctl stop k3s-agent  # or kubelet

# Exit gaming mode
sudo systemctl start k3s-agent
kubectl uncordon gpu-node
```

### Which to use?

- **Taint toggle**: Fast (~seconds), keeps node healthy in cluster, sufficient when
  the device plugin doesn't hold GPU memory (it doesn't — it only advertises the
  resource). Good enough for most cases.
- **Drain + stop**: Full cleanup. Use if something holds a GPU context that interferes
  with gaming (e.g., a CUDA process that didn't exit cleanly).

A desktop script/shortcut can automate either workflow.

## NixOS Configuration

Builds on the existing `k8s-worker` NixOS module (`nix/nixos/modules/k8s-worker.nix`),
already tested with the `k8s-worker-test` VM (see <roaming-laptop-worker.md>).

Additional requirements beyond the roaming laptop worker:

- **NVIDIA drivers**: `hardware.nvidia` with open kernel modules (matching Talos's
  `nvidia-open-gpu-kernel-modules` extension)
- **nvidia-container-toolkit**: containerd runtime hook for GPU pods
- **Desktop environment**: GNOME or KDE
- **Steam / gaming**: `programs.steam.enable`
- **Node labels**: `feature.node.kubernetes.io/pci-10de.present=true` (for Ollama
  nodeSelector), `topology.kubernetes.io/region=proxmox`
- **Node taints**: `nvidia.com/gpu=true:PreferNoSchedule` (matches current Talos config)
- **Kubelet config**: `default_runtime_name = "nvidia"` in containerd config

## Migration Steps

1. **Prepare NixOS config**: Extend `k8s-worker-test` host config with GPU + desktop
2. **Create new VM**: Proxmox VM with both GPUs passed through, q35 machine type,
   PCIe passthrough (same hardware config as current `talos-pve-gpu-worker-0`)
3. **Join cluster**: Bootstrap kubeconfig + Headscale registration + CSR approval
   (same procedure as roaming laptop worker)
4. **Verify GPU workloads**: Ollama schedules on the NixOS node, `nvidia-smi` works
   inside pods
5. **Migrate wyrm data**: Copy home directory, dev environments, etc.
6. **Decommission old VMs**: Remove `talos-pve-gpu-worker-0` and `wyrm` from Proxmox

## Differences from Talos GPU Worker

| Aspect             | Talos GPU Worker (current)  | NixOS GPU Desktop (target)     |
| ------------------ | --------------------------- | ------------------------------ |
| OS management      | Talos API (`talosctl`)      | NixOS (`nixos-rebuild`, SSH)   |
| Immutability       | Fully immutable filesystem  | Declarative but mutable        |
| Desktop            | None                        | Full desktop environment       |
| GPU mode switching | Not possible (Talos only)   | Taint toggle or drain+stop     |
| Container runtime  | Talos-managed containerd    | NixOS-managed containerd       |
| NVIDIA drivers     | Talos extension             | `hardware.nvidia` NixOS module |
| Debugging          | `talosctl` only             | SSH + standard Linux tools     |
| Node join          | Automatic (Talos bootstrap) | Manual (bootstrap kubeconfig)  |

## Open Questions

- **Partial GPU detach**: Could expose only 1 GPU to k8s (via device plugin config
  file `NVIDIA_VISIBLE_DEVICES` filter) and keep 1 for desktop. Adds complexity;
  probably not worth it vs the clean taint-toggle approach.
- **NVIDIA driver version alignment**: NixOS and Talos extension may ship different
  driver versions. Shouldn't matter (each node runs its own drivers), but container
  images built for one driver version might behave differently on another.
- **NFD on NixOS**: Node Feature Discovery CrashLoopBackOff was observed on the
  `k8s-worker-test` VM (non-critical, but labels like `pci-10de.present` may need
  to be set manually until resolved).
- **Proxmox CSI**: Current GPU worker uses `proxmox-csi-retain` for some PVCs.
  NixOS node would need the same CSI driver or those PVCs migrate to `local-path`.

## Related

- <roaming-laptop-worker.md> — NixOS k8s-worker module design and testing
- Cluster plan entry: `docs/plan.md` "GPU Worker Node"
