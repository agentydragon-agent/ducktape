# Cluster Changelog

## 2026-02-26

1. **Headscale: Helm chart → raw manifests** — Replaced Wrenix HelmRelease with standalone
   K8s manifests (Deployment, Service, Certificate, ServiceAccount, ConfigMap via
   `configMapGenerator`). Secrets injected via Viper env var overrides
   (`HEADSCALE_OIDC_CLIENT_SECRET`, `HEADSCALE_DATABASE_POSTGRES_PASS`) from ESO secrets.
   ESOs changed from Helm values fragments to raw key outputs. ACL policy managed via
   `policy.mode: database` (Terraform provider). ServiceMonitor for Prometheus metrics.
2. **Headscale API key bootstrap Job** — New `headscale-api-key-bootstrap` Job creates a
   Headscale API key via `kubectl exec` and stores it in a K8s Secret with Reflector
   annotations to copy to `flux-system`. Follows the `gitea-admin-token` pattern. Idempotent
   (skips if Secret already exists). `dependsOn: [headscale]`.
3. **Headscale config Terraform module** — New `terraform/gitops/headscale-config/` module
   using `awlsring/headscale` provider v0.5.0. Creates `subnet-router` robot user, ACL
   policy with `autoApprovers` for `10.96.0.0/12` routes tagged `tag:router`, and a reusable
   pre-auth key stored in Vault at `kv/tailscale-router/authkey`.
   `dependsOn: [headscale-api-key-bootstrap, vault-token, tofu-controller]`.
4. **Tailscale subnet router** — New `tailscale-router` namespace with Deployment running
   `ghcr.io/tailscale/tailscale:latest`. Advertises K8s service CIDR (`10.96.0.0/12`) to
   the Headscale tailnet, enabling devices (wyrm, atlas) to reach cluster-internal services
   like ActivityWatch directly over the WireGuard mesh. Split DNS routes
   `svc.cluster.local` queries to CoreDNS, so cluster services are resolvable by name
   (e.g., `activitywatch.activitywatch:5600`) from tailnet devices. Pre-auth key
   from Vault via ESO. State persisted in `tailscale-state` K8s Secret. Init container
   enables IP forwarding; main container has `NET_ADMIN` + `NET_RAW` capabilities.

## 2026-02-24

1. **OpenClaw: shared-workspace sidecar for MCP token isolation** — Kept the node-host
   sidecar (`tools.exec.host: node`) but mounted the operator-managed `data` PVC into both
   the gateway and sidecar containers at `/home/openclaw/.openclaw`. This fixes the
   split-brain filesystem problem (built-in file tools and shell commands now see the same
   files) while keeping MCP server API tokens isolated in the gateway's env vars —
   unreachable from the sidecar via `env` or `/proc/1/environ`. Removed
   `extraVolumes`/`extraVolumeMounts` (projected SA token) from the gateway; the operator
   sets `AutomountServiceAccountToken: false`, so the gateway has zero k8s credentials.
   The sidecar keeps its sandbox SA token scoped to `openclaw-sandbox` namespace. MCP
   security model: stdio servers are safe (pipe-based IPC), HTTP servers must require
   bearer token auth. See <operations/2026-02-24-openclaw-execution-model.md> for full
   analysis.
2. **OpenClaw default model → Claude Opus 4.6** — Changed `agents.defaults.model.primary`
   from `ollama/gpt-oss:20b` to `anthropic/claude-opus-4-6`.
3. **Headlamp: direct OIDC with per-user K8s RBAC** — Switched from proxy outpost +
   shared ServiceAccount to direct OIDC login. kube-apiserver on all nodes now has
   `--oidc-issuer-url`, `--oidc-client-id=headlamp`, `--oidc-username-claim=preferred_username`,
   `--oidc-username-prefix=oidc:` (in Talos machine config `cluster.apiServer.extraArgs`).
   Headlamp switched from `inCluster: true` to OIDC mode via `headlamp-oidc-secret` (ESO).
   ClusterRoleBinding `oidc-agentydragon-admin` maps `oidc:agentydragon` → `cluster-admin`.
   Authentik `oauth2provider` blueprint replaces `proxyprovider`; headlamp removed from
   proxy outpost and `authentik-proxy-routes`. Direct HTTPRoute activated.
