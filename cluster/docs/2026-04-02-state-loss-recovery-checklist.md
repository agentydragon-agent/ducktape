# State Loss Recovery Checklist — 2026-04-02 (Historical)

**Status**: Superseded. The general bootstrap dependency guide is at
<bootstrap-dependencies.md>.

Tofu state was lost during a failed migration from temp PG to in-cluster PG
(see <lessons_learned/2026-04-01-cluster-nuke-postmortem.md>). All
persistent-auth resources were regenerated fresh during the 2026-04-03
bootstrap.

## What happened

1. Cluster torn down after cascading failures (Nebula DNS, haproxy, kubelet)
2. Fresh bootstrap attempted with temp PG
3. `tofu init -migrate-state` to in-cluster PG wrote nothing (silent failure)
4. Temp PG and `errored.tfstate` deleted before verifying migration
5. All tofu state lost — full re-bootstrap required

## What changed during recovery

- SealedSecrets fully replaced with SOPS (all 26 secret files converted)
- Nebula CA moved from tofu-generated to SOPS (`secrets/nebula-ca.yaml`)
- Flux deploy key moved from tofu-generated to SOPS (`secrets/flux-deploy-key.yaml`)
- Cluster age keypair moved to SOPS (`secrets/cluster-secrets-age.yaml`)
- Sealed-secrets controller removed from cluster
- `flux-system` namespace now created by tofu in Phase 2 (for SOPS age secret)
- DNS records moved from tofu-controller to declarative ClusterRRset CRDs

## Completed steps

- [x] Run bootstrap with `--exclude=module.wyrm2`
- [x] Flux deploy key registered in GitHub
- [x] SOPS cluster age public key in `.sops.yaml`
- [x] All SealedSecrets converted to SOPS (no re-sealing needed)
- [x] Nebula certs generated from SOPS CA

## Remaining steps

- [x] Copy new nebula node certs to NixOS worker SOPS files
- [x] Update `secrets/k8s-worker.yaml` with new k8s bootstrap kubeconfig + CA cert
- [x] `nixos-rebuild switch` on wyrm2 — joined cluster, Ready
- [x] `nixos-rebuild switch` on rugged — joined cluster, Ready
- [ ] Verify nebula DNS: `resolvectl query talos-vps-cp-0.nebula.allegedly.works` (pending PowerDNS zone propagation)
- [x] ~~Authentik SSO resync~~ — not needed, fresh cluster has no stale DB state
- [ ] Verify: `get-passwords` returns working credentials
- [x] Migrate tofu state to in-cluster PG — done via `tofu state pull` / `tofu state push` (port-forward to CNPG). Note: `tofu init -migrate-state` doesn't work for PG backend env var changes — use pull/push instead.
- [x] Clean up temp PG container

## Lesson learned

**ALWAYS verify `tofu state list` shows resources in the target backend
before deleting any backups or source backends.** See
<lessons_learned/2026-04-01-cluster-nuke-postmortem.md>.
