# talosctl upgrade: Hostname Loss and Accidental VPS Replacement

**Date**: 2026-03-07
**Status**: Resolved (explicit hostnames added, image ignore_changes added)
**Affected**: Both Hetzner VPS nodes and Proxmox node

## Incident Summary

Upgrading Talos nodes via `talosctl upgrade` with a new schematic (adding `iscsi-tools`)
caused all upgraded nodes to lose their logical hostnames and register with random names.
A subsequent `tofu apply` accidentally replaced both Hetzner VPS servers, destroying the
cluster (2/3 etcd members lost).

## Root Cause 1: Hostname Loss After talosctl upgrade

### What happened

After `talosctl upgrade`, all three nodes (2 Hetzner VPS + 1 Proxmox) lost their hostnames
and registered with random names like `talos-6we-boc` instead of `talos-vps-cp-0`.

### Mechanistic explanation: Talos hostname resolution internals

Talos determines hostnames through a **controller-based pipeline** with layered config
sources. Understanding the full pipeline explains why hostname was lost.

#### The hostname controller pipeline

Talos v1alpha2 runtime uses three controllers for hostname resolution:

1. **`HostnameConfigController`** — produces hostname config specs from multiple sources,
   each tagged with a config layer (cmdline, machine config, platform, default)
2. **`HostnameMergeController`** — merges specs from all layers by precedence
3. **`HostnameSpecController`** — applies the winning hostname to the system

`HostnameConfigController` consults these sources in order:

| Source                | Config layer                 | How it works                                       |
| --------------------- | ---------------------------- | -------------------------------------------------- |
| Kernel cmdline        | `ConfigCmdline`              | Parsed from boot args via `ParseCmdlineNetwork()`  |
| Machine configuration | `ConfigMachineConfiguration` | From `machine.network.hostname` in machine config  |
| Platform metadata     | `ConfigPlatform`             | From `PlatformConfig` resource (see below)         |
| Auto-generated        | `ConfigDefault`              | Based on `HostnameConfig.auto` setting (see below) |

The merge controller picks the highest-precedence non-empty source. If machine config
has no hostname, and platform metadata provides nothing, the auto-generated fallback wins.

#### The platform metadata pipeline

Platform metadata flows through four controllers:

1. **`PlatformConfigController`** — calls `platform.NetworkConfiguration()` to fetch
   metadata from the platform-specific source (Hetzner metadata API, nocloud cidata disk,
   etc.). Publishes to a `PlatformConfig` resource in runtime state.
2. **`PlatformConfigStoreController`** — persists the `PlatformConfig` to disk on the
   STATE partition (at `constants.PlatformNetworkConfigFilename`). Only writes when
   content changes (content-based comparison, not timestamp-based).
3. **`PlatformConfigLoadController`** — on boot, loads the previously-persisted
   `PlatformConfig` from disk as the initial value.
4. **`PlatformConfigApplyController`** — applies the platform config to network resources.

**The critical detail**: `PlatformConfigController` runs continuously and calls the
platform's `NetworkConfiguration()` method. But what that method does depends on
whether the platform-specific metadata source is accessible.

#### Platform-specific metadata reading

**Hetzner (`hcloud` platform)**:

- Calls the Hetzner metadata API (`http://169.254.169.254/...`) to get hostname and
  network config
- Hostname comes from the server name via the metadata service
- The metadata API is accessible from the VM at any time (it's a link-local HTTP endpoint
  on the hypervisor), so in theory it should work after kexec too

**Proxmox (`nocloud` platform)**:

- Reads from a `cidata`-labeled disk (ISO9660/VFAT) containing `meta-data`,
  `network-config`, and `user-data` files
- Hostname comes from `local-hostname` field in `meta-data`
- Network config (static IPs, routes) comes from `network-config`

#### Why kexec loses platform metadata

During `talosctl upgrade`, the default reboot mode is **kexec** — the new kernel is loaded
directly into memory via the `kexec()` syscall, bypassing full BIOS/firmware boot.

