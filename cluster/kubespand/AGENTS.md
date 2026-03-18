@README.md

## Critical Requirements

- **nftables is mandatory**: The KubeSpan agent MUST use nftables for packet marking and policy routing. Do NOT implement fallback modes that bypass nftables (e.g., direct routes without fwmark-based routing). If nftables operations fail, fix the root cause rather than working around it.

## Talos Correspondence

kubespand reimplements Talos's KubeSpan for non-Talos Linux. Maintain structural
correspondence with upstream Talos (`github.com/siderolabs/talos`):

```text
Upstream Talos code (embedded via @talos_internal):
  @talos_internal//:adapters_kubespan        ↔  internal/.../adapters/kubespan/
  @talos_internal//:adapters_network         ↔  internal/.../adapters/network/
  @talos_internal//:controllers_cluster      ↔  internal/.../controllers/cluster/  (LocalAffiliateController)
  @talos_internal//:controllers_kubespan     ↔  internal/.../controllers/kubespan/
  @talos_internal//:controllers_kubeprism    ↔  internal/.../controllers/k8s/      (KubePrismController)
  @talos_internal//:controllers_network      ↔  internal/.../controllers/network/
  @talos_internal//:controllers_secrets     ↔  internal/.../controllers/secrets/ (APIController + APICertSANsController)
  (go_library targets in BUILD.overlay.bazel, importpath matches Talos)

kubespand code:
  controllers/kubespan/manager.go      ↔  controllers/kubespan/manager.go           (reimplemented, declarative LinkSpec)
  controllers/kubespan/identity.go     ↔  controllers/kubespan/identity.go          (reimplemented)
  controllers/cluster/discovery_service.go  ↔  controllers/cluster/discovery_service.go  (reimplemented, publishes affiliate)
  controllers/cluster/kubernetes_node.go    ↔  (kubespand-only: K8s informer → k8s.NodeStatus for PodCIDRs)
  controllers/kubespand/config.go      ↔  (kubespand-only: YAML → COSI config injection)
  controllers/kubespand/node_metadata.go  ↔  (kubespand-only: produces shim COSI resources for LocalAffiliateController)
  controllers/kubespand/os_root.go  ↔  (kubespand-only: produces secrets.OSRoot from YAML config for trustd CSR flow)
  controllers/k8s/kubeprism_config.go  ↔  controllers/k8s/kubeprism_endpoints.go + kubeprism_config.go  (adapted)
  controllers/network/wireguard_link.go  ↔  controllers/network/link_spec.go  (WG subset only)
  @talos_internal controllers_kubespan  ↔  controllers/kubespan/ (PeerSpecController + EndpointController, direct dep)
  identity/                  ↔  (kubespand-only: disk identity)
  discovery/                 ↔  (kubespand-only: discovery client wrapper)
  agentconfig/               ↔  (kubespand-only: YAML config + COSI resource)
```

## Cost Framing

kubespand's cost is the **size of the delta** from Talos — the glue code, shims, and
patches needed to bridge kubespand's YAML-config world to Talos's COSI controller world.
Code imported directly from Talos (via `@talos_internal` or `@com_github_siderolabs_talos`)
is free — it's an upstream dependency, not ducktape LOC.

**Prefer importing a 3k-LOC Talos controller over writing a 300-LOC reimplementation**,
if the controller works as a drop-in. Examples:

- `RouteConfigController` (346 LOC), `RouteMergeController` (42 LOC): imported directly,
  our cost is ~25 LOC of glue (`NetworkConfig` struct, `DeviceConfigSpec` shim, registration).
- `PeerSpecController`, `EndpointController`: imported directly from `@talos_internal`.
- `KubePrismController`, `APIController`, `APICertSANsController`: imported directly.

When evaluating whether to import vs reimplement, consider:

1. **Does it work as a drop-in?** Check what resources it reads/writes, and whether
   kubespand can produce the required inputs (possibly via a shim).
2. **Does it pull in unwanted dependencies?** Some Talos controllers depend on `machined`
   internals (udev, STATE partition) that don't exist on non-Talos hosts.
3. **Is the shim simpler than the reimplementation?** e.g., `DeviceConfigSpec` shim
   (~10 LOC) vs importing `DeviceConfigController` (245 LOC of device selector/bond
   expansion we don't need).

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
