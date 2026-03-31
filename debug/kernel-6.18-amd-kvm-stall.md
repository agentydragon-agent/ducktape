# Kernel 6.18 `pv_native_safe_halt` Stall on AMD KVM

## Status: PARTIAL WORKAROUND — `halt_poll_ns=0` fixes idle stalls only

Linux kernel 6.18 has a bug in the KVM paravirtualized idle halt path
(`pv_native_safe_halt`) that causes periodic CPU stalls on AMD hosts. Reproduces on a
completely idle VM within 38 seconds of boot. Kernel 6.12 is unaffected on the same host.

**Host**: Proxmox 8 on AMD Ryzen 9 9950X3D (Zen 5), `cpu: host` passthrough.
**Workaround**: `echo 0 > /sys/module/kvm/parameters/halt_poll_ns` on the host.
**Upstream**: Red Hat Bugzilla #2448303 (NEW, unresolved). Fedora discussion:
<https://discussion.fedoraproject.org/t/kvm-guests-become-unstable-on-6-18-kernel/182870>

## Workaround: Disable KVM Halt Polling (2026-03-30)

Setting `halt_poll_ns=0` on the host **eliminates idle stalls** (idle VM stable for 2+
minutes). However, **stalls still occur under real workload** (etcd, kubelet, apiserver
booting). There are likely multiple bug paths in the 6.18 AMD KVM code.

**Idle test**: Talos v1.12.3 (kernel 6.18.8) VM with `halt_poll_ns=0` on atlas:
1m55s uptime, CPU 0.3%, zero stalls, clean boot. Same kernel with default
`halt_poll_ns=200000` stalls within 38 seconds.

**Real workload test**: Same VM with `halt_poll_ns=0`, configured to join the cluster
(etcd + kubelet + apiserver). Stalled at 4m1s — NMI "unknown reason 30 on CPU 3" in
a `seq_read_iter` / `ufs_read` path. CPU 98.3%. The halt polling workaround is
insufficient when the VM is under load.

**Conclusion**: `halt_poll_ns=0` fixes one stall path (`pv_native_safe_halt` idle loop)
but there's at least one more bug in kernel 6.18 on AMD KVM that triggers under load.
The workaround alone is not sufficient for production use.

**Root cause (partial)**: KVM halt polling on AMD Zen 5. When a vCPU executes HLT
(idle), the host KVM module "polls" briefly before halting the vCPU. The polling
implementation in kernel 6.18 has a bug on AMD that causes the vCPU to get stuck.

**Apply**:

```bash
# Immediate (non-persistent):
echo 0 > /sys/module/kvm/parameters/halt_poll_ns

# Persistent (survives reboot) — add to host kernel cmdline or modprobe.d:
echo "options kvm halt_poll_ns=0" > /etc/modprobe.d/kvm-halt-poll.conf
```

**Trade-off**: Disabling halt polling may slightly increase VM exit latency for short
idle periods (microseconds). In practice, the impact is negligible for server workloads.
The default 200μs polling window is an optimization, not a requirement.

## Probable upstream cause: AMD Idle HLT Intercept (kernel 6.15)

LKML search found a **new AMD KVM feature** merged in kernel 6.15 that changes how
KVM handles guest HLT instructions on AMD:

- **Patch**: <https://lore.kernel.org/kvm/20241022054810.23369-1-manali.shukla@amd.com/T/>
- **Author**: Manali Shukla (AMD)
- **Reviewer**: Sean Christopherson (KVM maintainer) — flagged nested support as
  "99% certain wrong", deferred to later
- **Phoronix coverage**: <https://www.phoronix.com/news/Linux-6.15-KVM>

The feature conditionally intercepts HLT based on pending `V_INTR` / `V_NMI` instead
of always intercepting. If there's a race where pending events are missed, the vCPU
sleeps when it shouldn't — causing exactly the stalls we observe in `pv_native_safe_halt`.

This landed in 6.15, between our known-good 6.12 and known-bad 6.18. The
`halt_poll_ns=0` workaround likely works because it changes the host-side behavior
around the HLT exit, sidestepping the buggy conditional intercept path.

