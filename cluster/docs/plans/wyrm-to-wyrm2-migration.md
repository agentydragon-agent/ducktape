# Migrate wyrm → wyrm2

## Context

wyrm (Pop!\_OS VM on Proxmox) is being replaced by wyrm2 (NixOS VM).
wyrm2 is a K8s worker with 2x RTX 5090 GPUs. Goal: move all personal
data, secrets, and config so wyrm can be decommissioned.

Most config is already Nix home-manager managed. This plan covers what ISN'T.

## Completed

### Data & secrets

- [x] SSH keypair copied to wyrm2
- [x] kubeconfig (KubePrism `localhost:7445`) configured on wyrm2
- [x] Loose home files + `skadis/` moved to wyrm2 (deleted from wyrm)
- [x] ducktape cloned on wyrm2
- [x] Untracked ducktape files moved to wyrm2 (deleted from wyrm):
      `x/` (benchmark_ollama, local_llm, markup_formats),
      `debug/`, `inop/`, `laser/material_test/`, `openai_utils/docs/`,
      `devinfra/claude_hooks/docs/`, `docs/flat-tool-convertible.md`,
      `props/specimens/docs/pruning-backlog.md`, `cluster/claude-plugins-todo`
- [x] `~/.secret_env` copied to wyrm2
- [x] Secrets copied: GNOME keyring, `~/.gmail-mcp/`, `~/.aws/`, rclone, docker
- [x] App data copied: Claude Code, atuin, Chrome, Firefox, Syncthing
- [x] Cleaned from wyrm: `~/.gmail-mcp/`, rclone, firefox

### Infrastructure

- [x] SPICE vdagent added to `nix/nixos/modules/vm-hardware.nix`
- [x] virtiofs support added to proxmox-vm Terraform module
- [x] tankshare virtiofs mapping added to wyrm2 Terraform + NixOS fstab
- [x] VGA display: `vga_type = "qxl"` for SPICE console
- [x] `libsecret` added to `gui.nix` (for `secret-tool` CLI)
- [x] `NVreg_OpenRmEnableUnsupportedGpus=1` kernel param added
- [x] NixOS rebuilt on wyrm2 (all above applied)
- [x] GPU passthrough working: 2x RTX 5090, SPICE console, K8s Ready

### GPU passthrough debugging (resolved)

Adding `vga: virtio-gl` via Terraform caused a cascade of issues:

1. **`virtio-gl` incompatible with GPU passthrough** — VirGL needs host DRM
   render nodes (`/dev/dri/renderD*`), which don't exist when GPUs are bound
   to `vfio-pci`. VM hung on boot.
2. **Dirty GPU PCIe state** — the failed virtio-gl boot left both GPUs in a
   bad PCIe state. VFIO reported "reset done" but the resets were insufficient.
   GPUs hung on every subsequent boot regardless of config changes.
3. **`rombar=0` workaround** — disabling GPU option ROM BAR let OVMF boot,
   but the second GPU (Gigabyte) failed: its `PMC_BOOT_42` register read as 0
   because the option ROM wasn't executed to initialize GPU internals.
4. **Root cause: host reboot needed** — a full host power cycle gave the GPUs
   a clean hardware PCIe reset. After that, `rombar=1` + `vga: qxl` works
   perfectly with both GPUs.

Key learnings:

- RTX 5090 (Blackwell) **requires** the open nvidia kernel module
- `NVreg_OpenRmEnableUnsupportedGpus=1` needed for Gigabyte variant (subsystem `1458:416f`)
- `qxl` is the correct VGA for SPICE + GPU passthrough (not `virtio-gl`)
- If GPUs get stuck after a bad QEMU config, a host reboot is the fix

### Verification

- [x] `ssh agentydragon@wyrm2` works with the same key
- [x] `nvidia-smi` shows both RTX 5090s
- [x] `kubectl get nodes` works (4 nodes, all Ready)
- [x] SPICE console shows GDM login
- [x] `secret-tool` installed
- [x] `ls /mnt/tankshare/` shows NAS data
- [x] `cat ~/.secret_env` has API keys
- [x] Claude Code sessions/memory accessible
- [x] `gh auth status` — authenticated
- [x] Chrome bookmarks/passwords — verified
- [ ] Syncthing peers — needs service running

## Remaining: Cleanup on wyrm

Items copied to wyrm2 but not yet deleted from wyrm:

| Item                        | Command                                    |
| --------------------------- | ------------------------------------------ |
| ~~`~/.aws/`~~               | ~~done~~                                   |
| ~~`~/.docker/config.json`~~ | ~~done~~                                   |
| GNOME keyring               | `rm ~/.local/share/keyrings/login.keyring` |
| `~/.secret_env`             | `rm ~/.secret_env`                         |
| Chrome                      | `rm -rf ~/.config/google-chrome`           |
| atuin                       | `rm -rf ~/.local/share/atuin`              |
| Syncthing                   | `rm -rf ~/.config/syncthing`               |
| Claude Code                 | `rm -rf ~/.claude`                         |

## Deferred

### Volume moves

- [ ] `/code` virtiofs: add to wyrm2 Terraform + NixOS fstab, remove from wyrm
      **This is the key blocker** — carries the ducktape repo which contains: - `talosconfig.yml` (needed for `talosctl`) - Terraform state files (`terraform.tfstate*`) - The ducktape working copy itself
- [ ] `/wyrmhdd` (~791G): detach virtio disk from wyrm, attach to wyrm2

### Terraform apply

- [x] State refreshed (`tofu apply -refresh-only`) — VGA `virtio-gl→qxl` recorded
- [ ] Full `tofu apply` in `terraform/nixos-dev-env/` — blocked on `atlas` DNS
      resolution from wyrm (host reboot broke mDNS). Image rebuild trigger also
      fires due to nix config changes. Non-urgent, VM config already matches.

### SPICE display

- [ ] SPICE auto-resize not working on wyrm2 — screen doesn't resize when the
      SPICE client window is resized. Suspect Wayland (GDM/GNOME on NixOS defaults
      to Wayland) — `spice-vdagent` resize relies on X11 `xrandr`. May need to
      force X11 session or configure Wayland-compatible resize.

### Decommission wyrm

- [ ] Stop wyrm services (tailscale, docker, syncthing)
- [ ] Remove from Headscale: `headscale nodes delete wyrm`
- [ ] Shut down VM, keep disk as backup for a few weeks