The upgrade sequence (`v1alpha1_sequencer.go Upgrade()`) runs:

1. Cordon and drain node
2. Stop services and unmount filesystems
3. Write new OS image to disk
4. `ReloadMeta` — reload META partition (boot metadata, not platform metadata)
5. `KexecPrepare` — load new kernel into memory
6. Stop all remaining services
7. `Reboot` — execute kexec (or full reboot if kexec disabled)

After kexec, the system boots the new kernel. The boot sequence
(`v1alpha1_sequencer.go Boot()`) starts services including all controllers. The
`PlatformConfigController` starts and attempts to fetch metadata. Here's where the
two platforms diverge:

**Nocloud after kexec**: The `acquireConfig()` method looks for the cidata disk. During
kexec, the cidata disk image is **not re-attached by the hypervisor** — it was a
one-time boot medium. The code handles this gracefully: if `metadataNetworkConfigDl == nil`,
it returns `nil` (no data). The `PlatformConfigLoadController` loads the last-persisted
config from the STATE partition. But this cached config was from the **initial boot**, and
the critical question is whether it still provides hostname. In practice, the nocloud
platform lost hostname because the cidata disk was unavailable and the cached platform
config either didn't include hostname or was treated as stale.

**Hcloud after kexec**: The Hetzner metadata API should be accessible (it's a link-local
endpoint). However, during kexec the network stack is reinitialized. There may be a
timing window where the `PlatformConfigController` tries to fetch before network is up,
gets an error, and the backoff/retry doesn't resolve before the hostname controller has
already settled on a fallback. The exact failure mode may also involve the platform config
cache on STATE being empty or incomplete from a prior boot.

**In both cases**: When platform metadata fails to provide hostname, and machine config has
no `machine.network.hostname`, the `HostnameConfigController` falls through to the
auto-generated default.

#### The auto-generated hostname fallback

The `HostnameConfig` document controls automatic hostname generation. The `auto` field
has three modes:

| Mode                           | Behavior                                                                             |
| ------------------------------ | ------------------------------------------------------------------------------------ |
| `stable` (default since v1.12) | SHA256 hash of node identity → `talos-{b36[1:4]}-{b36[4:7]}` (e.g., `talos-6we-boc`) |
| `addr`                         | Derives from default node address → `talos-{ip-with-dashes}`                         |
| `off`                          | No auto-generation; hostname must come from another source                           |

Before our fix, no `HostnameConfig` document was explicitly set, so the default `auto: stable`
was in effect. When platform metadata failed to provide hostname after kexec, the stable
auto-generation produced random-looking hostnames from the machine ID hash.

#### Why it's not stupid that explicit hostname is needed

The design intent is:

- **Platform metadata** is the primary hostname source for cloud VMs
- **Machine config** is the persistent, user-controlled override
- **Auto-generated** is the last-resort fallback for bare-metal or degraded scenarios

The assumption is that platform metadata is always available. This holds for full reboots
(firmware re-attaches cidata, network comes up cleanly before controllers). But kexec skips
firmware — it's a kernel-to-kernel transition. The nocloud cidata disk is literally gone.
For hcloud, the metadata API may be inaccessible during the network reinitialization window.

This is a **known gap in Talos's upgrade path**: kexec trades boot speed for completeness
of the boot environment. Platform metadata is a casualty. The Talos Terraform provider
actually appends an auto-generated `HostnameConfig` document (with `auto: stable`) to
machine configs by default — this is why the fallback is specifically the stable hash, not
a truly random name.

The fix is correct: set `machine.network.hostname` in the machine config (or use an explicit
`HostnameConfig` with `auto: off`). Machine config is stored on the SYSTEM partition and
persists across both kexec and full reboot. It's the only hostname source guaranteed to
survive all upgrade paths.

### Proxmox-specific: static IP also lost

