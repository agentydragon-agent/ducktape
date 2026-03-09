@README.md

## Critical Requirements

- **nftables is mandatory**: The KubeSpan agent MUST use nftables for packet marking and policy routing. Do NOT implement fallback modes that bypass nftables (e.g., direct routes without fwmark-based routing). If nftables operations fail, fix the root cause rather than working around it.

## Talos Correspondence

kubespand reimplements Talos's KubeSpan for non-Talos Linux. Maintain structural
correspondence with upstream Talos (`github.com/siderolabs/talos`):

```text
cluster/kubespand/           ↔  github.com/siderolabs/talos/internal/app/machined/pkg/
├── network/                 ↔  adapters/network/ + controllers/network/  (talos_copy)
├── peerstate/               ↔  adapters/kubespan/                        (talos_copy)
├── peerspec/                ↔  controllers/kubespan/peer_spec.go         (talos_copy)
├── endpoint/                ↔  controllers/kubespan/endpoint.go          (talos_copy)
├── routing/                 ↔  controllers/kubespan/routing_rules.go     (talos_copy)
├── controller_manager.go    ↔  controllers/kubespan/manager.go           (reimplemented)
├── controller_identity.go   ↔  controllers/kubespan/identity.go          (reimplemented)
├── controller_discovery.go  ↔  controllers/cluster/discovery_service.go  (reimplemented)
├── controller_config.go     ↔  (no equivalent — Talos reads MachineConfig)
├── controller_k8s_node.go   ↔  controllers/cluster/local_affiliate.go    (reimplemented)
├── identity/                ↔  (kubespand-only: disk-based identity persistence)
├── discovery/               ↔  (kubespand-only: discovery client wrapper)
├── wireguard/               ↔  (kubespand-only: imperative WG via netlink)
├── agentconfig/             ↔  (kubespand-only: YAML agent config)
└── k8snet/                  ↔  (kubespand-only: KubernetesNetworks COSI resource)
```

**Rules:**

1. **Prefer `talos_copy`** — use the `talos_copy` genrule (defined in `upstream.bzl`)
   to import Talos source files verbatim with patches. 9 files currently use this pattern.
   Check if `talos_copy` works before reimplementing.
2. **Reimplemented files** must reference the Talos equivalent at the top:
   `// Ref: internal/.../controllers/kubespan/manager.go`
3. **kubespand-only files** exist where Talos's approach doesn't apply (disk identity
   persistence, YAML config, direct netlink for WireGuard since LinkSpecController
   depends on Talos udev integration).
