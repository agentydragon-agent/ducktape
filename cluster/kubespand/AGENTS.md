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
  controllers/kubespan/manager.go      ↔  controllers/kubespan/manager.go           (reimplemented, declarative LinkSpec)
  controllers/kubespan/identity.go     ↔  controllers/kubespan/identity.go          (reimplemented)
  controllers/cluster/discovery_service.go  ↔  controllers/cluster/discovery_service.go  (reimplemented)
  controllers/cluster/local_affiliate.go    ↔  controllers/cluster/local_affiliate.go    (reimplemented)
  controllers/kubespand/config.go      ↔  (kubespand-only: YAML → COSI config injection)
  controllers/k8s/kubeprism_config.go  ↔  controllers/k8s/kubeprism_endpoints.go + kubeprism_config.go  (adapted)
  controllers/network/wireguard_link.go  ↔  controllers/network/link_spec.go  (WG subset only)
  peerspec/                  embeds @talos_internal controllers_kubespan + peer_spec_filters.go
  identity/                  ↔  (kubespand-only: disk identity)
  discovery/                 ↔  (kubespand-only: discovery client)
  agentconfig/               ↔  (kubespand-only: YAML config + COSI resource)
  k8snet/                    ↔  (kubespand-only: KubernetesNetworks resource)
  @talos_internal controllers_kubeprism  ↔  controllers/k8s/kubeprism.go  (embedded)
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
   persistence, YAML config, WireguardLinkController instead of the monolithic
   LinkSpecController which depends on Talos udev integration).