On Proxmox, the problem was worse. The nocloud `network-config` file provides static IP
configuration (addresses, routes, nameservers). When the cidata disk is unavailable after
kexec, the node also loses its static IP and falls back to DHCP — getting a different
address, breaking etcd peering. The fix required adding explicit `machine.network.interfaces`
with `dhcp = false` and static addressing to the machine config.

### Symptoms

- `kubectl get nodes` shows random names alongside stale NotReady entries with original names
- Upgraded nodes register as new Kubernetes nodes (new name, same IP on Hetzner; different
  IP on Proxmox)
- Old node entries remain as `NotReady,SchedulingDisabled` (cordoned during upgrade)

### Fix

Two complementary patches in the Terraform machine config:

**1. Explicit hostname** via `HostnameConfig` document (both Hetzner and Proxmox):

```hcl
yamlencode({
  apiVersion = "v1alpha1"
  kind       = "HostnameConfig"
  auto       = "off"
  hostname   = each.value.name
})
```

This overrides the Terraform provider's default `auto: stable` HostnameConfig and sets an
explicit hostname that persists in machine config across all reboot modes.

**2. Explicit network interfaces** (Proxmox only):

```hcl
machine = {
  network = {
    interfaces = [{
      interface   = "eth0"
      dhcp        = false
      addresses   = ["${each.value.ip}/16"]
      routes      = [{ network = "0.0.0.0/0", gateway = local.proxmox_gateway }]
    }]
    nameservers = ["1.1.1.1", "8.8.8.8"]
  }
}
```

Hetzner doesn't need this because the hcloud platform's metadata API (link-local HTTP)
is more reliably available than nocloud's cidata disk.

**Workaround**: `talosctl upgrade --reboot-mode powercycle` forces a full BIOS reboot
instead of kexec, which re-reads platform metadata. But this is slower and doesn't fix the
underlying config gap.

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

## Root Cause 3: podCIDR Reassignment After Transient Hostname (2026-03-19)

When a node registers with a transient hostname (e.g., `talos-34f-5sc` instead of
`talos-vps-cp-1`), the Kubernetes node controller assigns it a fresh podCIDR from
`--cluster-cidr`. When the node later re-registers with its correct hostname, it gets
**yet another** podCIDR — the original allocation is orphaned under the transient name.

In IPAM mode `kubernetes` (used here), Cilium reads `spec.podCIDR` from the Node object
and programs eBPF routes accordingly. After a Cilium restart, it only routes the new CIDR.

**The dangerous part**: DaemonSet pods and long-lived pods that survived the hostname
transition still hold IPs from the **old** CIDR. These pods lose all connectivity —
they can't reach ClusterIP services, the API server, or any other pod. But they appear
`Running` in kubectl because the kubelet on the node still sees them as alive.

**Observed cascade (2026-03-19)**:

1. After TF-driven upgrade, `talos-vps-cp-1` temporarily registered as `talos-34f-5sc`
   and `talos-ner-5do`
2. podCIDR changed from `10.244.4.0/24` (old) to `10.244.2.0/24` (new)
3. Cilium restarted and only programs routes for `10.244.2.0/24`
4. 5 DaemonSet pods survived with `10.244.4.x` IPs — notably `longhorn-manager`
5. `longhorn-manager` can't reach API server (`10.96.0.1:443` → "no route to host")
   → Longhorn marks node as `NotReady` (`ManagerPodDown`)
6. Longhorn can't attach volumes → Vault stuck in `Init:0/1` → `vault-backend`
   ClusterSecretStore invalid → `external-secrets-config` fails → **84 kustomizations
   blocked**, 44 pods Pending

Also left behind stale Longhorn node entries (`talos-34f-5sc`, `talos-ner-5do`) holding
volume replicas that can't be rebuilt until the stale nodes are cleaned up.

**Fix (immediate)**: Delete pods with old-CIDR IPs so DaemonSets recreate them:

```bash
# Identify stale pods (IPs not in the node's current podCIDR)
kubectl get pods -A --field-selector spec.nodeName=<node> \
  -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,IP:.status.podIP' | \
  grep "10.244.4\."  # old CIDR

# Delete them — DaemonSets will recreate with correct IPs
kubectl delete pod <pod> -n <namespace>
```

