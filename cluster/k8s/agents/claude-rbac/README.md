# Claude Sandbox Namespace

This directory configures a sandbox namespace for Claude AI assistant with full access
for experimentation.

**Cross-references**: RBAC is referenced from the root `AGENTS.md` (Kubernetes MCP Server
section). Keep both in sync when changing permissions.

## Permissions Granted

### 1. claude-sandbox namespace — full CRUD

Defined in <role-sandbox.yaml>, bound via <rolebinding-sandbox.yaml>:

- Pods: create/delete, logs, exec, attach
- Workloads: deployments, statefulsets, daemonsets, replicasets, jobs, cronjobs
- Config: configmaps, secrets, PVCs, events, services
- ⚠️ **Resource limits** (<resourcequota.yaml>): 8 CPU, 16Gi memory, 20 pods

### 2. Cluster-wide read — diagnostics

`cluster-diagnostics-reader` ClusterRole (<clusterrole-cluster-diagnostics-reader.yaml>),
bound via `shared-rbac/clusterrolebinding-cluster-diagnostics-reader.yaml`:

- Core: nodes, pods, services, endpoints, PVs, PVCs, events, namespaces, resourcequotas
- Workloads: deployments, replicasets, statefulsets, daemonsets, jobs, cronjobs, HPAs, VPAs
- Networking: ingresses, networkpolicies, Gateway API routes, Cilium policies
- Storage: storageclasses, volumeattachments, Longhorn volumes/replicas/nodes
- GitOps: Flux kustomizations (+ patch for reconcile), HelmReleases, git/helm/OCI repos,
  image policies, Terraform resources
- Certs & secrets: cert-manager certificates/issuers, trust-manager bundles, ExternalSecrets
- Monitoring: Prometheus, Alertmanager, ServiceMonitors, metrics API (pods + nodes)
- Other: RBAC roles/bindings, CRDs, webhooks, leases, priority classes, Kyverno policies,
  PowerDNS zones, Vault

### 3. Cross-namespace read

Namespaced Roles + RoleBindings for specific namespaces:

- Namespace diagnostics (pods, logs, services, configmaps, PVCs, events, deployments, replicasets, statefulsets) in harbor, gatus, authentik-mcp-poc, csi-proxmox, openebs, proxmox-proxy, cnpg-system, nvidia-device-plugin, node-feature-discovery, local-path-storage, cert-manager, litellm, docker-ci, matrix, grocy-sf, grocy-vallejo
- Extended read in langfuse, ollama (read + consumer), openclaw, props (+ jobs, constrained secrets)
- Logs/configmaps in monitoring, kube-system, longhorn-system, flux-system, grocy-sf, grocy-vallejo, airlock, authentik

## Authentication

Claude Code web sessions authenticate via **client certificate** with
`O=oidc-ksbx-groups:kubectl-sandbox-users` (maps to the OIDC sandbox group).
The cert is auto-rotated by a CronJob in `agents-infra` namespace — see
<../claude-cert-rotation/>.

OIDC users from the `kubectl-sandbox-mcp` Authentik application also get
these permissions via the same group.

## Kubeconfig Provisioning

Kubeconfig is generated automatically by the session start hook via
<devinfra/claude/scripts/write_kubeconfig.py>. It decrypts the SOPS-encrypted
client cert+key from `secrets/claude-web-k8s-cert.yaml` and writes a
kubeconfig with `client-certificate-data`/`client-key-data` auth.

## Security Considerations

- **Write isolation**: Full CRUD only in `claude-sandbox` namespace
- **Broad read**: Cluster-wide diagnostics read (nodes, pods, Flux, certs, metrics, etc.)
- **Resource quotas**: 8 CPU, 16Gi memory, 20 pods (see <resourcequota.yaml>)
- **Flux patch**: Can trigger Flux reconciliation via annotation patch (Kyverno policy
  restricts to annotation-only patches)
