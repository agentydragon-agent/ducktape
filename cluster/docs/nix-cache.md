# Nix Binary Cache (Attic)

Attic server at `cache.allegedly.works`, backed by PostgreSQL (CNPG) and local
storage on a `longhorn` PVC. Manifests in `k8s/nix-cache/`.

## Architecture

- **Server**: `ghcr.io/zhaofengli/attic:latest` (NixOS-based image)
- **Database**: CNPG cluster `attic-db` (2 instances, `longhorn`)
- **Cache storage**: 30Gi `longhorn-2r` PVC at `/cache`
- **Cache name**: `main` (public, priority 40)
- **Signing public key**: `cache.allegedly.works-1:OX/cis8G1W13DALkGvhdUZ1OY3yGATbXw8+tIc8J7oA=`

## Secrets

| Secret                  | Source                          | Contains                                                   |
| ----------------------- | ------------------------------- | ---------------------------------------------------------- |
| `nix-cache-signing-key` | SealedSecret (`terraform/main`) | Nix signing keypair (`signing-key.pub`, `signing-key.sec`) |
| `attic-jwt-token`       | SealedSecret (`terraform/main`) | JWT HS256 secret for token signing                         |
| `attic-db-app`          | CNPG-generated                  | PostgreSQL connection URI                                  |

Tokens (admin, CI push) are JWTs signed with the `attic-jwt-token` secret.
They are ephemeral — generate with `atticadm make-token`, store where needed.

## Cache Initialization

After a fresh deployment (empty DB), the cache must be created once:

```bash
# 1. Generate an ephemeral admin token
ADMIN_TOKEN=$(kubectl exec -n nix-cache deployment/attic -- \
  atticadm -f /config/server.toml make-token \
    --sub "admin" --validity "1y" \
    --pull "*" --push "*" --delete "*" \
    --create-cache "*" --configure-cache "*" \
    --configure-cache-retention "*" --destroy-cache "*")

# 2. Create the "main" cache (auto-generated keypair, public)
curl -s -X POST "https://cache.allegedly.works/_api/v1/cache-config/main" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"keypair":"Generate","is_public":true,"store_dir":"/nix/store","priority":40}'

# 3. Update keypair to match the committed signing key
SIGNING_SEC=$(kubectl get secret nix-cache-signing-key -n nix-cache \
  -o jsonpath='{.data.signing-key\.sec}' | base64 -d)
curl -s -X PATCH "https://cache.allegedly.works/_api/v1/cache-config/main" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"keypair\":{\"Keypair\":\"$SIGNING_SEC\"}}"
```

## CI Push

CI pushes build outputs to the cache after `nix build`.

**Generating a push token** (store as GitHub Actions secret `ATTIC_TOKEN`):

```bash
kubectl exec -n nix-cache deployment/attic -- \
  atticadm -f /config/server.toml make-token \
    --sub "ci" --validity "1y" \
    --pull "main" --push "main"
```

**GitHub Actions usage:**

```yaml
- uses: cachix/install-nix-action@v31
- run: |
    nix run nixpkgs#attic-client -- login ducktape https://cache.allegedly.works ${{ secrets.ATTIC_TOKEN }}
    nix run nixpkgs#attic-client -- push main ./result
```

## Pulling (NixOS Hosts)

The cache is public — no authentication needed. Add to `nix.settings`:

```nix
nix.settings = {
  substituters = [ "https://cache.allegedly.works/main" ];
  trusted-public-keys = [ "cache.allegedly.works-1:OX/cis8G1W13DALkGvhdUZ1OY3yGATbXw8+tIc8J7oA=" ];
};
```

## Environment Variables

Attic uses serde defaults for env var fallback — values must be **absent** from
`server.toml` for the env var to take effect (TOML values always win).

| Env Var                                  | TOML Field                              | Source                   |
| ---------------------------------------- | --------------------------------------- | ------------------------ |
| `ATTIC_SERVER_DATABASE_URL`              | `database.url`                          | `attic-db-app` secret    |
| `ATTIC_SERVER_TOKEN_HS256_SECRET_BASE64` | `jwt.signing.token-hs256-secret-base64` | `attic-jwt-token` secret |

## Known Issues

The Attic image is NixOS-based and triggers a containerd bug on nodes with
containerd 2.2.x + Go 1.24 (absolute `/etc/passwd` symlink rejection). The
deployment has a `nodeAffinity` excluding NixOS nodes (which run containerd
2.2.x). See <lessons_learned/> and `debug/attic-containerd-symlink.md`.
