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
- [x] `~/downloads` moved to `/mnt/tankshare/wyrm-downloads/`
- [x] `~/code` transplanted to wyrm2: symlinks recreated, repos moved
      (`eza`, `rules_mypy`, `rfc3987-syntax`, `anyproto`, `github.com/eza-community`),
      loose files copied. Only `ducktape/` remains on wyrm.
- [x] Terraform state + `.terraform/` dirs copied to wyrm2 (deleted from wyrm)
- [x] talosconfig files copied to wyrm2 (deleted from wyrm)
- [x] `/code` virtiofs removed from wyrm Proxmox config
- [x] BuildBuddy bazelrc (`~/.config/bazel/buildbuddy.bazelrc`) copied to wyrm2

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

- [x] `/code` virtiofs: added to wyrm2 Terraform + NixOS fstab, `tofu apply`
      completed, `nixos-rebuild switch` applied, `/code` mounted on wyrm2
- [x] `/wyrmhdd`: decided not to migrate. Deleted LLM caches (~280G), kept diffusion
      models (chromafur-alpha, Pony Diffusion). Disk will be purged with wyrm decommission.

### Terraform apply

- [x] State refreshed (`tofu apply -refresh-only`) — VGA `virtio-gl→qxl` recorded
- [x] Full `tofu apply` in `terraform/nixos-dev-env/` — completed (used IP override
      `-var='proxmox_host=10.0.182.102'` to work around atlas DNS)

### SPICE display

- [ ] SPICE auto-resize not working on wyrm2 — screen doesn't resize when the
      SPICE client window is resized. Suspect Wayland (GDM/GNOME on NixOS defaults
      to Wayland) — `spice-vdagent` resize relies on X11 `xrandr`. May need to
      force X11 session or configure Wayland-compatible resize.

### Decommission wyrm

- [ ] Stop wyrm services (tailscale, docker, syncthing)
- [ ] Remove from Headscale: `headscale nodes delete wyrm`
- [ ] Shut down VM, keep disk as backup for a few weeks
