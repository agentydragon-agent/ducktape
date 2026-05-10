# wyrm2 Suspension — 2026-05-10

Machine will be physically relocated and offline for ~2 weeks.

## Suspend + Delete (with data removal)

- [x] **props** — deleted Deployment, CNPG cluster (`props-db`), PVC, all Secrets, namespace, Flux Kustomizations (props, props-db, props-namespace, props-secrets). Also deleted `harbor-props` Kustomization. Removed entries from `cluster/k8s/kustomization.yaml`.
- [x] **openhands** — deleted Deployment, PVC (`openhands-data`), all Secrets, namespace, Flux Kustomizations (openhands, openhands-namespace, openhands-sandboxes, openhands-secrets). Removed entries from `cluster/k8s/kustomization.yaml`.
  - `TODO`: reevaluate whether to redeploy after machine comes back.
- [ ] **openclaw** — back up any persistent state to `~/drive/2026-05-10-cluster-suspensions/openclaw/`, then delete StatefulSet, PVCs, K8s objects.
  - `TODO`: play with it again once machine is restored.
- [x] **thrive-scraper** — deleted CronJob, Deployment, PVC (`thrive-data`), all Secrets, namespace, Flux Kustomization. Commented out entry in `gaffer-private` kustomization.yaml (thrive-scraper is from `gaffer-private` repo, not ducktape).

## Down but Not Suspended

- [ ] **ollama** — stays in k8s, just offline until wyrm2 comes back up.

## Deliberately Do Nothing

These are node-level infra or don't need action:

- proxmox-proxy, openebs, nvidia-device-plugin, node-feature-discovery, kube-system/cilium

## Decide What To Do

### Apps that serve externally (need to decide: leave running on another node? suspend?):

- [ ] **atuin** (server + CNPG `atuin-db-1`) — shell history sync
- [ ] **grocy-sf** (grocy + mcp-server) — SF household inventory
- [ ] **grocy-vallejo** (grocy + mcp-server) — Vallejo household inventory
- [ ] **matrix** (synapse + CNPG `matrix-db-1`) — Matrix homeserver
- [ ] **manifold-mcp** — Manifold Markets MCP server
- [ ] **harbor** (full stack: core, db, registry, redis, portal, nginx, jobservice, exporter) — container registry
- [ ] **nix-cache** (attic + CNPG `attic-db-1`) — Nix binary cache

### Infra/system services (need to decide: leave alone? these may reschedule or just be offline):

- [ ] **cnpg-system** (operator) — will it try to failover CNPG primaries when wyrm2 goes down?
- [ ] **cpap-sync** (webdav) — CPAP data sync
- [ ] **docker-ci** — CI Docker daemon
- [ ] **flux-system/tofu-controller** — Terraform GitOps controller
- [ ] **google-workspace-mcp** — currently broken (Init:CreateContainerConfigError), may not matter
- [ ] **loki** (canary + promtail) — log collection, node-local
- [ ] **monitoring** (grafana, grafana-operator, node-exporter) — dashboards + metrics
- [ ] **csi-proxmox** — node + controller, storage driver
- [ ] **kvm-device-plugin** — node-local device plugin

### Also noted:

- [ ] **claude-sandbox/aime-gpt20** — `Error` pod from 11 days ago, cleanup
- [ ] **MCP secret access** — `kubectl-local` and in-cluster MCP servers can't list/read secrets. See `cluster/docs/todo_k8s_mcp_secret_access.md`.

## Git changes to commit and push

- `cluster/k8s/kustomization.yaml` — removed props, openhands, harbor/props entries
- `cluster/docs/todo-k8s-mcp-secret-access.md` — new TODO for MCP secret RBAC
- gaffer-private: `k8s/kustomization.yaml` — commented out thrive-scraper
