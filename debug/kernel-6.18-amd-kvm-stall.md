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

## Host vs Guest Interaction (2026-03-31)

**Host kernel**: 6.17.13-1-pve (Proxmox). Has the Idle HLT Intercept feature (merged
6.15) in its kvm_amd module.

**Key observation**: v1.11.6 guest (kernel 6.12) runs clean on this host — zero NMIs,
zero stalls after 5+ minutes in maintenance mode. Same host, same kvm_amd module,
same `halt_poll_ns=0`. v1.12.3 guest (kernel 6.18) stalls within minutes.

**Conclusion**: The bug is an **interaction** between the guest kernel 6.18 and the
host's kvm_amd, not purely a host-side or guest-side bug. The guest kernel 6.18 does
something differently (new paravirt halt mechanism, different HLT usage pattern, or
different interrupt handling) that triggers the buggy host-side code path. Kernel 6.12
guests avoid the buggy path.

**kvm_amd parameters investigated**: No `idle_hlt_intercept` parameter exists. `vnmi=Y`
(read-only, can't test without module reload). `npt=Y` (read-only). Only
`dump_invalid_vmcb` is writable at runtime. Testing `vnmi=N` or `npt=N` requires
stopping all VMs and reloading kvm_amd — disruptive since wyrm2 runs on the same host.

**Load stall under `halt_poll_ns=0`**: VM 10000 (v1.12.3) stalled at 2m3s with a TLB
flush stack trace (`flush_tlb_mm_range` → `do_wp_page` → `__handle_mm_fault`). NMI on
CPU 3. This is yet another arbitrary kernel path, confirming the stall mechanism is
CPU-level, not subsystem-specific.

## Host Kernel Data (2026-03-31)

**Current host kernel**: `6.17.13-1-pve` (Proxmox)
**Available boot entries**: `6.17.13-1-pve`, `6.17.9-1-pve`, `6.8.12-18-pve`
**Upgradable**: `proxmox-kernel-6.17` → `6.17.13-2`, `proxmox-kernel-6.8` → `6.8.12-20`

**Key code path** (from svm.c source analysis):

```c
if (!kvm_hlt_in_guest(vcpu->kvm)) {
    if (cpu_feature_enabled(X86_FEATURE_IDLE_HLT))
        svm_set_intercept(svm, INTERCEPT_IDLE_HLT);   // ← NEW path on Zen 5
    else
        svm_set_intercept(svm, INTERCEPT_HLT);         // ← old path
}
```

AMD Zen 5 (9950X3D) advertises `X86_FEATURE_IDLE_HLT`, so the host's kvm_amd uses
`INTERCEPT_IDLE_HLT` instead of the traditional `INTERCEPT_HLT`. No module parameter
exists to disable this — it's keyed off CPU feature detection.

**Critical test available**: Reboot atlas into kernel **6.8.12-18-pve** (pre-6.15, before
Idle HLT Intercept was merged). If guest stalls disappear on host kernel 6.8, it confirms
the bug is in the **host's** kvm_amd, not the guest kernel. The guest kernel 6.18 merely
triggers the host-side bug; an older host avoids it entirely.

This would also confirm the `X86_FEATURE_IDLE_HLT` / `INTERCEPT_IDLE_HLT` code path as
the root cause, since it doesn't exist in kernel 6.8.

## Targeted Fix: `clearcpuid=510` (2026-03-31)

LKML/source research found: `X86_FEATURE_IDLE_HLT` = bit 510 (word 15, bit 30). The
feature is auto-enabled by CPU feature detection (`cpu_feature_enabled()`), with **no
module parameter** to disable it. But the kernel supports `clearcpuid=N` boot parameter
to mask individual CPUID bits.

**`clearcpuid=510`** on the **host** kernel cmdline forces the old `INTERCEPT_HLT` path
instead of `INTERCEPT_IDLE_HLT`. This is the most targeted possible fix — disables only
the Idle HLT Intercept while keeping everything else on kernel 6.17.

The two bugs may be coupled via the V_NMI interaction:

- Idle HLT Intercept suppresses VMEXITs when `V_NMI_PENDING` is set
- If V_NMI pending state is incorrect, spurious NMIs are delivered to the guest
- This explains both: idle stalls (HLT exit suppressed) and load NMIs (spurious NMI
  injection from incorrectly pending V_NMI)

**Alternative**: `kvm_amd.vnmi=0` would disable vNMI entirely (requires module reload).
Could fix the "unknown reason 30" NMIs independently. But `clearcpuid=510` is cleaner
since it targets the root feature.

**Test**: Add `clearcpuid=510` to atlas kernel cmdline, reboot, verify both idle and
load stalls are gone.

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

## Current Fix: `clearcpuid=510` on host (pending reboot)

Applied in `ansible/atlas.yaml` kernel cmdline + `halt_poll_ns=0` in modprobe.d.
Requires atlas reboot to take effect. After reboot, VMs should start clean.

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

## After Reboot Checklist

1. **Verify `clearcpuid=510` took effect**:

   ```bash
   cat /proc/cmdline | grep clearcpuid
   dmesg | grep -i idle_hlt  # should show nothing (feature disabled)
   ```

2. **Verify `halt_poll_ns=0` persisted** (from modprobe.d):

   ```bash
   cat /sys/module/kvm/parameters/halt_poll_ns  # should be 0
   ```

3. **Quick idle test**: Boot a throwaway v1.12.3 VM (9901), wait 2 min, screenshot.
   Should be clean (no stalls, no NMIs).

4. **Load test**: If idle test passes, check pve-cp-0 (VM 10000) — it should boot,
   join etcd, and reach Ready without stalling.

5. **Uncordon VPS nodes** once pve-cp-0 is Ready and etcd has 3 members:

   ```bash
   kubectl uncordon talos-vps-cp-0
   kubectl uncordon talos-vps-cp-1
   ```

6. **If `clearcpuid=510` doesn't fix load stalls**: Try also adding `kvm_amd.vnmi=0`
   to the kernel cmdline (disables vNMI entirely). Or fall back to host kernel
   6.8.12-18-pve (already installed, select at boot).

## TODOs

- [ ] Add `NoSchedule` taints to VPS control plane nodes (prevent OOM cascade)
- [ ] File upstream bug on `kvm@vger.kernel.org` with bisect data + `clearcpuid=510`
      finding, CC Manali Shukla and Sean Christopherson
- [ ] File Talos issue linking to the upstream bug
- [ ] Monitor Red Hat Bugzilla #2448303 for upstream fix
- [ ] Remove `clearcpuid=510` and `halt_poll_ns=0` workarounds once fix lands

## Related

- <debug/pve-cp0-notready-2026-03-23/README.md> — original NMI incident investigation
- <debug/wyrm2-chrome-network-changed.md> — Chrome ERR_NETWORK_CHANGED (downstream effect)
- <debug/atlas/wyrm2-freezes.md> — wyrm2 QXL TTM bug (different issue, resolved)
