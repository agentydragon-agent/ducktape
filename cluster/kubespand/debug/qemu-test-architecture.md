# QEMU Test Architecture

## VM Init Binaries

Each VM topology has its own PID-1 init binary in `qemu_tests/vms/`:

```text
kubespand/qemu_tests/
  events.go                    # Event types (shared by init binaries + tests)
  helpers.go                   # VM, BootVM, StartVM, McastNIC, etc.
  BUILD.bazel                  # go_library + vmlinuz/modules genrules
  vms/
    initlib/                   # Shared PID-1 helpers (EmitEvent, MustRun, etc.)
    kubespanlib/               # Shared kubespand helpers (config, probes, peer wait)
    discovery/                 # Discovery VM: init + initramfs
    router/                    # NAT router VM: init + initramfs
    kubespan/                  # 2-node KubeSpan VM: init + initramfs
    doublenat/                 # 3-node double-NAT KubeSpan VM: init + initramfs
  nft/                         # TestNftSmoke (init + initramfs + test, all inline)
  kubespan/                    # TestFlat, TestCrossSubnet, TestDiscoveryOnly
  doublenat/                   # TestDoubleNAT
  talos/                       # TestTalosKubeSpanDoubleNAT
    testdata/                  # Pre-generated Talos machine configs + talosconfig
```

## Key Design Decisions

- **Separate go_test targets per test group** for Bazel parallelism.
- **Separate init binaries per VM role** — each VM type has its own `package main`.
  Shared code in `initlib` (PID-1 basics) and `kubespanlib` (kubespand startup + probes).
- **Event channel on VM struct** — `VM.Events` is a buffered channel. Tests use
  `select` over multiple VM channels for fail-fast signaling.
- **Pre-generated Talos configs** committed as testdata — avoids runtime `talosctl gen`.
- **nocloud raw disk image** built locally via Docker genrule. Each Talos VM gets a
  `snapshot=on` overlay (no full copy needed).

## Peer Discovery Flow

`WaitForPeers` (in `kubespanlib.go`) tails `/tmp/kubespand.log` looking for the
`"configuring peer"` zap JSON log line emitted by `ManagerController.reconcile`.
This requires the full COSI controller chain to complete:

1. ConfigController → produces Config, ClusterConfig, AgentConfig
2. IdentityController → produces Identity (WireGuard keypair + ULA)
3. NodeMetadataController → produces node metadata shims
4. LocalAffiliateController (upstream) → produces local Affiliate
5. DiscoveryController → connects to discovery service, publishes/reads affiliates
6. PeerSpecController (upstream) → produces PeerSpec from affiliates
7. ManagerController → sees PeerSpec → logs `"configuring peer"` → writes LinkSpec

## Gotchas

### YAML nil vs empty slice semantics

Go's `yaml.v3` marshals nil slices as `[]` (empty sequence) without `omitempty`.
Unmarshaling `[]` produces `[]string{}` (non-nil empty), not nil. This matters when
upstream code checks `!= nil` to decide whether to apply filtering. Always use
`omitempty` on optional slice YAML tags to preserve nil semantics through round-trips.

### Talos KSPP kernel parameters

Talos requires `slab_nomerge` and `pti=on` on the kernel cmdline. Without them, the
`systemRequirements` phase fails and boot stalls. (Only relevant for kernel+initramfs
boot, not for disk image boot.)

### bufio.Scanner cannot tail files

Go's `bufio.Scanner` caches `io.EOF` — once it reads past the end of a file, it never
retries. Do NOT use a single Scanner to poll a file being appended by another process.
Use `os.ReadFile` + `strings.Split` or manual `Read()` calls instead. This caused a
multi-day debugging session (see `debug/qemu-test-failure-analysis.md`).

### RBE PATH doesn't include /usr/sbin

`mkfs.vfat` is at `/usr/sbin/mkfs.vfat`, `mcopy` at `/usr/bin/mcopy`. Use full paths
in test code since Bazel's sandbox PATH is minimal.

## Observed Timings (RBE, Firecracker, TCG)

- Alpine VM boot (discovery/router): ~5s
- Talos qcow2 VM boot to apid healthy: ~33-64s
- Talos config acquisition from CIDATA: ~15-29s
