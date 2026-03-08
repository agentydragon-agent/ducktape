# talosctl upgrade: Hostname Loss and Accidental VPS Replacement

**Date**: 2026-03-07
**Status**: Resolved (explicit hostnames added, image ignore_changes added)

## Incident Summary

Upgrading Talos nodes via `talosctl upgrade` with a new schematic (adding `iscsi-tools`)
caused all upgraded nodes to lose their logical hostnames and register with random names.
A subsequent `tofu apply` accidentally replaced both Hetzner VPS servers, destroying the
cluster (2/3 etcd members lost).

## Root Cause 1: Hostname Loss After talosctl upgrade

Talos derives hostnames from platform metadata (cloud-init for Proxmox/nocloud, Hetzner
metadata API for hcloud). During `talosctl upgrade`, the node kexecs into the new image.
The platform metadata is **not re-read during kexec** — only on full boot from disk image.
Without an explicit `machine.network.hostname` in the machine config, Talos falls back to
generating a random hostname from the machine ID (e.g., `talos-6we-boc` instead of
`talos-vps-cp-0`).

**Symptoms**:

- `kubectl get nodes` shows random names alongside stale NotReady entries with original names
- Upgraded nodes register as new Kubernetes nodes (new name, same IP)
- Old node entries remain as `NotReady,SchedulingDisabled` (cordoned during upgrade)

**Fix**: Add explicit `machine.network.hostname` as a separate config patch in Terraform
for all node types:

```hcl
# Separate config patch (Talos merges patches, so this safely adds hostname
# without conflicting with the existing network.kubespan config)
yamlencode({
  machine = {
    network = {
      hostname = each.value.name
    }
  }
})
```

This survives `talosctl upgrade` because the machine config is preserved across upgrades —
only the OS image changes.

**Affected files**:

- `terraform/bootstrap/infrastructure/hetzner-nodes.tf`
- `terraform/bootstrap/infrastructure/proxmox-nodes.tf`

## Root Cause 2: Accidental VPS Server Replacement

The `hcloud_server` resource had `lifecycle { ignore_changes = [user_data] }` to prevent
server replacement when machine config changes. However, changing the Talos schematic also
changes the Packer-built Hetzner snapshot (different `image` ID). The `image` field was NOT
in `ignore_changes`, so Terraform planned a destroy+recreate of both VPS servers.

A `tofu apply -target=talos_machine_configuration_apply.vps[...]` was run, but Terraform's
dependency resolution pulled in the `hcloud_server` resources (since `machine_configuration_apply`
references `hcloud_server.vps[each.key].ipv4_address`). The `-auto-approve` flag allowed the
replacement to proceed without confirmation.

**Symptoms**:

- `hcloud server list` shows new server IDs and different IPs
- Kubernetes API and Talos API unreachable on old IPs
- etcd quorum lost (2/3 control plane nodes destroyed)

**Fix**: Add `image` to `lifecycle.ignore_changes`:

```hcl
lifecycle {
  ignore_changes = [user_data, image]
}
```

Schematic/image changes are applied via `talosctl upgrade`, not server replacement.

## Prevention Checklist

1. **Always set explicit hostnames** in Talos machine config — never rely on platform
   auto-detection surviving upgrades
2. **Never run `tofu apply -auto-approve`** with `-target` flags that might pull in
   destructive upstream dependencies — always review the plan first
3. **Add `image` to `ignore_changes`** for `hcloud_server` resources — image changes
   should only happen via `talosctl upgrade`
4. **Verify `tofu plan` output** for `must be replaced` before applying — even targeted
   applies can cascade through dependencies

## Timeline

1. Added `iscsi-tools` to all Talos schematics (Hetzner + Proxmox)
2. Ran `talosctl upgrade` on vps0, vps1, and proxmox-cp — all succeeded but got random hostnames
3. Noticed hostname loss, decided to fix via Terraform (add explicit `machine.network.hostname`)
4. Ran `tofu apply -target=...machine_configuration_apply... -auto-approve`
5. Terraform resolved dependencies, planned VPS server replacement (image changed), executed it
6. Both VPS servers destroyed and recreated with fresh Talos — etcd quorum lost
7. Full cluster teardown and rebuild required
