# wyrm2 Suspension — 2026-05-10

Machine will be physically relocated and offline for ~2 weeks.

## Suspend + Delete (with data removal)

- [x] **props** — deleted Deployment, CNPG cluster (`props-db`), PVC, all Secrets, namespace. Set `spec.suspend: true` on Flux Kustomizations (props-{namespace,db,secrets,app}, harbor-props).
- [x] **openhands** — deleted Deployment, PVC (`openhands-data`), all Secrets, namespace. Set `spec.suspend: true` on Flux Kustomizations (openhands-{namespace,secrets,sandboxes,app}).
  - `TODO`: reevaluate whether to redeploy after machine comes back.
- [ ] **openclaw** — back up any persistent state to `~/drive/2026-05-10-cluster-suspensions/openclaw/`, then delete StatefulSet, PVCs, K8s objects.
  - `TODO`: play with it again once machine is restored.
- [x] **thrive-scraper** — deleted CronJob, Deployment, PVC (`thrive-data`), all Secrets, namespace. Set `spec.suspend: true` on Flux Kustomization in gaffer-private.

## Down but Not Suspended

- [ ] **ollama** — stays in k8s, just offline until wyrm2 comes back up.

## Deliberately Do Nothing

These are node-level infra or don't need action:

- proxmox-proxy, openebs, nvidia-device-plugin, node-feature-discovery, kube-system/cilium

## No Action Needed (will reschedule to VPS automatically)

- **manifold-mcp** — stateless Deployment, will reschedule to VPS
- **cnpg-system** (operator) — will reschedule; single-replica CNPG clusters won't attempt failover (nothing to fail over to)
- **flux-system/tofu-controller** — stateless Deployment, will reschedule
- **google-workspace-mcp** — already broken (Init:CreateContainerConfigError), no action changes nothing
- **loki** (canary + promtail) — loki-0 already on vps-worker-0; DaemonSet instances on wyrm2 just stop
- **monitoring** (grafana, grafana-operator, node-exporter) — most stack already on VPS (mimir, tempo, alloy); grafana/operator will reschedule; node-exporter DaemonSet stops on wyrm2
- **csi-proxmox** — controller Deployment will reschedule; node plugin DaemonSet stops on wyrm2
- **kvm-device-plugin** — DaemonSet, stops when wyrm2 goes down, irrelevant on VPS (no KVM)
- **cpap-sync** — CronJob already paused; webdav pod will be offline (PVC data on wyrm2)

## Decide What To Do

### Apps that serve externally (need to decide: leave running on another node? suspend?):

- [ ] **atuin** (server + CNPG `atuin-db-1`) — shell history sync
- [ ] **grocy-sf** (grocy + mcp-server) — SF household inventory
- [ ] **grocy-vallejo** (grocy + mcp-server) — Vallejo household inventory
- [ ] **matrix** (synapse + CNPG `matrix-db-1`) — Matrix homeserver
- [ ] **harbor** (full stack: core, db, registry, redis, portal, nginx, jobservice, exporter) — container registry
- [ ] **nix-cache** (attic + CNPG `attic-db-1`) — Nix binary cache

### Infra/system services:

- [ ] **docker-ci** — CI Docker daemon (needs Docker, likely wyrm2-only)

### Also noted:

- [x] **claude-sandbox/aime-gpt20** — `Error` pod deleted.
- [x] **MCP secret access** — TODO filed at `cluster/docs/todo_k8s_mcp_secret_access.md`.
