# Bootstrap Investigation Diary

## 2026-02-11 05:11 UTC — Bootstrap #2 (kyverno dependency fix)

### What Changed Since Last Bootstrap

Commit `52a58797` added `dependsOn: kyverno` to:

- `k8s/cert-manager-trust/flux-kustomization.yaml`
- `k8s/ingress-nginx/flux-kustomization.yaml`

### Infrastructure Apply

All 4 nodes came up successfully:

- talos-vps-cp-0 (5.78.106.249) — Ready
- talos-vps-cp-1 (5.78.43.147) — Ready
- talos-pve-cp-0 (10.2.1.1) — Ready
- talos-pve-worker-0 (10.2.2.1) — Ready

Cilium deployed, all nodes Ready within ~2 minutes of bootstrap.

### Flux Convergence — What Worked

| Kustomization          | Status       | Notes                                  |
| ---------------------- | ------------ | -------------------------------------- |
| kyverno                | ✅ Ready     | Health check passed in 55.2s           |
| kyverno-policies       | ✅ Ready     | Applied 1s after kyverno               |
| cert-manager           | ✅ Ready     |                                        |
| **cert-manager-trust** | **✅ Ready** | **FIX VERIFIED — no webhook timeout!** |
| sealed-secrets         | ✅ Ready     |                                        |
| metrics-server         | ✅ Ready     |                                        |
| reloader               | ✅ Ready     |                                        |

### Flux Convergence — What Failed

| Kustomization | Status    | Error                               |
| ------------- | --------- | ----------------------------------- |
| core          | ❌ Failed | tofu-controller HelmRelease stalled |
| ingress-nginx | ❌ Failed | HelmRelease failed                  |

Both failures are the same kyverno webhook timeout:

```text
failed calling webhook "validate.kyverno.svc-fail": context deadline exceeded
```

### Timeline Analysis

```text
T+0s    kyverno HelmRelease install succeeded
T+3s    kyverno kustomization health check passed (VWC exists, deployment ready)
T+4s    tofu-controller HelmChart created (core kustomization started)
T+8s    tofu-controller chart pulled
T+21s   tofu-controller INSTALL FAILED — kyverno webhook timeout
T+24s   core kustomization health check failed
```

### Key Observation: Dependency Was Met

Both `core` and `ingress-nginx` kustomizations correctly depend on kyverno.
Kyverno WAS ready before they started. The webhook timeout happened AFTER the
dependency was satisfied.

### Root Cause Hypothesis: Cross-Node VXLAN Convergence

Kyverno admission-controller is running on `talos-pve-worker-0` (Proxmox, 10.2.2.1).
The API server is on VPS nodes. Webhook calls require VPS → Proxmox pod networking
via VXLAN tunnel, which goes through KubeSpan (WireGuard).

In previous bootstrap (earlier this session), we observed that cross-node VXLAN
tunnels take ~5-10 minutes to fully converge. The kyverno kustomization health
check passes (VWC exists, deployment ready) before VXLAN tunnels are fully stable.

**The VWC existence check is necessary but not sufficient** — it proves the webhook
was registered, but not that the API server can reliably reach the webhook pod
across the VXLAN tunnel.

### Resource Usage at Time of Failure

```text
NODE                 CPU    MEM
talos-pve-cp-0       1%     17%
talos-pve-worker-0   0%     9%
talos-vps-cp-0       4%     24%
talos-vps-cp-1       4%     24%

kyverno-admission-controller: 3m CPU, 41Mi memory
```

**No overloading.** Pure transient network issue.

### Current State

- tofu-controller and ingress-nginx HelmReleases stuck in Failed with no auto-retry
  (retries: `<none>`)
- cert-manager-webhook-powerdns also failing (different issue — likely depends on
  PowerDNS which isn't deployed yet)
- Everything downstream of core and ingress-nginx is blocked

### Fix Options

1. **Add install.remediation.retries to affected HelmReleases** — This is the correct
   fix for transient failures. This isn't masking a dependency bug (the dependency IS
   correct), it's handling the reality that webhook calls can transiently fail during
   cluster convergence.

2. **Pin kyverno to VPS nodes** — Would eliminate the cross-node latency for webhook
   calls. But kyverno should work on any node.

3. **Add a post-kyverno delay** — Hacky, not deterministic.

### 05:20 UTC — Deeper Investigation

#### KubeSpan Peer Status (from vps-cp-0)

| Peer               | Endpoint                  | State       | RX       | TX       |
| ------------------ | ------------------------- | ----------- | -------- | -------- |
| talos-vps-cp-1     | 5.78.43.147:51820         | up          | 43MB     | 100MB    |
| talos-pve-cp-0     | 98.51.154.161:27949 (NAT) | up          | 28MB     | 79MB     |
| talos-pve-worker-0 | 98.51.154.161:51820 (NAT) | **up**      | **56KB** | **52KB** |
| talos-pve-worker-0 | 98.51.154.161:51820 (NAT) | **unknown** | 0        | 24KB     |

