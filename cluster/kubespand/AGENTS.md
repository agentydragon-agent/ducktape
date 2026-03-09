@README.md

## Critical Requirements

- **nftables is mandatory**: The KubeSpan agent MUST use nftables for packet marking and policy routing. Do NOT implement fallback modes that bypass nftables (e.g., direct routes without fwmark-based routing). If nftables operations fail, fix the root cause rather than working around it.

## Talos Correspondence

kubespand reimplements Talos's KubeSpan for non-Talos Linux. Maintain structural
correspondence with upstream Talos (`github.com/siderolabs/talos`):

```text
Upstream Talos code:
  @talos_internal//:adapters_kubespan        ↔  internal/.../adapters/kubespan/
  @talos_internal//:adapters_network         ↔  internal/.../adapters/network/
  @talos_internal//:controllers_kubespan     ↔  internal/.../controllers/kubespan/
  @talos_internal//:controllers_network      ↔  internal/.../controllers/network/
  (go_library targets in BUILD.overlay.bazel, importpath matches Talos)

kubespand code:
  peerspec/                  embeds @talos_internal controllers_kubespan + peer_spec_filters.go
  controller_manager.go      ↔  controllers/kubespan/manager.go           (reimplemented)
  controller_identity.go     ↔  controllers/kubespan/identity.go          (reimplemented)
  controller_discovery.go    ↔  controllers/cluster/discovery_service.go  (reimplemented)
  controller_config.go       ↔  (kubespand-only)
  controller_k8s_node.go     ↔  controllers/cluster/local_affiliate.go    (reimplemented)
  identity/                  ↔  (kubespand-only: disk identity)
  discovery/                 ↔  (kubespand-only: discovery client)
  wireguard/                 ↔  (kubespand-only: WG via netlink)
  agentconfig/               ↔  (kubespand-only: YAML config)
  k8snet/                    ↔  (kubespand-only: KubernetesNetworks resource)
```

**Rules:**

1. **Upstream Talos code lives in `@talos_internal`** — `go_library` targets in
   `BUILD.overlay.bazel` with `importpath` matching Talos internal paths. Patches
   are functional-only (no import rewrites). Consumer code deps on
   `@talos_internal//:target_name`.
2. **Check if Talos has it before reimplementing** — prefer adding a `go_library`
   target to `BUILD.overlay.bazel` over writing new code.
3. **Reimplemented files** must reference the Talos equivalent at the top:
   `// Ref: internal/.../controllers/kubespan/manager.go`
4. **kubespand-only files** exist where Talos's approach doesn't apply (disk identity
   persistence, YAML config, direct netlink for WireGuard since LinkSpecController
   depends on Talos udev integration).