**Fix (cleanup)**: Remove stale Longhorn nodes after verifying no unique replicas:

```bash
kubectl delete node.longhorn.io <stale-hostname> -n longhorn-system
```

**TODO — unsolved**: This will happen again on any future node upgrade/replacement
that involves a transient hostname change. The explicit `machine.network.hostname`
fix (Root Cause 1) prevents hostname loss during `talosctl upgrade`, but a full
server replacement via `tofu apply` (e.g., if `ignore_changes` is bypassed or a new
server is provisioned) can still cause a CIDR gap. Needs investigation into whether:

- kube-controller-manager can be configured to reuse CIDRs for nodes with the same IP
- A pre-upgrade drain + node deletion would prevent CIDR orphaning
- Cilium's `kubernetes` IPAM mode handles this better in newer versions
- Switching to Cilium's `cluster-pool` IPAM mode (which manages CIDRs itself) would
  avoid this class of problem entirely

See <../../debug/vps-cp-1-networking.md> for the full 2026-03-19 diagnostic.

## Prevention Checklist

1. **Always set explicit hostnames** in Talos machine config — never rely on platform
   auto-detection surviving upgrades. Use `HostnameConfig` with `auto: off` and explicit
   `hostname`, or `machine.network.hostname`.
2. **Always set explicit network interfaces** for platforms with one-time metadata
   sources (nocloud/cidata). The cidata disk is not available after kexec.
3. **Never run `tofu apply -auto-approve`** with `-target` flags that might pull in
   destructive upstream dependencies — always review the plan first
4. **Add `image` to `ignore_changes`** for `hcloud_server` resources — image changes
   should only happen via `talosctl upgrade`
5. **Verify `tofu plan` output** for `must be replaced` before applying — even targeted
   applies can cascade through dependencies
6. **Prefer `--reboot-mode powercycle`** when upgrading nodes without explicit hostname/IP
   in machine config, as a safety measure (slower but re-reads platform metadata)
7. **After any node hostname change**: check for pods with IPs outside the node's current
   `spec.podCIDR` and delete them. Check `kubectl get nodes.longhorn.io -n longhorn-system`
   for stale entries
8. **After any TF apply that touches nodes**: verify podCIDRs haven't changed
   (`kubectl get nodes -o custom-columns='NAME:.metadata.name,CIDR:.spec.podCIDR'`)

## Guidance for Future Talos Upgrades

When setting up new Talos nodes on any platform, always include in the machine config:

1. **Explicit hostname** — via `HostnameConfig` document or `machine.network.hostname`
2. **Explicit network config** — via `machine.network.interfaces` if the platform uses
   one-time metadata sources (nocloud cidata, VMware guestinfo, etc.)
3. **Explicit nameservers** — if not using DHCP

These settings are stored on the SYSTEM partition and survive all upgrade modes (kexec,
powercycle, staged). Platform metadata is a convenience for initial provisioning, not a
reliable source across the node lifecycle.

For platforms with persistent metadata APIs (Hetzner, AWS, GCP, Azure), explicit network
config is less critical (the API remains accessible after kexec), but explicit hostname is
still recommended because the platform controller may fail to fetch during the network
reinitialization window after kexec.

## Timeline

1. Added `iscsi-tools` to all Talos schematics (Hetzner + Proxmox)
2. Ran `talosctl upgrade` on vps0, vps1, and proxmox-cp — all succeeded but got random hostnames
3. Noticed hostname loss, decided to fix via Terraform (add explicit `machine.network.hostname`)
4. Ran `tofu apply -target=...machine_configuration_apply... -auto-approve`
5. Terraform resolved dependencies, planned VPS server replacement (image changed), executed it
6. Both VPS servers destroyed and recreated with fresh Talos — etcd quorum lost
7. Full cluster teardown and rebuild required