**Key finding**: pve-worker-0 has two KubeSpan entries:

- One `up` with only 56KB traffic (barely established)
- One `unknown` with 0 bytes received (never handshaked)

Compare to pve-cp-0 which has 28MB traffic — the worker tunnel is orders of magnitude
less established. Both go through same NAT (98.51.154.161) which is atlas's public IP.

#### Kyverno Admission Controller Logs

```text
05:13:27 TLS handshake error from 10.244.0.60:38118: EOF
05:14:19 TLS handshake error from 10.244.0.60:45058: EOF
05:14:46 TLS handshake error from 10.244.0.60:58668: EOF
```

10.244.0.x is talos-vps-cp-1's pod CIDR. The API server on vps-cp-1 tried
to reach the kyverno webhook on pve-worker-0 and got TLS EOF.

**This is the smoking gun**: The VXLAN tunnel from vps-cp-1 to pve-worker-0 was
unstable when the webhook call happened. The TLS handshake bytes got lost or the
connection was reset mid-handshake.

#### Cilium Health Matrix (at 05:20, ~8 minutes after failure)

```text
vps-cp-1 → pve-worker-0: ICMP OK (32ms), HTTP OK (28ms)
vps-cp-1 → pve-cp-0:     ICMP OK (41ms), HTTP OK (35ms)
vps-cp-1 → vps-cp-0:     ICMP OK (0.9ms), HTTP OK (0.8ms)
```

All connectivity OK at 05:20 — **confirms the issue was transient**.

#### Node Resource Usage

- All nodes: 0-4% CPU, 4-24% memory
- Kyverno admission-controller: 3m CPU, 41Mi memory
- **No overloading whatsoever**

### Analysis: Why pve-worker-0 KubeSpan Was Slow

The two Proxmox nodes share the same NAT gateway (98.51.154.161 = atlas public IP).
pve-cp-0 established its tunnel quickly (already at 28MB by 05:20), but pve-worker-0
was barely connected (56KB). Possible reasons:

1. **NAT port mapping conflict**: Both Proxmox VMs go through the same NAT. WireGuard
   uses the same port (51820). NAT might have trouble differentiating the two.
2. **Worker joined later**: Worker node's etcd membership was established after CP nodes.
   KubeSpan discovery relies on Kubernetes membership — worker joined ~30s after CP.
3. **Endpoint discovery delay**: KubeSpan checks discovery every ~15s. Worker might
   have taken an extra cycle to register its endpoint.

### Deeper Question: Is This a Systemic Issue?

This isn't a one-time fluke — it's a structural problem:

- The cluster has cross-datacenter nodes (VPS in Hetzner, Proxmox at home)
- KubeSpan WireGuard tunnels go through NAT
- During bootstrap, tunnels converge over several minutes
- Kyverno webhook on Proxmox worker is unreachable from VPS during this window
- Any `failurePolicy: Fail` webhook will cause install failures

### Fix Options (Revised)

**Option A**: Pin kyverno admission-controller to VPS nodes (avoid cross-node webhook calls)

- Pros: Eliminates the latency/convergence issue entirely
- Cons: Less flexible scheduling, all webhook traffic stays on VPS
- Implementation: `nodeSelector` or `affinity` on kyverno admission-controller

**Option B**: Ensure reliable cross-node networking BEFORE deploying kyverno

- This is the "fix the root cause" approach
- Would need to add a connectivity test step between infra and services deployment
- E.g., bootstrap.py runs a cross-node ping test before applying services

**Option C**: Add install.remediation.retries to all HelmReleases

- Not addressing root cause — user explicitly rejected this approach
- Would work pragmatically but masks the networking issue

**Option D**: Investigate KubeSpan NAT issue

- Why does pve-worker-0 take longer to establish KubeSpan than pve-cp-0?
- Both go through same NAT — is there a port conflict?
- Could we use different WireGuard ports per node?

---

## 05:25 UTC — Discovery Service Dual-Identity Root Cause Found

### Raw Affiliate Data (the Smoking Gun)

Checked `cluster-raw` namespace — ALL 7 affiliates come from the discovery service
(`service/` prefix). There are ZERO `k8s/` prefixed entries.