4. **Talos machine config deduplication** — Extracted shared `api_server_config`,
   `common_cluster_config`, and `common_machine_base` locals into `main.tf`. Hetzner and
   Proxmox node configs both reference these, eliminating duplication of kube-apiserver
   OIDC flags, cluster settings, and network/feature config.
5. **Matrix OIDC fix** — Fixed `publicBaseurl` not being applied by the ananace chart.
   The top-level `publicBaseurl` value was silently ignored; replaced with
   `publicServerName: matrix.allegedly.works` which the chart uses to derive
   `public_baseurl`. This fixed the OIDC redirect URI mismatch (`allegedly.works` vs
   `matrix.allegedly.works`) that was blocking Authentik SSO login for Element.
6. **Proxmox CSI SCSI slot exhaustion fix** — `talos-pve-cp-0` had 29/29 CSI data
   volumes (CSI driver hardcodes `for lun = 1; lun < 30`), blocking harbor-database.
   Deleted 3 orphaned Gitea Valkey PVCs (redis-cluster disabled but PVCs remained)
   and detached their SCSI devices from Proxmox. Switched Harbor Redis and Langfuse
   Zookeeper PVCs to `local-path` storageClass (cache/ephemeral data, acceptable to
   lose on cluster rebuild). Harbor database rescheduled to gpu-worker-0 (automatic —
   scheduler picked the node with free CSI slots).

## 2026-02-23

1. **Sealed secrets public cert committed to repo** — Added
   `k8s/sealed-secrets/sealed-secrets-cert.pem` managed by a `local_file` terraform
   resource in `persistent-auth`. Enables sealing secrets without terraform state access.
   `seal-secret.sh` reads the committed file (falls back to tofu state). Private key
   remains in terraform state only.
2. **Headscale → CloudNativePG PostgreSQL** — Migrated Headscale from SQLite with
   `local-path` PVC (single-node-bound) to a 2-instance CloudNativePG cluster
   (`headscale-db`) on `local-path` with `topologyKey: kubernetes.io/hostname`. Database
   password injected via ESO ExternalSecret (`headscale-db-values`) using a new
   `kubernetes-headscale-secret-store` ClusterSecretStore reading from the headscale
   namespace. Headscale `persistence.enabled: false` — keys stored in `headscale-keys`
   Secret so the pod can reschedule freely to the surviving VPS node.
3. **Authentik bundled PostgreSQL → CloudNativePG** — Migrated Authentik database from
   the bundled Bitnami PostgreSQL (single instance) to a 2-instance CloudNativePG cluster.
   Both CNPG pods run on Hetzner VPS nodes for HA and zero-downtime failover.
4. **PowerDNS MariaDB → CloudNativePG PostgreSQL** — Migrated PowerDNS backend from
   MariaDB (proxmox-csi-retain) to a 2-instance CloudNativePG PostgreSQL cluster
   (`powerdns-db`) on `hcloud-volumes`. Both PostgreSQL pods run on Hetzner VPS nodes
   with `topologyKey: kubernetes.io/hostname` for real HA. PowerDNS DaemonSet now uses
   `GPGSQL_PASSWORD` from the CNPG-generated secret. VPS-only resilience invariant for
   DNS is now fully satisfied. Old orphaned MariaDB PVC (`data-powerdns-mariadb-0`)
   pending deletion.
5. **Gatus comprehensive monitoring** — Added monitors for Vault, Gitea, Grafana, Matrix,
   Harbor OIDC, Ollama, LiteLLM (including live inference probe), Langfuse, Loki,
   Prometheus, Hubble UI, Headlamp, InventTree, Headscale, Nix Cache, Atuin, Grocy,
   FileBrowser, OpenClaw.
