@README.md

## Critical Requirements

- **nftables is mandatory**: The KubeSpan agent MUST use nftables for packet marking and policy routing. Do NOT implement fallback modes that bypass nftables (e.g., direct routes without fwmark-based routing). If nftables operations fail, fix the root cause rather than working around it.

## Talos Correspondence

kubespand reimplements Talos's KubeSpan for non-Talos Linux. Maintain structural
correspondence with upstream Talos (`github.com/siderolabs/talos`):

```text
cluster/kubespand/                                ↔  github.com/siderolabs/talos/
├── talos/adapters/kubespan/                      ↔  internal/.../adapters/kubespan/      (talos_copy)
├── talos/adapters/network/                       ↔  internal/.../adapters/network/       (talos_copy)
├── talos/controllers/kubespan/                   ↔  internal/.../controllers/kubespan/   (talos_copy)
│   └── peer_spec_filters.go                           (kubespand-only addition)
├── talos/controllers/network/                    ↔  internal/.../controllers/network/    (talos_copy)
├── controller_manager.go                         ↔  controllers/kubespan/manager.go      (reimplemented)
├── controller_identity.go                        ↔  controllers/kubespan/identity.go     (reimplemented)
├── controller_discovery.go                       ↔  controllers/cluster/discovery_service.go (reimplemented)
├── controller_config.go                          ↔  (kubespand-only)
├── controller_k8s_node.go                        ↔  controllers/cluster/local_affiliate.go (reimplemented)
├── identity/                                     ↔  (kubespand-only: disk identity)
├── discovery/                                    ↔  (kubespand-only: discovery client)
├── wireguard/                                    ↔  (kubespand-only: WG via netlink)
├── routing/routes.go                             ↔  (kubespand-only: to be replaced by COSI RouteSpec)
├── agentconfig/                                  ↔  (kubespand-only: YAML config)
└── k8snet/                                       ↔  (kubespand-only: KubernetesNetworks resource)
```

**Rules:**

1. **`talos/` subtree mirrors Talos** — each subdirectory's `importpath` matches
   the Talos internal path, so `talos_copy`'d files need zero import patches.
   Only functional patches (removing Talos-specific runtime deps) are allowed.
2. **Prefer `talos_copy`** — use the `talos_copy` genrule (defined in `upstream.bzl`)
   to import Talos source files verbatim. Check if `talos_copy` works before
   reimplementing.
3. **Reimplemented files** must reference the Talos equivalent at the top:
   `// Ref: internal/.../controllers/kubespan/manager.go`
4. **kubespand-only files** exist where Talos's approach doesn't apply (disk identity
   persistence, YAML config, direct netlink for WireGuard since LinkSpecController
   depends on Talos udev integration).