**Next steps to confirm**: Test kernel 6.14 vs 6.15 guests (6.14 should be fine, 6.15
should stall). File on `kvm@vger.kernel.org` with bisect data + CC Manali Shukla and
Sean Christopherson.

## Bisect (2026-03-30)

Two throwaway VMs on atlas, identical config (4 cores, 4 GiB, `cpu: host`, virtio-gpu,
`balloon: 0`, no cluster, no workload):

- **Talos v1.11.6 (kernel 6.12.62)**: Clean boot, stable, no issues.
- **Talos v1.12.3 (kernel 6.18.8)**: **RCU stall + NMI within 38 seconds of boot**
  while idle. CPU stuck in `pv_native_safe_halt` (idle loop). NMI sent from CPU 3 to
  CPU 2. No workload running.

The stall is in `pv_native_safe_halt` — the KVM paravirt halt path. All earlier stalls
observed in production (page allocator, XFS, slab) were just whatever code happened to
be running when the CPU came out of the broken halt.

## Symptoms

- Periodic CPU stalls every ~38s to ~5 min (depends on load)
- RCU stalls: `rcu_sched detected stalls on CPUs/tasks`
- NMIs: `Uhhuh. NMI received for unknown reason N on CPU M`
- Health check `DeadlineExceeded` across all services
- Stack traces in arbitrary kernel paths (page allocator, XFS, slab, idle)
- CPU usage spikes to 90%+
- Node recovers after each stall but etcd/kubelet health checks fail during it

## What was ruled out

| Hypothesis              | Test                                  | Result        |
| ----------------------- | ------------------------------------- | ------------- |
| QXL VGA driver          | Switched to virtio-gpu                | Still stalls  |
| Memory balloon          | Disabled balloon                      | Still stalls  |
| Host NMI watchdog       | `nmi_watchdog=0` on host              | Still stalls  |
| CPU passthrough         | Changed to `cpu: x86-64-v3`           | Still stalls  |
| `init_on_alloc=1`       | Can't disable (baked into Talos UKI)  | N/A           |
| VM instance state       | Fresh VM, fresh disk                  | Still stalls  |
| Resource pressure       | 43% RAM, <1% steal, 20% CPU           | Not the cause |
| Fedora `migratable=off` | `cpu: x86-64-v3` doesn't pass through | Still stalls  |

## What works

- Same Talos v1.12.3 on Hetzner Intel KVM — fine
- NixOS kernel 6.12 on same AMD host (wyrm2, 32 vCPUs) — fine
- Talos v1.11.6 (kernel 6.12) on same AMD host — fine (bisect confirmed)

## Impact on cluster

The Proxmox control plane node (`talos-pve-cp-0`) runs Talos v1.12.3. The stalls cause:

1. etcd health check failures → intermittent quorum issues
2. Operator leader election losses → restart cascades → pod churn on wyrm2
3. Pod churn → Chrome `ERR_NETWORK_CHANGED` on wyrm2 (see below)

Cascading failure on 2026-03-30: removing pve-cp-0 during debugging left 2-member etcd.
VPS nodes (no `NoSchedule` taint) absorbed workload pods → OOM → nebula tunnel broke →
etcd no leader → full cluster outage. See <debug/wyrm2-chrome-network-changed.md>.

## Options

1. **Run 2-member etcd (no Proxmox CP)**: Simple but zero fault tolerance.
2. **Tolerate the stalls**: v1.12.3 stalls but recovers. Provides 3rd etcd member.
3. **Downgrade entire cluster K8s to ~1.32**: Allows Talos v1.11.6 everywhere. Very
   disruptive.
4. **Custom Talos image with kernel 6.12**: Build via `siderolabs/pkgs`. Complex but
   preserves K8s 1.35.1.
5. **Wait for upstream fix**: Monitor Red Hat Bugzilla #2448303 and kernel changelogs.
6. **Run etcd outside Talos**: On wyrm2 NixOS. Unconventional.

**Recommended**: Option 2 (tolerate) + Option 5 (wait). Add `NoSchedule` taints to VPS
nodes to prevent OOM cascade.

## Investigation timeline

