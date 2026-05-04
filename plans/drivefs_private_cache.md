# Drivefs: serve from private cache, install on NixOS

## Context

The private-cache + JWT-rotation infra landed in commits
`96c039b69..6ad34978d`:

- `cache.allegedly.works/gaffer` cache exists (empty),
  pubkey `gaffer:Z8sM2kptUUDGk4ARVD/YkcpzWdMgmZX7nVLV5joK7r8=`.
- Writer JWT for gaffer at `secrets/ci/attic-gaffer-writer.sops.yaml`,
  decryptable by the CI age key (already in gaffer-private's GHA secrets).
- `nix/packages/gaffer.nix` ready to expose pins as `builtins.storePath`
  derivations driven by `nix/gaffer-pins.json` (currently `{"pins": {}}`).
- `nix/home/modules/google-drive.nix` ready to consume `gafferPkgs.drivefs`.
- wyrm2 NixOS host wired as substituter consumer.

Scope: **drivefs only** (the upstream Google Drive binary blob).
gaffer-private's `drivefs/package.nix` already wraps it, and its
`flake.nix` already exposes `packages.${system}.google-drive`. Nothing
new on the gaffer-private nix side. drivectl (the Rust wrapper) is a
separate followup.

## Phase 1 — gaffer-private CI workflow

`.github/workflows/nix-attic-push.yml` in **the gaffer-private repo**.
Triggered on push to default branch.

### Steps

1. **Checkout** with `lfs: true` — `drivefs/upstream/` is LFS-tracked;
   the upstream Google Drive blob has to be smudged for nix-build to
   read it.
2. **Install Nix** (Determinate Systems installer, same as ducktape's
   `.github/workflows/nix-attic-push.yml`) and the `attic-client`.
3. **Sparse-clone ducktape** for the writer token at
   `secrets/ci/attic-gaffer-writer.sops.yaml`. The token isn't checked
   into gaffer-private — single source of truth in ducktape, decryptable
   via the CI age key (already a GHA secret on gaffer-private, synced
   from cluster by `tf/gitops/github-secrets-sync/main.tf`).
4. **Decrypt writer token**:
   `sops -d secrets/ci/attic-gaffer-writer.sops.yaml | yq .attic_token`
   → exported as `ATTIC_GAFFER_TOKEN`.
5. **Build drivefs**: `nix build .#google-drive --no-link --print-out-paths`
   captures the store path (e.g., `/nix/store/<hash>-google-drive-122.0.1.0`).
6. **Push to attic**:
   ```bash
   attic login gaffer https://cache.allegedly.works "$ATTIC_GAFFER_TOKEN"
   attic push gaffer "$DRIVEFS_STORE_PATH"
   ```
   `attic push` walks the closure and uploads everything not already in
   the cache (deduped — most invocations after the first are near-no-ops).
7. **Update ducktape pin** (`nix/gaffer-pins.json`):
   ```bash
   git clone --depth 1 \
     "https://x-access-token:${DUCKTAPE_REPIN_PAT}@github.com/agentydragon/ducktape" ducktape
   cd ducktape
   jq --arg sp "$DRIVEFS_STORE_PATH" \
      --arg rev "$GITHUB_SHA" \
      '.pins.drivefs = {store_path: $sp, version: "122.0.1.0", rev: $rev}' \
      nix/gaffer-pins.json > tmp.json && mv tmp.json nix/gaffer-pins.json
   git diff --quiet -- nix/gaffer-pins.json && exit 0  # idempotent
   git -c user.name=gaffer-bot -c user.email=noreply@allegedly.works \
       commit -am "chore: bump gaffer-private drivefs to ${GITHUB_SHA:0:12}"
   git pull --rebase origin devel
   git push origin HEAD:devel
   ```
   Concurrency group `gaffer-repin` (so it doesn't race with `sync-pins`).
   Order matters: push to attic **before** updating the pin, so the pin
   never references a closure attic doesn't yet have.

### Required secrets on gaffer-private's GHA

Both follow the same pattern: SOPS-encrypted k8s Secret in
`cluster/k8s/github-secrets-sync/secrets/` → Flux applies →
`tf/gitops/github-secrets-sync/main.tf` reads via
`data.kubernetes_secret` → pushes to gaffer-private's GHA via
`github_actions_secret`. The PAT thus lives in SOPS at rest and TF
handles cross-repo provisioning.

- **`SOPS_AGE_KEY`** — already provisioned. Decrypts
  `secrets/ci/attic-gaffer-writer.sops.yaml` from a sparse-cloned
  ducktape (and any other CI-scoped SOPS files).
- **`DUCKTAPE_REPIN_PAT`** — fine-grained PAT on `agentydragon/ducktape`
  with `Contents: write`. Net new. Provisioning:
  1. **Mint** the PAT on the `agentydragon` GitHub account: fine-grained,
     repo `agentydragon/ducktape` only, `Contents: write` (no other
     scopes), 1-year expiry.
  2. **SOPS-encrypt** it as a new manifest at
     `cluster/k8s/github-secrets-sync/secrets/ducktape-repin-pat.sops.yaml`:

     ```yaml
     apiVersion: v1
     kind: Secret
     metadata:
       name: ducktape-repin-pat
       namespace: flux-system
     type: Opaque
     stringData:
       token: <PAT plaintext>
     ```

     Then `sops -e -i cluster/k8s/github-secrets-sync/secrets/ducktape-repin-pat.sops.yaml`
     in the repo (the `cluster/k8s/.*\.sops\.yaml$` rule encrypts to
     `admin + cluster-secrets`).

  3. **Add to kustomization** —
     `cluster/k8s/github-secrets-sync/secrets/kustomization.yaml`
     resources list: `- ducktape-repin-pat.sops.yaml`.
  4. **Wire into TF** — extend `tf/gitops/github-secrets-sync/main.tf`:

     ```hcl
     data "kubernetes_secret" "ducktape_repin_pat" {
       metadata {
         name      = "ducktape-repin-pat"
         namespace = "flux-system"
       }
     }

     resource "github_actions_secret" "ducktape_repin_pat_gaffer_private" {
       repository      = "gaffer-private"
       secret_name     = "DUCKTAPE_REPIN_PAT"
       plaintext_value = data.kubernetes_secret.ducktape_repin_pat.data["token"]
     }
     ```

  Once the SOPS manifest + kustomization update + TF stanza are committed
  and pushed, Flux deploys the Secret and tofu-controller reconciles the
  module within ~15min, landing `DUCKTAPE_REPIN_PAT` as a GHA secret on
  gaffer-private. PAT rotation = re-mint + re-encrypt the SOPS file +
  push; TF picks it up on next reconcile.

## Phase 2 — ducktape consumer flip

After Phase 1's first successful gaffer CI run, `nix/gaffer-pins.json`
will have a `pins.drivefs` entry. Then:

1. **No code change needed** — `nix/packages/gaffer.nix` already exposes
   any pin keys via `builtins.mapAttrs (_: spec: builtins.storePath spec.store_path) pins`,
   and `nix/home/modules/google-drive.nix` already references
   `gafferPkgs.drivefs`. Both will resolve as soon as the pin file
   has an entry.
2. **Flip the host opt-in** in `nix/home/hosts/wyrm2.nix:59`:
   ```nix
   services.google-drive.enable = true;
   ```
3. **`home-manager switch --flake .#wyrm2`** on wyrm2 — drivefs gets
   substituted from `cache.allegedly.works/gaffer` (no source fetch),
   the systemd-user unit starts, `~/drive` symlink lands.

## Phase 3 — Verification

On wyrm2 after the flip:

```bash
# Substituter sees the gaffer cache.
nix show-config | grep -E "substituters|trusted-public-keys" | grep gaffer

# drivefs realizes from cache (not local build).
nix-store --realise "$(jq -r .pins.drivefs.store_path nix/gaffer-pins.json)" \
  --print-build-logs
# Expect: "copying path '...' from 'https://cache.allegedly.works/gaffer'"

# Service active.
systemctl --user status google-drive.service
ls ~/drive  # FUSE mount of My Drive
```

If substitution fails, sanity-check the reader token:

```bash
sudo curl -fI \
  -H "Authorization: Bearer $(grep password /etc/nix/attic-netrc | awk '{print $2}')" \
  https://cache.allegedly.works/gaffer/nix-cache-info
```

## Followups (out of scope)

- **drivectl**: same shape as drivefs but Bazel-built Rust binary, needs
  a nix wrapper for the Bazel output (open question on Bazel→nix
  bridging — stage Bazel output in source tree vs `--arg`-based impure
  build). Add to `flake.nix` `packages.${system}.drivectl`, then
  re-bump the pin to also include it.
- Roll the wiring (`ducktape.attic-substituter.enable = true` +
  `services.google-drive.enable = true`) to rugged, iguana, atlas
  per-host. Each needs its own per-host SOPS reader file plus a parallel
  `attic-rotate-<host>-reader` CronJob (mirror the wyrm2 one in
  `cluster/k8s/agents/attic-jwt-rotation/`).
- Auto-fetch the gaffer pubkey post-cache-creation and PR it into
  `nix/nixos/modules/attic-substituter.nix` (TODO already noted in the
  module + bootstrap.sh).
- Split `&ci` age recipient into `&ducktape-ci` and `&gaffer-ci` so
  the gaffer writer token isn't decryptable by ducktape CI's age key
  (TODO already noted in `.sops.yaml`).

## Critical files

| File                                                                   | Role                                                               |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `gaffer-private/.github/workflows/nix-attic-push.yml`                  | **NEW** — Phase 1 CI                                               |
| `cluster/k8s/github-secrets-sync/secrets/ducktape-repin-pat.sops.yaml` | **NEW** — SOPS-encrypted k8s Secret holding the repin PAT          |
| `cluster/k8s/github-secrets-sync/secrets/kustomization.yaml`           | add the new SOPS file to the resources list                        |
| `tf/gitops/github-secrets-sync/main.tf`                                | new `data.kubernetes_secret` + `github_actions_secret` for the PAT |
| `ducktape/nix/gaffer-pins.json`                                        | populated by gaffer CI direct-push                                 |
| `ducktape/nix/home/hosts/wyrm2.nix:59`                                 | flip `services.google-drive.enable = true` after first CI run      |