```text
service/1kwR... → talos-vps-cp-1   (version 2, addr ...e9b4) ← ACTIVE
service/xWm7... → talos-vps-cp-1   (version 1, addr ...c8c6) ← STALE
service/G8nv... → talos-vps-cp-0   (version 3, addr ...e9b5) ← ACTIVE
service/vEMU... → talos-vps-cp-0   (version 1, addr ...c8c7) ← STALE
service/exnj... → talos-pve-cp-0   (version 1, addr ...5c8e) ← ACTIVE
service/56hO... → talos-pve-worker-0 (version 1, addr ...93ee) ← ACTIVE
service/Q0hA... → talos-pve-worker-0 (version 1, addr ...16f8) ← STALE
```

Each node has TWO different `nodeId` values and TWO different IPv6 addresses.
The active entry has version > 1 (being updated). The stale entry stays at version 1.

### Each Node's Current Identity vs Stale

| Node         | Current IPv6 | Stale IPv6  | Active Key | Stale Key   |
| ------------ | ------------ | ----------- | ---------- | ----------- |
| vps-cp-0     | ...e9b5      | ...c8c7     | h/N5...    | (different) |
| vps-cp-1     | ...e9b4      | ...c8c6     | +oak...    | (different) |
| pve-cp-0     | ...5c8e      | (different) | 98fE...    | (different) |
| pve-worker-0 | ...93ee      | ...16f8     | TXJWl...   | (different) |

### Root Cause: Install-to-Disk Identity Regeneration

The KubeSpan identity (WireGuard keypair) is generated per-node and stored on the
STATE partition at `/.STATE/kubespan/identity.yaml`.

**During bootstrap, each node goes through TWO boots:**

1. **First boot** (from cloud-init/ISO): Talos runs in memory, generates
   KubeSpan identity A, registers with `discovery.talos.dev`
2. **Config apply** → triggers install to disk → node reboots
3. **Second boot** (from disk): New STATE partition → generates identity B,
   registers with discovery service
4. Identity A is still in discovery service with 30-minute TTL
5. Both A and B coexist → 7 peer entries instead of 3

**Source code reference** (Talos identity generation):

- `internal/app/machined/pkg/controllers/kubespan/identity.go` — `LoadOrNewFromFile()`
  loads existing identity from STATE or generates new one via `wgtypes.GeneratePrivateKey()`
- The identity is NOT derived from machine secrets — it's independently generated
- Each new STATE partition means a new identity

### Confirmation: Stale Entries Cleaned Up at ~30 Minutes

At 05:20 (12 minutes after boot): 7 peer entries, 7 affiliates
At 05:38 (30 minutes after boot): 3 peer entries, 4 affiliates (stale cleaned up by TTL)

### Impact on Bootstrap Reliability

**The first ~30 minutes after bootstrap, every node has a phantom twin in the
KubeSpan mesh.** This means:

- WireGuard tries to establish tunnels to stale (non-existent) identities
- Each 30-second reconciliation cycle processes 7 peers instead of 3
- Cross-node tunnels compete with phantom tunnels for NAT port mappings
- The Proxmox nodes behind NAT are especially affected — their phantom twin
  has the same NAT gateway, causing potential port mapping confusion

This explains why pve-worker-0 was slower to converge — it was competing with
its own phantom for the same NAT endpoint.

### Members Resource Shows Stale IDs

The `members` resource (discovery-based) references the STALE nodeIDs:

```text
talos-vps-cp-0: nodeId vEMU... (STALE identity)
talos-vps-cp-1: nodeId xWm7... (STALE identity)
```

While the active identities are different (G8nv... and 1kwR... respectively).
This suggests the members resource was populated from the first boot's registration
and hasn't been updated with the post-install identity.

### Potential Fixes (Root Cause Level)

**Option E**: Prevent identity regeneration on install-to-disk

- If machine config could include a pre-generated KubeSpan identity (derived from
  machine secrets or specified in config), the identity would survive the install-to-disk
  reboot.
- Talos config has `machine.network.kubespan` but no field for identity/key.
- This would need an upstream Talos change or a creative workaround.

**Option F**: Clear discovery registrations during bootstrap

- After `talos_machine_bootstrap`, but before deploying services, run something
  that causes the old discovery entries to be evicted
- Could be a custom step in bootstrap.py that waits for discovery cleanup

**Option G**: Wait for discovery convergence before deploying services

- Add a step in bootstrap.py that checks `talosctl get kubespanpeerstatuses` and
  waits until the number of peers equals (node_count - 1)
- Only proceed with services layer after KubeSpan is fully converged
- This is declarative (the check is in the bootstrap script) and addresses root cause

---

## 05:40 UTC — VPS Boot Flow Analysis: Can We Avoid the Reboot?

### Current VPS Boot Flow (ISO-based)

