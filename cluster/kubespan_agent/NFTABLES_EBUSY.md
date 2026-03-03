# nftables EBUSY on GHA Runners

kubespand's nftables `Flush()` returns `EBUSY` deterministically on GitHub
Actions runners (Azure VMs, kernel 6.x) when the batch contains **mark
expressions**. This blocks `TestKubeSpanNetworking` (full WireGuard mesh test)
in CI.

## Graduated Smoke Test Results

`TestNftablesSmoke` runs 6 levels inside Docker containers, each adding one
nftables feature kubespand uses. Each level runs on two network modes:
`--network=none` (clean netns) and default bridge (Docker iptables-nft state
present).

| Level | What it adds                                        | network-none | default-bridge |
| ----- | --------------------------------------------------- | :----------: | :------------: |
| 1     | table + chains with hooks (separate batches)        |     PASS     |      PASS      |
| 2     | + anonymous interval set + lookup rule              |     PASS     |      PASS      |
| 3     | + rules with `Meta{Key:MetaKeyMARK}` + `Bitwise`    |   **FAIL**   |    **FAIL**    |
| 4     | all of level 3 in single `New()`+`Flush()` batch    |   **FAIL**   |    **FAIL**    |
| 5     | + `FlushChain` (re-install over existing state)     |   **FAIL**   |    **FAIL**    |
| 6     | full kubespand pattern (dual-stack sets, MSS clamp) |   **FAIL**   |    **FAIL**    |

CI run: `22618913076` (commit `b34f715`).

## What We Know

1. **Mark expressions are the trigger.** Level 2 (anonymous interval sets +
   lookup + verdict) passes. Level 3 (adds `meta mark` read + `Bitwise` mask +
   `meta mark` write) fails. The only difference is the mark-related
   expressions.

2. **Docker's bridge networking is NOT the cause.** Levels 3-6 fail identically
   on `--network=none` containers that have 0 existing tables and 0 existing
   chains. The earlier theory about Docker's nat table holding
   `nf_tables_commit_mutex` was wrong.

3. **The failure is deterministic, not a race.** EBUSY persists through 200
   retries over 30+ seconds. If it were simple mutex contention (some other
   process briefly holding the lock), retries would eventually succeed.

4. **Basic nftables operations work fine.** Creating tables, adding chains with
   hook registrations (prerouting filter, output route), adding anonymous
   interval sets, flushing — all succeed. The kernel nftables subsystem is
   functional.

## What We Don't Know

- **Why mark expressions specifically cause EBUSY.** The kernel returns EBUSY
  from `nf_tables_commit()`. Possible mechanisms:
  - A kernel module required by `nft_meta` mark set/get isn't loaded in the
    container namespace, causing a commit-time validation failure that surfaces
    as EBUSY rather than ENOENT.
  - A kernel bug in the 6.x series on Azure VMs where mark expression
    validation interacts badly with network namespace isolation.
  - The `Bitwise` expression combined with mark write triggers a code path
    that checks for something unavailable in containers.

- **Whether this reproduces outside GHA.** We haven't tested on other CI
  platforms or local QEMU VMs.

## Disproven Theories

- **Docker iptables-nft contention**: Docker's daemon continuously manages
  iptables-nft rules (nat table) in bridge-networked containers. We initially
  theorized this held `nf_tables_commit_mutex`, blocking kubespand. Disproven:
  `--network=none` containers with no Docker nftables state fail identically.

- **Mutex race condition**: Simple mutex contention from another process would
  produce intermittent failures, not deterministic 30-second EBUSY. The failure
  pattern suggests a state/validation error, not a timing race.

## Upstream References

- kubernetes/kubernetes#122604, #128829 — kube-proxy nftables EBUSY
- containers/podman#23404 — netavark nftables EBUSY
- siderolabs/talos#9426, #8498 — KubeSpan nftables EBUSY
- Talos CI: all KubeSpan tests use `e2e-qemu` (VMs), never Docker containers

## Path Forward

Testing kubespand's nftables rules requires real VMs. Options:

1. **`talosctl cluster create --provisioner=qemu`** — spin up Talos QEMU VMs,
   deploy kubespand as a privileged DaemonSet. Real kernel, no container
   nftables restrictions.

2. **Lightweight VM harness** (Firecracker/cloud-hypervisor) — run kubespand
   directly in minimal Linux VMs. Faster than full Talos but more setup.

3. **Self-hosted runner with real VMs** — GHA self-hosted runner on hardware
   where nftables mark expressions work.

See `TestKubeSpanNetworking` in `e2e_test.go` (gated behind
`KUBESPAN_TEST_NETWORKING=1`).