- **2026-03-23**: First NMI incident on talos-pve-cp-0 (incident 1)
- **2026-03-25**: Second NMI (incident 2), third incident as RCU stall (no NMI)
- **2026-03-25**: Ruled out QXL, balloon, NMI watchdog, resource pressure, `ostype`
- **2026-03-26**: Ruled out instance-specific state (fresh VM reproduces)
- **2026-03-26**: Found Fedora report (Bugzilla #2448303), `cpu: x86-64-v3` didn't help
- **2026-03-26**: Confirmed `init_on_alloc=0` can't be set (Talos UKI/SDBoot)
- **2026-03-26**: Confirmed v1.12.6 (kernel 6.18.18) has no KVM fixes
- **2026-03-30**: Cluster outage from VPS OOM during debugging
- **2026-03-30**: v1.11.6 downgrade blocked (K8s 1.35.1 incompatible)
- **2026-03-30**: **Bisect confirmed**: kernel 6.18 stalls in `pv_native_safe_halt`
  within 38s on idle VM. Kernel 6.12 fine.

## Next investigation steps

### High priority (can run in parallel, ~5 min each)

1. **LKML search with precise keyword**: Now that we know the exact function, search
   `pv_native_safe_halt AMD 6.18 regression` on lore.kernel.org. Much more targeted
   than previous searches. May find the exact commit or an existing fix.

2. **Parallel kernel version bisect**: Spin up 6 VMs simultaneously on atlas, one per
   kernel minor version (6.13, 6.14, 6.15, 6.16, 6.17, 6.18). The stall appears in
   <60 seconds, so one round of screenshots after 2 minutes identifies exactly which
   minor version introduced the regression. Use Talos Image Factory or generic distro
   ISOs. This narrows the search from "somewhere in 6.13-6.18" to a single version,
   making `git bisect` on the kernel source feasible.

3. **Host-side KVM parameter tests**: Toggle `kvm_amd` module parameters on atlas that
   affect the halt path. Each is a quick `echo` to `/sys/module/kvm_amd/parameters/`
   or module reload, then boot a test VM:
   - `halt_poll_ns=0` — disable halt polling (most likely to help)
   - `avic=0` — disable AMD virtual interrupt controller
   - `npt=0` — disable nested page tables
     If one of these fixes it, we have an immediate workaround.

### Medium priority

4. **Read kernel source diff**: `pv_native_safe_halt` is tiny. Read the diff between
   6.12 and 6.18 for the halt path and its callers:

   ```
   git log v6.12..v6.18 -- arch/x86/kernel/paravirt.c arch/x86/kvm/
   ```

   The bug is probably in something that changed around the function (the `do_idle`
   caller, KVM halt polling, or the AMD-specific halt exit handler).

5. **Test non-Talos kernel 6.18**: Boot a generic distro live ISO (Fedora, Arch) with
   kernel 6.18 as a KVM guest on atlas. If it also stalls → pure kernel bug. If stable
   → something in Talos's kernel config triggers it (e.g., specific `CONFIG_PARAVIRT`
   options, `init_on_alloc=1`, KSPP hardening flags).

6. **Test `idle=poll` kernel arg**: If we can boot a non-Talos kernel 6.18 with
   `idle=poll` (bypasses `pv_native_safe_halt` entirely) and it doesn't stall, that
   confirms the halt path is the sole issue and `idle=poll` is a workaround (at the
   cost of 100% CPU on idle cores).

### Cluster TODOs

- [ ] Add `NoSchedule` taints to VPS control plane nodes
- [ ] Decide: tolerate stalls (option 2) or run 2-member etcd (option 1)
- [ ] File upstream Talos issue linking bisect results + Bugzilla #2448303
- [ ] Monitor Red Hat Bugzilla #2448303 for upstream fix

## Related

- <debug/pve-cp0-notready-2026-03-23/README.md> — original NMI incident investigation
- <debug/wyrm2-chrome-network-changed.md> — Chrome ERR_NETWORK_CHANGED (downstream effect)
- <debug/atlas/wyrm2-freezes.md> — wyrm2 QXL TTM bug (different issue, resolved)