```text
1. hcloud_server created: image=debian-12, iso=122630 (Talos ISO), user_data=machine_config
2. Server boots from ISO → Talos runs in RAM, STATE on tmpfs → identity A generated
3. talos_machine_configuration_apply: machine.install.disk = "/dev/sda"
4. Talos installs to /dev/sda → reboot
5. Talos boots from disk → new STATE partition → identity B generated
6. terraform_data.detach_iso removes ISO mount
```

**Two Talos boots = two identities.** The reboot in step 4 is mandatory — Talos
running from ISO is entirely in RAM, `install.disk` causes write-to-disk + reboot.
You can't "just unmount the ISO."

### Proxmox Boot Flow (disk-image-based, for comparison)

```text
1. QCOW2 downloaded from Image Factory (nocloud platform)
2. QCOW2 imported into VM disk via proxmox_virtual_environment_download_file
3. VM boots from disk → Talos starts, STATE partition empty → identity A generated
4. talos_machine_configuration_apply updates config in-place
5. No reinstall, no reboot — identity A persists
```

**One Talos boot = one identity.** No install-to-disk reboot needed.

### Image Factory Platform Support

Talos Image Factory supports `hcloud` platform:

- Source: `siderolabs/talos/pkg/machinery/platforms/platforms.go`
- Output: `hcloud-amd64.raw.xz` (raw disk image, xz-compressed)
- Boot methods: `BootMethodDiskImage` only (no ISO from factory)
- The `talos_image_factory_urls` data source returns `urls.disk_image` for hcloud

The clean disk image has an EMPTY STATE partition — each server would generate
its own unique identity on first boot.

### Problem: Hetzner Doesn't Support Direct Disk Image Upload

Hetzner Cloud API has no endpoint for uploading raw disk images. You can only:

- Create servers from stock images (debian-12, ubuntu-24.04, etc.)
- Create servers from snapshots of existing servers

### Potential Solutions

#### Option H: Rescue Mode + DD (most promising)

```text
1. hcloud_server created with image=debian-12 (no ISO)
2. Enable rescue mode on server → reboot into rescue Linux
3. In rescue: download Talos hcloud disk image, dd to /dev/sda
4. Disable rescue, reboot → Talos boots from disk (first boot)
5. STATE partition created, identity generated (once)
6. talos_machine_configuration_apply → config updated, no reinstall
```

Two reboots but only ONE Talos boot. Identity generated once, persists.

Implementation: terraform provisioner SSHs into rescue system, runs dd.
Complexity: SSH into rescue, timing, error handling.

#### Option I: Snapshot from builder (has a gotcha!)

```text
1. Boot temporary server from Talos ISO → install to disk
2. Take snapshot → delete temp server
3. Boot real VPS nodes from snapshot
```

**PROBLEM**: All nodes from same snapshot share the same STATE partition contents,
including KubeSpan identity. All nodes would have the SAME WireGuard key!
This is WORSE than the dual-identity problem.

Unless the snapshot is taken BEFORE Talos initializes STATE (i.e., immediately
after install but before first real boot). But snapshots of powered-off servers
might not work reliably.

#### Option G (revisited): Wait for convergence

Simplest approach — add to bootstrap.py:

```bash
echo "Waiting for KubeSpan convergence..."
while true; do
  peers=$(talosctl -n $BOOTSTRAP_IP get kubespanpeerstatuses -o json | jq length)
  if [ "$peers" -eq "$((NODE_COUNT - 1))" ]; then
    all_up=$(talosctl -n $BOOTSTRAP_IP get kubespanpeerstatuses -o json | \
      jq '[.[].spec.state] | all(. == "up")')
    if [ "$all_up" = "true" ]; then
      echo "KubeSpan fully converged ($peers peers, all up)"
      break
    fi
  fi
  echo "  $peers peers, waiting..."
  sleep 10
done
```

Doesn't fix dual-identity root cause but ensures network stability before
deploying services. The stale entries clean up at 30-min TTL.

### Analysis: Which Option Addresses Root Cause?

| Option        | Fixes dual identity? | Fixes webhook timeout?                  | Complexity             |
| ------------- | -------------------- | --------------------------------------- | ---------------------- |
| H (rescue+dd) | ✅ Yes               | ✅ Yes (single identity, fast converge) | High                   |
| I (snapshot)  | ❌ Worse             | ❌ Worse                                | Medium                 |
| G (wait)      | ❌ No (still dual)   | ✅ Yes (waits for stability)            | Low                    |
| E (upstream)  | ✅ Yes               | ✅ Yes                                  | Blocked (Talos change) |

### Recommendation

**Short-term**: Option G (wait for convergence) — minimal changes, directly prevents
the webhook timeout that triggered this investigation.

**Long-term**: Option H (rescue+dd) — eliminates the dual-identity root cause,
makes VPS boot flow consistent with Proxmox.