6. **Headscale deployed** — Raw K8s manifests (replacing Wrenix Helm chart). Gatus probe
   configured. Device migration from ansible VPS still pending.
7. Tempo, Langfuse, Scanner FileBrowser, InvenTree, Headscale SSO deployed

## 2026-02-18 (Fixes)

1. **Authentik moved to VPS nodes** — All Authentik components (server, worker, PostgreSQL,
   Redis, outposts) pinned to Hetzner VPS nodes. PostgreSQL switched from `proxmox-csi-retain`
   to `hcloud-volumes`. Server and worker scaled to 2 replicas with pod anti-affinity across
   VPS nodes. Fixes: cross-site latency causing 1-1.6s outpost API calls (Django ORM
   round-trips over VXLAN+KubeSpan), liveness probe kills (33 restarts/26h from 3s timeout
   with only 2 gunicorn workers), and single-node-failure vulnerability. Liveness/readiness
   probe timeout increased from 3s to 10s. Outpost deployments pinned via
   `kubernetes_json_patches` in Terraform config.

## 2026-02-16 (Fixes)

1. **Cilium Gateway API migration complete** — Replaced ingress-nginx with Cilium
   Gateway API. Single `cluster-gateway` Gateway with wildcard + apex HTTPS listeners,
   HTTP→HTTPS redirect. Per-service HTTPRoutes in each app namespace. ingress-nginx
   directory deleted.
2. **Vault internal HTTPS→HTTP** — TLS now terminates at Gateway. All internal Vault
   URLs switched from `https://` to `http://` (ESO config, 16 tofu-controller specs).
   Removed `VAULT_CACERT`, `SSL_CERT_FILE` env vars and CA volume mounts.
3. **Gateway API CRDs: experimental channel** — Cilium 1.16.x requires TLSRoute CRD,
   only in experimental channel. Standard channel caused `"Required GatewayAPI resources
are not found"`. Added `kubectl wait --for=condition=Established` before Cilium install.
4. **cert-manager Gateway API enablement** — `--feature-gates=ExperimentalGatewayAPISupport`
   obsolete since cert-manager v1.15. `gateway-shim` controller was silently disabled.
   Switched to `config.enableGatewayAPI: true`. Wildcard + apex certs now auto-issued.
5. **external-dns Gateway API** — Added `--source=gateway-httproute`, RBAC for
   `gateway.networking.k8s.io` resources + namespaces. Added
   `external-dns.alpha.kubernetes.io/target` annotation on Gateway via Flux postBuild
   substitution from `cluster-info` ConfigMap (new `vps_ips_csv` key).
6. **dns-records terraform idempotency** — Route 53 glue records now use
   `allow_overwrite = true` (upsert across cluster lifecycles). Domain registration
   uses declarative `import` block + `lifecycle { ignore_changes }` for non-nameserver
   attributes (transfer lock, contacts, privacy). IAM policy slimmed from
   `route53domains:*` to 4 specific actions (see `docs/iam-policy-route53.json`).

## 2026-02-13 (Fixes)

1. **Dual ClusterIssuer with single-toggle switching** — Two always-present ClusterIssuers
   (`letsencrypt-prod`, `letsencrypt-staging`). Active issuer selected by a single ConfigMap
   (`k8s/cert-manager-issuer-config/configmap.yaml`). Every Ingress has
   `cert-manager.io/cluster-issuer: "${LETSENCRYPT_ISSUER}"` annotation substituted by Flux,
   so flipping the toggle re-issues all certificates. Trust bundle also follows the toggle
   via `${LETSENCRYPT_ISSUER}-root-ca` naming convention (staging CA only trusted in staging
   mode). `ingressShim.defaultIssuerName` kept as fallback.
2. **Authentik ESO key naming** — All 4 Authentik ExternalSecrets now use direct `secretKey`
   matching the env var name (`AUTHENTIK_BOOTSTRAP_PASSWORD`, `AUTHENTIK_BOOTSTRAP_TOKEN`, etc.).
3. **Proxmox CSI `nodeSelector`** — chart uses top-level key, not `controller.nodeSelector`.
