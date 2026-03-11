# LXC k8s-test TODO

## NVIDIA GPU passthrough in LXC

Test GPU access from the LXC container. Unlike VM passthrough (VFIO), LXC GPU
access works by bind-mounting host `/dev/nvidia*` devices into the container.

### Prerequisites

- **Host NVIDIA drivers**: Atlas currently blacklists all NVIDIA drivers
  (`ansible/atlas.yaml` → `blacklist-nvidia.conf`) for VFIO passthrough to VMs.
  To use GPUs in LXC, the host must load NVIDIA drivers instead of blacklisting
  them. This conflicts with the current wyrm2 VFIO setup — can't do both
  simultaneously for the same GPU.
- **Possible approaches**:
  - Dedicate one GPU to VFIO (wyrm2) and one to the host driver (LXC) — requires
    per-device VFIO binding instead of blanket NVIDIA blacklist
  - Use NVIDIA vGPU (MIG) if the hardware supports it (RTX 5090 does not)
  - Time-share: stop wyrm2, unblacklist NVIDIA, load host driver, start LXC with GPU

### Container-side changes

- Add device passthrough via `pct set 200` for `/dev/nvidia0`, `/dev/nvidiactl`,
  `/dev/nvidia-uvm` (or via Proxmox web UI)
- Enable `ducktape.k8sWorker.enableNvidiaRuntime = true` in `default.nix`
- The NVIDIA userspace libraries inside the container must match the host driver
  version exactly — pin `hardware.nvidia.package` in NixOS config
- Enable `hardware.nvidia-container-toolkit` for CDI spec generation

### Verification

- `nvidia-smi` inside the container shows the GPU
- `crictl` can run a container with `--runtime=nvidia`
- NVIDIA device plugin DaemonSet discovers the GPU via NVML
