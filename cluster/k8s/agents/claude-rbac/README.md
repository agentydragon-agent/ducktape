# Claude Sandbox Namespace

This directory configures a sandbox namespace for Claude AI assistant with full access
for experimentation.

**Cross-references**: RBAC is referenced from the root `AGENTS.md` (Kubernetes MCP Server
section). Keep both in sync when changing permissions.

## Permissions Granted

**claude-sandbox namespace** (full access, defined in <role-sandbox.yaml>):

- Pods: create/delete, logs, exec, attach
- Workloads: deployments, statefulsets, daemonsets, replicasets, jobs, cronjobs
- Config: configmaps, secrets, PVCs, events, services
- ⚠️ **Resource limits** (<resourcequota.yaml>): 8 CPU, 16Gi memory, 20 pods

**Cross-namespace read access** (separate rolebindings in this directory):
harbor, langfuse, ollama, openclaw, props, gatus, logs/configmaps

## ServiceAccount

- **Name**: `claude-code-web`
- **Namespace**: `default`

## Generating a Kubeconfig

To generate a kubeconfig for Claude to use:

```bash
# Create a token (valid for 1 year)
kubectl create token claude-code-web -n default --duration=8760h > /tmp/claude-token.txt

# Get cluster info
CLUSTER_NAME=$(kubectl config view --minify -o jsonpath='{.clusters[0].name}')
SERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')

# Get CA certificate
kubectl config view --raw --minify --flatten \
  -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' \
  | base64 -d > /tmp/ca.crt

# Generate kubeconfig
cat <<EOF > /tmp/claude-kubeconfig.yaml
apiVersion: v1
kind: Config
clusters:
- cluster:
    certificate-authority-data: $(base64 -w0 < /tmp/ca.crt)
    server: $SERVER
  name: $CLUSTER_NAME
contexts:
- context:
    cluster: $CLUSTER_NAME
    user: claude-code-web
    namespace: default
  name: claude-code-web
current-context: claude-code-web
users:
- name: claude-code-web
  user:
    token: $(cat /tmp/claude-token.txt)
EOF

chmod 600 /tmp/claude-kubeconfig.yaml
```

## Kubeconfig Provisioning

Kubeconfig is generated automatically by the session start hook via
`devinfra/claude/hook_daemon/session_start/secret_sources.py`. The SA token is stored as a k8s Secret in the
`claude-sandbox` namespace and read at session start. No manual encryption needed.

## Testing Permissions

```bash
# Should work (full access in sandbox)
kubectl --kubeconfig=/tmp/claude-kubeconfig.yaml -n claude-sandbox create deployment nginx --image=nginx
kubectl --kubeconfig=/tmp/claude-kubeconfig.yaml -n claude-sandbox get pods
kubectl --kubeconfig=/tmp/claude-kubeconfig.yaml -n claude-sandbox create secret generic test --from-literal=key=value
kubectl --kubeconfig=/tmp/claude-kubeconfig.yaml -n claude-sandbox get secrets
kubectl --kubeconfig=/tmp/claude-kubeconfig.yaml -n claude-sandbox exec -it <pod> -- /bin/bash

# Should fail (no permissions outside sandbox without cluster-wide RBAC)
kubectl --kubeconfig=/tmp/claude-kubeconfig.yaml get pods -A
# Error: pods is forbidden
```

## Security Considerations

The sandbox provides an isolated environment with resource limits:

- **Namespace isolation**: Full CRUD only in `claude-sandbox`; other namespaces are read-only
- **Resource quotas**: 8 CPU, 16Gi memory, 20 pods (see <resourcequota.yaml>)
- **Full control**: Create/delete/modify any resources including secrets within sandbox
